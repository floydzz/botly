from datetime import datetime, timezone

import pytest

from app.channels.types import InboundEnvelope
from app.runtime.brain import Brain, DraftReply, EchoBrain


def envelope(text: str = "where is my parcel") -> InboundEnvelope:
    return InboundEnvelope(
        provider="fake",
        external_thread_id="7",
        provider_update_id="1",
        sender_ref="8",
        text=text,
        sent_at=datetime.now(timezone.utc),
    )


def test_a_draft_must_say_something_or_escalate():
    """A reply that is neither text nor an escalation is a customer left on
    read."""
    with pytest.raises(ValueError):
        DraftReply()


def test_an_escalation_needs_no_text():
    draft = DraftReply(escalate=True, reason="tool failure")

    assert draft.escalate is True
    assert draft.text is None


def test_an_escalation_must_carry_a_reason():
    """The reason is what the agent reads when the conversation lands in the
    inbox. An unexplained handoff wastes their first minute."""
    with pytest.raises(ValueError):
        DraftReply(escalate=True)


def test_the_echo_brain_satisfies_the_protocol():
    assert isinstance(EchoBrain(), Brain)


async def test_the_echo_brain_repeats_the_message():
    draft = await EchoBrain().respond(envelope())

    assert draft.text == "botly received: where is my parcel"
    assert draft.escalate is False


async def test_the_echo_brain_escalates_a_message_it_cannot_read():
    """A photo with no caption is exactly the case the real brain will hand to
    vision. Until that exists, guessing is the one thing forbidden -- facts
    come from tools, never from the model."""
    from app.channels.types import Attachment

    media_only = InboundEnvelope(
        provider="fake",
        external_thread_id="7",
        provider_update_id="2",
        sender_ref="8",
        attachments=(Attachment(kind="image", url="tg-file://x"),),
        sent_at=datetime.now(timezone.utc),
    )

    draft = await EchoBrain().respond(media_only)

    assert draft.escalate is True
    assert draft.reason
