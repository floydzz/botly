"""Outbound dispatch.

Everything a channel will and will not accept is read from its capability
manifest. There is no provider name in this file and there must never be one:
the moment a rule here says "if telegram", the same rule has to be repeated for
WhatsApp, and then for Shopee, and the channel layer stops containing anything.

Order of operations, from the spec: escalation short-circuits; the session
window and template rule are checked before anything is sent; text is chunked
to the manifest limit; each chunk takes a rate-limit token; retryable failures
back off; a permanent failure stops the rest and is reported so it reaches the
inbox as "delivery failed".
"""

import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from app.channels.base import ChannelAdapter
from app.channels.types import OutboundMessage, SendResult
from app.dispatch.ratelimit import InMemoryTokenBucket, RateLimiter, bucket_key
from app.models.channel_connection import ChannelConnection
from app.runtime.brain import DraftReply


def window_is_closed(caps, last_inbound_at: datetime | None) -> bool:
    """Return whether a channel's session window has shut.

    The inbox send policy and the dispatcher both use this function so the UI
    cannot promise a send that the provider path will refuse.
    """
    if caps.session_window is None:
        return False
    if last_inbound_at is None:
        return True
    return datetime.now(timezone.utc) - last_inbound_at > caps.session_window


def chunk_text(text: str, limit: int) -> list[str]:
    """Split to the channel's limit, preferring a break a reader would choose.

    A newline first, then a space, then a hard cut. Cutting mid-word makes the
    bot look broken; cutting at a line break is invisible.
    """
    chunks: list[str] = []
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit
        piece = remaining[:cut].strip()
        if piece:
            chunks.append(piece)
        remaining = remaining[cut:].strip()
    return chunks


class DispatchOutcome(BaseModel):
    """What happened, in a form the inbox can render."""

    model_config = ConfigDict(frozen=True)

    sent: tuple[SendResult, ...] = ()
    escalated: bool = False
    reason: str | None = None
    # Set when delivery is over and it did not succeed. The caller writes a
    # FailedJob and the inbox shows "delivery failed".
    permanent_failure: str | None = None


class OutboundDispatcher:
    def __init__(
        self,
        adapter: ChannelAdapter,
        limiter: RateLimiter | None = None,
        sleep=asyncio.sleep,
        max_attempts: int = 3,
    ) -> None:
        self._adapter = adapter
        self._limiter = limiter or InMemoryTokenBucket()
        # Injected so retry tests do not spend real seconds sleeping.
        self._sleep = sleep
        self._max_attempts = max_attempts

    async def dispatch(
        self,
        conn: ChannelConnection,
        draft: DraftReply,
        last_inbound_at: datetime | None = None,
        external_thread_id: str | None = None,
    ) -> DispatchOutcome:
        caps = type(self._adapter).capabilities

        if draft.escalate:
            return DispatchOutcome(escalated=True, reason=draft.reason)

        if draft.attachments and not caps.supports_media:
            # Dropping it silently means the customer never sees something we
            # meant them to see. A human should decide what to do instead.
            return DispatchOutcome(
                escalated=True,
                reason="the channel carries no media and the reply has attachments",
            )

        if self._window_is_closed(caps, last_inbound_at):
            if caps.requires_template_outside_window:
                # No approved template selection exists yet -- message_template
                # is a later plan -- so the only correct move is a human.
                return DispatchOutcome(
                    escalated=True,
                    reason=(
                        "the session window has closed and this channel requires "
                        "an approved template outside it"
                    ),
                )

        pieces = chunk_text(draft.text or "", caps.max_text_len)
        results: list[SendResult] = []
        for piece in pieces:
            result = await self._send_with_retry(conn, OutboundMessage(text=piece, external_thread_id=external_thread_id))
            results.append(result)
            if not result.ok:
                # Chunks 1 and 3 of a three-part answer is worse than chunk 1
                # plus a human.
                return DispatchOutcome(
                    sent=tuple(results), permanent_failure=result.error
                )

        return DispatchOutcome(sent=tuple(results))

    @staticmethod
    def _window_is_closed(caps, last_inbound_at: datetime | None) -> bool:
        return window_is_closed(caps, last_inbound_at)

    async def _send_with_retry(
        self, conn: ChannelConnection, out: OutboundMessage
    ) -> SendResult:
        last: SendResult | None = None
        for attempt in range(self._max_attempts):
            if not await self._limiter.acquire(bucket_key(conn.id)):
                return SendResult(
                    ok=False, error="outbound rate limit exhausted", retryable=True
                )

            last = await self._adapter.send(conn, out)
            if last.ok or not last.retryable:
                return last

            if attempt < self._max_attempts - 1:
                # Exponential: 0.5s, 1s, 2s. A provider that just rate-limited
                # us is not helped by an immediate second attempt.
                await self._sleep(0.5 * (2**attempt))

        return last
