"""SQL query functions for the batches aggregate.

Rules:
- One function = one SQL statement (or minimal conditional WHERE building).
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. No conditionals beyond parameterizing the SQL.
"""

from __future__ import annotations

from apps.core.owner_scope import scoped


def _row_to_dict(cur, row) -> dict:
    """Convert a cursor row to a dict using cursor.description column names."""
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


@scoped
def insert_batch(cur, *, params: dict) -> dict:
    """INSERT a new batch row. Returns the inserted row as a dict.

    params keys: owner_id, product_id, purchase_order_line_id (nullable),
                 batch_code, expiration_date (nullable), unit_cost
    """
    cur.execute(
        """
        INSERT INTO batches (
            owner_id, product_id, purchase_order_line_id,
            batch_code, expiration_date, unit_cost
        ) VALUES (
            %(owner_id)s, %(product_id)s, %(purchase_order_line_id)s,
            %(batch_code)s, %(expiration_date)s, %(unit_cost)s
        )
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def select_batch_by_id(cur, *, params: dict) -> dict | None:
    """SELECT a single batch by (id, owner_id). Returns None on miss.

    Cross-owner access returns None — caller maps to 404 (D4).

    params keys: id, owner_id
    """
    cur.execute(
        """
        SELECT b.*, COALESCE(v.on_hand, 0) AS on_hand
          FROM batches b
          LEFT JOIN v_stock_by_batch v
                 ON v.batch_id = b.id AND v.owner_id = b.owner_id
         WHERE b.id = %(id)s AND b.owner_id = %(owner_id)s
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def select_batch_for_update(cur, *, params: dict) -> dict | None:
    """SELECT a batch by (id, owner_id) WITH FOR UPDATE lock.

    Used by recall/movement recording to lock the row during the transaction.

    params keys: id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM batches
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
def update_batch_metadata(cur, *, params: dict) -> dict | None:
    """UPDATE batch_code and/or expiration_date, set updated_at=NOW().

    Only updates fields present and non-sentinel in params. Uses COALESCE
    so we can pass the current value to leave it unchanged.

    params keys: id, owner_id, batch_code (new value), expiration_date (new value)
    Returns None if no row matched.
    """
    cur.execute(
        """
        UPDATE batches
           SET batch_code      = %(batch_code)s,
               expiration_date = %(expiration_date)s,
               updated_at      = NOW()
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        RETURNING *
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def set_recall_state(cur, *, params: dict) -> dict | None:
    """UPDATE is_recalled, recall_reason, recalled_at on a batch.

    params keys: id, owner_id, is_recalled, recall_reason (nullable), recalled_at (nullable)
    Returns None if no row matched.
    """
    cur.execute(
        """
        UPDATE batches
           SET is_recalled  = %(is_recalled)s,
               recall_reason = %(recall_reason)s,
               recalled_at   = %(recalled_at)s,
               updated_at    = NOW()
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        RETURNING *
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def list_batches(cur, *, params: dict) -> tuple[list[dict], int]:
    """Paginated SELECT with optional filters, LEFT JOIN v_stock_by_batch.

    params keys:
      owner_id         : int
      product_id       : str | None
      is_recalled      : bool | None
      expiring_within  : int | None   — days; filter expiration_date within N days
      limit            : int
      offset           : int

    Returns (rows, total_count).
    """
    where_parts = ["b.owner_id = %(owner_id)s"]
    query_params: dict = {"owner_id": params["owner_id"]}

    if params.get("product_id") is not None:
        where_parts.append("b.product_id = %(product_id)s")
        query_params["product_id"] = params["product_id"]

    if params.get("is_recalled") is not None:
        where_parts.append("b.is_recalled = %(is_recalled)s")
        query_params["is_recalled"] = params["is_recalled"]

    if params.get("expiring_within") is not None:
        where_parts.append(
            "b.expiration_date IS NOT NULL "
            "AND b.expiration_date <= CURRENT_DATE + %(expiring_within)s::int"
        )
        query_params["expiring_within"] = params["expiring_within"]

    where_sql = " AND ".join(where_parts)

    cur.execute(
        f"SELECT COUNT(*) FROM batches b WHERE {where_sql}",
        query_params,
    )
    total = cur.fetchone()[0]

    query_params["limit"] = params["limit"]
    query_params["offset"] = params["offset"]
    cur.execute(
        f"""
        SELECT b.*, COALESCE(v.on_hand, 0) AS on_hand
          FROM batches b
          LEFT JOIN v_stock_by_batch v
                 ON v.batch_id = b.id AND v.owner_id = b.owner_id
         WHERE {where_sql}
         ORDER BY b.created_at DESC, b.id DESC
         LIMIT %(limit)s OFFSET %(offset)s
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows, total


@scoped
def list_eligible_for_fefo(cur, *, params: dict) -> list[dict]:
    """Return batches eligible for FEFO allocation for a given (owner_id, product_id).

    FEFO rules (D11):
    - Not recalled (is_recalled = FALSE)
    - Not expired (expiration_date >= CURRENT_DATE OR expiration_date IS NULL)
    - Positive on-hand (SUM(signed_quantity) > 0)
    - ORDER BY expiration_date ASC NULLS LAST, created_at ASC

    Uses FOR UPDATE OF b to lock rows during allocation (prevents concurrent
    double-allocation from two simultaneous sales commits).

    params keys: owner_id, product_id
    """
    cur.execute(
        """
        SELECT b.*, COALESCE(v.on_hand, 0) AS on_hand
          FROM batches b
          JOIN v_stock_by_batch v
            ON v.batch_id = b.id AND v.owner_id = b.owner_id
         WHERE b.owner_id    = %(owner_id)s
           AND b.product_id  = %(product_id)s
           AND b.is_recalled = FALSE
           AND (b.expiration_date IS NULL OR b.expiration_date >= CURRENT_DATE)
           AND v.on_hand > 0
         ORDER BY b.expiration_date ASC NULLS LAST, b.created_at ASC
         FOR UPDATE OF b
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
