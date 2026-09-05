from sqlalchemy import BigInteger, Column, ForeignKey, String
from sqlmodel import Field, SQLModel

from app.models.base import SoftDeleteMixin, TimestampMixin


class User(TimestampMixin, SoftDeleteMixin, SQLModel, table=True):
    """An agent who works a merchant's inbox.

    A user belongs to exactly one merchant. Multi-merchant access would need a
    join table, and inventing one before a customer asks for it buys nothing
    but a second place to get the tenant filter wrong.
    """

    __tablename__ = "users"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    merchant_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("merchants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    # The login identifier, so it is unique globally rather than per merchant:
    # the login form has no merchant field to disambiguate with.
    email: str = Field(
        sa_column=Column(String(255), nullable=False, unique=True, index=True)
    )
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))
    name: str = Field(sa_column=Column(String(255), nullable=False))
