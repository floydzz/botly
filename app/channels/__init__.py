"""Channel adapters.

The only package permitted to know a provider by name. Nothing here imports a
concrete adapter -- importing one would put its provider name in every module
that touches the package root.
"""

from app.channels.base import ChannelAdapter
from app.channels.types import (
    Attachment,
    ChannelCapabilities,
    InboundEnvelope,
    OutboundMessage,
    SendResult,
)

__all__ = [
    "Attachment",
    "ChannelAdapter",
    "ChannelCapabilities",
    "InboundEnvelope",
    "OutboundMessage",
    "SendResult",
]
