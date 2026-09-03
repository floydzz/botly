from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Aware UTC on both columns.

    aib-backend mixed naive ``datetime.now`` defaults with aware UTC writes on
    update, so one row held two time bases and ``updated_at`` could sort before
    ``created_at``. One base, set here, for every table.

    Declared with ``sa_type`` rather than a ``Column`` instance: a Column is
    bound to the first table that claims it, so a shared one makes the second
    model importing this mixin fail with "already assigned to Table".
    """

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        nullable=False,
        sa_column_kwargs={"onupdate": utcnow},
    )


class SoftDeleteMixin:
    deleted_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),
        nullable=True,
    )
