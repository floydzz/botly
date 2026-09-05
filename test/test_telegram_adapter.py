from datetime import timezone

import pytest

from app.channels.telegram.adapter import SECRET_HEADER, TelegramAdapter
from app.channels.telegram.api import FakeTelegramApi, TelegramApiResponse
from app.channels.types import OutboundMessage
from app.models.channel_connection import ChannelConnection
from test.conformance import ChannelAdapterConformance

SECRET = "s3cr3t-token"


def make_adapter(api: FakeTelegramApi | None = None) -> TelegramAdapter:
    return TelegramAdapter(
        token="123:ABC",
        secret_token=SECRET,
        api=api or FakeTelegramApi(),
        webhook_url="https://example.test/webhooks/telegram/1",
    )


def text_update(update_id: int = 900) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": 42,
            "date": 1_757_000_000,
            "chat": {"id": -100123, "type": "private"},
            "from": {"id": 555, "is_bot": False, "first_name": "Siti"},
            "text": "where is my parcel",
        },
    }


class TestTelegramConformance(ChannelAdapterConformance):
    """The shared contract. Four hooks, and Telegram is held to the same
    definition of correct as every other channel."""

    def make_adapter(self):
        return make_adapter()

    def make_connection(self) -> ChannelConnection:
        return ChannelConnection(
            id=1, bot_id=1, provider="telegram", external_ref="@botly_test_bot"
        )

    def make_signed_webhook(self) -> tuple[dict[str, str], bytes]:
        return {SECRET_HEADER: SECRET}, b'{"update_id": 1}'

    def make_inbound_payload(self) -> dict:
        return text_update()

    def body_is_authenticated(self) -> bool:
        # Telegram signs nothing. It echoes the secret_token given to
        # setWebhook, which proves who is calling and not what they said.
        return False


# --- Telegram-specific behaviour -------------------------------------------


def test_a_wrong_secret_is_rejected():
    assert make_adapter().verify_webhook({SECRET_HEADER: "wrong"}, b"{}") is False


def test_a_tampered_body_with_a_valid_secret_is_accepted():
    """Documented, not desired.

    Telegram's scheme does not cover the payload, so anyone holding the secret
    token can send any body. The protection is TLS plus the secrecy of that
    token -- which is why it must be high-entropy and treated as a credential.
    This test exists so the property is written down rather than discovered.
    """
    adapter = make_adapter()
    assert adapter.verify_webhook({SECRET_HEADER: SECRET}, b'{"anything": true}')


def test_the_secret_header_is_matched_case_insensitively():
    """Header casing is not guaranteed across proxies; the value is exact."""
    adapter = make_adapter()
    assert adapter.verify_webhook({"X-Telegram-Bot-Api-Secret-Token": SECRET}, b"{}")


def test_a_text_message_parses_into_one_envelope():
    [envelope] = make_adapter().parse_inbound(text_update())

    assert envelope.provider == "telegram"
    assert envelope.external_thread_id == "-100123"
    assert envelope.provider_update_id == "900"
    assert envelope.provider_message_id == "42"
    assert envelope.sender_ref == "555"
    assert envelope.text == "where is my parcel"
    assert envelope.sent_at.tzinfo is not None
    assert envelope.sent_at.astimezone(timezone.utc).year == 2025


def test_the_raw_update_is_kept_on_the_envelope():
    """Ingress persists it, and a parser bug found next month is only
    debuggable against the bytes that actually arrived."""
    payload = text_update()
    [envelope] = make_adapter().parse_inbound(payload)

    assert envelope.raw == payload


def test_an_edited_message_is_parsed_too():
    payload = {
        "update_id": 901,
        "edited_message": {
            "message_id": 43,
            "date": 1_757_000_100,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "text": "actually, order 12345",
        },
    }
    [envelope] = make_adapter().parse_inbound(payload)

    assert envelope.text == "actually, order 12345"


def test_a_photo_becomes_an_attachment_carrying_the_largest_file_id():
    """Telegram sends one entry per resolution. The last is the biggest, and
    OCR on a thumbnail reads nothing."""
    payload = {
        "update_id": 902,
        "message": {
            "message_id": 44,
            "date": 1_757_000_200,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "photo": [
                {"file_id": "small", "width": 90},
                {"file_id": "large", "width": 1280},
            ],
        },
    }
    [envelope] = make_adapter().parse_inbound(payload)
    [attachment] = envelope.attachments

    assert attachment.kind == "image"
    assert attachment.url == "tg-file://large"


