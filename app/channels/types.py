from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

AttachmentKind = Literal["image", "video", "audio", "file"]


class Attachment(BaseModel):
    """One media item on a message, already resolved to a fetchable URL."""

    model_config = ConfigDict(frozen=True)

    kind: AttachmentKind
    url: str = Field(min_length=1)
    mime_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class ChannelCapabilities(BaseModel):
    """What one channel will and will not accept.

    The channels genuinely disagree: Telegram sends anything at any time,
    WhatsApp refuses free-form text once its 24-hour window closes. Without a
    manifest that is a special case in the dispatcher per provider, and those
    special cases leak into the runtime and the inbox. With one, the dispatcher
    asks a question instead of branching on a name.
    """

    model_config = ConfigDict(frozen=True)

    supports_media: bool
    max_text_len: int = Field(gt=0)
    # None means the channel never closes -- Telegram.
    session_window: timedelta | None = None
    requires_template_outside_window: bool = False
    supports_typing_indicator: bool = False

    @model_validator(mode="after")
    def _template_rule_needs_a_window(self) -> "ChannelCapabilities":
        if self.requires_template_outside_window and self.session_window is None:
            raise ValueError(
                "requires_template_outside_window=True is meaningless without a "
                "session_window: there is no 'outside' of a window that never closes."
            )
        return self


class InboundEnvelope(BaseModel):
    """One customer message, normalised out of a provider's webhook payload.

    Not frozen, unlike the value objects above: it carries ``raw`` as a dict, and
    a frozen model advertises a ``__hash__`` that would raise the moment anyone
    tried to use it. Mutability here is the lesser trap.
    """

    provider: str = Field(min_length=1)
    # The provider's own conversation key -- a chat id, a thread id.
    external_thread_id: str = Field(min_length=1)
    # Unique per delivery. Ingress dedupes on (provider, provider_update_id)
    # against both Redis and the inbound_event table, because Meta retries
    # aggressively and will deliver the same update more than once.
    provider_update_id: str = Field(min_length=1)
    provider_message_id: str | None = None
    sender_ref: str = Field(min_length=1)
    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    sent_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> "InboundEnvelope":
        if self.text is None and not self.attachments:
            raise ValueError("an inbound envelope needs text or at least one attachment")
        if self.sent_at.tzinfo is None or self.sent_at.utcoffset() is None:
            raise ValueError(
                "sent_at must be timezone-aware; a naive timestamp puts two time "
                "bases in one conversation"
            )
        return self


class OutboundMessage(BaseModel):
    """What the dispatcher asks an adapter to deliver.

    Carries a template reference rather than resolved text, because whether a
    template is required is the channel's business, not the brain's.
    """

    text: str | None = None
    attachments: tuple[Attachment, ...] = ()
    template_name: str | None = None
    template_variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _must_carry_something(self) -> "OutboundMessage":
        if self.text is None and not self.attachments and self.template_name is None:
            raise ValueError(
                "an outbound message needs text, an attachment, or a template"
            )
        return self


class SendResult(BaseModel):
    """The outcome of one delivery attempt.

    ``retryable`` separates a rate limit from a rejected recipient: the first is
    worth backing off on, the second belongs in failed_job where an agent sees
    "delivery failed" in the inbox.
    """

    model_config = ConfigDict(frozen=True)

    ok: bool
    provider_message_id: str | None = None
    error: str | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def _check(self) -> "SendResult":
        if not self.ok and not self.error:
            raise ValueError("a failed SendResult must carry an error")
        if self.ok and self.retryable:
            raise ValueError("a successful send is not retryable")
        return self
