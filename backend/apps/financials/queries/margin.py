"""SQL query functions for the financials margin aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (selector) provides the cursor and owns the connection.
- No business logic. No margin_pct computation (that belongs in the selector).
"""

from __future__ import annotations

from apps.core.db import row_to_dict as _row_to_dict
from apps.core.owner_scope import scoped


@scoped
def select_margin_aggregates(cur, *, params: dict) -> dict:
    """SELECT total revenue, COGS, and units aggregated across all products in range.

    params keys: owner_id, date_from (date), date_to (date)

    Returns a single dict with keys: total_revenue, total_cogs, total_units.
    """
    cur.execute(
        """
        SELECT
            COALESCE(SUM(revenue), 0)::NUMERIC(14, 4)    AS total_revenue,
            COALESCE(SUM(cogs), 0)::NUMERIC(14, 4)        AS total_cogs,
            COALESCE(SUM(units_sold), 0)::NUMERIC(14, 4)  AS total_units
        FROM v_margin_by_product
        WHERE owner_id    = %(owner_id)s
          AND committed_at >= %(date_from)s
          AND committed_at <  %(date_to_exclusive)s
        """,
        {
            "owner_id": params["owner_id"],
            "date_from": params["date_from"],
            "date_to_exclusive": params["date_to_exclusive"],
        },
    )
    row = cur.fetchone()
    return _row_to_dict(cur, row)


@scoped
def select_margin_by_product(cur, *, params: dict) -> list[dict]:
    """SELECT per-product aggregated revenue, COGS, units in range.

    params keys:
      owner_id, date_from (date), date_to_exclusive (date)
      top_n (int | None) — when set, returns at most top_n rows (dashboard path)
      cursor_revenue (Decimal | None) — when set with cursor_product_id, enables cursor pagination
      cursor_product_id (str | None)
      limit (int | None) — page size for cursor path (fetch limit+1 to detect next page)

    Returns list of dicts with keys: product_id, product_name, units_sold, revenue, cogs.
    """
    # Build WHERE clause for cursor pagination
    cursor_clause = ""
    if params.get("cursor_revenue") is not None and params.get("cursor_product_id") is not None:
        cursor_clause = (
            "AND (agg.revenue, agg.product_id::text) < (%(cursor_revenue)s, %(cursor_product_id)s)"
        )

    # Build LIMIT clause
    if params.get("top_n") is not None:
        limit_clause = "LIMIT %(top_n)s"
    elif params.get("limit") is not None:
        # Fetch limit+1 so caller can detect has_more
        limit_clause = "LIMIT %(limit_plus_one)s"
    else:
        limit_clause = ""

    sql = f"""
        SELECT
            agg.product_id,
            agg.product_name,
            SUM(agg.units_sold)::NUMERIC(14, 4) AS units_sold,
            SUM(agg.revenue)::NUMERIC(14, 4)    AS revenue,
            SUM(agg.cogs)::NUMERIC(14, 4)       AS cogs
        FROM v_margin_by_product agg
        WHERE agg.owner_id    = %(owner_id)s
          AND agg.committed_at >= %(date_from)s
          AND agg.committed_at <  %(date_to_exclusive)s
          {cursor_clause}
        GROUP BY agg.product_id, agg.product_name
        ORDER BY revenue DESC, agg.product_id DESC
        {limit_clause}
    """

    bind: dict = {
        "owner_id": params["owner_id"],
        "date_from": params["date_from"],
        "date_to_exclusive": params["date_to_exclusive"],
    }
    if params.get("top_n") is not None:
        bind["top_n"] = params["top_n"]
    if params.get("limit") is not None:
        bind["limit_plus_one"] = params["limit"] + 1
    if params.get("cursor_revenue") is not None:
        bind["cursor_revenue"] = params["cursor_revenue"]
    if params.get("cursor_product_id") is not None:
        bind["cursor_product_id"] = params["cursor_product_id"]

    cur.execute(sql, bind)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
