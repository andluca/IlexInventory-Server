"""Shared psycopg connection + row-projection helpers.

Replaces the per-app `_connect()` and `_row_to_dict(cur, row)` helpers that
were duplicated across 9 service/selector modules and 10 query modules
respectively. ILEX-016 §2.3.

Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

import psycopg
from django.conf import settings


def connect() -> psycopg.Connection:
    """Open a raw psycopg connection to the configured DATABASE_URL.

    Caller owns commit/rollback. The connection is autocommit=False (the
    psycopg default), so service-layer transaction control is explicit.
    """
    return psycopg.connect(settings.DATABASE_URL)


def row_to_dict(cur, row) -> dict:
    """Project a raw psycopg row tuple into a dict keyed by column name.

    Uses `cur.description` for column ordering. Returns an empty dict if
    `row` is None — query callers usually check None before calling this,
    but this keeps the helper safe for `row_to_dict(cur, cur.fetchone())`.
    """
    if row is None:
        return {}
    return {d.name: row[i] for i, d in enumerate(cur.description)}
