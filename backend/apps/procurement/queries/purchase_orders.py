"""SQL query functions for the purchase_orders aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. No conditionals beyond what one query needs.
"""

from __future__ import annotations

from apps.core.owner_scope import scoped


def _row_to_dict(cur, row) -> dict:
    """Convert a cursor row to a dict using cursor.description column names."""
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


@scoped
def insert_purchase_order(cur, *, params: dict) -> dict:
    """INSERT a new purchase_order row. Returns the inserted row as a dict.

    params keys: owner_id, supplier_name, supplier_contact
    Status defaults to 'draft'; received_at defaults to NULL.
    """
    cur.execute(
        """
        INSERT INTO purchase_orders (owner_id, supplier_name, supplier_contact)
        VALUES (%(owner_id)s, %(supplier_name)s, %(supplier_contact)s)
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def select_purchase_order_by_id(cur, *, params: dict) -> dict | None:
    """SELECT a single PO by (id, owner_id). Returns None on miss.

    Cross-owner access returns None — caller maps to 404 (D4).

    params keys: id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM purchase_orders
         WHERE id = %(id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def select_purchase_order_for_update(cur, *, params: dict) -> dict | None:
    """SELECT a PO by (id, owner_id) with FOR UPDATE lock.

    Used by receive_purchase_order to lock the row during the receive tx.

    params keys: id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM purchase_orders
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
def update_purchase_order_header(cur, *, params: dict) -> dict | None:
    """UPDATE supplier_name and/or supplier_contact on (id, owner_id).

    Only updates fields explicitly provided in params (non-None).
    Returns the updated row or None if the PO doesn't exist / cross-owner.

    params keys: id, owner_id, supplier_name (opt), supplier_contact (opt)
    """
    updates: list[str] = []
    if params.get("supplier_name") is not None:
        updates.append("supplier_name = %(supplier_name)s")
    if "supplier_contact" in params and params["supplier_contact"] is not None:
        updates.append("supplier_contact = %(supplier_contact)s")

    if not updates:
        return select_purchase_order_by_id(cur, params=params)

    updates.append("updated_at = NOW()")
    set_clause = ", ".join(updates)

    cur.execute(
        f"""
        UPDATE purchase_orders
           SET {set_clause}
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
def mark_purchase_order_received(cur, *, params: dict) -> dict | None:
    """UPDATE status='received', received_at=NOW(), updated_at=NOW()
    WHERE id=... AND owner_id=... AND status='draft'.

    Returns None if no row matched (already received, cross-owner, or missing).
    Caller distinguishes the reason via a prior SELECT.

    params keys: id, owner_id
    """
    cur.execute(
        """
        UPDATE purchase_orders
           SET status = 'received',
               received_at = NOW(),
               updated_at = NOW()
         WHERE id = %(id)s
           AND owner_id = %(owner_id)s
           AND status = 'draft'
        RETURNING *
        """,
        params,
    )
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_dict(cur, row)


@scoped
def delete_purchase_order(cur, *, params: dict) -> int:
    """DELETE a PO by (id, owner_id) WHERE status='draft'. Returns rowcount.

    Service reads status before calling so it can return the precise error code
    (PurchaseOrderNotFound vs PurchaseOrderNotDraft).

    params keys: id, owner_id
    """
    cur.execute(
        """
        DELETE FROM purchase_orders
         WHERE id = %(id)s AND owner_id = %(owner_id)s AND status = 'draft'
        """,
        params,
    )
    return cur.rowcount


@scoped
def list_purchase_orders(cur, *, params: dict) -> tuple[list[dict], int]:
    """Paginated SELECT with optional status filter, supplier ILIKE search, date range.

    params keys:
      owner_id   : int
      status     : str | None  — 'draft' or 'received'; None = all
      search     : str | None  — ILIKE match on supplier_name
      date_from  : date | str | None  — filter created_at >= date_from
      date_to    : date | str | None  — filter created_at <= date_to
      limit      : int
      offset     : int

    Returns (rows, total_count).
    """
    where_parts = ["owner_id = %(owner_id)s"]
    query_params: dict = {"owner_id": params["owner_id"]}

    if params.get("status"):
        where_parts.append("status = %(status)s")
        query_params["status"] = params["status"]

    if params.get("search"):
        where_parts.append("supplier_name ILIKE %(search_pat)s")
        query_params["search_pat"] = f"%{params['search']}%"

    if params.get("date_from"):
        where_parts.append("created_at >= %(date_from)s")
        query_params["date_from"] = params["date_from"]

    if params.get("date_to"):
        where_parts.append("created_at <= %(date_to)s")
        query_params["date_to"] = params["date_to"]

    where_sql = " AND ".join(where_parts)

    # Count first
    cur.execute(
        f"SELECT COUNT(*) FROM purchase_orders WHERE {where_sql}",
        query_params,
    )
    total = cur.fetchone()[0]

    # Fetch page
    query_params["limit"] = params["limit"]
    query_params["offset"] = params["offset"]
    cur.execute(
        f"""
        SELECT * FROM purchase_orders
         WHERE {where_sql}
         ORDER BY created_at DESC, id DESC
         LIMIT %(limit)s OFFSET %(offset)s
        """,
        query_params,
    )
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows, total
