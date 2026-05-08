"""SQL query functions for the recall report (v_recall_report view).

Rules:
- One function = one SQL statement.
- Every owner-scoped function is decorated with @scoped.
- No business logic.
"""

from __future__ import annotations

from typing import Generator

from apps.core.owner_scope import scoped


def _row_to_dict(cur, row) -> dict:
    """Convert a cursor row to a dict using cursor.description column names."""
    cols = [d.name for d in cur.description]
    return dict(zip(cols, row))


@scoped
def select_recall_report_for_batch(cur, *, params: dict) -> tuple[list[dict], int]:
    """SELECT recall report rows for a batch_id, offset-paginated.

    Reads from v_recall_report filtered by batch_id (and voided_at IS NULL is
    already enforced by the view definition).

    params keys: batch_id, owner_id, limit, offset
    Returns (rows, total_count).
    """
    cur.execute(
        """
        SELECT COUNT(*) FROM v_recall_report
         WHERE batch_id = %(batch_id)s AND owner_id = %(owner_id)s
        """,
        params,
    )
    total = cur.fetchone()[0]

    cur.execute(
        """
        SELECT sale_order_id, customer_name, customer_contact,
               quantity_received, sale_committed_at
          FROM v_recall_report
         WHERE batch_id = %(batch_id)s AND owner_id = %(owner_id)s
         ORDER BY sale_committed_at DESC
         LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    rows = [dict(zip(cols, row)) for row in cur.fetchall()]
    return rows, total


@scoped
def stream_recall_report_for_batch(cur, *, params: dict) -> Generator[dict, None, None]:
    """Yield all recall report rows for a batch with no LIMIT (used for CSV export).

    params keys: batch_id, owner_id
    Yields: one dict per row (sale_order_id, customer_name, customer_contact,
                               quantity_received, sale_committed_at).
    """
    cur.execute(
        """
        SELECT sale_order_id, customer_name, customer_contact,
               quantity_received, sale_committed_at
          FROM v_recall_report
         WHERE batch_id = %(batch_id)s AND owner_id = %(owner_id)s
         ORDER BY sale_committed_at DESC
        """,
        params,
    )
    cols = [d.name for d in cur.description]
    for row in cur:
        yield dict(zip(cols, row))
