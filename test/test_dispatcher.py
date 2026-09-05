from datetime import datetime, timedelta, timezone

import pytest

from app.channels.fake.adapter import FakeAdapter
from app.channels.types import Attachment, ChannelCapabilities
from app.dispatch.dispatcher import OutboundDispatcher, chunk_text
from app.dispatch.ratelimit import InMemoryTokenBucket
from app.models.channel_connection import ChannelConnection
from app.runtime.brain import DraftReply


def connection() -> ChannelConnection:
    return ChannelConnection(id=1, bot_id=1, provider="fake", external_ref="x")


def adapter_with(**overrides) -> FakeAdapter:
    """A FakeAdapter wearing a different capability manifest.

    This is how a channel the dispatcher has never seen gets tested: change the
    manifest, not the dispatcher. If a test here ever needs a new provider
    name, the dispatcher has a bug.
    """
    base = FakeAdapter.capabilities.model_dump()
    base.update(overrides)

    class _Adapter(FakeAdapter):
        capabilities = ChannelCapabilities(**base)

    return _Adapter()


def dispatcher(adapter, **kwargs) -> OutboundDispatcher:
    kwargs.setdefault("limiter", InMemoryTokenBucket(capacity=100))
    return OutboundDispatcher(adapter, **kwargs)


# --- chunking ---------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert chunk_text("hello", 100) == ["hello"]


def test_long_text_is_split_to_the_limit():
    chunks = chunk_text("a" * 250, 100)

    assert [len(c) for c in chunks] == [100, 100, 50]


def test_splitting_prefers_a_line_break():
    """Cutting mid-word makes the bot look broken. Cutting at a newline does
    not."""
    text = "first line\n" + "b" * 50

    chunks = chunk_text(text, 20)

    assert chunks[0] == "first line"


def test_splitting_falls_back_to_a_space_then_to_a_hard_cut():
    assert chunk_text("word " + "c" * 30, 10)[0] == "word"
    assert chunk_text("d" * 30, 10)[0] == "d" * 10


def test_chunking_never_returns_an_empty_piece():
    """An empty chunk becomes an OutboundMessage with nothing in it, which the
    envelope refuses to construct -- a crash at send time."""
    for chunk in chunk_text("a\n\n\nb", 4):
        assert chunk.strip()


# --- the capability rules ---------------------------------------------------


async def test_a_reply_is_sent_through_the_adapter():
    adapter = adapter_with()
    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="your parcel is out for delivery")
    )

    assert outcome.escalated is False
    assert len(adapter.sent) == 1
    assert adapter.sent[0][1].text == "your parcel is out for delivery"


async def test_a_long_reply_is_split_to_the_manifest_limit():
    adapter = adapter_with(max_text_len=10)

    await dispatcher(adapter).dispatch(connection(), DraftReply(text="x" * 25))

    assert len(adapter.sent) == 3
    assert all(len(sent.text) <= 10 for _, sent in adapter.sent)


async def test_a_closed_window_with_a_template_rule_escalates_without_a_template():
    """This is the WhatsApp case, expressed entirely as a manifest. The
    dispatcher has never heard of WhatsApp."""
    adapter = adapter_with(
        session_window=timedelta(hours=24), requires_template_outside_window=True
    )
    stale = datetime.now(timezone.utc) - timedelta(hours=25)

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=stale
    )

    assert outcome.escalated is True
    assert "window" in outcome.reason
    assert adapter.sent == []


async def test_an_open_window_sends_free_text_normally():
    adapter = adapter_with(
        session_window=timedelta(hours=24), requires_template_outside_window=True
    )
    fresh = datetime.now(timezone.utc) - timedelta(minutes=5)

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=fresh
    )

    assert outcome.escalated is False
    assert len(adapter.sent) == 1


async def test_no_inbound_at_all_counts_as_a_closed_window():
    """A conversation the bot starts has no window. Treating unknown as open
    is how a send fails at the provider instead of at the guard."""
    adapter = adapter_with(
        session_window=timedelta(hours=24), requires_template_outside_window=True
    )

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=None
    )

    assert outcome.escalated is True


