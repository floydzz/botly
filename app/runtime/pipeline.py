"""Event to reply.

This is the function the Celery task calls, and it is plain async code with no
Celery import -- so it can be tested without a broker, and the queue stays a
seam rather than a framework the logic is welded to.

What is deliberately missing: the handoff check. The spec puts it first in the
runtime -- a conversation in `human` state must store the message and push it
to the inbox without invoking the LLM -- but Conversation is build-order step
4. When that model lands, the check goes in immediately after the event is
loaded and before the brain is called.
"""

from datetime import datetime, timezone

from sqlalchemy import select

from app.channels.registry import UnknownProvider, build_adapter
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.dispatch.dispatcher import OutboundDispatcher
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.models.channel_connection import ChannelConnection
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.runtime.brain import Brain, EchoBrain


async def run_inbound_pipeline(
    event_id: int,
    session_factory=None,
    brain: Brain | None = None,
    limiter=None,
) -> None:
    session_factory = session_factory or AsyncSessionLocal
    brain = brain or EchoBrain()

    async with session_factory() as db:
        event = await db.get(InboundEvent, event_id)
        if event is None or event.status is not InboundEventStatus.PENDING:
            # Already handled, or the row is gone. acks_late means a worker
            # that died mid-task gets the message again; that redelivery must
            # be a no-op, not a second reply.
            return

        connection = (
            await db.execute(
                select(ChannelConnection).where(
                    ChannelConnection.id == event.connection_id
                )
            )
        ).scalar_one_or_none()
        if connection is None:
            await _fail(db, event, None, "the channel connection no longer exists")
            return

        try:
            adapter = build_adapter(connection)
        except (UnknownProvider, ValueError) as exc:
            await _fail(db, event, connection.id, str(exc))
            return

        envelopes = adapter.parse_inbound(event.payload)
        if not envelopes:
            event.status = InboundEventStatus.PROCESSED
            event.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        dispatcher = OutboundDispatcher(
            adapter,
            limiter=limiter
            or InMemoryTokenBucket(
                capacity=settings.OUTBOUND_RATE_CAPACITY,
                refill_per_second=settings.OUTBOUND_RATE_REFILL_PER_SECOND,
            ),
            max_attempts=settings.OUTBOUND_MAX_ATTEMPTS,
        )

        for envelope in envelopes:
            draft = await brain.respond(envelope)
            outcome = await dispatcher.dispatch(
                connection, draft, last_inbound_at=envelope.sent_at
            )
            # outcome.escalated is deliberately not acted on yet: setting
            # handoff_state and pushing to the inbox needs Conversation, which
            # is build-order step 4. Until then an escalation means the bot
            # stays silent, which is the safe half of the behaviour.
            if outcome.permanent_failure:
                await _fail(db, event, connection.id, outcome.permanent_failure)
                return

        event.status = InboundEventStatus.PROCESSED
        event.processed_at = datetime.now(timezone.utc)
        await db.commit()


async def _fail(db, event: InboundEvent, connection_id: int | None, error: str) -> None:
    """Mark the event failed and leave a row a human can find.

    A poison message must leave the queue rather than block it, and it must not
    leave without a trace -- the inbox shows a permanent send failure as
    "delivery failed".
    """
    event.status = InboundEventStatus.FAILED
    event.error = error
    event.processed_at = datetime.now(timezone.utc)
    db.add(
        FailedJob(
            kind="inbound",
            connection_id=connection_id,
            inbound_event_id=event.id,
            payload=event.payload,
            error=error,
            attempts=1,
        )
    )
    await db.commit()
