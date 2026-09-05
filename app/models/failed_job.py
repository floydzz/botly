from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class FailedJob(TimestampMixin, SQLModel, table=True):
    """Work that will not be retried again, kept so a human can see it.

    A permanent send failure has to reach the seller inbox as "delivery
    failed"; a poison inbound event has to leave the queue without blocking it.
    Both land here.
    """

    __tablename__ = "failed_jobs"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    # "inbound" | "outbound". A plain string: a new kind of job must not need
    # a migration.
    kind: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    # SET NULL, not CASCADE: deleting a connection must not erase the record of
    # what went wrong on it.
    connection_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("channel_connections.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    inbound_event_id: int | None = Field(
        default=None,
        sa_column=Column(
            BigInteger,
            ForeignKey("inbound_events.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    payload: dict = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    error: str = Field(sa_column=Column(Text, nullable=False))
    attempts: int = Field(
        default=0, sa_column=Column(Integer, nullable=False, server_default="0")
    )
