"""SQL query functions for the sales_order_lines aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic.
"""

from __future__ import annotations

from apps.core.owner_scope import scoped


def _row_to_dict(cur, row) -> dict:
    """Convert a cursor row to a dict using cursor.description column names."""
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


@scoped
def insert_sales_order_line(cur, *, params: dict) -> dict:
    """INSERT a new sales_order_line row. Returns inserted row.

    params keys: owner_id, sales_order_id, product_id, quantity, sell_price
    """
    cur.execute(
        """
        INSERT INTO sales_order_lines
               (owner_id, sales_order_id, product_id, quantity, sell_price)
        VALUES (%(owner_id)s, %(sales_order_id)s, %(product_id)s,
                %(quantity)s, %(sell_price)s)
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def select_lines_for_sales_order(cur, *, params: dict) -> list[dict]:
    """SELECT all lines for a SO.

    params keys: sales_order_id, owner_id
    """
    cur.execute(
        """
        SELECT * FROM sales_order_lines
         WHERE sales_order_id = %(sales_order_id)s AND owner_id = %(owner_id)s
         ORDER BY created_at ASC
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


@scoped
def delete_lines_for_sales_order(cur, *, params: dict) -> None:
    """DELETE all lines for a SO.

    params keys: sales_order_id, owner_id
    """
    cur.execute(
        """
        DELETE FROM sales_order_lines
         WHERE sales_order_id = %(sales_order_id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
