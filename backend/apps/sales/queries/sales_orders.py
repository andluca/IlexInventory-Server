"""SQL query functions for the sales_orders aggregate.

Rules:
- One function = one SQL statement (or minimal conditional WHERE building).
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. No conditionals beyond parameterizing the SQL.
"""

from __future__ import annotations

from apps.core.db import row_to_dict as _row_to_dict
from apps.core.owner_scope import scoped
from apps.core.pagination import build_next_cursor, decode_cursor


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


def _build_sales_orders_where(params: dict) -> tuple[list[str], dict]:
    """Build WHERE clause parts + bind params for list_sales_orders filters."""
    where_parts = ["so.owner_id = %(owner_id)s"]
    bind: dict = {"owner_id": params["owner_id"]}

    if params.get("status") is not None:
        where_parts.append("so.status = %(status)s")
        bind["status"] = params["status"]

    if params.get("voided") is not None:
        where_parts.append(
            "so.voided_at IS NOT NULL" if params["voided"] else "so.voided_at IS NULL"
        )

    if params.get("search") is not None:
        where_parts.append("so.customer_name ILIKE %(search)s")
        bind["search"] = f"%{params['search']}%"

    if params.get("date_from") is not None:
        where_parts.append("so.created_at >= %(date_from)s")
        bind["date_from"] = params["date_from"]

    if params.get("date_to") is not None:
        where_parts.append("so.created_at <= %(date_to)s")
        bind["date_to"] = params["date_to"]

    decoded = decode_cursor(params.get("cursor"))
    if decoded is not None:
        cursor_id, cursor_ts = decoded
        where_parts.append(
            "(so.created_at, so.id::text) < (%(cursor_ts)s, %(cursor_id)s)"
        )
        bind["cursor_ts"] = cursor_ts
        bind["cursor_id"] = str(cursor_id)

    return where_parts, bind


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
    where_parts, query_params = _build_sales_orders_where(params)
    limit = params.get("limit", 50)
    query_params["limit"] = limit + 1

    cur.execute(
        f"""
        SELECT so.*
          FROM sales_orders so
         WHERE {" AND ".join(where_parts)}
         ORDER BY so.created_at DESC, so.id DESC
         LIMIT %(limit)s
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    all_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    return build_next_cursor(all_rows, limit)


# ---------------------------------------------------------------------------
# Aggregated reads (header + lines + allocations in one SQL statement)
#
# Replace the selector-layer N+1 (1 header query + N line queries + up to N
# allocation queries) with a single statement carrying two correlated
# jsonb_agg subqueries. Allocations are gated on status='committed' to
# preserve the existing "draft → empty allocations" contract.
# Selector callers project the result via apps.sales._assemble.
# Services that only need the header keep using the plain queries above.
# ---------------------------------------------------------------------------

_SO_LINES_JSONB_SUBQUERY = """\
COALESCE((
  SELECT jsonb_agg(
           jsonb_build_object(
             'id',             sol.id::text,
             'owner_id',       sol.owner_id,
             'sales_order_id', sol.sales_order_id::text,
             'product_id',     sol.product_id::text,
             'quantity',       sol.quantity::text,
             'sell_price',     sol.sell_price::text,
             'created_at',     sol.created_at
           ) ORDER BY sol.created_at ASC, sol.id ASC
         )
    FROM sales_order_lines sol
   WHERE sol.sales_order_id = so.id
     AND sol.owner_id       = so.owner_id
), '[]'::jsonb) AS lines
"""

_SO_ALLOCATIONS_JSONB_SUBQUERY = """\
CASE WHEN so.status = 'committed' THEN
  COALESCE((
    SELECT jsonb_agg(
             jsonb_build_object(
               'id',                  sa.id::text,
               'owner_id',            sa.owner_id,
               'sales_order_line_id', sa.sales_order_line_id::text,
               'batch_id',            sa.batch_id::text,
               'allocated_quantity',  sa.allocated_quantity::text,
               'unit_cost',           sa.unit_cost::text,
               'created_at',          sa.created_at
             ) ORDER BY sa.created_at ASC, sa.id ASC
           )
      FROM sale_allocations sa
      JOIN sales_order_lines sol
        ON sol.id       = sa.sales_order_line_id
       AND sol.owner_id = sa.owner_id
     WHERE sol.sales_order_id = so.id
       AND sa.owner_id        = so.owner_id
  ), '[]'::jsonb)
ELSE '[]'::jsonb END AS allocations
"""


@scoped
def select_sales_order_with_relations(cur, *, params: dict) -> dict | None:
    """SELECT a SO by (id, owner_id) with lines + allocations embedded.

    Single statement. Allocations resolve to [] when status != 'committed'.

    params keys: id, owner_id
    """
    cur.execute(
        f"""
        SELECT so.*,
               {_SO_LINES_JSONB_SUBQUERY},
               {_SO_ALLOCATIONS_JSONB_SUBQUERY}
          FROM sales_orders so
         WHERE so.id = %(id)s AND so.owner_id = %(owner_id)s
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def list_sales_orders_with_relations(cur, *, params: dict) -> tuple[list[dict], str | None]:
    """Cursor-paginated list with lines + allocations embedded per row.

    Replaces the previous ~2N+1 selector pattern with one statement.
    Cursor contract is preserved: build_next_cursor reads id + created_at
    from each header row.

    params keys: same as list_sales_orders.
    """
    where_parts, query_params = _build_sales_orders_where(params)
    limit = params.get("limit", 50)
    query_params["limit"] = limit + 1

    cur.execute(
        f"""
        SELECT so.*,
               {_SO_LINES_JSONB_SUBQUERY},
               {_SO_ALLOCATIONS_JSONB_SUBQUERY}
          FROM sales_orders so
         WHERE {" AND ".join(where_parts)}
         ORDER BY so.created_at DESC, so.id DESC
         LIMIT %(limit)s
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    all_rows = [dict(zip(cols, row)) for row in cur.fetchall()]

    return build_next_cursor(all_rows, limit)
