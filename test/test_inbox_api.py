from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import conversations as conversations_api
from app.api.deps import TenantScope, tenant
from app.core.database import get_db
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.conversation import Conversation, HandoffState
from app.models.merchant import Merchant
from app.models.message import Direction, Message, SenderType
from app.models.shop import Shop
from app.models.user import User

pytestmark = pytest.mark.integration


async def _graph(db, suffix: str):
    merchant = Merchant(name=f"Inbox merchant {suffix}")
    db.add(merchant)
    await db.flush()
    shop = Shop(merchant_id=merchant.id, name="Store", platform="standalone")
    db.add(shop)
    await db.flush()
    bot = Bot(shop_id=shop.id, name="Order assistant")
    db.add(bot)
    await db.flush()
    connection = ChannelConnection(
        bot_id=bot.id, provider="fake", external_ref=f"inbox-{suffix}"
    )
    connection.set_credentials({})
    db.add(connection)
    user = User(
        merchant_id=merchant.id,
        email=f"inbox-{suffix}@example.com",
        password_hash="not-used",
        name=f"Agent {suffix}",
    )
    db.add(user)
    await db.flush()
    return merchant, bot, connection, user


async def _conversation(db, graph, thread: str, **values):
    merchant, bot, connection, _ = graph
    conversation = Conversation(
        merchant_id=merchant.id,
        bot_id=bot.id,
        channel_connection_id=connection.id,
        external_thread_id=thread,
        customer_ref=f"customer-{thread}",
        customer_name=values.pop("customer_name", "Siti Rahman"),
        **values,
    )
    db.add(conversation)
    await db.flush()
    return conversation


@pytest.fixture
def wired(db_session):
    async def apply(graph):
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[tenant] = lambda: TenantScope(graph[3])

    yield apply
    app.dependency_overrides.clear()


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_list_is_tenant_scoped_filterable_and_carries_preview(db_session, wired):
    mine = await _graph(db_session, "mine")
    theirs = await _graph(db_session, "theirs")
    await wired(mine)
    now = datetime.now(timezone.utc)
    visible = await _conversation(
        db_session,
        mine,
        "visible",
        handoff_state=HandoffState.PENDING_HUMAN,
        last_message_at=now,
    )
    await _conversation(
        db_session,
        theirs,
        "hidden",
        customer_name="Hidden customer",
        last_message_at=now,
    )
    db_session.add(
        Message(
            conversation_id=visible.id,
            merchant_id=mine[0].id,
            direction=Direction.INBOUND,
            sender_type=SenderType.CUSTOMER,
            text="I need a refund",
        )
    )
    await db_session.flush()

    async with _client() as http:
        response = await http.get(
            "/conversations", params={"state": "pending_human", "unread": "true"}
        )
        counts = await http.get("/conversations/counts")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [visible.id]
    assert response.json()["items"][0]["last_message_preview"] == "I need a refund"
    assert counts.json()["needs_attention"] == 1


async def test_detail_messages_read_and_cross_tenant_404(db_session, wired):
    mine = await _graph(db_session, "detail-mine")
    theirs = await _graph(db_session, "detail-theirs")
    await wired(mine)
    now = datetime.now(timezone.utc)
    visible = await _conversation(db_session, mine, "detail", last_message_at=now)
    hidden = await _conversation(db_session, theirs, "secret")
    for index, text in enumerate(("first", "second")):
        db_session.add(
            Message(
                conversation_id=visible.id,
                merchant_id=mine[0].id,
                direction=Direction.INBOUND,
                sender_type=SenderType.CUSTOMER,
                text=text,
                created_at=now + timedelta(seconds=index),
            )
        )
    await db_session.flush()

    async with _client() as http:
        detail = await http.get(f"/conversations/{visible.id}")
        messages = await http.get(f"/conversations/{visible.id}/messages")
        read = await http.post(f"/conversations/{visible.id}/read")
        denied = await http.get(f"/conversations/{hidden.id}")

    assert detail.status_code == 200
    assert detail.json()["send_policy"]["can_send_freeform"] is True
    assert [item["text"] for item in messages.json()["items"]] == ["second", "first"]
    assert read.status_code == 204
    assert denied.status_code == 404


async def test_takeover_send_release_and_resolve(db_session, wired, monkeypatch):
    graph = await _graph(db_session, "actions")
    await wired(graph)
    conversation = await _conversation(
        db_session,
        graph,
        "actions",
        handoff_state=HandoffState.PENDING_HUMAN,
        last_inbound_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        conversations_api, "send_limiter", lambda: InMemoryTokenBucket()
    )

    async with _client() as http:
        takeover = await http.post(f"/conversations/{conversation.id}/takeover")
        sent = await http.post(
            f"/conversations/{conversation.id}/messages",
            json={"text": "I am checking this now"},
        )
        release = await http.post(f"/conversations/{conversation.id}/release")
        resolve = await http.post(f"/conversations/{conversation.id}/resolve")

    assert takeover.json()["assignee"]["id"] == graph[3].id
    assert sent.status_code == 201
    assert sent.json()["sender_type"] == "agent"
    assert release.json()["handoff_state"] == "bot"
    assert resolve.json()["handoff_state"] == "resolved"


async def test_reply_requires_takeover(db_session, wired, monkeypatch):
    graph = await _graph(db_session, "guard")
    await wired(graph)
    conversation = await _conversation(
        db_session, graph, "guard", handoff_state=HandoffState.BOT
    )
    monkeypatch.setattr(
        conversations_api, "send_limiter", lambda: InMemoryTokenBucket()
    )
    async with _client() as http:
        response = await http.post(
            f"/conversations/{conversation.id}/messages", json={"text": "hello"}
        )
    assert response.status_code == 409
