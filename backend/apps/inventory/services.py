"""Business-logic services for apps.inventory.

Rules:
- Kwarg-only functions (past owner_id). Type-annotated.
- Accept typed Python data; return typed Python data.
- Raise from apps.inventory.errors — never raw psycopg errors.
- Open their own psycopg connection; wrap mutations in a transaction.
- Never accept owner_id from the request body — API layer passes request.user.id.
- Module-top imports only (ilex-discipline invariant #6 — no function-local imports).
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import psycopg
import psycopg.errors

from apps.core.db import connect as _connect

from apps.inventory.errors import (
    BatchExists,
    BatchNotFound,
    InvalidMovementKind,
    ProductNotFound,
    RecallReasonRequired,
    WriteOffExceedsOnHand,
)
from apps.inventory.errors import ValidationError as InventoryValidationError
from apps.inventory.queries.batches import (
    insert_batch,
    list_eligible_for_fefo,
    select_batch_by_id,
    select_batch_for_update,
    set_recall_state,
    update_batch_metadata as _update_batch_metadata_query,
)
from apps.inventory.queries.movements import (
    insert_movement,
    on_hand_for_batch,
)
from apps.inventory.types import BatchRow, MovementRow, ReceiveLine
from apps.sales.selectors import (
    list_recall_report_for_batch as _sales_list_recall_report,
    stream_recall_report_for_batch as _sales_stream_recall_report,
)

# Kinds that callers of record_movement (the public endpoint) may request.
_PUBLIC_MOVEMENT_KINDS = {"adjustment", "write_off"}


def _row_to_batch(row: dict) -> BatchRow:
    """Normalize batch row: UUIDs to str, add on_hand default."""
    r = dict(row)
    for key in ("id", "product_id", "purchase_order_line_id", "reference_id"):
        if key in r and r[key] is not None and not isinstance(r[key], str):
            r[key] = str(r[key])
    if "on_hand" not in r:
        r["on_hand"] = Decimal("0")
    return r  # type: ignore[return-value]


def _row_to_movement(row: dict) -> MovementRow:
    """Normalize movement row: UUIDs to str."""
    r = dict(row)
    for key in ("id", "batch_id", "reference_id"):
        if key in r and r[key] is not None and not isinstance(r[key], str):
            r[key] = str(r[key])
    return r  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Cursor-accepting service surface — for cross-app within-transaction work.
#
# These functions take `cur` as their first argument so the caller (a service
# in another app, e.g. apps.sales) can keep the connection and transaction
# open across multiple steps. The FOR UPDATE locks acquired by
# list_eligible_for_fefo survive until the caller commits.
#
# Wrap query functions, never bypass them. The wrappers ARE the cross-app
# contract — sales depends on these signatures, not on the underlying SQL.
# --------------------------------------------------------------------------


def fefo_eligible_batches(
    cur, *, owner_id: int, product_id: str
) -> list[dict]:
    """SELECT eligible batches FOR UPDATE in FEFO order. Caller holds the tx."""
    return list_eligible_for_fefo(
        cur, params={"owner_id": owner_id, "product_id": product_id}
    )


def get_batch_with_on_hand(
    cur, *, owner_id: int, batch_id: str
) -> dict | None:
    """Read a single batch (no lock) with v_stock_by_batch.on_hand joined."""
    return select_batch_by_id(
        cur, params={"id": batch_id, "owner_id": owner_id}
    )


def append_movement(
    cur,
    *,
    owner_id: int,
    batch_id: str,
    kind: str,
    signed_quantity: Decimal,
    notes: str | None = None,
    reference_type: str | None = None,
    reference_id: str | None = None,
) -> dict:
    """Append a stock_movements row inside the caller's transaction."""
    return insert_movement(
        cur,
        params={
            "owner_id": owner_id,
            "batch_id": batch_id,
            "kind": kind,
            "signed_quantity": signed_quantity,
            "notes": notes,
            "reference_type": reference_type,
            "reference_id": reference_id,
        },
    )


