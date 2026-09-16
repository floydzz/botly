"""The centralized channel receiver.

Every provider enters here after its HTTP transport has obtained the raw body.
The receiver authenticates through the provider adapter, turns the delivery into
durable inbound-event receipts, then gives their IDs to the queue. It contains
no provider-specific payload rules: those stay in channel adapters.
"""

import json
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.channels.registry import MissingCredentials, UnknownProvider, build_adapter
from app.ingress.queue import InboundQueue
from app.models.channel_connection import ChannelConnection
from app.models.inbound_event import InboundEvent


class WebhookHeaders(Protocol):
    def items(self): ...


class ReceiveError(Exception):
    """A provider-safe error the HTTP boundary can turn into a response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class CentralReceiver:
    """Provider-neutral, durable inbound delivery receiver."""

    def __init__(self, queue: InboundQueue) -> None:
        self._queue = queue

    async def receive(
        self,
        *,
        provider: str,
        connection_id: int,
        headers: WebhookHeaders,
        raw_body: bytes,
        db,
    ) -> None:
        connection = await self._connection(db, provider, connection_id)
        adapter = self._adapter(connection)

        if not adapter.verify_webhook(headers, raw_body):
            raise ReceiveError(403, "bad signature")

        payload = self._payload(raw_body)
        try:
            envelopes = adapter.parse_inbound(payload)
        except (ValueError, KeyError, TypeError, OverflowError):
            raise ReceiveError(400, "malformed payload") from None

        event_ids = await self._store_receipts(
            db=db,
            connection=connection,
            provider=provider,
            payload=payload,
            envelopes=envelopes,
        )
        await self._publish(db, event_ids)

    @staticmethod
    async def _connection(db, provider: str, connection_id: int) -> ChannelConnection:
        connection = (
            await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.id == connection_id,
                    ChannelConnection.provider == provider,
                    ChannelConnection.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            raise ReceiveError(404, "unknown connection")
        return connection

    @staticmethod
    def _adapter(connection: ChannelConnection):
        try:
            return build_adapter(connection)
        except (UnknownProvider, MissingCredentials, ValueError):
            # Never reveal a provider name or credential state to a caller.
            raise ReceiveError(404, "unknown connection") from None

    @staticmethod
    def _payload(raw_body: bytes) -> dict:
        try:
            payload = json.loads(raw_body)
        except (UnicodeDecodeError, ValueError):
            raise ReceiveError(400, "malformed payload") from None
        if not isinstance(payload, dict):
            raise ReceiveError(400, "payload must be an object")
        return payload

    async def _store_receipts(self, *, db, connection, provider, payload, envelopes) -> list[int]:
        """Commit all receipts before one is submitted to the queue."""
        pending_event_ids: list[int] = []
        now = datetime.now(timezone.utc)
        for envelope in envelopes:
            statement = insert(InboundEvent).values(
                connection_id=connection.id,
                provider=provider,
                provider_update_id=envelope.provider_update_id,
                payload=payload,
                created_at=now,
                updated_at=now,
            ).on_conflict_do_nothing(constraint="uq_inbound_events_dedupe")
            await db.execute(statement)
            event = (
                await db.execute(
                    select(InboundEvent).where(
                        InboundEvent.connection_id == connection.id,
                        InboundEvent.provider == provider,
                        InboundEvent.provider_update_id == envelope.provider_update_id,
                    )
                )
            ).scalar_one()
            if event.enqueued_at is None:
                pending_event_ids.append(event.id)
        await db.commit()
        return list(dict.fromkeys(pending_event_ids))

    async def _publish(self, db, event_ids: list[int]) -> None:
        for event_id in event_ids:
            try:
                await self._queue.enqueue(event_id)
            except Exception:
                # The receipt stays durable and unmarked. A provider retry can
                # publish it again without creating a second receipt.
                raise ReceiveError(503, "queue unavailable; retry delivery") from None

            event = await db.get(InboundEvent, event_id)
            event.enqueued_at = datetime.now(timezone.utc)
            await db.commit()
