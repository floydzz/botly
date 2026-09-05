"""The rules that take a conversation away from the bot.

Two of the spec's six triggers cannot be built yet: "low model confidence" and
"strong negative sentiment" both need a real brain, and the brain is EchoBrain.
They exist here as stubs that never fire, so the interface is settled and the
inbox never has to change when the real brain lands.
"""

from datetime import datetime, timezone

import pytest

from app.channels.types import Attachment, InboundEnvelope
from app.runtime.brain import DraftReply
from app.runtime.escalation import (
    EscalationPolicy,
    LowConfidenceTrigger,
    NegativeSentimentTrigger,
    default_policy,
)


def envelope(text: str | None = "hello") -> InboundEnvelope:
    return InboundEnvelope(
        provider="fake",
        external_thread_id="t",
        provider_update_id="u",
        sender_ref="c",
        text=text,
        # An envelope needs text or an attachment. A photo with no caption is
        # exactly the media-only case the keyword rules must survive.
        attachments=() if text else (Attachment(kind="image", url="x://a.jpg"),),
        sent_at=datetime.now(timezone.utc),
    )


async def evaluate(text: str, *, draft=None, bot_turns: int = 0, max_turns: int = 3):
    return await default_policy().evaluate(
        envelope(text),
        draft=draft or DraftReply(text="a reply"),
        bot_turns=bot_turns,
        max_bot_turns=max_turns,
    )


# --- the four that are computable today -------------------------------------


async def test_a_brain_that_escalated_is_honoured():
    """A tool failure reaches here as DraftReply.escalate. The bot saying "I
    could not check" is the whole point: a hallucinated order status is a
    refund dispute."""
    signal = await evaluate(
        "where is my parcel",
        draft=DraftReply(escalate=True, reason="order lookup timed out"),
    )

    assert signal.escalate is True
    assert signal.reason == "order lookup timed out"


async def test_an_explicit_request_for_a_human_escalates():
    signal = await evaluate("can I talk to a real person please")

    assert signal.escalate is True
    assert "human" in signal.reason


@pytest.mark.parametrize(
    "text",
    [
        "I want to speak to an agent",
        "boleh cakap dengan orang",  # Malay
        "我要人工",  # Chinese
    ],
)
async def test_the_request_is_recognised_in_the_languages_sellers_actually_get(text):
    """The audience writes English, Malay and Chinese, often in one sentence.
    An English-only match would silently never fire for half the customers."""
    assert (await evaluate(text)).escalate is True


@pytest.mark.parametrize(
    "text",
    ["I want a refund", "can I get my money back", "退款", "nak refund boleh?"],
)
async def test_money_talk_escalates(text):
    """v1 is read-only against commerce systems and the bot may not take an
    action that costs money. Anything shaped like a refund goes to a person."""
    signal = await evaluate(text)

    assert signal.escalate is True
    assert "money" in signal.reason or "refund" in signal.reason


async def test_an_ordinary_question_does_not_escalate():
    assert (await evaluate("what size should I buy")).escalate is False


async def test_too_many_bot_turns_escalates():
    """Three answers that did not land is a customer being kept from a human
    by a machine that is not helping."""
    assert (await evaluate("still not working", bot_turns=3)).escalate is True
    assert (await evaluate("still not working", bot_turns=2)).escalate is False


async def test_the_turn_threshold_is_configurable():
    assert (await evaluate("hm", bot_turns=1, max_turns=1)).escalate is True


# --- the two that are waiting on a real brain -------------------------------


async def test_the_confidence_trigger_never_fires_yet():
    """EchoBrain has no notion of confidence. A stub that guesses would be
    worse than one that abstains."""
    signal = await LowConfidenceTrigger().evaluate(
        envelope(), draft=DraftReply(text="x"), bot_turns=0, max_bot_turns=3
    )

    assert signal is None


async def test_the_sentiment_trigger_never_fires_yet():
    signal = await NegativeSentimentTrigger().evaluate(
        envelope("this is terrible and I am furious"),
        draft=DraftReply(text="x"),
        bot_turns=0,
        max_bot_turns=3,
    )

    assert signal is None


async def test_both_stubs_are_wired_into_the_default_policy():
    """The point of the stubs is that the policy already calls them. Swapping
    in the real implementation must not require touching the pipeline."""
    kinds = {type(t).__name__ for t in default_policy().triggers}

    assert "LowConfidenceTrigger" in kinds
    assert "NegativeSentimentTrigger" in kinds


# --- policy mechanics -------------------------------------------------------


async def test_the_first_trigger_to_fire_wins():
    """Reasons are read by a human in a hurry. Concatenating every rule that
    matched buries the one that mattered."""

    class _Always:
        def __init__(self, reason):
            self._reason = reason

        async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
            from app.runtime.escalation import EscalationSignal

            return EscalationSignal(escalate=True, reason=self._reason)

    policy = EscalationPolicy([_Always("first"), _Always("second")])
    signal = await policy.evaluate(
        envelope(), draft=DraftReply(text="x"), bot_turns=0, max_bot_turns=3
    )

    assert signal.reason == "first"


async def test_a_message_with_no_text_is_not_keyword_matched():
    """A photo has no text to search. Matching against None is a crash, and
    treating it as an empty match is a rule that silently never fires."""
    signal = await default_policy().evaluate(
        envelope(None), draft=DraftReply(text="x"), bot_turns=0, max_bot_turns=3
    )

    assert signal.escalate is False
