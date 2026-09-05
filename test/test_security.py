from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import (
    hash_password,
    hash_session_token,
    new_session_token,
    session_expiry,
    verify_password,
)


def test_a_password_verifies_against_its_own_hash():
    hashed = hash_password("correct horse battery staple")

    assert verify_password("correct horse battery staple", hashed) is True


def test_a_wrong_password_does_not_verify():
    assert verify_password("wrong", hash_password("right")) is False


def test_the_hash_is_not_the_password():
    """Obvious, and worth a test anyway: the one bug this class of code has is
    storing the plaintext by accident."""
    assert "hunter2" not in hash_password("hunter2")


def test_the_same_password_hashes_differently_each_time():
    """A per-hash salt is what stops one leaked table from revealing that two
    accounts share a password."""
    assert hash_password("same") != hash_password("same")


def test_verifying_against_a_corrupt_hash_is_false_not_an_exception():
    """A malformed row must fail the login, not 500 the endpoint -- a stack
    trace here tells an attacker they found something interesting."""
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_a_password_longer_than_bcrypt_accepts_still_works():
    """bcrypt truncates at 72 bytes and raises on longer input in 4.1+. A
    passphrase must not be able to 500 the login endpoint."""
    long_password = "a" * 200

    assert verify_password(long_password, hash_password(long_password)) is True


def test_two_session_tokens_are_never_the_same():
    assert new_session_token() != new_session_token()


def test_a_session_token_is_stored_as_a_hash():
    token = new_session_token()

    assert hash_session_token(token) != token
    assert hash_session_token(token) == hash_session_token(token)


def test_session_expiry_is_timezone_aware_and_in_the_future():
    expiry = session_expiry(timedelta(days=14))

    assert expiry.tzinfo is not None
    assert expiry > datetime.now(timezone.utc)
