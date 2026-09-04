import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, ClassVar

from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection

SIGNATURE_HEADER = "x-fake-signature"


class FakeAdapter:
    """An in-memory channel, used by the conformance suite and by runtime tests.

    Deliberately a real implementation rather than a mock. The suite that will
    later prove Telegram correct has to prove itself against something first,
    and a mock agrees with every assertion made of it -- which proves nothing.
    So the signature check is real HMAC, and the parser really parses.
    """

    provider: ClassVar[str] = "fake"
    capabilities: ClassVar[ChannelCapabilities] = ChannelCapabilities(
        supports_media=True,
        max_text_len=4096,
        session_window=None,
        requires_template_outside_window=False,
        supports_typing_indicator=True,
    )

    def __init__(self, secret: bytes = b"fake-secret") -> None:
        self._secret = secret
        self.sent: list[tuple[int | None, OutboundMessage]] = []
        self.connected: set[int | None] = set()
        # Set to an error string to make exactly the next send fail.
        self.fail_next_send: str | None = None

    def sign(self, raw_body: bytes) -> str:
        return hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        offered = headers.get(SIGNATURE_HEADER)
        if offered is None:
            return False
        # compare_digest, not ==, so a wrong signature costs the same time as a
        # right one. The habit belongs in the fake too, because adapters get
        # written by copying this one.
        return hmac.compare_digest(offered, self.sign(raw_body))

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundEnvelope]:
        envelopes: list[InboundEnvelope] = []
        for update in payload.get("updates", []):
            raw_message_id = update.get("message_id")
            envelopes.append(
                InboundEnvelope(
                    provider=self.provider,
                    external_thread_id=str(update["thread"]),
                    provider_update_id=str(update["update_id"]),
                    provider_message_id=(
                        str(raw_message_id) if raw_message_id is not None else None
                    ),
                    sender_ref=str(update["from"]),
                    text=update.get("text"),
                    attachments=tuple(
                        Attachment(**a) for a in update.get("attachments", [])
                    ),
                    sent_at=datetime.fromtimestamp(update["ts"], tz=timezone.utc),
                    raw=update,
                )
            )
        return envelopes

    async def send(self, conn: ChannelConnection, out: OutboundMessage) -> SendResult:
        if self.fail_next_send is not None:
            error, self.fail_next_send = self.fail_next_send, None
            return SendResult(ok=False, error=error, retryable=True)
        self.sent.append((conn.id, out))
        return SendResult(ok=True, provider_message_id=f"fake-{len(self.sent)}")

    async def connect(self, conn: ChannelConnection) -> None:
        self.connected.add(conn.id)

    async def disconnect(self, conn: ChannelConnection) -> None:
        self.connected.discard(conn.id)
