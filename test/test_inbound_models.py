import pytest
from sqlalchemy.exc import IntegrityError

from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.merchant import Merchant
from app.models.shop import Shop

pytestmark = pytest.mark.integration


async def _connection(db_session) -> ChannelConnection:
    merchant = Merchant(name="Kedai Siti")
    db_session.add(merchant)
    await db_session.flush()
    shop = Shop(merchant_id=merchant.id, name="Kedai Siti Official", platform="standalone")
    db_session.add(shop)
    await db_session.flush()
    bot = Bot(shop_id=shop.id, name="Siti Bot")
    db_session.add(bot)
    await db_session.flush()
    conn = ChannelConnection(bot_id=bot.id, provider="telegram", external_ref="@siti_bot")
    db_session.add(conn)
    await db_session.flush()
    return conn


async def test_an_inbound_event_stores_its_raw_payload(db_session):
    conn = await _connection(db_session)
    event = InboundEvent(
        connection_id=conn.id,
        provider="telegram",
        provider_update_id="900",
        payload={"update_id": 900, "message": {"text": "hi"}},
    )
    db_session.add(event)
    await db_session.flush()

    assert event.id is not None
    assert event.status is InboundEventStatus.PENDING
    assert event.payload["message"]["text"] == "hi"
    assert event.processed_at is None


async def test_the_same_update_cannot_be_stored_twice(db_session):
    """The second line of dedupe defence. Redis is the fast one and Redis can
    be flushed; this constraint is what makes a double-delivery impossible
    rather than merely unlikely."""
    conn = await _connection(db_session)
    for _ in range(2):
        db_session.add(
            InboundEvent(
                connection_id=conn.id,
                provider="telegram",
                provider_update_id="901",
                payload={},
            )
        )

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_two_providers_may_share_an_update_id(db_session):
    """Update ids are only unique within a provider."""
    conn = await _connection(db_session)
    db_session.add(
        InboundEvent(
            connection_id=conn.id, provider="telegram", provider_update_id="1", payload={}
        )
    )
    db_session.add(
        InboundEvent(
            connection_id=conn.id, provider="fake", provider_update_id="1", payload={}
        )
    )

    await db_session.flush()


async def test_created_timestamps_are_timezone_aware(db_session):
    conn = await _connection(db_session)
    event = InboundEvent(
        connection_id=conn.id, provider="telegram", provider_update_id="902", payload={}
    )
    db_session.add(event)
    await db_session.flush()

    assert event.created_at.utcoffset() is not None


async def test_a_failed_job_records_the_payload_and_the_error(db_session):
    conn = await _connection(db_session)
    job = FailedJob(
        kind="outbound",
        connection_id=conn.id,
        payload={"text": "your parcel is out for delivery"},
        error="bot was blocked",
        attempts=3,
    )
    db_session.add(job)
    await db_session.flush()

    assert job.id is not None
    assert job.attempts == 3


async def test_a_failed_job_survives_its_connection(db_session):
    """Deleting a connection must not erase the record of what went wrong on
    it -- that history is the whole point of the table."""
    conn = await _connection(db_session)
    job = FailedJob(kind="outbound", connection_id=conn.id, payload={}, error="boom")
    db_session.add(job)
    await db_session.flush()

    await db_session.delete(conn)
    await db_session.flush()
    await db_session.refresh(job)

    assert job.connection_id is None
    assert job.error == "boom"
