"""Row-assembly helpers shared between sales services and selectors.

Both layers need to project (header, lines, allocations) into a SalesOrderRow.
Hosting the helper here breaks the previous selector → service import that
violated the layering rule (selector cannot depend on service).

Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from apps.sales.types import AllocationRow, SalesOrderLineRow, SalesOrderRow


def row_to_sales_order(
    header: dict, lines: list[dict], allocations: list[dict]
) -> SalesOrderRow:
    """Assemble a SalesOrderRow from header + lines + allocations dicts.

    UUIDs are stringified for JSON-shape compatibility; Decimal/datetime are
    passed through and serialized later by the response serializer.
    """
    h = dict(header)
    if "id" in h and not isinstance(h["id"], str):
        h["id"] = str(h["id"])

    converted_lines = []
    for ln in lines:
        ln = dict(ln)
        for key in ("id", "sales_order_id", "product_id"):
            if key in ln and ln[key] is not None and not isinstance(ln[key], str):
                ln[key] = str(ln[key])
        converted_lines.append(ln)

    converted_allocs = []
    for alloc in allocations:
        alloc = dict(alloc)
        for key in ("id", "sales_order_line_id", "batch_id"):
            if key in alloc and alloc[key] is not None and not isinstance(alloc[key], str):
                alloc[key] = str(alloc[key])
        converted_allocs.append(alloc)

    return {
        "id": h["id"],
        "owner_id": h["owner_id"],
        "customer_name": h["customer_name"],
        "customer_contact": h.get("customer_contact"),
        "status": h["status"],
        "committed_at": h.get("committed_at"),
        "voided_at": h.get("voided_at"),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "lines": converted_lines,
        "allocations": converted_allocs,
    }


def line_from_json(d: dict) -> SalesOrderLineRow:
    """Project one jsonb_agg sales-line element back to a SalesOrderLineRow.

    The SQL casts UUIDs and Decimals to text; we reconstruct Decimal and
    parse the ISO-8601 timestamp string with datetime.fromisoformat.
    """
    return {
        "id": d["id"],
        "owner_id": d["owner_id"],
        "sales_order_id": d["sales_order_id"],
        "product_id": d["product_id"],
        "quantity": Decimal(d["quantity"]),
        "sell_price": Decimal(d["sell_price"]),
        "created_at": datetime.fromisoformat(d["created_at"]),
    }


def allocation_from_json(d: dict) -> AllocationRow:
    """Project one jsonb_agg allocation element back to an AllocationRow."""
    return {
        "id": d["id"],
        "owner_id": d["owner_id"],
        "sales_order_line_id": d["sales_order_line_id"],
        "batch_id": d["batch_id"],
        "allocated_quantity": Decimal(d["allocated_quantity"]),
        "unit_cost": Decimal(d["unit_cost"]),
        "created_at": datetime.fromisoformat(d["created_at"]),
    }


def row_to_sales_order_aggregated(row: dict) -> SalesOrderRow:
    """Assemble a SalesOrderRow from a header row whose `lines` and
    `allocations` columns hold jsonb_agg results.

    Used by selectors that fetch header + lines + allocations in one SQL
    statement (eliminates N+1 in list endpoints).
    """
    h = dict(row)
    if "id" in h and not isinstance(h["id"], str):
        h["id"] = str(h["id"])

    raw_lines = h.get("lines") or []
    raw_allocs = h.get("allocations") or []

    return {
        "id": h["id"],
        "owner_id": h["owner_id"],
        "customer_name": h["customer_name"],
        "customer_contact": h.get("customer_contact"),
        "status": h["status"],
        "committed_at": h.get("committed_at"),
        "voided_at": h.get("voided_at"),
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "lines": [line_from_json(d) for d in raw_lines],
        "allocations": [allocation_from_json(d) for d in raw_allocs],
    }
