"""SQL query functions for the sales_orders aggregate.

Rules:
- One function = one SQL statement (or minimal conditional WHERE building).
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. No conditionals beyond parameterizing the SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from apps.core.owner_scope import scoped
from apps.core.pagination import decode_cursor, encode_cursor


def _row_to_dict(cur, row) -> dict:
    """Convert a cursor row to a dict using cursor.description column names."""
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


@scoped
def insert_sales_order(cur, *, params: dict) -> dict:
    """INSERT a new sales_order row (status='draft'). Returns inserted row.

    params keys: owner_id, customer_name, customer_contact (nullable)
    """
    cur.execute(
        """
        INSERT INTO sales_orders (owner_id, customer_name, customer_contact)
        VALUES (%(owner_id)s, %(customer_name)s, %(customer_contact)s)
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def select_sales_order_by_id(cur, *, params: dict) -> dict | None:
    """SELECT a single SO by (id, owner_id). Returns None on miss.

    params keys: id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM sales_orders
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def select_sales_order_for_update(cur, *, params: dict) -> dict | None:
    """SELECT a SO by (id, owner_id) WITH FOR UPDATE lock.

    params keys: id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM sales_orders
         WHERE id = %(id)s AND owner_id = %(owner_id)s
         FOR UPDATE
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def update_sales_order_header(cur, *, params: dict) -> dict:
    """UPDATE customer_name and/or customer_contact. Sets updated_at=NOW().

    params keys: id, owner_id, customer_name, customer_contact (both optional)
    Returns the updated row.
    """
    cur.execute(
        """
        UPDATE sales_orders
           SET customer_name    = COALESCE(%(customer_name)s, customer_name),
               customer_contact = CASE
                   WHEN %(customer_contact_set)s THEN %(customer_contact)s
                   ELSE customer_contact
               END,
               updated_at = NOW()
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def mark_sales_order_committed(cur, *, params: dict) -> dict:
    """UPDATE status='committed', committed_at=NOW().

    params keys: id, owner_id
    """
    cur.execute(
        """
        UPDATE sales_orders
           SET status       = 'committed',
               committed_at = NOW(),
               updated_at   = NOW()
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def set_sales_order_voided(cur, *, params: dict) -> dict:
    """UPDATE voided_at=NOW().

    params keys: id, owner_id
    """
    cur.execute(
        """
        UPDATE sales_orders
           SET voided_at  = NOW(),
               updated_at = NOW()
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def delete_sales_order(cur, *, params: dict) -> None:
    """DELETE a SO by (id, owner_id). Lines cascade.

    params keys: id, owner_id
    """
    cur.execute(
        "DELETE FROM sales_orders WHERE id = %(id)s AND owner_id = %(owner_id)s",
        params,
    )


@scoped
def list_sales_orders(cur, *, params: dict) -> tuple[list[dict], str | None]:
    """Cursor-paginated SELECT with optional filters.

    Ordering: created_at DESC, id DESC (stable for cursor pagination).

    params keys:
      owner_id  : int
      status    : str | None   — exact match
      voided    : bool | None  — True=voided only, False=non-voided, None=all
      search    : str | None   — ILIKE on customer_name
      date_from : str | None   — created_at >= date_from
      date_to   : str | None   — created_at <= date_to
      cursor    : str | None   — opaque cursor from previous page
      limit     : int          — page size

    Returns (rows, next_cursor_or_None).
    """
    where_parts = ["so.owner_id = %(owner_id)s"]
    query_params: dict = {"owner_id": params["owner_id"]}

    if params.get("status") is not None:
        where_parts.append("so.status = %(status)s")
        query_params["status"] = params["status"]

    if params.get("voided") is not None:
        if params["voided"]:
            where_parts.append("so.voided_at IS NOT NULL")
        else:
            where_parts.append("so.voided_at IS NULL")

    if params.get("search") is not None:
        where_parts.append("so.customer_name ILIKE %(search)s")
        query_params["search"] = f"%{params['search']}%"

    if params.get("date_from") is not None:
        where_parts.append("so.created_at >= %(date_from)s")
        query_params["date_from"] = params["date_from"]

    if params.get("date_to") is not None:
        where_parts.append("so.created_at <= %(date_to)s")
        query_params["date_to"] = params["date_to"]

    decoded = decode_cursor(params.get("cursor"))
    if decoded is not None:
        cursor_id, cursor_ts = decoded
        where_parts.append(
            "(so.created_at, so.id::text) < (%(cursor_ts)s, %(cursor_id)s)"
        )
        query_params["cursor_ts"] = cursor_ts
        query_params["cursor_id"] = str(cursor_id)

    where_sql = " AND ".join(where_parts)
    limit = params.get("limit", 50)
    query_params["limit"] = limit + 1

    cur.execute(
        f"""
        SELECT so.*
          FROM sales_orders so
         WHERE {where_sql}
         ORDER BY so.created_at DESC, so.id DESC
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
