"""Connection to adapter. The one dispatch point on a provider name.

It lives inside app/channels/ deliberately: this is the single place allowed to
import concrete adapters and to know their names. Everything upstream -- the
webhook route, the worker, the dispatcher -- takes an adapter and asks it
questions.

Note that app/channels/__init__.py still imports no concrete adapter. Importing
this module is an explicit act.
"""

from collections.abc import Callable

from app.channels.base import ChannelAdapter
from app.channels.fake.adapter import FakeAdapter
from app.channels.telegram.adapter import TelegramAdapter
from app.channels.telegram.api import DEFAULT_API_BASE
from app.core.config import settings
from app.models.channel_connection import ChannelConnection


class UnknownProvider(LookupError):
    """No adapter is registered for this connection's provider."""


class MissingCredentials(ValueError):
    """The connection exists but its credential blob is incomplete."""


def _require(credentials: dict, key: str, provider: str) -> str:
    try:
        return credentials[key]
    except KeyError:
        raise MissingCredentials(
            f"{provider} connection is missing {key!r} in its credentials"
        ) from None


def _build_telegram(
    conn: ChannelConnection, webhook_url: str | None
) -> ChannelAdapter:
    credentials = conn.get_credentials()
    return TelegramAdapter(
        token=_require(credentials, "bot_token", TelegramAdapter.provider),
        secret_token=_require(credentials, "secret_token", TelegramAdapter.provider),
        webhook_url=webhook_url,
        # Provider-neutral key, so the pipeline never learns whose base it is.
        api_base=(conn.config or {}).get("api_base") or DEFAULT_API_BASE,
    )


def _build_fake(conn: ChannelConnection, webhook_url: str | None) -> ChannelAdapter:
    if settings.is_production:
        raise UnknownProvider(
            "the in-memory channel is not available in production"
        )
    return FakeAdapter()


_BUILDERS: dict[str, Callable[[ChannelConnection, str | None], ChannelAdapter]] = {
    TelegramAdapter.provider: _build_telegram,
    FakeAdapter.provider: _build_fake,
}


def build_adapter(
    conn: ChannelConnection, webhook_url: str | None = None
) -> ChannelAdapter:
    # .get() then an explicit check, not try/except KeyError around the call:
    # a KeyError raised *inside* a builder is a missing credential, and
    # wrapping the call would report it as an unknown provider.
    builder = _BUILDERS.get(conn.provider)
    if builder is None:
        raise UnknownProvider(f"no adapter registered for provider {conn.provider!r}")
    return builder(conn, webhook_url)
