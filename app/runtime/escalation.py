"""What takes a conversation away from the bot and gives it to a person.

Six triggers are named in the spec. Four are computable from what exists today.
Two -- low model confidence and strong negative sentiment -- need a brain that
can report a confidence and read a tone, and the brain is currently EchoBrain.
Those two are here as stubs that always abstain.

That is deliberate and it is the point of the Protocol: when the real brain
lands, its author replaces two classes. The pipeline, the inbox and every test
around them keep working, because they were written against the interface
rather than against the four rules that happened to be implementable first.

No trigger may guess. A rule that fires on a maybe sends a human a conversation
that did not need one, and an inbox full of those is an inbox nobody reads.
"""

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.channels.types import InboundEnvelope
from app.runtime.brain import DraftReply


class EscalationSignal(BaseModel):
    """One trigger's verdict.

    ``reason`` is what an agent reads when the conversation lands in their
    queue, so it is written for them, not for a log.
    """

    model_config = ConfigDict(frozen=True)

    escalate: bool
    reason: str | None = None


@runtime_checkable
class EscalationTrigger(Protocol):
    async def evaluate(
        self,
        envelope: InboundEnvelope,
        draft: DraftReply,
        bot_turns: int,
        max_bot_turns: int,
    ) -> EscalationSignal | None:
        """A signal, or None to abstain. Abstaining is not the same as voting
        no: a trigger that cannot tell must not out-vote one that can."""
        ...


def _matches(text: str | None, pattern: re.Pattern[str]) -> bool:
    # A media-only message has no text. Searching None crashes; treating it as
    # an empty string is a rule that silently never fires -- so say so here
    # once rather than in every trigger.
    return bool(text) and bool(pattern.search(text))


class BrainEscalationTrigger:
    """The brain asked for a human.

    This is how a tool failure arrives: the brain could not get a fact, and the
    one thing forbidden is inventing it.
    """

    async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
        if draft.escalate:
            return EscalationSignal(escalate=True, reason=draft.reason)
        return None


# English, Malay and Chinese in one pattern because customers here write all
# three, frequently inside one sentence. An English-only rule would simply
# never fire for a large part of the audience -- and would look like it worked.
_HUMAN_REQUEST = re.compile(
    r"real person|speak to (a |an )?(human|agent|person|someone)"
    r"|talk to (a |an )?(human|agent|person|someone)"
    r"|customer service|live agent"
    r"|cakap dengan orang|nak orang|bercakap dengan (orang|manusia)"
    r"|人工|真人|转人工|客服",
    re.IGNORECASE,
)

_MONEY = re.compile(
    r"refund|money back|chargeback|reimburse|compensation"
    r"|pulangkan (duit|wang)|duit balik|ganti rugi"
    r"|退款|退钱|赔偿|退货退款",
    re.IGNORECASE,
)


class HumanRequestedTrigger:
    async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
        if _matches(envelope.text, _HUMAN_REQUEST):
            return EscalationSignal(
                escalate=True, reason="the customer asked for a human"
            )
        return None


class MoneyKeywordTrigger:
    """Anything shaped like a refund goes to a person.

    v1 is read-only against commerce systems by design -- the bot may not take
    an action that costs money. A confident wrong answer about a refund is the
    single most expensive thing this product can say.
    """

    async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
        if _matches(envelope.text, _MONEY):
            return EscalationSignal(
                escalate=True, reason="the customer raised money or a refund"
            )
        return None


class UnresolvedTurnsTrigger:
    """The bot has answered N times and the customer is still asking.

    Whatever it is saying is not landing, and each further attempt is a person
    being kept from a person by a machine.
    """

    async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
        if bot_turns >= max_bot_turns:
            return EscalationSignal(
                escalate=True,
                reason=f"the bot replied {bot_turns} times without resolving it",
            )
        return None


class LowConfidenceTrigger:
    """Waiting on a brain that can report a confidence.

    EchoBrain has none. Inventing a proxy -- reply length, keyword coverage --
    would be a rule nobody validated, firing for reasons nobody intended, and
    it would be trusted because it looks like a real signal.
    """

    async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
        return None


class NegativeSentimentTrigger:
    """Waiting on a brain that can read tone.

    A keyword list of angry words is exactly the implementation to avoid: it
    misses sarcasm, misses every language it was not written in, and fires on
    "this is terrible weather".
    """

    async def evaluate(self, envelope, draft, bot_turns, max_bot_turns):
        return None


class EscalationPolicy:
    def __init__(self, triggers: list[EscalationTrigger]) -> None:
        self.triggers = triggers

    async def evaluate(
        self,
        envelope: InboundEnvelope,
        draft: DraftReply,
        bot_turns: int,
        max_bot_turns: int,
    ) -> EscalationSignal:
        for trigger in self.triggers:
            signal = await trigger.evaluate(
                envelope, draft, bot_turns, max_bot_turns
            )
            # First to fire wins. An agent reads the reason in a hurry, and
            # concatenating every rule that matched buries the one that
            # actually mattered.
            if signal is not None and signal.escalate:
                return signal
        return EscalationSignal(escalate=False)


def default_policy() -> EscalationPolicy:
    """Order matters: the most specific reason should be the one an agent sees.

    A refund request that the brain also failed a tool lookup on is better
    described as "the order lookup failed" than as "they said refund".
    """
    return EscalationPolicy(
        [
            BrainEscalationTrigger(),
            HumanRequestedTrigger(),
            MoneyKeywordTrigger(),
            LowConfidenceTrigger(),
            NegativeSentimentTrigger(),
            UnresolvedTurnsTrigger(),
        ]
    )
