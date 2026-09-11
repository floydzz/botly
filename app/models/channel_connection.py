from enum import Enum

from sqlalchemy import BigInteger, Column, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.crypto import decrypt_credentials, encrypt_credentials
from app.models.base import EnumString, SoftDeleteMixin, TimestampMixin


class ChannelConnectionStatus(str, Enum):
    ACTIVE = "active"
    CONNECTING = "connecting"
    # Credentials failed to refresh. The connection still exists and the inbox
    # still shows its history; sends are expected to fail until it is repaired.
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class ChannelConnection(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """One bot's presence on one channel.

    ``provider`` is a plain string and nothing outside ``app/channels/<provider>/``
    may branch on its value -- capability differences belong in the adapter's
    manifest, not in scattered conditionals.
    """

    __tablename__ = "channel_connections"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_ref", name="uq_channel_connections_provider_ref"
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    bot_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    # The provider's own identifier for this endpoint: a Telegram bot username,
    # a WhatsApp phone number id, a Shopee shop id.
    external_ref: str = Field(sa_column=Column(String(191), nullable=False))
    credentials_encrypted: str = Field(
        default="", sa_column=Column(Text, nullable=False, server_default="")
    )
    config: dict = Field(
        default_factory=dict, sa_column=Column(JSONB, nullable=False, server_default="{}")
    )
    status: ChannelConnectionStatus = Field(
        default=ChannelConnectionStatus.DISCONNECTED,
        sa_column=Column(
            EnumString(ChannelConnectionStatus, 32),
            nullable=False,
            server_default="disconnected",
        ),
    )

    def set_credentials(self, payload: dict) -> None:
        self.credentials_encrypted = encrypt_credentials(payload)

    def get_credentials(self) -> dict:
        return decrypt_credentials(self.credentials_encrypted)
