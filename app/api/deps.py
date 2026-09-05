"""Request-scoped identity, and the tenant boundary built on it.

``current_user`` is the only place a session cookie is turned into a user, and
``TenantScope`` is the only thing endpoints are given to filter by. Neither
endpoint code nor query code ever reads a merchant id out of a request body or
a path parameter -- if it could, a caller could name someone else's tenant.
"""

from datetime import datetime, timezone

from fastapi import Cookie, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_session_token
from app.models.login_session import LoginSession
from app.models.user import User

SESSION_COOKIE = "botly_session"


async def current_user(
    botly_session: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not botly_session:
        raise HTTPException(status_code=401, detail="not authenticated")

    now = datetime.now(timezone.utc)
    user = (
        await db.execute(
            select(User)
            .join(LoginSession, LoginSession.user_id == User.id)
            .where(
                LoginSession.token_hash == hash_session_token(botly_session),
                LoginSession.revoked_at.is_(None),
                LoginSession.expires_at > now,
                User.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if user is None:
        # One message for every reason -- expired, revoked, forged, or a user
        # who has since been removed. Telling them apart tells an attacker
        # which of their guesses was closest.
        raise HTTPException(status_code=401, detail="not authenticated")
    return user


class TenantScope:
    """The signed-in user's merchant, and nothing else.

    A separate type rather than a bare int so that a query helper's signature
    says out loud that it is tenant-filtered, and so that passing the wrong
    integer is a type error rather than a leak.
    """

    def __init__(self, user: User) -> None:
        self.user = user
        self.merchant_id = user.merchant_id


async def tenant(user: User = Depends(current_user)) -> TenantScope:
    return TenantScope(user)
