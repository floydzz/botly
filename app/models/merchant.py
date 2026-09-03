from sqlalchemy import BigInteger, Column, String
from sqlmodel import Field, SQLModel

from app.models.base import SoftDeleteMixin, TimestampMixin


class Merchant(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """The billing tenant. Owns shops; holds no commerce credentials itself."""

    __tablename__ = "merchants"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    name: str = Field(sa_column=Column(String(255), nullable=False, unique=True, index=True))
    status: str = Field(
        default="active",
        sa_column=Column(String(32), nullable=False, server_default="active"),
    )
