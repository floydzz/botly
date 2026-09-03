"""Model registry.

Importing a model class is what registers its table on ``SQLModel.metadata``.
Alembic autogenerate reads that metadata, so a model missing from this file is
a model missing from every migration -- and the omission is silent.
"""

from app.models.bot import Bot
from app.models.channel_connection import ChannelConnection, ChannelConnectionStatus
from app.models.merchant import Merchant
from app.models.shop import Shop

__all__ = [
    "Bot",
    "ChannelConnection",
    "ChannelConnectionStatus",
    "Merchant",
    "Shop",
]
