"""Channel ingress.

The order of operations here is a correctness requirement, not a style: verify
the signature against the raw bytes, persist raw, enqueue, and ACK 200. Nothing slow is allowed in this function -- no LLM call, no
outbound HTTP, no waiting on a task result. A slow ACK makes the provider
retry, and a retry is a second reply to the customer.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import UnknownProvider, build_adapter
from app.core.database import get_db
from app.ingress.queue import InboundQueue
from app.models.channel_connection import ChannelConnection
from app.models.inbound_event import InboundEvent

router = APIRouter(tags=["webhooks"])

def get_inbound_queue() -> InboundQueue:
    from app.worker.queue import CeleryInboundQueue

    return CeleryInboundQueue()


@router.post("/webhooks/{provider}/{connection_id}")
async def receive_webhook(
    provider: str,
    connection_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    queue: InboundQueue = Depends(get_inbound_queue),
) -> Response:
    connection = (
        await db.execute(
            select(ChannelConnection).where(
                ChannelConnection.id == connection_id,
                # The provider in the path must agree with the row. A mismatch
                # is a misconfigured webhook, and guessing is worse than 404.
                ChannelConnection.provider == provider,
                ChannelConnection.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if connection is None:
        raise HTTPException(status_code=404, detail="unknown connection")

    try:
        adapter = build_adapter(connection)
    except UnknownProvider:
        raise HTTPException(status_code=404, detail="unknown connection") from None

    # Raw bytes, not the parsed body: a signature covers the exact bytes sent,
    # and re-serialising a parsed dict will not reproduce them.
    raw_body = await request.body()
    if not adapter.verify_webhook(request.headers, raw_body):
        raise HTTPException(status_code=403, detail="bad signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        raise HTTPException(status_code=400, detail="malformed payload") from None

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    try:
        envelopes = adapter.parse_inbound(payload)
    except (ValueError, KeyError, TypeError, OverflowError):
        raise HTTPException(status_code=400, detail="malformed payload") from None

    # The database is the authoritative receipt log. A Redis claim before
    # persistence can lose an update when persistence or queue publication fails.
    event_ids = []
    for envelope in envelopes:
        statement = insert(InboundEvent).values(
            connection_id=connection.id,
            provider=provider,
            provider_update_id=envelope.provider_update_id,
            payload=payload,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(constraint="uq_inbound_events_dedupe")
        await db.execute(statement)
        event = (await db.execute(select(InboundEvent).where(
            InboundEvent.connection_id == connection.id,
            InboundEvent.provider == provider,
            InboundEvent.provider_update_id == envelope.provider_update_id,
        ))).scalar_one()
        if event.enqueued_at is None:
            event_ids.append(event.id)
    await db.commit()

    # Persist the complete batch before publishing any tasks. If publication
    # fails, a provider retry finds the durable, unpublished rows and retries.
    for event_id in dict.fromkeys(event_ids):
        event = await db.get(InboundEvent, event_id)
        try:
            await queue.enqueue(event_id)
        except Exception:
            raise HTTPException(status_code=503, detail="queue unavailable; retry delivery") from None
        event.enqueued_at = datetime.now(timezone.utc)
        await db.commit()

    return Response(status_code=200)
