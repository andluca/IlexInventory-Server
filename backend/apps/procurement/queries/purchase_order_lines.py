"""SQL query functions for the purchase_order_lines aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. No conditionals beyond what one query needs.
"""

from __future__ import annotations

from apps.core.db import row_to_dict as _row_to_dict
from apps.core.owner_scope import scoped


@scoped
def insert_purchase_order_line(cur, *, params: dict) -> dict:
    """INSERT a new purchase_order_line row. Returns the inserted row as a dict.

    params keys: owner_id, purchase_order_id, product_id, quantity, unit_cost

    quantity and unit_cost must be Python Decimal — never float.
    Composite FKs enforced by DB:
      - (purchase_order_id, owner_id) → purchase_orders(id, owner_id)
      - (product_id, owner_id) → products(id, owner_id)
    """
    cur.execute(
        """
        INSERT INTO purchase_order_lines
            (owner_id, purchase_order_id, product_id, quantity, unit_cost)
        VALUES
            (%(owner_id)s, %(purchase_order_id)s, %(product_id)s,
             %(quantity)s, %(unit_cost)s)
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def delete_lines_for_purchase_order(cur, *, params: dict) -> int:
    """DELETE all lines for a given (purchase_order_id, owner_id). Returns rowcount.

    Used by replace-style PATCH: delete all then re-insert.

    params keys: purchase_order_id, owner_id
    """
    cur.execute(
        """
        DELETE FROM purchase_order_lines
         WHERE purchase_order_id = %(purchase_order_id)s
           AND owner_id = %(owner_id)s
        """,
        params,
    )
    return cur.rowcount


@scoped
def select_lines_for_purchase_order(cur, *, params: dict) -> list[dict]:
    """SELECT all lines for a given (purchase_order_id, owner_id).

    Returns list of dicts ordered by created_at ASC, id ASC.
    Returns [] if no lines or cross-owner (D4).

    params keys: purchase_order_id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM purchase_order_lines
         WHERE purchase_order_id = %(purchase_order_id)s
           AND owner_id = %(owner_id)s
         ORDER BY created_at ASC, id ASC
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


@scoped
def select_lines_for_update(cur, *, params: dict) -> list[dict]:
    """SELECT all lines for a given (purchase_order_id, owner_id) with FOR UPDATE lock.

    Used by receive_purchase_order to lock lines during the receive tx.

    params keys: purchase_order_id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM purchase_order_lines
         WHERE purchase_order_id = %(purchase_order_id)s
           AND owner_id = %(owner_id)s
         ORDER BY created_at ASC, id ASC
         FOR UPDATE
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
