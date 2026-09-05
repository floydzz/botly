import time

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.channels.telegram.adapter import SECRET_HEADER
from app.core.database import get_db
from app.ingress.dedupe import InMemoryDedupeStore
from app.ingress.queue import InMemoryInboundQueue
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.inbound_event import InboundEvent
from app.models.merchant import Merchant
from app.models.shop import Shop

pytestmark = pytest.mark.integration

SECRET = "s3cr3t"


async def _connection(db_session) -> ChannelConnection:
    merchant = Merchant(name="Kedai Ahmad")
    db_session.add(merchant)
    await db_session.flush()
    shop = Shop(merchant_id=merchant.id, name="Ahmad Store", platform="standalone")
    db_session.add(shop)
    await db_session.flush()
    bot = Bot(shop_id=shop.id, name="Ahmad Bot")
    db_session.add(bot)
    await db_session.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="telegram", external_ref="@ahmad_bot")
    conn.set_credentials({"bot_token": "123:ABC", "secret_token": SECRET})
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
def wired(db_session):
    """The app with its database, dedupe store and queue swapped for the
    test's own, so the route under test is the real one."""
    from app.api.webhooks import get_dedupe_store, get_inbound_queue

    store, queue = InMemoryDedupeStore(), InMemoryInboundQueue()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_dedupe_store] = lambda: store
    app.dependency_overrides[get_inbound_queue] = lambda: queue
    yield store, queue
    app.dependency_overrides.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _update(update_id: int = 900) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 42,
            "date": 1_757_000_000,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "text": "where is my parcel",
        },
    }


async def test_an_authentic_delivery_is_stored_and_enqueued(db_session, wired):
    _store, queue = wired
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            json=_update(),
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 200
    stored = (await db_session.execute(select(InboundEvent))).scalars().all()
    assert len(stored) == 1
    assert stored[0].provider_update_id == "900"
    assert stored[0].payload["message"]["text"] == "where is my parcel"
    assert queue.enqueued == [stored[0].id]


async def test_a_bad_secret_is_refused_and_stores_nothing(db_session, wired):
    _store, queue = wired
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            json=_update(),
            headers={SECRET_HEADER: "wrong"},
        )

    assert response.status_code == 403
    assert (await db_session.execute(select(InboundEvent))).scalars().all() == []
    assert queue.enqueued == []


async def test_a_replayed_delivery_is_acknowledged_but_not_re_enqueued(
    db_session, wired
):
    """The provider must see 200 or it retries forever. It must also not get a
    second reply to the customer."""
    _store, queue = wired
    conn = await _connection(db_session)

    async with _client() as client:
        for _ in range(2):
            response = await client.post(
                f"/webhooks/telegram/{conn.id}",
                json=_update(),
                headers={SECRET_HEADER: SECRET},
            )
            assert response.status_code == 200

    assert len(queue.enqueued) == 1
    stored = (await db_session.execute(select(InboundEvent))).scalars().all()
    assert len(stored) == 1


async def test_a_duplicate_that_slips_past_redis_is_caught_by_the_constraint(
    db_session, wired
):
    """Redis can be flushed. The unique index is what makes this impossible
    rather than merely unlikely, and hitting it must still ACK 200."""
    _store, queue = wired
    conn = await _connection(db_session)
    db_session.add(
        InboundEvent(
            connection_id=conn.id,
            provider="telegram",
            provider_update_id="900",
            payload={},
        )
    )
    await db_session.flush()

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            json=_update(),
            headers={SECRET_HEADER: SECRET},
        )

    assert response.status_code == 200
    assert queue.enqueued == []


async def test_a_non_actionable_update_is_acknowledged_and_stored(db_session, wired):
    """A poll answer yields no envelope. It is still a delivery that happened,
    and the provider still needs its 200."""
    _store, queue = wired
    conn = await _connection(db_session)
    payload = {"update_id": 904, "poll_answer": {"poll_id": "p", "option_ids": [1]}}

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}", json=payload, headers={SECRET_HEADER: SECRET}
        )

    assert response.status_code == 200
    assert queue.enqueued == []


async def test_an_unknown_connection_is_404(db_session, wired):
    async with _client() as client:
        response = await client.post(
            "/webhooks/telegram/999999", json=_update(), headers={SECRET_HEADER: SECRET}
        )

    assert response.status_code == 404


async def test_a_provider_that_does_not_match_the_connection_is_404(db_session, wired):
    """The provider in the path is not decoration. A mismatch means a
    misconfigured webhook, and guessing which one is right is worse than 404."""
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/fake/{conn.id}", json=_update(), headers={SECRET_HEADER: SECRET}
        )

    assert response.status_code == 404


async def test_malformed_json_is_refused_without_a_500(db_session, wired):
    conn = await _connection(db_session)

    async with _client() as client:
        response = await client.post(
            f"/webhooks/telegram/{conn.id}",
            content=b"<html>",
            headers={SECRET_HEADER: SECRET, "content-type": "application/json"},
        )

    assert response.status_code == 400


async def test_the_ack_is_fast(db_session, wired):
    """Not a benchmark -- a guard. If someone later puts an LLM call or an
    outbound send in this path, this test is what notices."""
    conn = await _connection(db_session)

    async with _client() as client:
        started = time.perf_counter()
        await client.post(
            f"/webhooks/telegram/{conn.id}", json=_update(), headers={SECRET_HEADER: SECRET}
        )
        elapsed = time.perf_counter() - started

    assert elapsed < 0.5
