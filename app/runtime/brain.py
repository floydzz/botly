"""The bot's brain, behind a Protocol.

The implementation here is a stub and is meant to be replaced. The Protocol is
not: the pipeline, the dispatcher and every test around them are written
against DraftReply, so swapping EchoBrain for the LangGraph brain is one class,
not a refactor.

The rule the real brain will have to keep, recorded here where its author will
read it: facts come from tools, never from the model. When a tool fails the bot
says it cannot check and escalates. A hallucinated order status is a refund
dispute.
"""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, model_validator

from app.channels.types import Attachment, InboundEnvelope


class DraftReply(BaseModel):
    """What the brain produced, before the channel has had its say.

    Deliberately not an OutboundMessage: the brain does not know whether the
    channel needs a template, how long its messages may be, or whether it takes
    media. That is the dispatcher's job, and keeping them separate is what
    stops channel rules leaking into the runtime.
    """

    model_config = ConfigDict(frozen=True)

    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    escalate: bool = False
    reason: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "DraftReply":
        if not self.escalate and self.text is None and not self.attachments:
            raise ValueError(
                "a draft reply must carry text, an attachment, or escalate; "
                "otherwise the customer is left on read"
            )
        if self.escalate and not self.reason:
            raise ValueError(
                "an escalation must carry a reason -- it is what the agent "
                "reads when the conversation lands in the inbox"
            )
        return self


@runtime_checkable
class Brain(Protocol):
    async def respond(self, envelope: InboundEnvelope) -> DraftReply: ...


class EchoBrain:
    """Repeats what it was told. Proves the pipeline, answers nothing.

    Build-order step 3 exists to prove ingress -> queue -> runtime -> dispatch
    works end to end. A real brain here would make that proof depend on an LLM
    provider, a knowledge base and a Shopee approval that has not arrived.
    """

    def __init__(self, prefix: str = "botly received: ") -> None:
        self._prefix = prefix

    async def respond(self, envelope: InboundEnvelope) -> DraftReply:
        if envelope.text is None:
            # Vision and OCR are a later plan. Until then, a message this brain
            # cannot read goes to a human rather than getting a guess.
            return DraftReply(
                escalate=True,
                reason="the message carries only media and cannot be read yet",
            )
        return DraftReply(text=f"{self._prefix}{envelope.text}")
