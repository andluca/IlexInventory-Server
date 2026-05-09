"""Business-logic services for apps.sales.

Rules:
- Kwarg-only functions (past owner_id / so_id). Type-annotated.
- Accept typed Python data; return typed Python data.
- Raise from apps.sales.errors — never raw psycopg errors.
- Open their own psycopg connection; wrap mutations in a transaction.
- Never accept owner_id from the request body — API layer passes request.user.id.
- Module-top imports only (ilex-discipline invariant #6 — no function-local imports).
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

import psycopg
import psycopg.errors
from django.conf import settings

from apps.inventory.queries.batches import list_eligible_for_fefo, select_batch_by_id as select_batch_with_on_hand
from apps.inventory.queries.movements import insert_movement
from apps.sales.errors import (
    InsufficientStock,
    InvalidAllocation,
    ProductNotFound,
    SalesOrderNotCommitted,
    SalesOrderNotDraft,
    SalesOrderNotFound,
)
from apps.sales.errors import ValidationError as SalesValidationError
from apps.sales.queries.sale_allocations import (
    insert_sale_allocation,
    select_allocations_for_sales_order,
)
from apps.sales.queries.sales_order_lines import (
    delete_lines_for_sales_order,
    insert_sales_order_line,
    select_lines_for_sales_order,
)
from apps.sales.queries.sales_orders import (
    delete_sales_order as _delete_sales_order,
    insert_sales_order,
    list_sales_orders as _list_sales_orders,
    mark_sales_order_committed,
    select_sales_order_by_id,
    select_sales_order_for_update,
    set_sales_order_voided,
    update_sales_order_header,
)
from apps.sales._assemble import row_to_sales_order
from apps.sales.types import (
    ExplicitAllocation,
    NewSaleLine,
    ProposedAllocation,
    SalesOrderRow,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _connect() -> psycopg.Connection:
    """Open a raw psycopg connection to the configured DATABASE_URL."""
    return psycopg.connect(settings.DATABASE_URL)


def _load_so_with_lines(cur, *, owner_id: int, so_id: str) -> SalesOrderRow | None:
    """Read header + lines + allocations for a SO. Returns None on miss/cross-owner."""
    header = select_sales_order_by_id(
        cur, params={"id": so_id, "owner_id": owner_id}
    )
    if header is None:
        return None
    lines = select_lines_for_sales_order(
        cur, params={"sales_order_id": so_id, "owner_id": owner_id}
    )
    allocations = select_allocations_for_sales_order(
        cur, params={"sales_order_id": so_id, "owner_id": owner_id}
    )
    return row_to_sales_order(header, lines, allocations)


# ---------------------------------------------------------------------------
# FEFO walk helpers (used by commit + preview)
# ---------------------------------------------------------------------------


def _fefo_walk(
    cur,
    *,
    owner_id: int,
    lines: list[dict],
) -> list[dict]:
    """Walk FEFO for a list of SO lines. Raise InsufficientStock on shortfall.

    Returns a list of allocation dicts: {line_id, batch_id, batch, quantity}.
    Locks eligible batch rows FOR UPDATE (via list_eligible_for_fefo).

    Cumulative-correctness (ILEX-016 §1.1): two SO lines that target the same
    product must not double-allocate the same batch. Each line's greedy take
    subtracts from the running `batch_usage` budget for that batch, computed
    across all earlier lines of this same walk. The DB has no on-hand CHECK
    on stock_movements, so this Python-side accumulator is the only thing
    preventing a single committed SO from driving on_hand negative.
    """
    planned: list[dict] = []
    batch_usage: dict[str, Decimal] = {}

    for line in lines:
        product_id = str(line["product_id"])
        required = Decimal(str(line["quantity"]))
        line_id = str(line["id"])

        batches = list_eligible_for_fefo(
            cur, params={"owner_id": owner_id, "product_id": product_id}
        )

        remaining = required
        for batch in batches:
            if remaining <= Decimal("0"):
                break
            batch_id = str(batch["id"])
            on_hand = Decimal(str(batch["on_hand"]))
            already_planned = batch_usage.get(batch_id, Decimal("0"))
            available = on_hand - already_planned
            if available <= Decimal("0"):
                continue
            take = min(available, remaining)
            planned.append({
                "line_id": line_id,
                "batch_id": batch_id,
                "batch": batch,
                "quantity": take,
            })
            batch_usage[batch_id] = already_planned + take
            remaining -= take

        if remaining > Decimal("0"):
            available_for_product = sum(
                (
                    max(
                        Decimal(str(b["on_hand"])) - batch_usage.get(str(b["id"]), Decimal("0")),
                        Decimal("0"),
                    )
                    for b in batches
                ),
                Decimal("0"),
            )
            allocated_so_far = required - remaining
            raise InsufficientStock(
                detail="Insufficient stock for FEFO allocation.",
                fields={
                    "shortfall": {
                        "product_id": product_id,
                        "required": str(required),
                        "available": str(allocated_so_far + available_for_product),
                    }
                },
            )

    return planned


def _validate_explicit_allocations(
    cur,
    *,
    owner_id: int,
    lines: list[dict],
    allocations: list[ExplicitAllocation],
) -> list[dict]:
    """Validate explicit allocations (D11 admin override).

    Checks:
    - Each batch exists for owner.
    - batch.product_id == line.product_id.
    - Batch not recalled; not expired.
    - Per-line SUM(quantity) == line.quantity.
    - Batch on-hand >= cumulative allocated per batch.

    Returns a list of planned allocation dicts (same shape as _fefo_walk).
    Raises InvalidAllocation on any failure.
    """
    line_by_id = {str(ln["id"]): ln for ln in lines}

    # Group allocations by line_id for sum check
    line_sums: dict[str, Decimal] = {}
    planned: list[dict] = []

    # Track cumulative per-batch usage
    batch_usage: dict[str, Decimal] = {}

    for alloc in allocations:
        line_id = str(alloc["line_id"])
        batch_id = str(alloc["batch_id"])
        qty = Decimal(str(alloc["quantity"]))

        if line_id not in line_by_id:
            raise InvalidAllocation(
                detail=f"line_id {line_id} does not belong to this SO."
            )
        line = line_by_id[line_id]

        # Read batch + on-hand via the inventory query layer (no raw SQL in services).
        batch = select_batch_with_on_hand(
            cur, params={"id": batch_id, "owner_id": owner_id}
        )
        if batch is None:
            raise InvalidAllocation(
                detail=f"batch_id {batch_id} not found for this owner."
            )

        if str(batch["product_id"]) != str(line["product_id"]):
            raise InvalidAllocation(
                detail=f"batch {batch_id} belongs to a different product than line {line_id}."
            )

        if batch["is_recalled"]:
            raise InvalidAllocation(
                detail=f"batch {batch_id} is recalled and cannot be allocated."
            )

        today = datetime.date.today()
        if batch["expiration_date"] is not None and batch["expiration_date"] < today:
            raise InvalidAllocation(
                detail=f"batch {batch_id} is expired and cannot be allocated."
            )

        batch_usage[batch_id] = batch_usage.get(batch_id, Decimal("0")) + qty
        on_hand = Decimal(str(batch["on_hand"]))
        if batch_usage[batch_id] > on_hand:
            raise InvalidAllocation(
                detail=f"batch {batch_id} has insufficient on-hand for requested allocation."
            )

        line_sums[line_id] = line_sums.get(line_id, Decimal("0")) + qty
        planned.append({
            "line_id": line_id,
            "batch_id": batch_id,
            "batch": batch,
            "quantity": qty,
        })

    # Validate per-line sum == line.quantity
    for line_id, total_alloc in line_sums.items():
        required = Decimal(str(line_by_id[line_id]["quantity"]))
        if total_alloc != required:
            raise InvalidAllocation(
                detail=(
                    f"line {line_id}: allocation sum {total_alloc} "
                    f"does not match line quantity {required}."
                )
            )

    # Check all lines are accounted for
    for line in lines:
        line_id = str(line["id"])
        if line_id not in line_sums:
            raise InvalidAllocation(
                detail=f"line {line_id} has no allocation provided."
            )

    return planned


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


def create_sales_order_draft(
    *,
    owner_id: int,
    customer_name: str,
    customer_contact: str | None,
    lines: list[NewSaleLine],
) -> SalesOrderRow:
    """INSERT a draft SO header + N lines in a single transaction.

    Raises:
      SalesValidationError  — if lines is empty.
      ProductNotFound       — if any line's (product_id, owner_id) is unknown (D4).
    """
    if not lines:
        raise SalesValidationError(detail="lines must not be empty.")

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                header = insert_sales_order(
                    cur,
                    params={
                        "owner_id": owner_id,
                        "customer_name": customer_name,
                        "customer_contact": customer_contact,
                    },
                )
                so_id = str(header["id"])
                inserted_lines = []
                for line in lines:
                    ln = insert_sales_order_line(
                        cur,
                        params={
                            "owner_id": owner_id,
                            "sales_order_id": so_id,
                            "product_id": str(line["product_id"]),
                            "quantity": line["quantity"],
                            "sell_price": line["sell_price"],
                        },
                    )
                    inserted_lines.append(ln)
            conn.commit()
        except psycopg.errors.ForeignKeyViolation as exc:
            conn.rollback()
            if "sol_product_owner_fkey" in str(exc):
                raise ProductNotFound(
                    detail="One or more products not found for this owner."
                )
            raise
        except SalesValidationError:
            conn.rollback()
            raise

    return row_to_sales_order(header, inserted_lines, [])


def update_sales_order_draft(
    *,
    owner_id: int,
    so_id: str,
    customer_name: str | None = None,
    customer_contact: str | None = None,
    customer_contact_set: bool = False,
    lines: list[NewSaleLine] | None = None,
) -> SalesOrderRow:
    """Update a draft SO header and optionally replace all lines.

    Replace-style: if lines is provided (non-None), DELETE all existing lines
    and INSERT the new set in a single transaction.

    Raises:
      SalesOrderNotFound  — missing or cross-owner (D4).
      SalesOrderNotDraft  — SO already committed (409).
      SalesValidationError — lines provided but empty.
      ProductNotFound      — replacement line references cross-owner product.
    """
    if lines is not None and len(lines) == 0:
        raise SalesValidationError(detail="lines must not be empty when provided.")

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                existing = select_sales_order_by_id(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )
                if existing is None:
                    raise SalesOrderNotFound(
                        detail=f"Sales order {so_id} not found."
                    )
                if existing["status"] != "draft":
                    raise SalesOrderNotDraft(
                        detail=f"Sales order {so_id} is not a draft."
                    )

                update_params: dict[str, Any] = {
                    "id": so_id,
                    "owner_id": owner_id,
                    "customer_name": customer_name,
                    "customer_contact": customer_contact,
                    "customer_contact_set": customer_contact_set,
                }
                header = update_sales_order_header(cur, params=update_params)

                if lines is not None:
                    delete_lines_for_sales_order(
                        cur,
                        params={"sales_order_id": so_id, "owner_id": owner_id},
                    )
                    inserted_lines = []
                    for line in lines:
                        ln = insert_sales_order_line(
                            cur,
                            params={
                                "owner_id": owner_id,
                                "sales_order_id": so_id,
                                "product_id": str(line["product_id"]),
                                "quantity": line["quantity"],
                                "sell_price": line["sell_price"],
                            },
                        )
                        inserted_lines.append(ln)
                else:
                    inserted_lines = select_lines_for_sales_order(
                        cur,
                        params={"sales_order_id": so_id, "owner_id": owner_id},
                    )

                allocations = select_allocations_for_sales_order(
                    cur,
                    params={"sales_order_id": so_id, "owner_id": owner_id},
                )

            conn.commit()
        except psycopg.errors.ForeignKeyViolation as exc:
            conn.rollback()
            if "sol_product_owner_fkey" in str(exc):
                raise ProductNotFound(
                    detail="One or more products not found for this owner."
                )
            raise
        except (SalesOrderNotFound, SalesOrderNotDraft, SalesValidationError):
            conn.rollback()
            raise

    return row_to_sales_order(header, inserted_lines, allocations)


def delete_sales_order_draft(
    *,
    owner_id: int,
    so_id: str,
) -> None:
    """Hard-delete a draft SO. Lines cascade.

    Raises:
      SalesOrderNotFound  — missing or cross-owner (D4).
      SalesOrderNotDraft  — SO already committed (409).
    """
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                existing = select_sales_order_by_id(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )
                if existing is None:
                    raise SalesOrderNotFound(
                        detail=f"Sales order {so_id} not found."
                    )
                if existing["status"] != "draft":
                    raise SalesOrderNotDraft(
                        detail=f"Sales order {so_id} is not a draft."
                    )
                # Delete lines before header (composite FK has no ON DELETE CASCADE)
                delete_lines_for_sales_order(
                    cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                )
                _delete_sales_order(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )
            conn.commit()
        except (SalesOrderNotFound, SalesOrderNotDraft):
            conn.rollback()
            raise


def list_sales_orders_for_owner(
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
    """Return a cursor-paginated list of SOs for the given owner."""
    with _connect() as conn:
        with conn.cursor() as cur:
            rows, next_cursor = _list_sales_orders(
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

            items = []
            for row in rows:
                so_id_str = str(row["id"])
                lines = select_lines_for_sales_order(
                    cur,
                    params={"sales_order_id": so_id_str, "owner_id": owner_id},
                )
                allocs: list[dict] = []
                if row.get("status") == "committed":
                    allocs = select_allocations_for_sales_order(
                        cur,
                        params={"sales_order_id": so_id_str, "owner_id": owner_id},
                    )
                items.append(row_to_sales_order(row, lines, allocs))

    return {"items": items, "next_cursor": next_cursor}


def commit_sales_order(
    *,
    owner_id: int,
    so_id: str,
    allocations: list[ExplicitAllocation] | None = None,
) -> SalesOrderRow:
    """Commit a draft SO atomically — FEFO walk by default, explicit allocations on override.

    Raises:
      SalesOrderNotFound    — missing or cross-owner.
      SalesOrderNotDraft    — SO is not in draft (409).
      InsufficientStock     — FEFO walk cannot satisfy a line (422).
      InvalidAllocation     — explicit allocation fails validation (422).
    """
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                header = select_sales_order_for_update(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )
                if header is None:
                    raise SalesOrderNotFound(
                        detail=f"Sales order {so_id} not found."
                    )
                if header["status"] != "draft":
                    raise SalesOrderNotDraft(
                        detail=f"Sales order {so_id} is not a draft."
                    )

                lines = select_lines_for_sales_order(
                    cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                )

                if allocations is None:
                    planned = _fefo_walk(cur, owner_id=owner_id, lines=lines)
                else:
                    planned = _validate_explicit_allocations(
                        cur, owner_id=owner_id, lines=lines, allocations=allocations
                    )

                inserted_allocs = []
                for plan in planned:
                    unit_cost = Decimal(str(plan["batch"]["unit_cost"]))
                    alloc = insert_sale_allocation(
                        cur,
                        params={
                            "owner_id": owner_id,
                            "sales_order_line_id": plan["line_id"],
                            "batch_id": plan["batch_id"],
                            "allocated_quantity": plan["quantity"],
                            "unit_cost": unit_cost,
                        },
                    )
                    alloc_id = str(alloc["id"])
                    insert_movement(
                        cur,
                        params={
                            "owner_id": owner_id,
                            "batch_id": plan["batch_id"],
                            "kind": "sale",
                            "signed_quantity": -plan["quantity"],
                            "notes": None,
                            "reference_type": "sale_allocation",
                            "reference_id": alloc_id,
                        },
                    )
                    inserted_allocs.append(alloc)

                updated_header = mark_sales_order_committed(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )

            conn.commit()
        except (SalesOrderNotFound, SalesOrderNotDraft, InsufficientStock, InvalidAllocation):
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return row_to_sales_order(updated_header, lines, inserted_allocs)


def void_sales_order(
    *,
    owner_id: int,
    so_id: str,
) -> SalesOrderRow:
    """Void a committed SO; idempotent if already voided.

    Raises:
      SalesOrderNotFound      — missing or cross-owner.
      SalesOrderNotCommitted  — SO is not committed (409).
    """
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                header = select_sales_order_for_update(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )
                if header is None:
                    raise SalesOrderNotFound(
                        detail=f"Sales order {so_id} not found."
                    )
                if header["status"] != "committed":
                    raise SalesOrderNotCommitted(
                        detail=f"Sales order {so_id} is not committed."
                    )

                # Already voided — idempotent, return current
                if header.get("voided_at") is not None:
                    lines = select_lines_for_sales_order(
                        cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                    )
                    allocs = select_allocations_for_sales_order(
                        cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                    )
                    conn.rollback()
                    return row_to_sales_order(header, lines, allocs)

                allocs = select_allocations_for_sales_order(
                    cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                )

                for alloc in allocs:
                    insert_movement(
                        cur,
                        params={
                            "owner_id": owner_id,
                            "batch_id": str(alloc["batch_id"]),
                            "kind": "sale_void",
                            "signed_quantity": Decimal(str(alloc["allocated_quantity"])),
                            "notes": None,
                            "reference_type": "sale_allocation",
                            "reference_id": str(alloc["id"]),
                        },
                    )

                lines = select_lines_for_sales_order(
                    cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                )
                updated_header = set_sales_order_voided(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )

            conn.commit()
        except (SalesOrderNotFound, SalesOrderNotCommitted):
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return row_to_sales_order(updated_header, lines, allocs)


def preview_so_allocations(
    *,
    owner_id: int,
    so_id: str,
) -> list[ProposedAllocation]:
    """Run FEFO inside a savepoint and roll back. No mutations persist.

    Raises:
      SalesOrderNotFound   — missing or cross-owner.
      SalesOrderNotDraft   — SO not in draft.
      InsufficientStock    — FEFO walk cannot satisfy a line (422).
    """
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                header = select_sales_order_by_id(
                    cur, params={"id": so_id, "owner_id": owner_id}
                )
                if header is None:
                    raise SalesOrderNotFound(
                        detail=f"Sales order {so_id} not found."
                    )
                if header["status"] != "draft":
                    raise SalesOrderNotDraft(
                        detail=f"Sales order {so_id} is not a draft."
                    )

                lines = select_lines_for_sales_order(
                    cur, params={"sales_order_id": so_id, "owner_id": owner_id}
                )

                cur.execute("SAVEPOINT preview")
                try:
                    planned = _fefo_walk(cur, owner_id=owner_id, lines=lines)
                finally:
                    cur.execute("ROLLBACK TO SAVEPOINT preview")

        except (SalesOrderNotFound, SalesOrderNotDraft, InsufficientStock):
            conn.rollback()
            raise
        finally:
            conn.rollback()

    return [
        {
            "line_id": p["line_id"],
            "batch_id": p["batch_id"],
            "batch_code": str(p["batch"].get("batch_code", "")),
            "quantity": p["quantity"],
            "unit_cost": Decimal(str(p["batch"]["unit_cost"])),
            "expiration_date": p["batch"].get("expiration_date"),
        }
        for p in planned
    ]
