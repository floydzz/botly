"""The provider rules the reply composer must explain before an agent types."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.channels.types import ChannelCapabilities
from app.dispatch.dispatcher import window_is_closed

_CLOSED = "the session window has closed and this channel requires an approved template"


class SendPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    can_send_freeform: bool
    reason: str | None = None
    max_text_len: int
    supports_media: bool
    window_closes_at: datetime | None = None


def build_send_policy(
    caps: ChannelCapabilities, last_inbound_at: datetime | None
) -> SendPolicy:
    refused = window_is_closed(caps, last_inbound_at) and caps.requires_template_outside_window
    return SendPolicy(
        can_send_freeform=not refused,
        reason=_CLOSED if refused else None,
        max_text_len=caps.max_text_len,
        supports_media=caps.supports_media,
        window_closes_at=(
            last_inbound_at + caps.session_window
            if caps.session_window is not None and last_inbound_at is not None
            else None
        ),
    )
