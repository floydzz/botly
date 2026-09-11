from datetime import datetime, timezone

import pytest

from app.api.pagination import InvalidCursor, decode_cursor, encode_cursor


def test_cursor_round_trip_and_opacity():
    when = datetime(2026, 9, 10, 8, 30, tzinfo=timezone.utc)
    encoded = encode_cursor(when, 41)
    cursor = decode_cursor(encoded)
    assert cursor.last_message_at == when
    assert cursor.id == 41
    assert "2026" not in encoded


def test_invalid_cursor_is_rejected():
    with pytest.raises(InvalidCursor):
        decode_cursor("not-a-cursor")