# --------------------------------------------------------------------------
# Cross-app read wrappers — recall reports.
#
# Recall report data lives in apps.sales (sale_allocations + v_recall_report)
# but the endpoint is mounted on /batches/{id}/recall-report (inventory URL).
# These wrappers make inventory.apis the only consumer of inventory.services
# and keep the cross-app boundary at the service layer.
# --------------------------------------------------------------------------


def get_recall_report_for_batch(
    *, owner_id: int, batch_id: str, limit: int = 50, offset: int = 0
) -> dict:
    """Offset-paginated recall report for a batch."""
    return _sales_list_recall_report(
        owner_id=owner_id, batch_id=batch_id, limit=limit, offset=offset
    )


def stream_recall_report_for_batch(
    *, owner_id: int, batch_id: str
) -> Generator[dict, None, None]:
    """Stream all recall-report rows for a batch (CSV export path)."""
    yield from _sales_stream_recall_report(owner_id=owner_id, batch_id=batch_id)


def _insert_batch_with_receipt(
    cur,
    *,
    owner_id: int,
    product_id: str,
    purchase_order_line_id: str | None,
    batch_code: str,
    expiration_date: Any,
    unit_cost: Decimal,
    quantity: Decimal,
    reference_type: str,
    reference_id: str | None,
) -> tuple[dict, dict]:
    """Private helper: INSERT batch + INSERT receipt movement in the same cursor/tx.

    Not directly tested — behavior is tested through create_manual_batch and
    create_receipt_batches per the TDD skill's "Behavioral, not structural" rule.
    """
    batch = insert_batch(cur, params={
        "owner_id": owner_id,
        "product_id": product_id,
        "purchase_order_line_id": purchase_order_line_id,
        "batch_code": batch_code,
        "expiration_date": expiration_date,
        "unit_cost": unit_cost,
    })
    movement = insert_movement(cur, params={
        "owner_id": owner_id,
        "batch_id": str(batch["id"]),
        "kind": "receipt",
        "signed_quantity": quantity,
        "notes": None,
        "reference_type": reference_type,
        "reference_id": reference_id,
    })
    return batch, movement


def create_receipt_batches(
    *,
    owner_id: int,
    lines: list[ReceiveLine],
) -> list[BatchRow]:
    """Create one batch per PO line + one receipt movement per batch.

    Procurement calls this AFTER receive_purchase_order commits the PO header
    transition. We open our own connection.

    For each line: INSERT batch (with purchase_order_line_id set, unit_cost from
    line) + INSERT receipt movement (kind='receipt', signed_quantity=+line.quantity,
    reference_type='purchase_order_line', reference_id=line.line_id).

    Wraps all inserts in a single transaction — if any fails, no batches or
    movements persist.

    Note: procurement already committed the PO header before calling us.
    If our writes fail, the PO is in 'received' state but has zero batches.
    This is a known seam from ILEX-005's split. The uniqueness constraint on
    (owner_id, product_id, batch_code) prevents double-receives at DB level.
    """
    if not lines:
        return []

    with _connect() as conn:
        try:
            results: list[BatchRow] = []
            with conn.cursor() as cur:
                for line in lines:
                    batch, _ = _insert_batch_with_receipt(
                        cur,
                        owner_id=owner_id,
                        product_id=str(line["product_id"]),
                        purchase_order_line_id=str(line["purchase_order_line_id"]),
                        batch_code=line["batch_code"],
                        expiration_date=line.get("expiration_date"),
                        unit_cost=Decimal(str(line["unit_cost"])),
                        quantity=Decimal(str(line["quantity"])),
                        reference_type="purchase_order_line",
                        reference_id=str(line["line_id"]),
                    )
                    results.append(_row_to_batch(batch))
            conn.commit()
        except psycopg.errors.ForeignKeyViolation:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return results


