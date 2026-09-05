"""Password and session-token primitives.

Two different one-way functions live here and the difference is deliberate.

A *password* is low-entropy and chosen by a human, so its hash must be slow --
bcrypt with a per-hash salt, so that a leaked table cannot be run through a
dictionary and cannot reveal that two accounts share a password.

A *session token* is 256 bits from a CSPRNG. There is nothing to guess, so
there is nothing for a slow hash to defend. Using bcrypt on it would add its
cost to *every authenticated request*, which is the wrong place to spend
100ms. SHA-256 is enough: it stops a database read from being turned directly
into a live session, which is the only threat that applies.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt

# bcrypt reads at most 72 bytes and raises on longer input. Pre-hashing keeps a
# long passphrase working -- and keeps a 200-character password from being a
# 500 on the login endpoint.
_BCRYPT_MAX_BYTES = 72


def _prepare(plain: str) -> bytes:
    encoded = plain.encode("utf-8")
    if len(encoded) <= _BCRYPT_MAX_BYTES:
        return encoded
    # Hex, not raw digest: a raw digest can contain a NUL byte, and bcrypt
    # truncates at the first one.
    return hashlib.sha256(encoded).hexdigest().encode("ascii")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prepare(plain), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # A malformed stored hash is a failed login, not a stack trace. A 500
        # here tells an attacker they found something worth poking at.
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(ttl: timedelta) -> datetime:
    return datetime.now(timezone.utc) + ttl
