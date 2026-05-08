"""Cursor pagination helpers.

Encodes (UUID, datetime) into an opaque base64url cursor and decodes safely
with a silent bad-cursor fallback (caller treats None as "first page").

Format: base64url(f"{uuid}|{created_at.isoformat()}")

Consumed by: /sales-orders (ILEX-007), /movements (ILEX-006),
             /financials/margin (ILEX-008) — per SPEC §2.6.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime


def encode_cursor(uid: uuid.UUID, created_at: datetime) -> str:
    """Encode (UUID, datetime) into an opaque base64url cursor string."""
    payload = f"{uid}|{created_at.isoformat()}"
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str | None) -> tuple[uuid.UUID, datetime] | None:
    """Decode a cursor string back to (UUID, datetime).

    Returns None for None or any malformed input — caller treats None as
    "first page" (silent fallback per SPEC §2.6, no logging).
    """
    if cursor is None:
        return None

    try:
        # Pad if necessary (base64url may omit trailing '=')
        padding = 4 - len(cursor) % 4
        if padding != 4:
            cursor = cursor + "=" * padding
        payload = base64.urlsafe_b64decode(cursor).decode()
    except Exception:  # noqa: BLE001 — any decode failure → first page
        return None

    parts = payload.split("|")
    if len(parts) != 2:
        return None

    try:
        uid = uuid.UUID(parts[0])
        dt = datetime.fromisoformat(parts[1])
    except (ValueError, AttributeError):
        return None

    return uid, dt
