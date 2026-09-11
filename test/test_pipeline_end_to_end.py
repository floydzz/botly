"""The proof that build-order step 3 is done.

A webhook goes in at the HTTP boundary and a reply comes out at the adapter,
through the real route, the real dedupe, the real registry, the real
dispatcher. No network, no broker: the queue is drained by hand, which is
exactly what Celery would do.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.channels.fake.adapter import SIGNATURE_HEADER, FakeAdapter
from app.core.database import get_db
from app.ingress.dedupe import InMemoryDedupeStore
from app.ingress.queue import InMemoryInboundQueue
from app.main import app
from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.shop import Shop
from app.runtime.pipeline import run_inbound_pipeline
from app.runtime.brain import EchoBrain

pytestmark = pytest.mark.integration


async def _connection(db_session) -> ChannelConnection:
    merchant = Merchant(name="Warung Budi")
    db_session.add(merchant)
    await db_session.flush()
    shop = Shop(merchant_id=merchant.id, name="Budi Store", platform="standalone")
    db_session.add(shop)
    await db_session.flush()
    bot = Bot(shop_id=shop.id, name="Budi Bot")
    db_session.add(bot)
    await db_session.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="fake", external_ref="budi-1")
    conn.set_credentials({})
    db_session.add(conn)
    await db_session.flush()
    return conn


@pytest.fixture
def wired(db_session):
    from app.api.webhooks import get_dedupe_store, get_inbound_queue

    store, queue = InMemoryDedupeStore(), InMemoryInboundQueue()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_dedupe_store] = lambda: store
    app.dependency_overrides[get_inbound_queue] = lambda: queue
    # Yields the queue: every test here asserts on what got enqueued.
    yield queue
    app.dependency_overrides.clear()


def _session_factory(db_session):
    """Hand the pipeline the test's session. A real factory would open a second
    connection and deadlock against the transaction this test holds."""

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return db_session

        async def __aexit__(self, *exc):
            return False

    return _Factory()


@pytest.fixture
def drain(db_session, monkeypatch):
    """Run the queued event the way a Celery worker would, with a chosen
    adapter, and hand back everything that adapter was asked to send."""
    import app.runtime.pipeline as pipeline

    async def _drain(event_id: int, adapter_class=FakeAdapter) -> list:
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

    return _drain


async def _deliver(conn_id: int, body: bytes) -> int:
    """POST one signed delivery at the real route and return its status."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/webhooks/fake/{conn_id}",
            content=body,
            headers={
                SIGNATURE_HEADER: FakeAdapter().sign(body),
                "content-type": "application/json",
            },
        )
    return response.status_code


def _update(update_id: str, **fields) -> bytes:
    import json

    return json.dumps(
        {"updates": [{"update_id": update_id, "thread": "t1", "from": "c1",
                      "ts": 1_757_000_000, **fields}]}
    ).encode()


async def test_a_webhook_becomes_a_reply(db_session, wired, drain):
    conn = await _connection(db_session)

    assert await _deliver(conn.id, _update("u1", text="where is my parcel")) == 200
    assert len(wired.enqueued) == 1

    sent = await drain(wired.enqueued[0])

    assert [m.text for m in sent] == ["botly received: where is my parcel"]
    event = (await db_session.execute(select(InboundEvent))).scalars().one()
    assert event.status is InboundEventStatus.PROCESSED
    assert event.processed_at is not None


async def test_running_the_same_event_twice_replies_once(db_session, wired, drain):
    """acks_late returns a message to the queue when a worker dies. The second
    run must be a no-op, not a second reply to the customer."""
    conn = await _connection(db_session)
    await _deliver(conn.id, _update("u2", text="hello"))

    first = await drain(wired.enqueued[0])
    second = await drain(wired.enqueued[0])

    assert len(first) == 1
    assert second == []


async def test_a_replayed_webhook_never_reaches_the_queue_twice(db_session, wired):
    """The other half of the same guarantee, one layer up."""
    conn = await _connection(db_session)
    body = _update("u3", text="hello")

    assert await _deliver(conn.id, body) == 200
    assert await _deliver(conn.id, body) == 200

    assert len(wired.enqueued) == 1


async def test_a_permanent_send_failure_lands_in_failed_jobs(db_session, wired, drain):
    conn = await _connection(db_session)
    await _deliver(conn.id, _update("u4", text="hello"))

    class _Rejects(FakeAdapter):
        async def send(self, connection, out):
            from app.channels.types import SendResult

            return SendResult(ok=False, error="recipient blocked", retryable=False)

    sent = await drain(wired.enqueued[0], adapter_class=_Rejects)

    assert sent == []
    event = (await db_session.execute(select(InboundEvent))).scalars().one()
    job = (await db_session.execute(select(FailedJob))).scalars().one()
    assert event.status is InboundEventStatus.FAILED
    assert job.kind == "inbound"
    assert job.error == "recipient blocked"
    assert job.inbound_event_id == event.id


async def test_a_media_only_message_escalates_and_sends_nothing(db_session, wired, drain):
    """The stub brain cannot read a photo, so it hands over rather than
    guessing. Facts come from tools, never from the model."""
    conn = await _connection(db_session)
    await _deliver(
        conn.id,
        _update("u5", attachments=[{"kind": "image", "url": "https://x.test/a.jpg"}]),
    )

    sent = await drain(wired.enqueued[0])

    assert sent == []
    event = (await db_session.execute(select(InboundEvent))).scalars().one()
    assert event.status is InboundEventStatus.PROCESSED
