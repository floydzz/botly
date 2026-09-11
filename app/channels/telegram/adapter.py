"""The Telegram channel. The only module in the codebase that knows what a
Telegram Update looks like.

Telegram is build-order step 3 because it has no gatekeeper: a BotFather token
and a webhook. That makes it the channel that proves the whole pipeline while
the Shopee and WhatsApp approvals are still in a queue somewhere.
"""

import hmac
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.channels.telegram.api import (
    DEFAULT_API_BASE,
    HttpTelegramApi,
    TelegramApi,
)
from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection

SECRET_HEADER = "x-telegram-bot-api-secret-token"

# Attachments arrive as file_ids, not URLs. Resolving one costs a getFile call,
# and parse_inbound must stay pure -- ingress reparses the stored payload on
# replay. So the file_id travels under a scheme only this module understands,
# and resolve_file_url() cashes it in when something actually needs the bytes.
FILE_URI_SCHEME = "tg-file://"

# The update keys that can carry a customer message. Anything else -- poll
# answers, chat member changes, delivery receipts -- is not actionable.
_MESSAGE_KEYS = ("message", "edited_message", "channel_post", "edited_channel_post")


class TelegramAdapter:
    provider: ClassVar[str] = "telegram"
    capabilities: ClassVar[ChannelCapabilities] = ChannelCapabilities(
        supports_media=True,
        # Bot API hard limit on sendMessage text.
        max_text_len=4096,
        # Telegram never closes. No window, so no template rule either.
        session_window=None,
        requires_template_outside_window=False,
        supports_typing_indicator=True,
    )

    def __init__(
        self,
        token: str,
        secret_token: str,
        api: TelegramApi | None = None,
        webhook_url: str | None = None,
        api_base: str = DEFAULT_API_BASE,
    ) -> None:
        self._token = token
        self._secret_token = secret_token
        self._api = api or HttpTelegramApi(api_base=api_base)
        self._webhook_url = webhook_url
        self._api_base = api_base.rstrip("/")

    # --- webhook verification ---------------------------------------------

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Telegram does not sign deliveries. It echoes the secret_token given
        to setWebhook, so authenticity is a constant-time string compare.

        compare_digest rather than ``==``: equality short-circuits on the first
        differing byte, which turns the token into a timing oracle.
        """
        offered = next(
            (v for k, v in headers.items() if k.lower() == SECRET_HEADER), None
        )
        if offered is None:
            return False
        return hmac.compare_digest(offered, self._secret_token)

    # --- parsing ------------------------------------------------------------

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundEnvelope]:
        """One Update in, zero or one envelope out.

        Zero is a normal, expected answer. Telegram sends plenty of updates
        that are not a customer saying something.
        """
        message = next(
            (payload[key] for key in _MESSAGE_KEYS if isinstance(payload.get(key), dict)),
            None,
        )
        if message is None:
            return []

        text = message.get("text") or message.get("caption")
        attachments = self._attachments(message)
        if text is None and not attachments:
            # A join notice, a pinned-message event: a message object with no
            # message in it. An envelope cannot represent that, and shouldn't.
            return []

        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        return [
            InboundEnvelope(
                provider=self.provider,
                external_thread_id=str(chat.get("id", "")),
                provider_update_id=str(payload["update_id"]),
                provider_message_id=str(message["message_id"]),
                sender_ref=str(sender.get("id") or chat.get("id", "")),
                text=text,
                attachments=attachments,
                sent_at=datetime.fromtimestamp(message["date"], tz=timezone.utc),
                raw=payload,
            )
        ]

    def _attachments(self, message: dict[str, Any]) -> tuple[Attachment, ...]:
        found: list[Attachment] = []

        photos = message.get("photo")
        if photos:
            # One entry per resolution, ascending. OCR on a thumbnail reads
            # nothing, so take the last.
            largest = photos[-1]
            found.append(
                Attachment(
                    kind="image",
                    url=FILE_URI_SCHEME + largest["file_id"],
                    size_bytes=largest.get("file_size"),
                )
            )

        for key, kind in (("video", "video"), ("voice", "audio"), ("audio", "audio")):
            item = message.get(key)
            if isinstance(item, dict) and item.get("file_id"):
                found.append(
                    Attachment(
                        kind=kind,
                        url=FILE_URI_SCHEME + item["file_id"],
                        mime_type=item.get("mime_type"),
                        size_bytes=item.get("file_size"),
                    )
                )

        document = message.get("document")
        if isinstance(document, dict) and document.get("file_id"):
            found.append(
                Attachment(
                    kind="file",
                    url=FILE_URI_SCHEME + document["file_id"],
                    mime_type=document.get("mime_type"),
                    size_bytes=document.get("file_size"),
                )
            )

        return tuple(found)

    async def resolve_file_url(self, attachment_url: str) -> str | None:
        """Cash a tg-file:// reference in for a real download URL."""
        file_id = attachment_url.removeprefix(FILE_URI_SCHEME)
        response = await self._api.call(self._token, "getFile", {"file_id": file_id})
        if not response.ok:
            return None
        file_path = (response.result or {}).get("file_path")
        if not file_path:
            return None
        return f"{self._api_base}/file/bot{self._token}/{file_path}"

    # --- sending ------------------------------------------------------------

    async def send(self, conn: ChannelConnection, out: OutboundMessage) -> SendResult:
        chat_id = out.external_thread_id or (conn.config or {}).get("chat_id") or conn.external_ref
        response = await self._api.call(
            self._token,
            "sendMessage",
            {"chat_id": chat_id, "text": out.text or ""},
        )
        if response.ok:
            return SendResult(
                ok=True,
                provider_message_id=str((response.result or {}).get("message_id", "")),
            )

        # error_code is None when the call never reached Telegram. A rate limit
        # and a 5xx are worth backing off on; a 403 from a blocked bot is not,
        # and retrying it forever is how a queue dies.
        code = response.error_code
        retryable = code is None or code == 429 or code >= 500
        return SendResult(ok=False, error=response.description, retryable=retryable)

    # --- lifecycle ----------------------------------------------------------

    async def connect(self, conn: ChannelConnection) -> None:
        if not self._webhook_url:
            raise ValueError(
                "TelegramAdapter needs a webhook_url to connect; without one "
                "setWebhook would silently leave the bot deaf."
            )
        response = await self._api.call(
            self._token,
            "setWebhook",
            {
                "url": self._webhook_url,
                "secret_token": self._secret_token,
                "allowed_updates": list(_MESSAGE_KEYS),
                # Idempotent: re-registering the same URL is a no-op upstream.
                "drop_pending_updates": False,
            },
        )
        if not response.ok:
            raise ValueError("channel webhook registration failed")

    async def disconnect(self, conn: ChannelConnection) -> None:
        # Safe before connect and safe twice: deleteWebhook on a bot with no
        # webhook returns ok.
        await self._api.call(self._token, "deleteWebhook", {})
