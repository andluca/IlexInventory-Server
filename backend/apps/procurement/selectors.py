"""Read-only selectors for apps.procurement.

Selectors open a connection, call query functions, close. They do not open
transactions (reads are non-mutating). They compose query functions from the
queries layer to build the response shapes needed by the API layer.
"""

from __future__ import annotations

from apps.core.db import connect as _connect
from apps.procurement._assemble import row_to_po_aggregated
from apps.procurement.queries.purchase_orders import (
    list_purchase_orders_with_lines as _list_purchase_orders_with_lines,
    select_purchase_order_with_lines,
)
from apps.procurement.types import PurchaseOrderRow


def purchase_order_by_id(*, owner_id: int, po_id: str) -> PurchaseOrderRow | None:
    """Return a single PurchaseOrderRow (header + lines) or None if not found.

    API layer maps None to 404 (D4 — 404 not 403).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            row = select_purchase_order_with_lines(
                cur, params={"id": str(po_id), "owner_id": owner_id}
            )
            if row is None:
                return None
    return row_to_po_aggregated(row)


def list_purchase_orders(
    *,
    owner_id: int,
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a paginated list of POs with their lines.

    Returns:
        {
          "items": [PurchaseOrderRow, ...],
          "total": int,
          "limit": int,
          "offset": int,
        }
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, total = _list_purchase_orders_with_lines(
                cur,
                params={
                    "owner_id": owner_id,
                    "status": status,
                    "search": search,
                    "date_from": date_from,
                    "date_to": date_to,
                    "limit": limit,
                    "offset": offset,
                },
            )

    items = [row_to_po_aggregated(row) for row in rows]
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
