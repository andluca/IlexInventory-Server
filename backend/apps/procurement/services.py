"""Business-logic services for apps.procurement.

Rules:
- Kwarg-only functions (past owner_id / po_id). Type-annotated.
- Accept typed Python data; return typed Python data.
- Raise from apps.procurement.errors — never raw psycopg errors.
- Open their own psycopg connection; wrap mutations in a transaction.
- Never accept owner_id from the request body — API layer passes request.user.id.
- Module-top imports only (ilex-discipline invariant #6 — no function-local imports).
"""

from __future__ import annotations

from uuid import UUID

import psycopg
import psycopg.errors

from apps.core.db import connect as _connect

from apps.inventory.services import create_receipt_batches
from apps.procurement.errors import (
    ProductNotFound,
    PurchaseOrderAlreadyReceived,
    PurchaseOrderNotDraft,
    PurchaseOrderNotFound,
    ReceiveLinesMismatch,
    ValidationError,
)
from apps.procurement.queries.purchase_order_lines import (
    delete_lines_for_purchase_order,
    insert_purchase_order_line,
    select_lines_for_purchase_order,
    select_lines_for_update,
)
from apps.procurement.queries.purchase_orders import (
    delete_purchase_order as _delete_purchase_order,
    insert_purchase_order,
    list_purchase_orders as _list_purchase_orders,
    mark_purchase_order_received,
    select_purchase_order_by_id,
    select_purchase_order_for_update,
    update_purchase_order_header,
)
from apps.procurement.types import NewLine, PurchaseOrderRow, ReceiveLineMeta


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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


def _load_po_with_lines(cur, *, owner_id: int, po_id: str) -> PurchaseOrderRow | None:
    """Read header + lines for a PO. Returns None on miss / cross-owner."""
    header = select_purchase_order_by_id(
        cur, params={"id": po_id, "owner_id": owner_id}
    )
    if header is None:
        return None
    lines = select_lines_for_purchase_order(
        cur, params={"purchase_order_id": po_id, "owner_id": owner_id}
    )
    return _row_to_po(header, lines)


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def create_purchase_order_draft(
    *,
    owner_id: int,
    supplier_name: str,
    supplier_contact: str | None,
    lines: list[NewLine],
) -> PurchaseOrderRow:
    """Insert a PO header + N lines in a single transaction.

    Raises:
      ValidationError    — if lines is empty.
      ProductNotFound    — if any line's (product_id, owner_id) is unknown (D4).
    """
    if not lines:
        raise ValidationError(detail="lines must not be empty.")

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                header = insert_purchase_order(
                    cur,
                    params={
                        "owner_id": owner_id,
                        "supplier_name": supplier_name,
                        "supplier_contact": supplier_contact,
                    },
                )
                po_id = str(header["id"])
                inserted_lines = []
                for line in lines:
                    ln = insert_purchase_order_line(
                        cur,
                        params={
                            "owner_id": owner_id,
                            "purchase_order_id": po_id,
                            "product_id": str(line["product_id"]),
                            "quantity": line["quantity"],
                            "unit_cost": line["unit_cost"],
                        },
                    )
                    inserted_lines.append(ln)
            conn.commit()
        except psycopg.errors.ForeignKeyViolation as exc:
            conn.rollback()
            if "pol_product_owner_fkey" in str(exc):
                raise ProductNotFound(
                    detail="One or more products not found for this owner."
                )
            raise

    return _row_to_po(header, inserted_lines)


def update_purchase_order_draft(
    *,
    owner_id: int,
    po_id: UUID,
    supplier_name: str | None = None,
    supplier_contact: str | None = None,
    lines: list[NewLine] | None = None,
) -> PurchaseOrderRow:
    """Update a draft PO header and optionally replace all lines.

    Replace-style: if lines is provided (non-None), DELETE all existing lines
    and INSERT the new set in a single transaction.

    Raises:
      PurchaseOrderNotFound  — missing or cross-owner (D4).
      PurchaseOrderNotDraft  — PO already received (409).
      ValidationError        — lines provided but empty.
      ProductNotFound        — replacement line references cross-owner product.
    """
    if lines is not None and len(lines) == 0:
        raise ValidationError(detail="lines must not be empty when provided.")

    po_id_str = str(po_id)

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                existing = select_purchase_order_by_id(
                    cur, params={"id": po_id_str, "owner_id": owner_id}
                )
                if existing is None:
                    raise PurchaseOrderNotFound(
                        detail=f"Purchase order {po_id} not found."
                    )
                if existing["status"] != "draft":
                    raise PurchaseOrderNotDraft(
                        detail=f"Purchase order {po_id} is not a draft."
                    )

                # Build update params — only include non-None fields
                update_params: dict = {"id": po_id_str, "owner_id": owner_id}
                if supplier_name is not None:
                    update_params["supplier_name"] = supplier_name
                if supplier_contact is not None:
                    update_params["supplier_contact"] = supplier_contact

                header = update_purchase_order_header(cur, params=update_params)

                if lines is not None:
                    delete_lines_for_purchase_order(
                        cur,
                        params={"purchase_order_id": po_id_str, "owner_id": owner_id},
                    )
                    inserted_lines = []
                    for line in lines:
                        ln = insert_purchase_order_line(
                            cur,
                            params={
                                "owner_id": owner_id,
                                "purchase_order_id": po_id_str,
                                "product_id": str(line["product_id"]),
                                "quantity": line["quantity"],
                                "unit_cost": line["unit_cost"],
                            },
                        )
                        inserted_lines.append(ln)
                else:
                    inserted_lines = select_lines_for_purchase_order(
                        cur,
                        params={"purchase_order_id": po_id_str, "owner_id": owner_id},
                    )

            conn.commit()
        except psycopg.errors.ForeignKeyViolation as exc:
            conn.rollback()
            if "pol_product_owner_fkey" in str(exc):
                raise ProductNotFound(
                    detail="One or more products not found for this owner."
                )
            raise
        except (PurchaseOrderNotFound, PurchaseOrderNotDraft, ValidationError):
            conn.rollback()
            raise

    return _row_to_po(header, inserted_lines)


