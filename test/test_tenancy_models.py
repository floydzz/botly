import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core import crypto
from app.models import Bot, ChannelConnection, ChannelConnectionStatus, Merchant, Shop

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(
        crypto.settings, "CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


async def _hierarchy(db_session) -> ChannelConnection:
    merchant = Merchant(name="Kopi Co")
    db_session.add(merchant)
    await db_session.flush()

    shop = Shop(
        merchant_id=merchant.id,
        name="Kopi Co Official",
        platform="shopee",
        external_shop_id="112233",
    )
    db_session.add(shop)
    await db_session.flush()

    bot = Bot(shop_id=shop.id, name="Kopi Bot", persona="Friendly barista")
    db_session.add(bot)
    await db_session.flush()

    connection = ChannelConnection(bot_id=bot.id, provider="telegram", external_ref="botly_kopi_bot")
    connection.set_credentials({"bot_token": "123:ABC"})
    db_session.add(connection)
    await db_session.flush()
    return connection


async def test_full_hierarchy_persists(db_session):
    connection = await _hierarchy(db_session)

    assert connection.id is not None
    assert connection.status is ChannelConnectionStatus.DISCONNECTED


async def test_timestamps_are_timezone_aware_utc(db_session):
    merchant = Merchant(name="Tz Co")
    db_session.add(merchant)
    await db_session.flush()

    assert merchant.created_at.tzinfo is not None
    assert merchant.created_at.utcoffset().total_seconds() == 0


async def test_merchant_name_is_unique(db_session):
    db_session.add(Merchant(name="Dupe Co"))
    await db_session.flush()
    db_session.add(Merchant(name="Dupe Co"))

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_credentials_are_not_stored_in_plaintext(db_session):
    connection = await _hierarchy(db_session)

    stored = (
        await db_session.execute(
            text(
                "SELECT credentials_encrypted FROM channel_connections WHERE id = :id"
            ).bindparams(id=connection.id)
        )
    ).scalar_one()

    assert "123:ABC" not in stored
    assert connection.get_credentials() == {"bot_token": "123:ABC"}


async def test_one_provider_reference_cannot_be_connected_twice(db_session):
    """Two connections on the same provider ref would both receive the same
    webhook and answer the customer twice."""

    connection = await _hierarchy(db_session)
    duplicate = ChannelConnection(
        bot_id=connection.bot_id, provider="telegram", external_ref="botly_kopi_bot"
    )
    duplicate.set_credentials({"bot_token": "123:ABC"})
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_config_is_jsonb_and_queryable_by_path(db_session):
    """The spec chose Postgres for exactly this: querying into a payload field
    nobody anticipated must not require a migration."""

    connection = await _hierarchy(db_session)
    connection.config = {"webhook_secret_set": True, "locale": "ms-MY"}
    await db_session.flush()

    found = (
        await db_session.execute(
            text("SELECT id FROM channel_connections WHERE config ->> 'locale' = 'ms-MY'")
        )
    ).scalar_one()

    assert found == connection.id


async def test_deleting_a_merchant_cascades_to_its_channel_connections(db_session):
    connection = await _hierarchy(db_session)
    merchant = (await db_session.execute(select(Merchant))).scalars().first()

    await db_session.delete(merchant)
    await db_session.flush()

    remaining = (
        await db_session.execute(
            text("SELECT count(*) FROM channel_connections WHERE id = :id").bindparams(
                id=connection.id
            )
        )
    ).scalar_one()
    assert remaining == 0
