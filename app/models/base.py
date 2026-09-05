from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, String
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EnumString(TypeDecorator):
    """A plain VARCHAR column that comes back as its Enum member.

    A str-Enum stored in a bare String column loads as a bare string, so
    ``row.status is Status.PENDING`` answers True for an object still in
    memory and False for the same row after it has been reloaded -- and the
    identity map holds only weak references, so which one you get depends on
    garbage collection. That is the worst shape a bug can have.

    Storing a string rather than a database enum is deliberate: a new status
    must not need a migration. This brings the Python type back without giving
    that up.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[Enum], length: int) -> None:
        super().__init__(length=length)
        self._enum = enum_class

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return self._enum(value).value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self._enum(value)


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
