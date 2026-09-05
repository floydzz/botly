"""Sign in, sign out, and who am I.

Deliberately small. There is no registration endpoint, no password reset and no
email verification: users are seeded, and every one of those flows is a new
attack surface that nobody has asked for yet.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SESSION_COOKIE, current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    hash_session_token,
    new_session_token,
    session_expiry,
    verify_password,
)
from app.models.login_session import LoginSession
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

# One message for a wrong password and for an email that has no account. Two
# messages turn the login form into a directory of who banks here.
_REFUSED = "invalid email or password"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    merchant_id: int


def _set_session_cookie(response: Response, token: str, ttl: timedelta) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ttl.total_seconds()),
        httponly=True,
        # Lax, not None: the inbox is same-site, and None would let any page
        # on the internet make authenticated requests on the agent's behalf.
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = (
        await db.execute(
            select(User).where(
                User.email == body.email.lower(), User.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()

    # verify_password runs even when there is no user, against a hash of the
    # submitted password, so that a missing account and a wrong password take
    # the same time. Without it the response time answers "does this address
    # have an account here?".
    stored_hash = user.password_hash if user else _DUMMY_HASH
    if not verify_password(body.password, stored_hash) or user is None:
        raise HTTPException(status_code=401, detail=_REFUSED)

    ttl = timedelta(seconds=settings.SESSION_TTL_SECONDS)
    token = new_session_token()
    db.add(
        LoginSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=session_expiry(ttl),
        )
    )
    await db.commit()

    _set_session_cookie(response, token, ttl)
    return user


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    now = datetime.now(timezone.utc)
    sessions = (
        await db.execute(
            select(LoginSession).where(
                LoginSession.user_id == user.id,
                LoginSession.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    for session in sessions:
        # Revoke the row, not merely the browser's copy. A cookie captured
        # before logout would otherwise still be a working key.
        session.revoked_at = now
        db.add(session)
    await db.commit()

    response.delete_cookie(SESSION_COOKIE, path="/")
    return Response(status_code=204)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> User:
    return user


# A real bcrypt hash of a value nobody can submit, used only to spend the same
# time on a missing account as on a wrong password.
_DUMMY_HASH = "$2b$12$" + "." * 53
