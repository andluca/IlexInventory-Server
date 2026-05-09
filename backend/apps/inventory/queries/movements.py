"""SQL query functions for the stock_movements aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. append-only — no UPDATE or DELETE functions here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Generator

from apps.core.db import row_to_dict as _row_to_dict
from apps.core.owner_scope import scoped
from apps.core.pagination import decode_cursor, encode_cursor


@scoped
def insert_movement(cur, *, params: dict) -> dict:
    """INSERT a new stock_movement row. Returns the inserted row as a dict.

    params keys: owner_id, batch_id, kind, signed_quantity, notes (nullable),
                 reference_type (nullable), reference_id (nullable)
    """
    cur.execute(
        """
        INSERT INTO stock_movements (
            owner_id, batch_id, kind, signed_quantity,
            notes, reference_type, reference_id
        ) VALUES (
            %(owner_id)s, %(batch_id)s, %(kind)s, %(signed_quantity)s,
            %(notes)s, %(reference_type)s, %(reference_id)s
        )
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def on_hand_for_batch(cur, *, params: dict) -> object:
    """SELECT on_hand from v_stock_by_batch for a single (batch_id, owner_id).

    Returns the Decimal on_hand or 0 if no movements exist.

    params keys: batch_id, owner_id
    """
    cur.execute(
        """
        SELECT COALESCE(on_hand, 0)
          FROM v_stock_by_batch
         WHERE batch_id = %(batch_id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return 0
    return row[0]


@scoped
def list_movements(cur, *, params: dict) -> tuple[list[dict], str | None]:
    """Cursor-paginated SELECT with optional filters.

    Ordering: created_at DESC, id DESC (stable for cursor pagination).

    params keys:
      owner_id    : int
      batch_id    : str | None   — filter by batch
      product_id  : str | None   — filter via JOIN to batches
      kind        : str | None   — exact match
      date_from   : str | None   — created_at >= date_from
      date_to     : str | None   — created_at <= date_to
      cursor      : str | None   — opaque cursor from previous page
      limit       : int          — page size

    Returns (rows, next_cursor_or_None).
    """
    where_parts = ["m.owner_id = %(owner_id)s"]
    query_params: dict = {"owner_id": params["owner_id"]}

    if params.get("batch_id") is not None:
        where_parts.append("m.batch_id = %(batch_id)s")
        query_params["batch_id"] = params["batch_id"]

    if params.get("product_id") is not None:
        where_parts.append("b.product_id = %(product_id)s")
        query_params["product_id"] = params["product_id"]

    if params.get("kind") is not None:
        where_parts.append("m.kind = %(kind)s")
        query_params["kind"] = params["kind"]

    if params.get("date_from") is not None:
        where_parts.append("m.created_at >= %(date_from)s")
        query_params["date_from"] = params["date_from"]

    if params.get("date_to") is not None:
        where_parts.append("m.created_at <= %(date_to)s")
        query_params["date_to"] = params["date_to"]

    # Cursor pagination: WHERE (created_at, id) < (cursor_ts, cursor_id)
    decoded = decode_cursor(params.get("cursor"))
    if decoded is not None:
        cursor_id, cursor_ts = decoded
        where_parts.append(
            "(m.created_at, m.id::text) < (%(cursor_ts)s, %(cursor_id)s)"
        )
        query_params["cursor_ts"] = cursor_ts
        query_params["cursor_id"] = str(cursor_id)

    needs_batch_join = params.get("product_id") is not None
    join_clause = (
        "JOIN batches b ON b.id = m.batch_id AND b.owner_id = m.owner_id"
        if needs_batch_join
        else ""
    )
    where_sql = " AND ".join(where_parts)

    limit = params.get("limit", 50)
    # Fetch one extra row to detect whether a next page exists.
    query_params["limit"] = limit + 1

    cur.execute(
        f"""
        SELECT m.*
          FROM stock_movements m
          {join_clause}
         WHERE {where_sql}
         ORDER BY m.created_at DESC, m.id DESC
         LIMIT %(limit)s
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    all_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    has_more = len(all_rows) > limit
    rows = all_rows[:limit]

    next_cursor: str | None = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            uuid.UUID(str(last["id"])),
            last["created_at"] if isinstance(last["created_at"], datetime) else datetime.fromisoformat(str(last["created_at"])),
        )

    return rows, next_cursor


@scoped
def stream_movements(cur, *, params: dict) -> Generator[dict, None, None]:
    """Yield all matching movement rows with no LIMIT (used for CSV export).

    Applies the same filters as list_movements except cursor pagination
    and the page-size LIMIT are omitted.

    params keys:
      owner_id    : int
      batch_id    : str | None
      product_id  : str | None
      kind        : str | None
      date_from   : str | None
      date_to     : str | None
    """
    where_parts = ["m.owner_id = %(owner_id)s"]
    query_params: dict = {"owner_id": params["owner_id"]}

    if params.get("batch_id") is not None:
        where_parts.append("m.batch_id = %(batch_id)s")
        query_params["batch_id"] = params["batch_id"]

    if params.get("product_id") is not None:
        where_parts.append("b.product_id = %(product_id)s")
        query_params["product_id"] = params["product_id"]

    if params.get("kind") is not None:
        where_parts.append("m.kind = %(kind)s")
        query_params["kind"] = params["kind"]

    if params.get("date_from") is not None:
        where_parts.append("m.created_at >= %(date_from)s")
        query_params["date_from"] = params["date_from"]

    if params.get("date_to") is not None:
        where_parts.append("m.created_at <= %(date_to)s")
        query_params["date_to"] = params["date_to"]

    needs_batch_join = params.get("product_id") is not None
    join_clause = (
        "JOIN batches b ON b.id = m.batch_id AND b.owner_id = m.owner_id"
        if needs_batch_join
        else ""
    )
    where_sql = " AND ".join(where_parts)

    cur.execute(
        f"""
        SELECT m.*
          FROM stock_movements m
          {join_clause}
         WHERE {where_sql}
         ORDER BY m.created_at DESC, m.id DESC
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    for row in cur:
        yield dict(zip(cols, row))
