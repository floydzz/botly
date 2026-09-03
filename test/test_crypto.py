import pytest
from cryptography.fernet import Fernet

from app.core import crypto
from app.core.crypto import CredentialsCryptoError


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(
        crypto.settings, "CREDENTIALS_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


def test_roundtrip_preserves_the_payload():
    payload = {"bot_token": "123:ABC", "shop_id": 99}

    assert crypto.decrypt_credentials(crypto.encrypt_credentials(payload)) == payload


def test_ciphertext_does_not_contain_the_secret():
    token = crypto.encrypt_credentials({"bot_token": "123:ABC"})

    assert "123:ABC" not in token


def test_each_encryption_produces_a_distinct_token():
    payload = {"bot_token": "123:ABC"}

    assert crypto.encrypt_credentials(payload) != crypto.encrypt_credentials(payload)


def test_tampered_token_is_rejected_rather_than_decoded():
    token = crypto.encrypt_credentials({"bot_token": "123:ABC"})
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")

    with pytest.raises(CredentialsCryptoError):
        crypto.decrypt_credentials(tampered)


def test_missing_key_fails_loudly(monkeypatch):
    monkeypatch.setattr(crypto.settings, "CREDENTIALS_ENCRYPTION_KEY", "")

    with pytest.raises(CredentialsCryptoError, match="CREDENTIALS_ENCRYPTION_KEY"):
        crypto.encrypt_credentials({"bot_token": "123:ABC"})
