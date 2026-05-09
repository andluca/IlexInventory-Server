"""Read-only selectors for apps.inventory.

Selectors compose query functions and return typed data.
They open their own psycopg connection (read-only semantics — no mutations).
Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

from typing import Generator


from apps.core.db import connect as _connect

from apps.inventory.queries.batches import (
    list_batches as _list_batches_query,
    select_batch_by_id as _select_batch_by_id_query,
)
from apps.inventory.queries.movements import (
    list_movements as _list_movements_query,
    stream_movements as _stream_movements_query,
)
from apps.inventory.types import BatchRow


def list_batches(
    *,
    owner_id: int,
    product_id: str | None = None,
    is_recalled: bool | None = None,
    expiring_within: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a paginated list of batches with on_hand.

    Returns: {items, total, limit, offset}
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, total = _list_batches_query(cur, params={
                "owner_id": owner_id,
                "product_id": product_id,
                "is_recalled": is_recalled,
                "expiring_within": expiring_within,
                "limit": limit,
                "offset": offset,
            })

    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def batch_by_id(*, owner_id: int, batch_id: str) -> BatchRow | None:
    """Return a single batch by id, or None on miss/cross-owner."""
    with _connect() as conn:
        with conn.cursor() as cur:
            return _select_batch_by_id_query(cur, params={"id": batch_id, "owner_id": owner_id})


def list_movements(
    *,
    owner_id: int,
    batch_id: str | None = None,
    product_id: str | None = None,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict:
    """Return a cursor-paginated list of movements.

    Returns: {items, next_cursor}
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, next_cursor = _list_movements_query(cur, params={
                "owner_id": owner_id,
                "batch_id": batch_id,
                "product_id": product_id,
                "kind": kind,
                "date_from": date_from,
                "date_to": date_to,
                "cursor": cursor,
                "limit": limit,
            })

    return {"items": rows, "next_cursor": next_cursor}


def stream_movements_for_owner(
    *,
    owner_id: int,
    batch_id: str | None = None,
    product_id: str | None = None,
    kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> Generator[dict, None, None]:
    """Yield all matching movement rows with no pagination cap.

    Used by the CSV export path. Applies the same filters as list_movements
    but streams the full result set via a psycopg cursor.

    Yields: one dict per movement row (same keys as MovementRow).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            yield from _stream_movements_query(cur, params={
                "owner_id": owner_id,
                "batch_id": batch_id,
                "product_id": product_id,
                "kind": kind,
                "date_from": date_from,
                "date_to": date_to,
            })
