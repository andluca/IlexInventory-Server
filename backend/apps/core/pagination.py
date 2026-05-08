"""Cursor pagination helpers.

Encodes/decodes opaque base64url cursors for stable pagination.

Two cursor variants:
  - encode_cursor / decode_cursor: (UUID, datetime) — used by /sales-orders, /movements
  - encode_decimal_cursor / decode_decimal_cursor: (Decimal, UUID) — used by /financials/margin

Format for (UUID, datetime): base64url(f"{uuid}|{created_at.isoformat()}")
Format for (Decimal, UUID):  base64url(f"{decimal}|{uuid}")

Consumed by: /sales-orders (ILEX-007), /movements (ILEX-006),
             /financials/margin (ILEX-008) — per SPEC §2.6.
"""

from __future__ import annotations

import base64
import uuid
from datetime import datetime
from decimal import Decimal


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


# ---------------------------------------------------------------------------
# Decimal+UUID cursor (for /financials/margin — ordered by revenue DESC, product_id DESC)
# ---------------------------------------------------------------------------

def encode_decimal_cursor(decimal_val: Decimal, uuid_val: uuid.UUID) -> str:
    """Encode (Decimal, UUID) into an opaque base64url cursor string."""
    payload = f"{decimal_val}|{uuid_val}"
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_decimal_cursor(cursor: str | None) -> tuple[Decimal, uuid.UUID] | None:
    """Decode a cursor string back to (Decimal, UUID).

    Returns None for None or any malformed input — caller treats None as
    "first page" (silent fallback per SPEC §2.6, no logging).
    """
    if cursor is None:
        return None

    try:
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
        decimal_val = Decimal(parts[0])
        uuid_val = uuid.UUID(parts[1])
    except (ValueError, AttributeError):
        return None

    return decimal_val, uuid_val
