"""Row-assembly helpers shared between sales services and selectors.

Both layers need to project (header, lines, allocations) into a SalesOrderRow.
Hosting the helper here breaks the previous selector → service import that
violated the layering rule (selector cannot depend on service).

Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

from apps.sales.types import SalesOrderRow


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
