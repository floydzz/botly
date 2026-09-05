"""Login, session and the tenant boundary.

The tenant assertions here are the important ones. A login bug is visible the
first time someone tries it; a tenant-scoping bug returns extra rows quietly
and nobody notices until it is a customer's data in someone else's inbox.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import hash_password, hash_session_token, new_session_token
from app.main import app
from app.models.login_session import LoginSession
from app.models.merchant import Merchant
from app.models.user import User

pytestmark = pytest.mark.integration

SESSION_COOKIE = "botly_session"


@pytest.fixture
def wired(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield
    app.dependency_overrides.clear()


async def _user(db, email="budi@example.com", password="s3cret-passphrase"):
    merchant = Merchant(name=f"M-{email}")
    db.add(merchant)
    await db.flush()
    user = User(
        merchant_id=merchant.id,
        email=email,
        password_hash=hash_password(password),
        name="Budi",
    )
    db.add(user)
    await db.flush()
    return user


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_correct_password_starts_a_session(db_session, wired):
    user = await _user(db_session)

    async with _client() as client:
        response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )

    assert response.status_code == 200
    assert response.json()["email"] == user.email
    assert SESSION_COOKIE in response.cookies


async def test_the_session_cookie_is_not_readable_by_javascript(db_session, wired):
    """An XSS on the inbox must not be able to walk away with the session."""
    user = await _user(db_session, email="httponly@example.com")

    async with _client() as client:
        response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


async def test_a_wrong_password_is_refused(db_session, wired):
    user = await _user(db_session, email="wrong@example.com")

    async with _client() as client:
        response = await client.post(
            "/auth/login", json={"email": user.email, "password": "not-it"}
        )

    assert response.status_code == 401
    assert SESSION_COOKIE not in response.cookies


async def test_an_unknown_email_fails_the_same_way_as_a_wrong_password(
    db_session, wired
):
    """Two different messages turn the login form into a directory of who has
    an account here."""
    await _user(db_session, email="known@example.com")

    async with _client() as client:
        unknown = await client.post(
            "/auth/login", json={"email": "nobody@example.com", "password": "x"}
        )
        wrong = await client.post(
            "/auth/login", json={"email": "known@example.com", "password": "x"}
        )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


async def test_the_stored_session_is_a_hash_of_the_cookie(db_session, wired):
    from sqlalchemy import select

    user = await _user(db_session, email="hash@example.com")

    async with _client() as client:
        response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )

    cookie = response.cookies[SESSION_COOKIE]
    stored = (
        await db_session.execute(
            select(LoginSession).where(LoginSession.user_id == user.id)
        )
    ).scalar_one()

    assert stored.token_hash == hash_session_token(cookie)
    assert cookie not in stored.token_hash


async def test_me_returns_the_signed_in_user(db_session, wired):
    user = await _user(db_session, email="me@example.com")

    async with _client() as client:
        await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )
        response = await client.get("/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == user.email
    assert body["merchant_id"] == user.merchant_id


async def test_me_without_a_cookie_is_401(db_session, wired):
    async with _client() as client:
        response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_a_forged_cookie_is_401(db_session, wired):
    async with _client() as client:
        client.cookies.set(SESSION_COOKIE, new_session_token())
        response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_an_expired_session_is_refused(db_session, wired):
    """A session that outlives its expiry is a session that never ends."""
    user = await _user(db_session, email="expired@example.com")
    token = new_session_token()
    db_session.add(
        LoginSession(
            user_id=user.id,
            token_hash=hash_session_token(token),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await db_session.flush()

    async with _client() as client:
        client.cookies.set(SESSION_COOKIE, token)
        response = await client.get("/auth/me")

    assert response.status_code == 401


async def test_logging_out_kills_the_session(db_session, wired):
    user = await _user(db_session, email="logout@example.com")

    async with _client() as client:
        await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )
        assert (await client.get("/auth/me")).status_code == 200

        await client.post("/auth/logout")
        after = await client.get("/auth/me")

    assert after.status_code == 401


async def test_a_revoked_session_cannot_be_replayed(db_session, wired):
    """Logout must invalidate the row, not merely clear the browser's cookie.
    A cookie captured before logout is otherwise still a valid key."""
    from sqlalchemy import select

    user = await _user(db_session, email="replay@example.com")

    async with _client() as client:
        login = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )
        stolen = login.cookies[SESSION_COOKIE]
        await client.post("/auth/logout")

    stored = (
        await db_session.execute(
            select(LoginSession).where(
                LoginSession.token_hash == hash_session_token(stolen)
            )
        )
    ).scalar_one()
    assert stored.revoked_at is not None

    async with _client() as replay:
        replay.cookies.set(SESSION_COOKIE, stolen)
        response = await replay.get("/auth/me")

    assert response.status_code == 401


async def test_a_soft_deleted_user_cannot_sign_in(db_session, wired):
    user = await _user(db_session, email="gone@example.com")
    user.deleted_at = datetime.now(timezone.utc)
    db_session.add(user)
    await db_session.flush()

    async with _client() as client:
        response = await client.post(
            "/auth/login",
            json={"email": user.email, "password": "s3cret-passphrase"},
        )

    assert response.status_code == 401
