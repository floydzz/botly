from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from app.models.base import EnumString, TimestampMixin


class HandoffState(str, Enum):
    """Who is answering. The pivotal field of the whole inbox."""

    BOT = "bot"
    # Escalated, nobody has picked it up yet. This is the queue an agent works.
    PENDING_HUMAN = "pending_human"
    HUMAN = "human"
    RESOLVED = "resolved"


class Conversation(TimestampMixin, SQLModel, table=True):
    """One customer's thread on one channel connection."""

    __tablename__ = "conversations"
    __table_args__ = (
        # One thread is one conversation. Without this a burst of concurrent
        # webhooks creates two rows for one customer and the agent sees a split
        # history. Scoped to the connection, not global: two providers will
        # collide on thread ids sooner or later.
        UniqueConstraint(
            "channel_connection_id",
            "external_thread_id",
            name="uq_conversations_connection_thread",
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    # Denormalised from bot -> shop -> merchant so that a tenant filter is one
    # indexed predicate instead of three joins. The spec makes the same trade
    # for kb_chunk, for the same reason: a forgotten join is a cross-tenant
    # leak that raises nothing and simply returns extra rows.
    merchant_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    bot_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("bots.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    channel_connection_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("channel_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    external_thread_id: str = Field(sa_column=Column(String(191), nullable=False))
    # The provider's identifier for the person on the other end.
    customer_ref: str = Field(sa_column=Column(String(191), nullable=False))
    customer_name: str | None = Field(
        default=None, sa_column=Column(String(255), nullable=True)
    )

    handoff_state: HandoffState = Field(
        default=HandoffState.BOT,
        sa_column=Column(
            EnumString(HandoffState, 32),
            nullable=False,
            server_default="bot",
            index=True,
        ),
    )
    assignee_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            # SET NULL: removing an agent must not delete the conversations
            # they were working.
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    # While set, the bot stays quiet even if handoff_state drifts back to bot.
    bot_muted_until: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )

    # What the dispatcher's session-window rule reads. Task 9 made it a
    # parameter precisely so the dispatcher would not have to wait for this
    # table -- the caller changes, the dispatcher does not.
    last_inbound_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    last_message_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True, index=True
    )
    # Unread is "messages after this instant", not a counter: a counter has to
    # be kept correct on every write and drifts the first time one is missed.
    agent_last_read_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
