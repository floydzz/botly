import httpx
import pytest

from app.channels.telegram.api import (
    FakeTelegramApi,
    HttpTelegramApi,
    TelegramApiResponse,
)


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_successful_call_returns_the_result_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 77}})

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {"chat_id": "1", "text": "hi"})

    assert response.ok is True
    assert response.result == {"message_id": 77}


async def test_the_token_goes_in_the_path_and_never_in_the_query():
    """A token in a query string lands in every proxy and access log there is."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True, "result": {}})

    api = HttpTelegramApi(client=_transport(handler))
    await api.call("secret-token", "getMe", {})

    assert seen[0].url.path == "/botsecret-token/getMe"
    assert "secret-token" not in str(seen[0].url.query)


async def test_a_rate_limit_surfaces_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 7",
                "parameters": {"retry_after": 7},
            },
        )

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.error_code == 429
    assert response.retry_after == 7


async def test_a_rejected_request_reports_its_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"ok": False, "error_code": 403, "description": "bot was blocked"}
        )

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.error_code == 403
    assert "blocked" in response.description


async def test_a_transport_error_becomes_a_response_not_an_exception():
    """The dispatcher records outcomes. A raised exception would bypass it."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns went away")

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.error_code is None
    assert response.description == "channel transport failed"


async def test_malformed_json_does_not_raise():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    api = HttpTelegramApi(client=_transport(handler))
    response = await api.call("tok", "sendMessage", {})

    assert response.ok is False
    assert response.description


async def test_the_fake_records_calls_and_replays_queued_responses():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=True, result={"message_id": 5}))

    first = await api.call("tok", "sendMessage", {"chat_id": "9"})
    second = await api.call("tok", "sendMessage", {"chat_id": "9"})

    assert first.result == {"message_id": 5}
    # Queue exhausted -> the default, so a test only queues what it cares about.
    assert second.ok is True
    assert api.calls == [
        ("tok", "sendMessage", {"chat_id": "9"}),
        ("tok", "sendMessage", {"chat_id": "9"}),
    ]


async def test_a_failed_response_must_carry_a_description():
    with pytest.raises(ValueError):
        TelegramApiResponse(ok=False)