async def test_a_channel_with_no_window_ignores_the_timestamp_entirely():
    adapter = adapter_with(session_window=None)
    ancient = datetime.now(timezone.utc) - timedelta(days=400)

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="hello"), last_inbound_at=ancient
    )

    assert outcome.escalated is False


async def test_attachments_on_a_text_only_channel_escalate():
    """Silently dropping something the customer was meant to see is worse than
    handing the conversation to a human."""
    adapter = adapter_with(supports_media=False)

    outcome = await dispatcher(adapter).dispatch(
        connection(),
        DraftReply(text="here", attachments=(Attachment(kind="image", url="u"),)),
    )

    assert outcome.escalated is True
    assert "media" in outcome.reason
    assert adapter.sent == []


async def test_an_escalating_draft_sends_nothing():
    adapter = adapter_with()

    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(escalate=True, reason="tool failure")
    )

    assert outcome.escalated is True
    assert outcome.reason == "tool failure"
    assert adapter.sent == []


# --- rate limiting, retry, failure ------------------------------------------


async def test_an_exhausted_bucket_stops_the_send():
    adapter = adapter_with()
    limiter = InMemoryTokenBucket(capacity=0, refill_per_second=0)

    outcome = await dispatcher(adapter, limiter=limiter).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert adapter.sent == []
    assert outcome.permanent_failure is not None


async def test_a_retryable_failure_is_retried_and_can_succeed():
    adapter = adapter_with()
    adapter.fail_next_send = "429 slow down"
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    outcome = await dispatcher(adapter, sleep=fake_sleep).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert outcome.permanent_failure is None
    assert len(adapter.sent) == 1
    assert slept, "a retry must back off rather than hammer the provider"


async def test_backoff_grows_between_attempts():
    class _AlwaysFails(FakeAdapter):
        async def send(self, conn, out):
            from app.channels.types import SendResult

            return SendResult(ok=False, error="429", retryable=True)

    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    await dispatcher(_AlwaysFails(), sleep=fake_sleep, max_attempts=3).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert slept == sorted(slept) and slept[0] < slept[-1]


async def test_a_permanent_failure_is_not_retried():
    class _Rejects(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def send(self, conn, out):
            from app.channels.types import SendResult

            self.attempts += 1
            return SendResult(ok=False, error="bot was blocked", retryable=False)

    adapter = _Rejects()
    outcome = await dispatcher(adapter, max_attempts=3).dispatch(
        connection(), DraftReply(text="hello")
    )

    assert adapter.attempts == 1
    assert outcome.permanent_failure == "bot was blocked"


async def test_giving_up_after_max_attempts_reports_a_permanent_failure():
    class _AlwaysFails(FakeAdapter):
        async def send(self, conn, out):
            from app.channels.types import SendResult

            return SendResult(ok=False, error="503", retryable=True)

    async def fake_sleep(seconds: float) -> None:
        return None

    outcome = await dispatcher(
        _AlwaysFails(), sleep=fake_sleep, max_attempts=2
    ).dispatch(connection(), DraftReply(text="hello"))

    assert outcome.permanent_failure == "503"


async def test_a_failed_chunk_stops_the_rest():
    """Sending chunks 1 and 3 of a three-part answer is worse than sending one
    and escalating."""

    class _FailsSecond(FakeAdapter):
        capabilities = ChannelCapabilities(supports_media=True, max_text_len=5)

        async def send(self, conn, out):
            from app.channels.types import SendResult

            # FakeAdapter.sent only grows on success, so length 1 means the
            # first chunk went out and this is the second.
            if len(self.sent) == 1:
                return SendResult(ok=False, error="blocked", retryable=False)
            return await super().send(conn, out)

    adapter = _FailsSecond()
    outcome = await dispatcher(adapter).dispatch(
        connection(), DraftReply(text="a" * 15)
    )

    assert len(adapter.sent) == 1
    assert outcome.permanent_failure == "blocked"
