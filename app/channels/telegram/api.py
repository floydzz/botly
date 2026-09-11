"""The HTTP half of the Telegram channel, isolated so the adapter is testable.

Nothing here knows about envelopes or connections. It turns a Bot API method
call into a structured response and never raises for an operational failure --
a blocked bot and a dead DNS server are both outcomes the dispatcher has to
record, not exceptions it has to catch.
"""

import logging
from typing import Any, ClassVar, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, model_validator

# Telegram's own host. It lives here rather than in app/core/config.py because
# no module outside app/channels/<provider>/ may name a provider -- and the
# hostname is the provider's name. Override per connection via
# ChannelConnection.config["api_base"].
DEFAULT_API_BASE = "https://api.telegram.org"

# HTTPX's INFO request log includes the full URL, which contains the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)


class TelegramApiResponse(BaseModel):
    """One Bot API outcome, success or failure, never an exception."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    result: dict[str, Any] | None = None
    # None means the call never reached Telegram: DNS, TLS, timeout.
    error_code: int | None = None
    description: str | None = None
    retry_after: int | None = None

    @model_validator(mode="after")
    def _failures_explain_themselves(self) -> "TelegramApiResponse":
        if not self.ok and not self.description:
            raise ValueError("a failed TelegramApiResponse must carry a description")
        return self


class TelegramApi(Protocol):
    """One Bot API call. Implementations must not raise for network failure."""

    async def call(
        self, token: str, method: str, payload: dict[str, Any]
    ) -> TelegramApiResponse: ...


class HttpTelegramApi:
    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._timeout = timeout
        # An injected client is how tests reach a MockTransport. Owning one
        # per adapter instance would also leak a connection pool per webhook.
        self._client = client

    async def call(
        self, token: str, method: str, payload: dict[str, Any]
    ) -> TelegramApiResponse:
        # The token is a path segment, not a query parameter: query strings are
        # written to proxy and access logs, and this token is the whole bot.
        url = f"{self._api_base}/bot{token}/{method}"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            raw = await client.post(url, json=payload, timeout=self._timeout)
        except httpx.HTTPError:
            return TelegramApiResponse(ok=False, description="channel transport failed")
        finally:
            if self._client is None:
                await client.aclose()

        try:
            body = raw.json()
            if not isinstance(body, dict):
                raise ValueError("response must be an object")
        except ValueError:
            return TelegramApiResponse(
                ok=False,
                error_code=raw.status_code,
                description=f"non-JSON response ({raw.status_code})",
            )

        if body.get("ok"):
            return TelegramApiResponse(ok=True, result=body.get("result") or {})

        return TelegramApiResponse(
            ok=False,
            error_code=body.get("error_code", raw.status_code),
            description=body.get("description") or f"HTTP {raw.status_code}",
            retry_after=(body.get("parameters") or {}).get("retry_after"),
        )


class FakeTelegramApi:
    """In-memory Bot API. Records every call; replays queued responses in order."""

    default_response: ClassVar[TelegramApiResponse] = TelegramApiResponse(
        ok=True, result={"message_id": 1}
    )

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.responses: list[TelegramApiResponse] = []

    async def call(
        self, token: str, method: str, payload: dict[str, Any]
    ) -> TelegramApiResponse:
        self.calls.append((token, method, payload))
        if self.responses:
            return self.responses.pop(0)
        return self.default_response
