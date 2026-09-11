"""Dashboard totals are real and stay inside the signed-in merchant."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import TenantScope, tenant
from app.core.database import get_db
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.conversation import Conversation, HandoffState
from app.models.merchant import Merchant
from app.models.message import Direction, Message, SenderType
from app.models.shop import Shop
from app.models.user import User

pytestmark = pytest.mark.integration


async def _merchant_graph(db, suffix: str):
    merchant = Merchant(name=f"Merchant {suffix}")
    db.add(merchant)
    await db.flush()
    shop = Shop(
        merchant_id=merchant.id,
        name=f"Shop {suffix}",
        platform="standalone",
        external_shop_id=suffix,
    )
    db.add(shop)
    await db.flush()
    bot = Bot(shop_id=shop.id, name=f"Order bot {suffix}")
    db.add(bot)
    await db.flush()
    connection = ChannelConnection(
        bot_id=bot.id,
        provider="fake",
        external_ref=f"connection-{suffix}",
        status=ChannelConnectionStatus.ACTIVE,
    )
    db.add(connection)
    await db.flush()
    return merchant, bot, connection


async def _conversation(
    db,
    merchant,
    bot,
    connection,
    suffix: str,
    state: HandoffState,
    read: bool = False,
):
    now = datetime.now(timezone.utc)
    conversation = Conversation(
        merchant_id=merchant.id,
        bot_id=bot.id,
        channel_connection_id=connection.id,
        external_thread_id=f"thread-{suffix}",
        customer_ref=f"customer-{suffix}",
        customer_name=f"Customer {suffix}",
        handoff_state=state,
        last_message_at=now,
        agent_last_read_at=now + timedelta(seconds=1) if read else None,
    )
    db.add(conversation)
    await db.flush()
    db.add(
        Message(
            conversation_id=conversation.id,
            merchant_id=merchant.id,
            direction=Direction.INBOUND,
            sender_type=SenderType.CUSTOMER,
            text=f"Message {suffix}",
            created_at=now,
            updated_at=now,
        )
    )
    await db.flush()
    return conversation


async def test_dashboard_is_tenant_scoped_and_uses_real_counts(db_session):
    merchant, bot, connection = await _merchant_graph(db_session, "visible")
    other, other_bot, other_connection = await _merchant_graph(db_session, "hidden")

    pending = await _conversation(
        db_session,
        merchant,
        bot,
        connection,
        "pending",
        HandoffState.PENDING_HUMAN,
    )
    bot_conversation = await _conversation(
        db_session, merchant, bot, connection, "bot", HandoffState.BOT, read=True
    )
    await _conversation(
        db_session,
        other,
        other_bot,
        other_connection,
        "other",
        HandoffState.PENDING_HUMAN,
    )

    user = User(
        merchant_id=merchant.id,
        email="dashboard@example.com",
        password_hash="not-used",
        name="Aina",
    )
    db_session.add(user)
    await db_session.flush()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[tenant] = lambda: TenantScope(user)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/dashboard/summary")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["counts"] == {
        "needs_attention": 1,
        "unread": 1,
        "bot_handling": 1,
        "active_channels": 1,
        "active_bots": 1,
    }
    assert {item["id"] for item in body["recent_conversations"]} == {
        pending.id,
        bot_conversation.id,
    }
    assert all("hidden" not in item["customer_ref"] for item in body["recent_conversations"])
    assert body["recent_conversations"][0]["last_message_preview"].startswith("Message")