def create_manual_batch(
    *,
    owner_id: int,
    product_id: str,
    batch_code: str,
    expiration_date: date | None,
    unit_cost: Decimal,
    initial_quantity: Decimal,
) -> BatchRow:
    """F4. INSERT batch (purchase_order_line_id=NULL) + receipt movement
    (reference_type='manual', reference_id=NULL). Atomic.

    Raises ProductNotFound on cross-owner / missing product (D4 → 404).
    Raises BatchExists on duplicate (owner_id, product_id, batch_code).
    Raises InventoryValidationError if initial_quantity <= 0.
    """
    if initial_quantity <= Decimal("0"):
        raise InventoryValidationError(detail="initial_quantity must be positive.")

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                batch, _ = _insert_batch_with_receipt(
                    cur,
                    owner_id=owner_id,
                    product_id=product_id,
                    purchase_order_line_id=None,
                    batch_code=batch_code,
                    expiration_date=expiration_date,
                    unit_cost=unit_cost,
                    quantity=initial_quantity,
                    reference_type="manual",
                    reference_id=None,
                )
            conn.commit()
        except psycopg.errors.UniqueViolation:
            conn.rollback()
            raise BatchExists(detail=f"Batch '{batch_code}' already exists for this product.")
        except psycopg.errors.ForeignKeyViolation:
            conn.rollback()
            raise ProductNotFound(detail=f"Product {product_id} not found for this owner.")
        except Exception:
            conn.rollback()
            raise

    return _row_to_batch(batch)


def update_batch_metadata(
    *,
    owner_id: int,
    batch_id: str,
    batch_code: str | None,
    expiration_date: date | None,
    clear_expiration: bool = False,
) -> BatchRow:
    """F12. Update batch_code and/or expiration_date. Writes a metadata_correction
    movement (kind='metadata_correction', signed_quantity=0) capturing the diff
    in notes. No-op (idempotent) when the value is already current.

    clear_expiration=True explicitly sets expiration_date to NULL.

    Raises BatchNotFound on missing/cross-owner.
    """
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                existing = select_batch_for_update(
                    cur, params={"id": batch_id, "owner_id": owner_id}
                )
                if existing is None:
                    raise BatchNotFound(detail=f"Batch {batch_id} not found.")

                new_code = batch_code if batch_code is not None else existing["batch_code"]
                if clear_expiration:
                    new_expiry = None
                elif expiration_date is not None:
                    new_expiry = expiration_date
                else:
                    new_expiry = existing["expiration_date"]

                # Detect actual changes
                changed: list[str] = []
                if new_code != existing["batch_code"]:
                    changed.append(f"batch_code: {existing['batch_code']!r} → {new_code!r}")
                old_expiry = existing["expiration_date"]
                if hasattr(old_expiry, "isoformat"):
                    old_expiry_str = old_expiry.isoformat()
                else:
                    old_expiry_str = str(old_expiry)
                new_expiry_str = new_expiry.isoformat() if hasattr(new_expiry, "isoformat") else str(new_expiry)
                if str(new_expiry) != str(existing["expiration_date"]):
                    changed.append(f"expiration_date: {old_expiry_str!r} → {new_expiry_str!r}")

                if not changed:
                    # No actual change — idempotent, skip writes
                    conn.rollback()
                    return _row_to_batch({**existing, "on_hand": Decimal("0")})

                updated = _update_batch_metadata_query(
                    cur, params={
                        "id": batch_id,
                        "owner_id": owner_id,
                        "batch_code": new_code,
                        "expiration_date": new_expiry,
                    }
                )
                insert_movement(cur, params={
                    "owner_id": owner_id,
                    "batch_id": batch_id,
                    "kind": "metadata_correction",
                    "signed_quantity": Decimal("0"),
                    "notes": "; ".join(changed),
                    "reference_type": None,
                    "reference_id": None,
                })
            conn.commit()
        except BatchNotFound:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return _row_to_batch(updated)


