"""Model registry.

Importing a model class is what registers its table on ``SQLModel.metadata``.
Alembic autogenerate reads that metadata, so a model missing from this file is
a model missing from every migration -- and the omission is silent.
"""

from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.conversation import Conversation, HandoffState
from app.models.failed_job import FailedJob
from app.models.inbound_event import InboundEvent, InboundEventStatus
from app.models.login_session import LoginSession
from app.models.merchant import Merchant
from app.models.message import DeliveryStatus, Direction, Message, SenderType
from app.models.shop import Shop
from app.models.user import User

__all__ = [
    "Bot",
    "ChannelConnection",
    "ChannelConnectionStatus",
    "Conversation",
    "DeliveryStatus",
    "Direction",
    "FailedJob",
    "HandoffState",
    "InboundEvent",
    "InboundEventStatus",
    "LoginSession",
    "Merchant",
    "Message",
    "SenderType",
    "Shop",
    "User",
]
