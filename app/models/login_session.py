from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin


class LoginSession(TimestampMixin, SQLModel, table=True):
    """One browser session.

    Named LoginSession rather than Session because every module here already
    has a ``session`` in scope that means a database session, and two meanings
    for one word in one file is how the wrong one gets passed.

    The row holds a hash, never the token itself: a database read must not be
    convertible straight into a live session.
    """

    __tablename__ = "login_sessions"

    id: int | None = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    user_id: int = Field(
        sa_column=Column(
            BigInteger,
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    # SHA-256 hex of the cookie value. Indexed because it is the lookup key on
    # every authenticated request.
    token_hash: str = Field(
        sa_column=Column(String(64), nullable=False, unique=True, index=True)
    )
    expires_at: datetime = Field(sa_type=DateTime(timezone=True), nullable=False)
    revoked_at: datetime | None = Field(
        default=None, sa_type=DateTime(timezone=True), nullable=True
    )