def record_movement(
    *,
    owner_id: int,
    batch_id: str,
    kind: str,
    signed_quantity: Decimal,
    notes: str | None,
) -> MovementRow:
    """F5/F6. kind ∈ {adjustment, write_off}. Locks the batch FOR UPDATE,
    reads on_hand, validates write-off doesn't drive negative, INSERTs the
    movement.

    Raises InvalidMovementKind for kinds outside the public allowlist.
    Raises InventoryValidationError for adjustment with empty notes.
    Raises WriteOffExceedsOnHand (422) when on_hand + signed_quantity < 0.
    Raises BatchNotFound on missing/cross-owner.
    """
    if kind not in _PUBLIC_MOVEMENT_KINDS:
        raise InvalidMovementKind(detail=f"kind '{kind}' is not allowed via this endpoint.")

    if kind == "adjustment" and (not notes or not notes.strip()):
        raise InventoryValidationError(detail="notes are required for adjustment movements.")

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                batch = select_batch_for_update(
                    cur, params={"id": batch_id, "owner_id": owner_id}
                )
                if batch is None:
                    raise BatchNotFound(detail=f"Batch {batch_id} not found.")

                if kind == "write_off":
                    current_on_hand = on_hand_for_batch(
                        cur, params={"batch_id": batch_id, "owner_id": owner_id}
                    )
                    projected = Decimal(str(current_on_hand)) + signed_quantity
                    if projected < Decimal("0"):
                        raise WriteOffExceedsOnHand(
                            detail=f"Write-off would result in negative on_hand ({projected})."
                        )

                movement = insert_movement(cur, params={
                    "owner_id": owner_id,
                    "batch_id": batch_id,
                    "kind": kind,
                    "signed_quantity": signed_quantity,
                    "notes": notes,
                    "reference_type": None,
                    "reference_id": None,
                })
            conn.commit()
        except (BatchNotFound, InvalidMovementKind, InventoryValidationError, WriteOffExceedsOnHand):
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return _row_to_movement(movement)


def recall_batch(*, owner_id: int, batch_id: str, reason: str) -> BatchRow:
    """F9. Idempotent (D3): if already recalled, no writes, return current.
    Otherwise UPDATE batches SET is_recalled=true, recall_reason, recalled_at
    + INSERT recall_block movement (kind='recall_block', signed_quantity=0, notes=reason).

    Raises BatchNotFound on missing/cross-owner.
    Raises RecallReasonRequired if reason is blank.
    """
    if not reason or not reason.strip():
        raise RecallReasonRequired(detail="recall reason must not be blank.")

    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                batch = select_batch_for_update(
                    cur, params={"id": batch_id, "owner_id": owner_id}
                )
                if batch is None:
                    raise BatchNotFound(detail=f"Batch {batch_id} not found.")

                if batch["is_recalled"]:
                    # Already recalled — idempotent, no writes
                    conn.rollback()
                    return _row_to_batch(batch)

                now = datetime.now(tz=timezone.utc)
                updated = set_recall_state(cur, params={
                    "id": batch_id,
                    "owner_id": owner_id,
                    "is_recalled": True,
                    "recall_reason": reason.strip(),
                    "recalled_at": now,
                })
                insert_movement(cur, params={
                    "owner_id": owner_id,
                    "batch_id": batch_id,
                    "kind": "recall_block",
                    "signed_quantity": Decimal("0"),
                    "notes": reason.strip(),
                    "reference_type": None,
                    "reference_id": None,
                })
            conn.commit()
        except (BatchNotFound, RecallReasonRequired):
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return _row_to_batch(updated)


def un_recall_batch(*, owner_id: int, batch_id: str) -> BatchRow:
    """F10. Idempotent: if not recalled, no writes, return current.
    Otherwise UPDATE batches SET is_recalled=false, recall_reason=NULL, recalled_at=NULL
    + INSERT recall_unblock movement.

    Raises BatchNotFound on missing/cross-owner.
    """
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                batch = select_batch_for_update(
                    cur, params={"id": batch_id, "owner_id": owner_id}
                )
                if batch is None:
                    raise BatchNotFound(detail=f"Batch {batch_id} not found.")

                if not batch["is_recalled"]:
                    # Not recalled — idempotent, no writes
                    conn.rollback()
                    return _row_to_batch(batch)

                updated = set_recall_state(cur, params={
                    "id": batch_id,
                    "owner_id": owner_id,
                    "is_recalled": False,
                    "recall_reason": None,
                    "recalled_at": None,
                })
                insert_movement(cur, params={
                    "owner_id": owner_id,
                    "batch_id": batch_id,
                    "kind": "recall_unblock",
                    "signed_quantity": Decimal("0"),
                    "notes": None,
                    "reference_type": None,
                    "reference_id": None,
                })
            conn.commit()
        except BatchNotFound:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    return _row_to_batch(updated)
