"""Channel ingress.

The order of operations here is a correctness requirement, not a style: verify
the signature against the raw bytes, dedupe, persist raw, ACK 200, and only
then enqueue. Nothing slow is allowed in this function -- no LLM call, no
outbound HTTP, no waiting on a task result. A slow ACK makes the provider
retry, and a retry is a second reply to the customer.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.registry import UnknownProvider, build_adapter
from app.core.config import settings
from app.core.database import get_db
from app.ingress.dedupe import DedupeStore, RedisDedupeStore, dedupe_key
from app.ingress.queue import InboundQueue
from app.models.channel_connection import ChannelConnection
from app.models.inbound_event import InboundEvent

router = APIRouter(tags=["webhooks"])

_redis_client: Redis | None = None


def get_dedupe_store() -> DedupeStore:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL)
    return RedisDedupeStore(_redis_client, ttl_seconds=settings.DEDUPE_TTL_SECONDS)


def get_inbound_queue() -> InboundQueue:
    from app.worker.queue import CeleryInboundQueue

    return CeleryInboundQueue()


@router.post("/webhooks/{provider}/{connection_id}")
async def receive_webhook(
    provider: str,
    connection_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    dedupe: DedupeStore = Depends(get_dedupe_store),
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

    envelopes = adapter.parse_inbound(payload)
    if not envelopes:
        # A delivery receipt or a poll answer. Nothing to run, but it did
        # arrive, and the provider still needs its 200.
        return Response(status_code=200)

    for envelope in envelopes:
        if not await dedupe.claim(
            dedupe_key(envelope.provider, envelope.provider_update_id)
        ):
            continue

        event = InboundEvent(
            connection_id=connection.id,
            provider=envelope.provider,
            provider_update_id=envelope.provider_update_id,
            payload=payload,
        )
        db.add(event)
        try:
            await db.flush()
        except IntegrityError:
            # Redis missed it -- flushed, or a race. The unique constraint is
            # the backstop, and losing that race is a duplicate, not an error.
            await db.rollback()
            continue

        await db.commit()
        await queue.enqueue(event.id)

    return Response(status_code=200)
