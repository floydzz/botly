from collections.abc import Mapping
from typing import Any, ClassVar, Protocol, runtime_checkable

from app.channels.types import (
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)
from app.models.channel_connection import ChannelConnection


@runtime_checkable
class ChannelAdapter(Protocol):
    """Everything a channel must implement, and the only place its name appears.

    ``runtime_checkable`` compares method *names* and nothing else -- not
    signatures, not return types, not whether ``send`` is actually a coroutine.
    An ``isinstance`` check here is a smoke test. The real contract is the
    conformance suite in ``test/conformance.py``, which every adapter runs.
    """

    provider: ClassVar[str]
    capabilities: ClassVar[ChannelCapabilities]

    def verify_webhook(self, headers: Mapping[str, str], raw_body: bytes) -> bool:
        """Authenticate a webhook delivery against the raw, unparsed body.

        Takes bytes rather than a parsed dict on purpose: signatures cover the
        exact bytes sent, and re-serialising a parsed payload will not reproduce
        them.
        """
        ...

    def parse_inbound(self, payload: dict[str, Any]) -> list[InboundEnvelope]:
        """Normalise one delivery into zero or more envelopes.

        A list because providers batch: one Telegram request can carry several
        updates. Zero is valid and means "nothing actionable here" -- a delivery
        receipt, a status change -- not an error.
        """
        ...

    async def send(self, conn: ChannelConnection, out: OutboundMessage) -> SendResult:
        """Deliver one message, returning an outcome rather than raising.

        Send failure is an expected operational state that must reach the inbox,
        so it is a return value the dispatcher can record, not an exception it
        has to catch.
        """
        ...

    async def connect(self, conn: ChannelConnection) -> None:
        """Register the webhook and validate credentials. Idempotent."""
        ...

    async def disconnect(self, conn: ChannelConnection) -> None:
        """Deregister the webhook. Idempotent, and safe on a dead connection."""
        ...
