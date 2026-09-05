from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password, hash_session_token, new_session_token
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.login_session import LoginSession
from app.models.merchant import Merchant
from app.models.message import DeliveryStatus, Direction, Message, SenderType
from app.models.shop import Shop
from app.models.user import User

pytestmark = pytest.mark.integration


async def _tenant(db):
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
    db.add(conn)
    await db.flush()
    return merchant, bot, conn


async def _conversation(db, **overrides) -> Conversation:
    merchant, bot, conn = await _tenant(db)
    fields = dict(
        merchant_id=merchant.id,
        bot_id=bot.id,
        channel_connection_id=conn.id,
        external_thread_id="t1",
        customer_ref="c1",
    )
    fields.update(overrides)
    conversation = Conversation(**fields)
    db.add(conversation)
    await db.flush()
    return conversation


# --- users and sessions -----------------------------------------------------


async def test_a_user_belongs_to_a_merchant(db_session):
    merchant, _, _ = await _tenant(db_session)
    user = User(
        merchant_id=merchant.id,
        email="budi@example.com",
        password_hash=hash_password("x"),
        name="Budi",
    )
    db_session.add(user)
    await db_session.flush()

    assert user.id is not None
    assert user.merchant_id == merchant.id


async def test_one_email_cannot_register_twice(db_session):
    """The email is the login identifier. Two rows for one identifier means
    which account you get depends on row order."""
    merchant, _, _ = await _tenant(db_session)
    for _ in range(2):
        db_session.add(
            User(
                merchant_id=merchant.id,
                email="dupe@example.com",
                password_hash=hash_password("x"),
                name="D",
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_a_session_stores_a_hash_not_the_token(db_session):
    """A database read must not be convertible straight into a live session."""
    merchant, _, _ = await _tenant(db_session)
    user = User(
        merchant_id=merchant.id,
        email="s@example.com",
        password_hash=hash_password("x"),
        name="S",
    )
    db_session.add(user)
    await db_session.flush()

    token = new_session_token()
    session = LoginSession(
        user_id=user.id,
        token_hash=hash_session_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db_session.add(session)
    await db_session.flush()

    assert token not in session.token_hash


# --- conversations ----------------------------------------------------------


async def test_a_new_conversation_starts_with_the_bot_in_charge(db_session):
    conversation = await _conversation(db_session)

    assert conversation.handoff_state is HandoffState.BOT
    assert conversation.assignee_id is None


async def test_one_thread_on_one_connection_is_one_conversation(db_session):
    """Without this constraint a burst of concurrent webhooks creates two
    conversations for one customer and the agent sees a split history."""
    conversation = await _conversation(db_session)
    db_session.add(
        Conversation(
            merchant_id=conversation.merchant_id,
            bot_id=conversation.bot_id,
            channel_connection_id=conversation.channel_connection_id,
            external_thread_id=conversation.external_thread_id,
            customer_ref="someone-else",
        )
    )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_the_same_thread_id_on_another_connection_is_a_separate_conversation(
    db_session,
):
    """Two providers -- or two bots on one provider -- will collide on thread
    ids sooner or later. The uniqueness is per connection, not global."""
    first = await _conversation(db_session)
    second = await _conversation(db_session, external_thread_id="t1")

    assert first.id != second.id


async def test_conversation_timestamps_are_timezone_aware(db_session):
    conversation = await _conversation(
        db_session, last_inbound_at=datetime.now(timezone.utc)
    )
    await db_session.commit()
    db_session.expunge_all()

    reloaded = (
        await db_session.execute(
            select(Conversation).where(Conversation.id == conversation.id)
        )
    ).scalar_one()

    assert reloaded.last_inbound_at.tzinfo is not None
    assert reloaded.created_at.tzinfo is not None


async def test_handoff_state_survives_a_reload_as_an_enum(db_session):
    """The bug this repo has already been bitten by once: a str-Enum in a
    String column loads back as a bare string, so `state is HandoffState.HUMAN`
    is False for any row that came from the database."""
    conversation = await _conversation(db_session, handoff_state=HandoffState.HUMAN)
    await db_session.commit()
    db_session.expunge_all()

    reloaded = (
        await db_session.execute(
            select(Conversation).where(Conversation.id == conversation.id)
        )
    ).scalar_one()

    assert reloaded.handoff_state is HandoffState.HUMAN


async def test_the_tenant_key_is_denormalised_onto_the_conversation(db_session):
    """merchant_id is on the row so a tenant filter is one indexed predicate
    rather than three joins -- a forgotten join is a cross-tenant leak that
    raises nothing."""
    conversation = await _conversation(db_session)

    assert "merchant_id" in Conversation.model_fields


# --- messages ---------------------------------------------------------------


async def test_a_message_records_who_sent_it_and_which_way_it_went(db_session):
    conversation = await _conversation(db_session)
    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=Direction.INBOUND,
        sender_type=SenderType.CUSTOMER,
        text="where is my parcel",
    )
    db_session.add(message)
    await db_session.flush()

    assert message.delivery_status is DeliveryStatus.SENT


async def test_an_outbound_message_can_record_a_permanent_delivery_failure(db_session):
    """This is what puts "delivery failed" in front of an agent. Before this
    column the dispatcher's permanent failure only reached failed_jobs, which
    no screen reads."""
    conversation = await _conversation(db_session)
    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=Direction.OUTBOUND,
        sender_type=SenderType.BOT,
        text="hello",
        delivery_status=DeliveryStatus.FAILED,
        error="recipient blocked",
    )
    db_session.add(message)
    await db_session.flush()
    await db_session.commit()
    db_session.expunge_all()

    reloaded = (
        await db_session.execute(select(Message).where(Message.id == message.id))
    ).scalar_one()

    assert reloaded.delivery_status is DeliveryStatus.FAILED
    assert reloaded.error == "recipient blocked"


async def test_an_agent_reply_records_which_agent_sent_it(db_session):
    conversation = await _conversation(db_session)
    user = User(
        merchant_id=conversation.merchant_id,
        email="agent@example.com",
        password_hash=hash_password("x"),
        name="A",
    )
    db_session.add(user)
    await db_session.flush()

    message = Message(
        conversation_id=conversation.id,
        merchant_id=conversation.merchant_id,
        direction=Direction.OUTBOUND,
        sender_type=SenderType.AGENT,
        sender_user_id=user.id,
        text="let me check that for you",
    )
    db_session.add(message)
    await db_session.flush()

    assert message.sender_user_id == user.id


async def test_deleting_a_conversation_takes_its_messages_with_it(db_session):
    conversation = await _conversation(db_session)
    db_session.add(
        Message(
            conversation_id=conversation.id,
            merchant_id=conversation.merchant_id,
            direction=Direction.INBOUND,
            sender_type=SenderType.CUSTOMER,
            text="hi",
        )
    )
    await db_session.flush()

    await db_session.delete(conversation)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            select(Message).where(Message.conversation_id == conversation.id)
        )
    ).scalars().all()

    assert remaining == []
