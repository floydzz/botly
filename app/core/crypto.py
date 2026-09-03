import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class CredentialsCryptoError(RuntimeError):
    """Raised when credentials cannot be encrypted or trusted."""


def _cipher() -> Fernet:
    key = settings.CREDENTIALS_ENCRYPTION_KEY
    if not key:
        raise CredentialsCryptoError(
            "CREDENTIALS_ENCRYPTION_KEY is not set; refusing to handle channel "
            "credentials. Generate one with Fernet.generate_key()."
        )
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise CredentialsCryptoError(
            "CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_credentials(payload: dict) -> str:
    """Encrypt a channel credential blob for storage.

    Fernet is authenticated, so a row edited in the database fails to decrypt
    instead of yielding attacker-chosen credentials that we then send to a
    provider.
    """

    return _cipher().encrypt(json.dumps(payload, sort_keys=True).encode()).decode()


def decrypt_credentials(token: str) -> dict:
    try:
        return json.loads(_cipher().decrypt(token.encode()))
    except InvalidToken as exc:
        raise CredentialsCryptoError(
            "Stored credentials failed authentication; they were tampered with "
            "or encrypted under a different key."
        ) from exc
