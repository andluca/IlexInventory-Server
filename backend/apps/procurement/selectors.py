"""Read-only selectors for apps.procurement.

Selectors open a connection, call query functions, close. They do not open
transactions (reads are non-mutating). They compose query functions from the
queries layer to build the response shapes needed by the API layer.
"""

from __future__ import annotations

from uuid import UUID

import psycopg
from django.conf import settings

from apps.procurement.queries.purchase_order_lines import (
    select_lines_for_purchase_order,
)
from apps.procurement.queries.purchase_orders import (
    list_purchase_orders as _list_purchase_orders,
    select_purchase_order_by_id,
)
from apps.procurement.types import PurchaseOrderRow


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.DATABASE_URL)


def _row_to_po(header: dict, lines: list[dict]) -> PurchaseOrderRow:
    """Assemble a PurchaseOrderRow from header dict + lines list."""
    h = dict(header)
    if "id" in h and not isinstance(h["id"], str):
        h["id"] = str(h["id"])

    converted_lines = []
    for ln in lines:
        ln = dict(ln)
        for key in ("id", "purchase_order_id", "product_id"):
            if key in ln and not isinstance(ln[key], str):
                ln[key] = str(ln[key])
        converted_lines.append(ln)

    return {
        "id": h["id"],
        "owner_id": h["owner_id"],
        "supplier_name": h["supplier_name"],
        "supplier_contact": h.get("supplier_contact"),
        "status": h["status"],
        "received_at": h.get("received_at"),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "lines": converted_lines,
    }


def purchase_order_by_id(*, owner_id: int, po_id: str) -> PurchaseOrderRow | None:
    """Return a single PurchaseOrderRow (header + lines) or None if not found.

    API layer maps None to 404 (D4 — 404 not 403).
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            header = select_purchase_order_by_id(
                cur, params={"id": str(po_id), "owner_id": owner_id}
            )
            if header is None:
                return None
            lines = select_lines_for_purchase_order(
                cur,
                params={"purchase_order_id": str(po_id), "owner_id": owner_id},
            )

    return _row_to_po(header, lines)


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
            rows, total = _list_purchase_orders(
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

            items = []
            for row in rows:
                po_id_str = str(row["id"])
                lines = select_lines_for_purchase_order(
                    cur,
                    params={"purchase_order_id": po_id_str, "owner_id": owner_id},
                )
                items.append(_row_to_po(row, lines))

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
