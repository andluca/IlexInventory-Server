"""Read-only selectors for apps.sales.

Selectors compose query functions and return typed data.
They open their own psycopg connection (read-only semantics — no mutations).
Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

from typing import Generator


from apps.core.db import connect as _connect

from apps.sales.queries.recall_report import (
    select_recall_report_for_batch as _select_recall_report_query,
    stream_recall_report_for_batch as _stream_recall_report_query,
)
from apps.sales.queries.sales_orders import (
    list_sales_orders_with_relations as _list_sales_orders_with_relations,
    select_sales_order_with_relations as _select_so_with_relations,
)
from apps.sales._assemble import row_to_sales_order_aggregated
from apps.sales.types import SalesOrderRow


def sales_order_by_id(*, owner_id: int, so_id: str) -> SalesOrderRow | None:
    """Return a single SO by id (with lines + allocations), or None on miss/cross-owner."""
    with _connect() as conn:
        with conn.cursor() as cur:
            row = _select_so_with_relations(
                cur, params={"id": so_id, "owner_id": owner_id}
            )
            if row is None:
                return None
    return row_to_sales_order_aggregated(row)


def list_sales_orders(
    *,
    owner_id: int,
    status: str | None = None,
    voided: bool | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    cursor: str | None = None,
    limit: int = 50,
) -> dict:
    """Return a cursor-paginated list of SOs.

    Returns: {items, next_cursor}
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, next_cursor = _list_sales_orders_with_relations(
                cur,
                params={
                    "owner_id": owner_id,
                    "status": status,
                    "voided": voided,
                    "search": search,
                    "date_from": date_from,
                    "date_to": date_to,
                    "cursor": cursor,
                    "limit": limit,
                },
            )

    items = [row_to_sales_order_aggregated(row) for row in rows]
    return {"items": items, "next_cursor": next_cursor}


def list_recall_report_for_batch(
    *,
    owner_id: int,
    batch_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return an offset-paginated recall report for a batch.

    Returns: {"items": [...], "total": int, "limit": int, "offset": int}
    Reads from v_recall_report (committed, non-voided SOs only).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, total = _select_recall_report_query(
                cur,
                params={
                    "owner_id": owner_id,
                    "batch_id": batch_id,
                    "limit": limit,
                    "offset": offset,
                },
            )
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def stream_recall_report_for_batch(
    *,
    owner_id: int,
    batch_id: str,
) -> Generator[dict, None, None]:
    """Yield all recall report rows for a batch with no pagination cap.

    Used by the CSV export path. Rows ordered sale_committed_at DESC.
    Yields: one dict per row (same keys as RecallReportItemResponse).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            yield from _stream_recall_report_query(
                cur,
                params={"owner_id": owner_id, "batch_id": batch_id},
            )
