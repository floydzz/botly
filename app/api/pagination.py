"""Opaque keyset cursors for lists that reorder while an agent reads them."""

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


class InvalidCursor(ValueError):
    pass


class Cursor(BaseModel):
    model_config = ConfigDict(frozen=True)

    last_message_at: datetime | None
    id: int


def encode_cursor(last_message_at: datetime | None, row_id: int) -> str:
    payload = json.dumps(
        {
            "t": last_message_at.isoformat() if last_message_at is not None else None,
            "i": row_id,
        },
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(raw: str | None) -> Cursor | None:
    if raw is None:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
        when = payload["t"]
        return Cursor(
            last_message_at=datetime.fromisoformat(when) if when is not None else None,
            id=int(payload["i"]),
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
        UnicodeDecodeError,
    ) as exc:
        raise InvalidCursor("cursor is not readable") from exc
