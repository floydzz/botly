from enum import Enum

from sqlalchemy import BigInteger, Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import EnumString, TimestampMixin


class Direction(str, Enum):
    INBOUND = "in"
    OUTBOUND = "out"


class SenderType(str, Enum):
    CUSTOMER = "customer"
    BOT = "bot"
    AGENT = "agent"


class DeliveryStatus(str, Enum):
    # An inbound message is delivered by definition, so SENT is the default.
    SENT = "sent"
    PENDING = "pending"
    FAILED = "failed"


class Message(TimestampMixin, SQLModel, table=True):
    """One message in a conversation, in either direction."""

    __tablename__ = "messages"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    conversation_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    # Denormalised for the same reason as on Conversation: every query that
    # reads messages must be tenant-filtered, and one predicate is harder to
    # forget than a join.
    merchant_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    direction: Direction = Field(
        sa_column=Column(EnumString(Direction, 8), nullable=False)
    )
    sender_type: SenderType = Field(
        sa_column=Column(EnumString(SenderType, 16), nullable=False)
    )
    # Only set when sender_type is AGENT. SET NULL so removing an agent does
    # not erase the history of what they said to a customer.
    sender_user_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    text: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    attachments: list = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default="[]"),
    )
    provider_message_id: str | None = Field(
        default=None, sa_column=Column(String(191), nullable=True)
    )
    delivery_status: DeliveryStatus = Field(
        default=DeliveryStatus.SENT,
        sa_column=Column(
            EnumString(DeliveryStatus, 16), nullable=False, server_default="sent"
        ),
    )
    # Why delivery failed, shown in the inbox next to the message. Without this
    # a permanent send failure only ever reached failed_jobs, which no screen
    # reads.
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
