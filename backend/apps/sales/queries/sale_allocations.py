"""SQL query functions for the sale_allocations aggregate.

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- The caller (service) provides the cursor and owns the transaction.
- No business logic. sale_allocations are immutable post-commit (D8).
"""

from __future__ import annotations

from apps.core.db import row_to_dict as _row_to_dict
from apps.core.owner_scope import scoped


@scoped
def insert_sale_allocation(cur, *, params: dict) -> dict:
    """INSERT a new sale_allocation row. Returns inserted row.

    params keys: owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost
    """
    cur.execute(
        """
        INSERT INTO sale_allocations
               (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost)
        VALUES (%(owner_id)s, %(sales_order_line_id)s, %(batch_id)s,
                %(allocated_quantity)s, %(unit_cost)s)
        RETURNING *
        """,
        params,
    )
    return _row_to_dict(cur, cur.fetchone())


@scoped
def select_allocations_for_sales_order(cur, *, params: dict) -> list[dict]:
    """SELECT all allocations for a SO via lines join.

    params keys: sales_order_id, owner_id
    """
    cur.execute(
        """
        SELECT sa.*
          FROM sale_allocations sa
          JOIN sales_order_lines sol
            ON sol.id        = sa.sales_order_line_id
           AND sol.owner_id  = sa.owner_id
         WHERE sol.sales_order_id = %(sales_order_id)s
           AND sa.owner_id        = %(owner_id)s
         ORDER BY sa.created_at ASC
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
