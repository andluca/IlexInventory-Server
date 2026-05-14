"""Row-assembly helpers shared between procurement services and selectors.

Mirrors apps/sales/_assemble.py. Centralizes projection of header rows
into PurchaseOrderRow dicts when lines arrive inline via a jsonb_agg
subquery (single-statement selectors).

Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.procurement.types import PurchaseOrderLineRow, PurchaseOrderRow


def line_from_json(d: dict) -> PurchaseOrderLineRow:
    """Project one jsonb_agg line element back to a PurchaseOrderLineRow.

    The SQL casts UUIDs and Decimals to text so the JSON round-trip
    preserves precision (a numeric→JSON number→float coercion would
    silently break money discipline). Timestamps inside jsonb_build_object
    serialize to ISO-8601 and parse cleanly via datetime.fromisoformat.
    """
    return {
        "id": d["id"],
        "owner_id": d["owner_id"],
        "purchase_order_id": d["purchase_order_id"],
        "product_id": d["product_id"],
        "quantity": Decimal(d["quantity"]),
        "unit_cost": Decimal(d["unit_cost"]),
        "created_at": datetime.fromisoformat(d["created_at"]),
    }


def row_to_po_aggregated(row: dict) -> PurchaseOrderRow:
    """Assemble a PurchaseOrderRow from a header row whose `lines` column
    holds a jsonb_agg result (list of JSON dicts).
    """
    h = dict(row)
    if "id" in h and not isinstance(h["id"], str):
        h["id"] = str(h["id"])

    raw_lines = h.get("lines") or []
    converted_lines: list[PurchaseOrderLineRow] = [line_from_json(d) for d in raw_lines]

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