def test_a_document_becomes_an_attachment_with_its_mime_type():
    payload = {
        "update_id": 903,
        "message": {
            "message_id": 45,
            "date": 1_757_000_300,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "document": {
                "file_id": "doc1",
                "mime_type": "application/pdf",
                "file_size": 2048,
            },
        },
    }
    [envelope] = make_adapter().parse_inbound(payload)
    [attachment] = envelope.attachments

    assert attachment.kind == "file"
    assert attachment.url == "tg-file://doc1"
    assert attachment.mime_type == "application/pdf"
    assert attachment.size_bytes == 2048


def test_a_non_message_update_yields_nothing_rather_than_failing():
    """A delivery receipt is not an error. Returning [] is how the adapter
    says 'nothing actionable', and ingress must still ACK 200."""
    payload = {"update_id": 904, "poll_answer": {"poll_id": "p", "option_ids": [1]}}

    assert make_adapter().parse_inbound(payload) == []


def test_an_empty_message_with_no_text_and_no_media_yields_nothing():
    """Chat-member joins arrive as a message with nothing in it. An envelope
    with neither text nor attachment cannot be constructed, and should not be."""
    payload = {
        "update_id": 905,
        "message": {
            "message_id": 46,
            "date": 1_757_000_400,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 8},
            "new_chat_members": [{"id": 99}],
        },
    }

    assert make_adapter().parse_inbound(payload) == []


async def test_send_posts_a_message_and_reports_the_provider_id():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=True, result={"message_id": 4321}))
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(
        conn, OutboundMessage(text="your parcel is out for delivery")
    )

    assert result.ok is True
    assert result.provider_message_id == "4321"
    token, method, payload = api.calls[0]
    assert method == "sendMessage"
    assert payload["text"] == "your parcel is out for delivery"


async def test_send_targets_the_thread_from_the_connection_config():
    api = FakeTelegramApi()
    conn = ChannelConnection(
        id=1, bot_id=1, provider="telegram", external_ref="@b",
        config={"chat_id": "-100123"},
    )

    await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert api.calls[0][2]["chat_id"] == "-100123"


async def test_a_rate_limited_send_is_retryable():
    api = FakeTelegramApi()
    api.responses.append(
        TelegramApiResponse(
            ok=False, error_code=429, description="Too Many Requests", retry_after=3
        )
    )
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert result.ok is False
    assert result.retryable is True


async def test_a_blocked_bot_is_not_retryable():
    """Retrying a 403 forever is how a queue dies. It belongs in failed_job."""
    api = FakeTelegramApi()
    api.responses.append(
        TelegramApiResponse(ok=False, error_code=403, description="bot was blocked")
    )
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert result.ok is False
    assert result.retryable is False


async def test_a_transport_failure_is_retryable():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=False, description="connection reset"))
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    result = await make_adapter(api).send(conn, OutboundMessage(text="hi"))

    assert result.retryable is True


async def test_connect_registers_the_webhook_with_the_secret():
    api = FakeTelegramApi()
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    await make_adapter(api).connect(conn)

    _, method, payload = api.calls[0]
    assert method == "setWebhook"
    assert payload["secret_token"] == SECRET
    assert payload["url"] == "https://example.test/webhooks/telegram/1"


async def test_connect_without_a_webhook_url_is_refused_loudly():
    """A silent no-op here means a bot that is 'connected' and deaf."""
    adapter = TelegramAdapter(token="1:A", secret_token=SECRET, api=FakeTelegramApi())
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    with pytest.raises(ValueError):
        await adapter.connect(conn)


async def test_disconnect_deletes_the_webhook():
    api = FakeTelegramApi()
    conn = ChannelConnection(id=1, bot_id=1, provider="telegram", external_ref="@b")

    await make_adapter(api).disconnect(conn)

    assert api.calls[0][1] == "deleteWebhook"


async def test_resolve_file_url_exchanges_a_file_id_for_a_download_url():
    api = FakeTelegramApi()
    api.responses.append(
        TelegramApiResponse(ok=True, result={"file_path": "photos/x.jpg"})
    )

    url = await make_adapter(api).resolve_file_url("tg-file://large")

    assert url == "https://api.telegram.org/file/bot123:ABC/photos/x.jpg"
    assert api.calls[0][2] == {"file_id": "large"}


async def test_resolve_file_url_returns_none_when_the_file_is_gone():
    api = FakeTelegramApi()
    api.responses.append(TelegramApiResponse(ok=False, description="file not found"))

    assert await make_adapter(api).resolve_file_url("tg-file://gone") is None