def delete_purchase_order_draft(
    *,
    owner_id: int,
    po_id: UUID,
) -> None:
    """Hard-delete a draft PO. Lines cascade.

    Raises:
      PurchaseOrderNotFound  — missing or cross-owner (D4).
      PurchaseOrderNotDraft  — PO already received (409).
    """
    po_id_str = str(po_id)

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                existing = select_purchase_order_by_id(
                    cur, params={"id": po_id_str, "owner_id": owner_id}
                )
                if existing is None:
                    raise PurchaseOrderNotFound(
                        detail=f"Purchase order {po_id} not found."
                    )
                if existing["status"] != "draft":
                    raise PurchaseOrderNotDraft(
                        detail=f"Purchase order {po_id} is not a draft."
                    )
                _delete_purchase_order(
                    cur, params={"id": po_id_str, "owner_id": owner_id}
                )
            conn.commit()
        except (PurchaseOrderNotFound, PurchaseOrderNotDraft):
            conn.rollback()
            raise


def receive_purchase_order(
    *,
    owner_id: int,
    po_id: UUID,
    line_metadata: list[ReceiveLineMeta],
) -> PurchaseOrderRow:
    """Receive a draft PO: flip status, then delegate batch+movement creation.

    Validates that line_metadata line_ids match the PO's actual lines exactly.
    Delegates inventory creation to create_receipt_batches (stub in ILEX-005;
    real implementation in ILEX-006).

    Raises:
      PurchaseOrderNotFound         — missing or cross-owner (D4).
      PurchaseOrderAlreadyReceived  — PO is already in 'received' state (409).
      ReceiveLinesMismatch          — line_metadata ids don't match PO's lines (400).
    """
    po_id_str = str(po_id)

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                # Lock header + lines together for the transition
                header = select_purchase_order_for_update(
                    cur, params={"id": po_id_str, "owner_id": owner_id}
                )
                if header is None:
                    raise PurchaseOrderNotFound(
                        detail=f"Purchase order {po_id} not found."
                    )
                if header["status"] == "received":
                    raise PurchaseOrderAlreadyReceived(
                        detail=f"Purchase order {po_id} has already been received."
                    )

                db_lines = select_lines_for_update(
                    cur, params={"purchase_order_id": po_id_str, "owner_id": owner_id}
                )

                # Validate that line_metadata matches the PO's lines exactly (1:1)
                db_line_ids = {str(ln["id"]) for ln in db_lines}
                meta_line_ids = {str(m["line_id"]) for m in line_metadata}
                if db_line_ids != meta_line_ids:
                    raise ReceiveLinesMismatch(
                        detail=(
                            "line_metadata line_ids must match the PO's lines exactly. "
                            f"Expected {sorted(db_line_ids)}, got {sorted(meta_line_ids)}."
                        )
                    )

                # Transition header to received
                updated_header = mark_purchase_order_received(
                    cur, params={"id": po_id_str, "owner_id": owner_id}
                )

            conn.commit()
        except (PurchaseOrderNotFound, PurchaseOrderAlreadyReceived, ReceiveLinesMismatch):
            conn.rollback()
            raise

    # Delegate batch + movement creation to apps.inventory
    # ILEX-006 fills the real body; signature is preserved from ILEX-005.
    create_receipt_batches(
        owner_id=owner_id,
        lines=[
            {
                "line_id": str(m["line_id"]),
                "batch_code": m["batch_code"],
                "expiration_date": m.get("expiration_date"),
                "product_id": next(
                    str(ln["product_id"]) for ln in db_lines if str(ln["id"]) == str(m["line_id"])
                ),
                "quantity": next(
                    ln["quantity"] for ln in db_lines if str(ln["id"]) == str(m["line_id"])
                ),
                "unit_cost": next(
                    ln["unit_cost"] for ln in db_lines if str(ln["id"]) == str(m["line_id"])
                ),
                "purchase_order_line_id": str(m["line_id"]),
            }
            for m in line_metadata
        ],
    )

    return _row_to_po(updated_header, db_lines)


def list_purchase_orders_for_owner(
    *,
    owner_id: int,
    status: str | None = None,
    search: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Return a paginated list of POs with their lines for the given owner."""
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
