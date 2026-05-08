"""Unit tests for apps.core.pagination — encode_cursor / decode_cursor.

Cursor format: base64url(f"{uuid}|{created_at.isoformat()}")
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def test_roundtrip():
    from apps.core.pagination import decode_cursor, encode_cursor

    u = uuid.uuid4()
    t = _utcnow()
    cursor = encode_cursor(u, t)
    result = decode_cursor(cursor)
    assert result is not None
    decoded_u, decoded_t = result
    assert decoded_u == u
    # ISO round-trip may lose sub-microsecond precision; compare to microsecond.
    assert decoded_t.replace(microsecond=decoded_t.microsecond) == t.replace(
        microsecond=t.microsecond
    )


def test_decode_none_returns_none():
    from apps.core.pagination import decode_cursor

    assert decode_cursor(None) is None


def test_decode_invalid_base64_returns_none():
    from apps.core.pagination import decode_cursor

    assert decode_cursor("not-base64!!!") is None


def test_decode_valid_b64_wrong_shape_returns_none():
    """Valid base64, but the payload doesn't contain a pipe separator."""
    from apps.core.pagination import decode_cursor

    assert decode_cursor("dmFsaWRiNjQ=") is None


def test_decode_wrong_separator_count_returns_none():
    """Too many pipes (would trip UUID parse)."""
    from apps.core.pagination import decode_cursor
    import base64

    junk = base64.urlsafe_b64encode(b"a|b|c").decode()
    assert decode_cursor(junk) is None


def test_no_logging_on_bad_cursor(caplog):
    """Bad-cursor fallback must be silent (no log lines emitted)."""
    from apps.core.pagination import decode_cursor

    with caplog.at_level("DEBUG"):
        decode_cursor("garbage-input")

    assert caplog.records == []
