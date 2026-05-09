"""SQL query functions for the idempotency_keys cache.

Companion module to ``apps.core.idempotency`` (the decorator). The decorator
owns the connection lifecycle and `psycopg.Error` swallowing semantics —
this module owns the parameterized SQL.

Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

from typing import Any


def cache_lookup(
    cur, *, owner_id: int, key: str, endpoint: str
) -> tuple[int, Any] | None:
    """Return (status, body) cached for (owner_id, key, endpoint), or None."""
    cur.execute(
        """
        SELECT response_status, response_body
          FROM idempotency_keys
         WHERE owner_id = %s AND key = %s AND endpoint = %s
        """,
        (owner_id, key, endpoint),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row[0], row[1]


def cache_insert(
    cur,
    *,
    owner_id: int,
    key: str,
    endpoint: str,
    status: int,
    body_text: str,
) -> None:
    """INSERT (owner_id, key, endpoint, status, body) ON CONFLICT DO NOTHING."""
    cur.execute(
        """
        INSERT INTO idempotency_keys
               (owner_id, key, endpoint, response_status, response_body)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (owner_id, key, endpoint) DO NOTHING
        """,
        (owner_id, key, endpoint, status, body_text),
    )
