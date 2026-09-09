"""The shared outbound recorder.

Covered once here rather than twice through its two callers: the whole point of
extracting it is that the bot path and the agent path stop being able to
disagree about what a failed send looks like in the thread.
"""

from datetime import datetime, timezone

import pytest

from app.channels.types import SendResult
from app.core.security import hash_password
from app.dispatch.dispatcher import DispatchOutcome
from app.dispatch.record import record_outbound
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation
from app.models.merchant import Merchant
from app.models.message import DeliveryStatus, Direction, SenderType
from app.models.shop import Shop
from app.models.user import User

pytestmark = pytest.mark.integration


async def _conversation(db) -> Conversation:
    merchant = Merchant(name=f"M{datetime.now(timezone.utc).timestamp()}")
    db.add(merchant)
    await db.flush()
    shop = Shop(merchant_id=merchant.id, name="S", platform="standalone")
    db.add(shop)
    await db.flush()
    bot = Bot(shop_id=shop.id, name="B")
    db.add(bot)
    await db.flush()
    connection = ChannelConnection(
        bot_id=bot.id, provider="fake", external_ref=f"r{bot.id}"
    )
    connection.set_credentials({})
    db.add(connection)
    await db.flush()
    conversation = Conversation(
        merchant_id=merchant.id,
        bot_id=bot.id,
        channel_connection_id=connection.id,
        external_thread_id=f"t{bot.id}",
        customer_ref="c1",
    )
    db.add(conversation)
    await db.flush()
    return conversation


async def test_a_successful_send_is_recorded_as_sent(db_session):
    conversation = await _conversation(db_session)
    outcome = DispatchOutcome(sent=(SendResult(ok=True, provider_message_id="p-1"),))

    message = record_outbound(
        db_session, conversation, "hello", [], outcome, SenderType.BOT
    )
    await db_session.flush()

    assert message.direction is Direction.OUTBOUND
    assert message.sender_type is SenderType.BOT
    assert message.delivery_status is DeliveryStatus.SENT
    assert message.provider_message_id == "p-1"
    assert message.error is None
    assert message.merchant_id == conversation.merchant_id


async def test_a_permanent_failure_is_recorded_with_its_error(db_session):
    """The agent must see their own failed message in the thread. Swallowing it
    as an error toast loses the text they typed."""
    conversation = await _conversation(db_session)
    outcome = DispatchOutcome(
        sent=(SendResult(ok=False, error="recipient blocked the bot"),),
        permanent_failure="recipient blocked the bot",
    )

    message = record_outbound(
        db_session, conversation, "hello", [], outcome, SenderType.BOT
    )
    await db_session.flush()

    assert message.delivery_status is DeliveryStatus.FAILED
    assert message.error == "recipient blocked the bot"


async def test_an_agent_message_carries_the_agent(db_session):
    conversation = await _conversation(db_session)
    user = User(
        merchant_id=conversation.merchant_id,
        email=f"a{conversation.id}@example.com",
        password_hash=hash_password("x"),
        name="Ani",
    )
    db_session.add(user)
    await db_session.flush()

    message = record_outbound(
        db_session,
        conversation,
        "on it",
        [],
        DispatchOutcome(sent=(SendResult(ok=True, provider_message_id="p-2"),)),
        SenderType.AGENT,
        sender_user_id=user.id,
    )
    await db_session.flush()

    assert message.sender_type is SenderType.AGENT
    assert message.sender_user_id == user.id


async def test_recording_advances_the_conversations_last_message_at(db_session):
    conversation = await _conversation(db_session)
    assert conversation.last_message_at is None

    record_outbound(
        db_session,
        conversation,
        "hello",
        [],
        DispatchOutcome(sent=(SendResult(ok=True),)),
        SenderType.BOT,
    )
    await db_session.flush()

    assert conversation.last_message_at is not None


async def test_a_partly_delivered_reply_keeps_the_first_chunks_id(db_session):
    """A long reply is several provider messages and only one column holds an
    id. The first is the one a human would quote."""
    conversation = await _conversation(db_session)
    outcome = DispatchOutcome(
        sent=(
            SendResult(ok=True, provider_message_id="p-1"),
            SendResult(ok=False, error="gave up"),
        ),
        permanent_failure="gave up",
    )

    message = record_outbound(
        db_session, conversation, "a long reply", [], outcome, SenderType.BOT
    )
    await db_session.flush()

    assert message.provider_message_id == "p-1"
    assert message.delivery_status is DeliveryStatus.FAILED
