from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class InboundEventStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    # The worker gave up. The row stays, and a FailedJob points at it.
    FAILED = "failed"


class InboundEvent(TimestampMixin, SQLModel, table=True):
    """One webhook delivery, stored raw before it is acted on.

    No soft delete: this is an event log, and an event that arrived cannot
    later not have arrived. The raw payload is kept because a parser bug found
    next month is only debuggable against the bytes that actually came in.
    """

    __tablename__ = "inbound_events"
    __table_args__ = (
        # The second line of dedupe defence, behind Redis. Redis is the fast
        # path and Redis can be flushed; this makes double-processing
        # impossible rather than merely unlikely.
        UniqueConstraint(
            "provider", "provider_update_id", name="uq_inbound_events_dedupe"
        ),
    )

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    connection_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("channel_connections.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    provider: str = Field(sa_column=Column(String(32), nullable=False))
    provider_update_id: str = Field(sa_column=Column(String(191), nullable=False))
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    status: InboundEventStatus = Field(
        default=InboundEventStatus.PENDING,
        sa_column=Column(
            String(16), nullable=False, server_default="pending", index=True
        ),
    )
    processed_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
