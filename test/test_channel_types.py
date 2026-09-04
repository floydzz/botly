from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)


def _envelope(**overrides):
    base = dict(
        provider="fake",
        external_thread_id="thread-1",
        provider_update_id="update-1",
        sender_ref="customer-1",
        text="hello",
        sent_at=datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return InboundEnvelope(**base)


class TestChannelCapabilities:
    def test_a_channel_that_never_closes_needs_no_template_rule(self):
        caps = ChannelCapabilities(
            supports_media=True, max_text_len=4096, session_window=None
        )
        assert caps.session_window is None
        assert caps.requires_template_outside_window is False

    def test_a_windowed_channel_may_require_templates(self):
        caps = ChannelCapabilities(
            supports_media=True,
            max_text_len=4096,
            session_window=timedelta(hours=24),
            requires_template_outside_window=True,
        )
        assert caps.session_window == timedelta(hours=24)

    def test_template_rule_without_a_window_is_incoherent(self):
        with pytest.raises(ValidationError):
            ChannelCapabilities(
                supports_media=True,
                max_text_len=4096,
                session_window=None,
                requires_template_outside_window=True,
            )

    def test_max_text_len_must_be_positive(self):
        with pytest.raises(ValidationError):
            ChannelCapabilities(supports_media=True, max_text_len=0)


class TestInboundEnvelope:
    def test_a_text_message_round_trips(self):
        env = _envelope()
        assert env.text == "hello"
        assert env.attachments == ()

    def test_an_attachment_only_message_is_valid(self):
        env = _envelope(
            text=None,
            attachments=(Attachment(kind="image", url="https://example.invalid/a.png"),),
        )
        assert env.text is None
        assert env.attachments[0].kind == "image"

    def test_a_message_with_neither_text_nor_attachment_is_rejected(self):
        with pytest.raises(ValidationError):
            _envelope(text=None, attachments=())

    def test_naive_timestamps_are_rejected(self):
        with pytest.raises(ValidationError):
            _envelope(sent_at=datetime(2026, 9, 5, 12, 0))

    def test_dedupe_key_is_required_and_non_empty(self):
        with pytest.raises(ValidationError):
            _envelope(provider_update_id="")


class TestOutboundMessage:
    def test_plain_text_is_valid(self):
        assert OutboundMessage(text="hi").text == "hi"

    def test_a_template_reference_is_valid_without_text(self):
        out = OutboundMessage(template_name="order_update", template_variables={"n": "7"})
        assert out.template_name == "order_update"

    def test_an_empty_message_is_rejected(self):
        with pytest.raises(ValidationError):
            OutboundMessage()


class TestSendResult:
    def test_success_carries_a_provider_id(self):
        r = SendResult(ok=True, provider_message_id="m-1")
        assert r.ok and r.provider_message_id == "m-1"

    def test_a_failure_must_explain_itself(self):
        with pytest.raises(ValidationError):
            SendResult(ok=False)

    def test_a_success_cannot_be_retryable(self):
        with pytest.raises(ValidationError):
            SendResult(ok=True, retryable=True)
