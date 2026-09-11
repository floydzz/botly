"""Event to conversation to reply.

This is the function the Celery task calls, and it is plain async code with no
Celery import -- so it can be tested without a broker, and the queue stays a
seam rather than a framework the logic is welded to.

The order here is a correctness requirement. The customer's message is stored
*before* anything decides what to do about it, so that a crash in the brain or
the dispatcher still leaves the agent looking at what the customer said. The
handoff check comes next, before the brain is invoked at all: a bot talking
over a human is worse than a bot saying nothing.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.channels.registry import UnknownProvider, build_adapter
from app.channels.types import InboundEnvelope
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.dispatch.dispatcher import OutboundDispatcher
from app.dispatch.ratelimit import default_limiter
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.dispatch.record import record_outbound
from app.models.message import Direction, Message, SenderType
from app.models.shop import Shop
from app.runtime.brain import Brain, DraftReply
from app.llm.brain import MeteredBrain
from app.runtime.escalation import EscalationPolicy, default_policy

# States in which the bot must stay quiet. pending_human is included on
# purpose: a conversation waiting for a person is not a conversation the bot
# should keep trying to answer.
_BOT_IS_SILENT = (HandoffState.PENDING_HUMAN, HandoffState.HUMAN)


async def run_inbound_pipeline(
    event_id: int,
    session_factory=None,
    brain: Brain | None = None,
    limiter=None,
    policy: EscalationPolicy | None = None,
    billing_session_factory=None,
    provider_factory=None,
) -> None:
    session_factory = session_factory or AsyncSessionLocal
    policy = policy or default_policy()

    async with session_factory() as db:
        event = (await db.execute(update(InboundEvent).where(
            InboundEvent.id == event_id, InboundEvent.status == InboundEventStatus.PENDING,
        ).values(status=InboundEventStatus.PROCESSING).returning(InboundEvent))).scalar_one_or_none()
        if event is None:
            # Already handled, or the row is gone. acks_late means a worker
            # that died mid-task gets the message again; that redelivery must
            # be a no-op, not a second reply.
            return

        # Durable claim: a crashed/ambiguous external call requires explicit review.
        # A second worker must never start another paid call for the same event.
        await db.commit()

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
            await _mark_processed(db, event)
            return

        bot = await db.get(Bot, connection.bot_id)
        if bot is None or bot.deleted_at is not None:
            await _fail(db, event, connection.id, "the bot no longer exists")
            return
        shop = await db.get(Shop, bot.shop_id)
        if shop is None or shop.deleted_at is not None:
            await _fail(db, event, connection.id, "the shop no longer exists")
            return

        dispatcher = OutboundDispatcher(
            adapter,
            # Redis, not in-process: the API is a second sender against the
            # same provider quota, and two full buckets double the effective
            # outbound rate. Tests inject InMemoryTokenBucket.
            limiter=limiter or default_limiter(),
            max_attempts=settings.OUTBOUND_MAX_ATTEMPTS,
        )

        for envelope in envelopes:
            conversation = await _get_or_create_conversation(
                db, connection, bot, shop.merchant_id, envelope
            )
            inbound_message = await _store_inbound(db, conversation, envelope)
            await db.commit()
            # Serialize processing against other messages in this conversation.
            # Billing commits use a separate session so this lock spans the send.
            conversation = (await db.execute(select(Conversation).where(
                Conversation.id == conversation.id,
            ).with_for_update().execution_options(populate_existing=True))).scalar_one()

            if _bot_must_stay_quiet(conversation):
                continue

            turns = await _replies_since_a_human_spoke(db, conversation) + 1
            preflight = await policy.evaluate(envelope, draft=DraftReply(text=""), bot_turns=turns, max_bot_turns=bot.escalation_max_bot_turns)
            if preflight.escalate:
                _escalate(conversation, preflight.reason)
                db.add(conversation)
                continue
            selected_brain = brain
            if selected_brain is None and bot.llm_model_id is not None:
                options = {"provider_factory": provider_factory} if provider_factory else {}
                selected_brain = MeteredBrain(db=db, bot=bot, conversation=conversation, event_id=event.id, inbound_message_id=inbound_message.id, session_factory=billing_session_factory, **options)
            if selected_brain is None:
                _escalate(conversation, "select a model before enabling this bot")
                db.add(conversation)
                continue
            draft = await selected_brain.respond(envelope)
            signal = await policy.evaluate(
                envelope,
                draft=draft,
                # The reply about to be made, counted 1-based: on the third
                # attempt the threshold should stop it, not permit it and
                # catch the fourth.
                bot_turns=turns,
                max_bot_turns=bot.escalation_max_bot_turns,
            )
            if signal.escalate:
                _escalate(conversation, signal.reason)
                db.add(conversation)
                continue

            outcome = await dispatcher.dispatch(
                connection, draft, last_inbound_at=conversation.last_inbound_at,
                external_thread_id=conversation.external_thread_id,
            )
            if outcome.escalated:
                # The channel itself refused -- a closed session window, or
                # media on a text-only channel. Same destination as any other
                # escalation: a person.
                _escalate(conversation, outcome.reason)
                db.add(conversation)
                continue

            record_outbound(
                db,
                conversation,
                draft.text,
                [a.model_dump() for a in draft.attachments],
                outcome,
                SenderType.BOT,
            )

            if outcome.permanent_failure:
                await _fail(db, event, connection.id, outcome.permanent_failure)
                return

        await _mark_processed(db, event)


async def _get_or_create_conversation(
    db,
    connection: ChannelConnection,
    bot: Bot,
    merchant_id: int,
    envelope: InboundEnvelope,
) -> Conversation:
    await db.execute(insert(Conversation).values(
        merchant_id=merchant_id, bot_id=bot.id, channel_connection_id=connection.id,
        external_thread_id=envelope.external_thread_id, customer_ref=envelope.sender_ref,
    ).on_conflict_do_nothing(constraint="uq_conversations_connection_thread"))
    conversation = (
        await db.execute(
            select(Conversation).where(
                Conversation.channel_connection_id == connection.id,
                Conversation.external_thread_id == envelope.external_thread_id,
            ).with_for_update().execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()

    if conversation.handoff_state is HandoffState.RESOLVED:
        # A closed conversation that gets a new message is a new question.
        conversation.handoff_state = HandoffState.BOT
        conversation.escalation_reason = None

    return conversation


async def _store_inbound(db, conversation: Conversation, envelope: InboundEnvelope):
    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=Direction.INBOUND,
        sender_type=SenderType.CUSTOMER,
        text=envelope.text,
        attachments=[a.model_dump() for a in envelope.attachments],
        provider_message_id=envelope.provider_message_id,
    )
    db.add(message)
    conversation.last_inbound_at = envelope.sent_at
    conversation.last_message_at = envelope.sent_at
    db.add(conversation)
    await db.flush()
    return message


def _bot_must_stay_quiet(conversation: Conversation) -> bool:
    if conversation.handoff_state in _BOT_IS_SILENT:
        return True
    muted_until = conversation.bot_muted_until
    if muted_until is None:
        return False
    return muted_until > datetime.now(timezone.utc)


def _escalate(conversation: Conversation, reason: str | None) -> None:
    conversation.handoff_state = HandoffState.PENDING_HUMAN
    conversation.escalation_reason = reason
    # Deliberately not assigned to anyone: pending_human is a queue every
    # agent can see, and auto-assigning would move it into one agent's list
    # and out of everyone else's view.


async def _replies_since_a_human_spoke(db, conversation: Conversation) -> int:
    """How many times the bot has answered without a person intervening.

    Counted rather than kept as a column: a counter has to be corrected on
    every write, and it drifts the first time one path forgets.
    """
    last_agent_message = (
        await db.execute(
            select(func.max(Message.created_at)).where(
                Message.conversation_id == conversation.id,
                Message.sender_type == SenderType.AGENT,
            )
        )
    ).scalar_one_or_none()

    statement = (
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.sender_type == SenderType.BOT,
        )
    )
    if last_agent_message is not None:
        statement = statement.where(Message.created_at > last_agent_message)
    return (await db.execute(statement)).scalar_one()


async def _mark_processed(db, event: InboundEvent) -> None:
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
