"""The pipeline, now that conversations exist.

The handoff check the original pipeline left a comment for is the important
one: a conversation a human has taken over must not get a bot reply on top of
what the human is saying.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.channels.fake.adapter import FakeAdapter
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.message import DeliveryStatus, Direction, Message, SenderType
from app.models.shop import Shop
from app.runtime.pipeline import run_inbound_pipeline
from app.runtime.brain import EchoBrain

pytestmark = pytest.mark.integration


def _session_factory(db_session):
    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    return _Factory()


async def _connection(db) -> ChannelConnection:
    merchant = Merchant(name=f"M{datetime.now(timezone.utc).timestamp()}")
    db.add(merchant)
    await db.flush()
    shop = Shop(merchant_id=merchant.id, name="S", platform="standalone")
    db.add(shop)
    await db.flush()
    bot = Bot(shop_id=shop.id, name="B")
    db.add(bot)
    await db.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="fake", external_ref=f"r{bot.id}")
    conn.set_credentials({})
    db.add(conn)
    await db.flush()
    return conn


async def _event(db, conn, update_id="u1", text="where is my parcel") -> InboundEvent:
    payload = {
        "updates": [
            {
                "update_id": update_id,
                "thread": "t1",
                "from": "c1",
                "ts": 1_757_000_000,
                "text": text,
            }
        ]
    }
    event = InboundEvent(
        connection_id=conn.id,
        provider="fake",
        provider_update_id=update_id,
        payload=payload,
    )
    db.add(event)
    await db.flush()
    return event


@pytest.fixture
def run(db_session, monkeypatch):
    import app.runtime.pipeline as pipeline

    async def _run(event_id: int, adapter_class=FakeAdapter):
        sent: list = []

        class _Recording(adapter_class):
            async def send(self, connection, out):
                result = await super().send(connection, out)
                if result.ok:
                    sent.append(out)
                return result

        monkeypatch.setattr(
            pipeline, "build_adapter", lambda c, webhook_url=None: _Recording()
        )
        await run_inbound_pipeline(
            event_id, session_factory=_session_factory(db_session), brain=EchoBrain()
        )
        return sent

    return _run


async def _conversations(db) -> list[Conversation]:
    return list((await db.execute(select(Conversation))).scalars().all())


async def _messages(db) -> list[Message]:
    return list(
        (await db.execute(select(Message).order_by(Message.id))).scalars().all()
    )


# --- conversation creation --------------------------------------------------


async def test_an_inbound_message_creates_a_conversation(db_session, run):
    conn = await _connection(db_session)
    event = await _event(db_session, conn)

    await run(event.id)

    conversations = await _conversations(db_session)
    assert len(conversations) == 1
    assert conversations[0].external_thread_id == "t1"
    assert conversations[0].customer_ref == "c1"
    assert conversations[0].handoff_state is HandoffState.BOT


async def test_the_tenant_key_is_copied_from_the_bot_chain(db_session, run):
    """The denormalised merchant_id is only safe if it is always right."""
    conn = await _connection(db_session)
    event = await _event(db_session, conn)

    await run(event.id)

    conversation = (await _conversations(db_session))[0]
    bot = await db_session.get(Bot, conn.bot_id)
    shop = await db_session.get(Shop, bot.shop_id)
    assert conversation.merchant_id == shop.merchant_id


async def test_a_second_message_reuses_the_same_conversation(db_session, run):
    conn = await _connection(db_session)
    first = await _event(db_session, conn, update_id="u1")
    second = await _event(db_session, conn, update_id="u2", text="hello again")

    await run(first.id)
    await run(second.id)

    assert len(await _conversations(db_session)) == 1


async def test_both_sides_of_the_exchange_are_stored(db_session, run):
    conn = await _connection(db_session)
    event = await _event(db_session, conn)

    await run(event.id)

    messages = await _messages(db_session)
    assert [(m.direction, m.sender_type) for m in messages] == [
        (Direction.INBOUND, SenderType.CUSTOMER),
        (Direction.OUTBOUND, SenderType.BOT),
    ]
    assert messages[1].text == "botly received: where is my parcel"
    assert messages[1].delivery_status is DeliveryStatus.SENT


async def test_last_inbound_at_is_recorded_for_the_window_rule(db_session, run):
    """This is the field the dispatcher's session-window check reads. Task 9
    made it a parameter so the dispatcher would not have to wait for this
    table; this is the wire finally being connected."""
    conn = await _connection(db_session)
    event = await _event(db_session, conn)

    await run(event.id)

    conversation = (await _conversations(db_session))[0]
    assert conversation.last_inbound_at is not None
    assert conversation.last_message_at is not None


# --- the handoff check ------------------------------------------------------


async def test_a_conversation_a_human_owns_gets_no_bot_reply(db_session, run):
    """The check the original pipeline left a TODO for. A bot talking over an
    agent is worse than a bot saying nothing."""
    conn = await _connection(db_session)
    first = await _event(db_session, conn, update_id="u1")
    await run(first.id)

    conversation = (await _conversations(db_session))[0]
    conversation.handoff_state = HandoffState.HUMAN
    db_session.add(conversation)
    await db_session.flush()

    second = await _event(db_session, conn, update_id="u2", text="are you there")
    sent = await run(second.id)

    assert sent == []
    messages = await _messages(db_session)
    assert messages[-1].text == "are you there"
    assert messages[-1].sender_type is SenderType.CUSTOMER


async def test_the_message_is_still_stored_when_a_human_owns_it(db_session, run):
    """Silence from the bot must not mean the message is lost -- the agent has
    to see what the customer just said."""
    conn = await _connection(db_session)
    first = await _event(db_session, conn)
    await run(first.id)
    conversation = (await _conversations(db_session))[0]
    conversation.handoff_state = HandoffState.HUMAN
    db_session.add(conversation)
    await db_session.flush()

    second = await _event(db_session, conn, update_id="u2", text="hello?")
    await run(second.id)

    texts = [m.text for m in await _messages(db_session)]
    assert "hello?" in texts


async def test_a_muted_bot_stays_quiet_even_in_bot_state(db_session, run):
    """bot_muted_until is the safety net for a release that raced with an
    inbound message."""
    conn = await _connection(db_session)
    first = await _event(db_session, conn)
    await run(first.id)
    conversation = (await _conversations(db_session))[0]
    conversation.bot_muted_until = datetime.now(timezone.utc) + timedelta(minutes=10)
    db_session.add(conversation)
    await db_session.flush()

    second = await _event(db_session, conn, update_id="u2", text="still there?")
    sent = await run(second.id)

    assert sent == []


async def test_an_expired_mute_lets_the_bot_speak_again(db_session, run):
    conn = await _connection(db_session)
    first = await _event(db_session, conn)
    await run(first.id)
    conversation = (await _conversations(db_session))[0]
    conversation.bot_muted_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(conversation)
    await db_session.flush()

    second = await _event(db_session, conn, update_id="u2", text="hello")
    sent = await run(second.id)

    assert len(sent) == 1


# --- escalation -------------------------------------------------------------


async def test_a_refund_question_escalates_and_the_bot_says_nothing(db_session, run):
    conn = await _connection(db_session)
    event = await _event(db_session, conn, text="I want a refund please")

    sent = await run(event.id)

    assert sent == []
    conversation = (await _conversations(db_session))[0]
    assert conversation.handoff_state is HandoffState.PENDING_HUMAN
    assert "refund" in conversation.escalation_reason or "money" in (
        conversation.escalation_reason or ""
    )


async def test_an_escalated_conversation_is_not_assigned_to_anyone_yet(db_session, run):
    """pending_human is a queue, not an assignment. Auto-assigning would put
    it in one agent's list and out of everyone else's view."""
    conn = await _connection(db_session)
    event = await _event(db_session, conn, text="let me talk to a real person")

    await run(event.id)

    conversation = (await _conversations(db_session))[0]
    assert conversation.handoff_state is HandoffState.PENDING_HUMAN
    assert conversation.assignee_id is None


async def test_repeated_bot_turns_eventually_escalate(db_session, run):
    """Three answers that did not land, using the default threshold."""
    conn = await _connection(db_session)
    for index in range(3):
        event = await _event(db_session, conn, update_id=f"u{index}", text="still no")
        await run(event.id)

    conversation = (await _conversations(db_session))[0]
    assert conversation.handoff_state is HandoffState.PENDING_HUMAN


async def test_a_failed_send_is_recorded_on_the_message(db_session, run):
    """"delivery failed" has to be visible on the message an agent is looking
    at, not only in a failed_jobs row nothing reads."""
    from app.channels.types import SendResult

    class _Rejects(FakeAdapter):
        async def send(self, connection, out):
            return SendResult(ok=False, error="recipient blocked", retryable=False)

    conn = await _connection(db_session)
    event = await _event(db_session, conn)

    await run(event.id, adapter_class=_Rejects)

    outbound = [m for m in await _messages(db_session) if m.direction is Direction.OUTBOUND]
    assert len(outbound) == 1
    assert outbound[0].delivery_status is DeliveryStatus.FAILED
    assert outbound[0].error == "recipient blocked"


async def test_a_replayed_event_does_not_duplicate_messages(db_session, run):
    conn = await _connection(db_session)
    event = await _event(db_session, conn)

    await run(event.id)
    await run(event.id)

    assert len(await _messages(db_session)) == 2
