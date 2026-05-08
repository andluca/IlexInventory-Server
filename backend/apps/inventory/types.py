"""Shared typed data structures for apps.inventory."""

from __future__ import annotations

from typing import Any, TypedDict


class BatchRow(TypedDict):
    id: str
    owner_id: int
    product_id: str
    purchase_order_line_id: str | None
    batch_code: str
    expiration_date: Any          # date | None
    unit_cost: Any                # Decimal
    is_recalled: bool
    recall_reason: str | None
    recalled_at: Any              # datetime | None
    archived_at: Any              # datetime | None
    created_at: Any               # datetime
    updated_at: Any               # datetime
    on_hand: Any                  # Decimal — populated by selectors via v_stock_by_batch


class MovementRow(TypedDict):
    id: str
    owner_id: int
    batch_id: str
    kind: str
    signed_quantity: Any          # Decimal
    notes: str | None
    reference_type: str | None
    reference_id: str | None
    created_at: Any               # datetime


class NewMovement(TypedDict):
    kind: str
    signed_quantity: Any          # Decimal
    notes: str | None


class ReceiveLine(TypedDict):
    """Shape that procurement's receive_purchase_order passes to create_receipt_batches."""

    line_id: str                  # UUID as string — matches reference_id on receipt movement
    batch_code: str
    expiration_date: Any          # date | str | None
    product_id: str               # UUID as string
    quantity: Any                 # Decimal
    purchase_order_line_id: str   # UUID as string (same as line_id from procurement)
    unit_cost: Any                # Decimal — pulled from the PO line
