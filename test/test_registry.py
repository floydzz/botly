import pytest

from app.channels.fake.adapter import FakeAdapter
from app.channels.registry import (
    MissingCredentials,
    UnknownProvider,
    build_adapter,
)
from app.channels.telegram.adapter import TelegramAdapter
from app.models.channel_connection import ChannelConnection


def telegram_connection() -> ChannelConnection:
    conn = ChannelConnection(
        id=1, bot_id=1, provider="telegram", external_ref="@botly_test_bot"
    )
    conn.set_credentials({"bot_token": "123:ABC", "secret_token": "s3cr3t"})
    return conn


def test_a_telegram_connection_builds_a_telegram_adapter():
    adapter = build_adapter(telegram_connection())

    assert isinstance(adapter, TelegramAdapter)
    assert type(adapter).provider == "telegram"


def test_the_webhook_url_is_passed_through_so_connect_works():
    adapter = build_adapter(
        telegram_connection(), webhook_url="https://example.test/webhooks/telegram/1"
    )

    assert adapter._webhook_url == "https://example.test/webhooks/telegram/1"


def test_an_unknown_provider_is_a_named_error_not_a_keyerror():
    conn = ChannelConnection(id=1, bot_id=1, provider="carrier-pigeon", external_ref="x")

    with pytest.raises(UnknownProvider) as exc:
        build_adapter(conn)

    assert "carrier-pigeon" in str(exc.value)


def test_missing_credentials_are_a_named_error_not_a_keyerror():
    """A KeyError raised inside a builder must not be mistaken for an unknown
    provider -- that is the classic dict.get-versus-try/except bug, and it
    would report a configuration problem as a missing channel."""
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")
    conn.set_credentials({"bot_token": "123:ABC"})  # secret_token absent

    with pytest.raises(MissingCredentials) as exc:
        build_adapter(conn)

    assert "secret_token" in str(exc.value)


def test_a_fake_connection_builds_the_fake_adapter():
    """Registered on purpose: the end-to-end test must exercise the real
    lookup path, not tiptoe around it."""
    conn = ChannelConnection(id=1, bot_id=1, provider="fake", external_ref="x")

    assert isinstance(build_adapter(conn), FakeAdapter)


def test_production_refuses_to_build_the_fake_adapter(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(type(settings), "is_production", property(lambda self: True))
    conn = ChannelConnection(id=1, bot_id=1, provider="fake", external_ref="x")

    with pytest.raises(UnknownProvider):
        build_adapter(conn)
