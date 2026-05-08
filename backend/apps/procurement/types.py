"""Shared typed data structures for apps.procurement."""

from __future__ import annotations

from typing import Any, TypedDict


class NewLine(TypedDict):
    product_id: str       # UUID as string
    quantity: Any         # Decimal
    unit_cost: Any        # Decimal


class ReceiveLineMeta(TypedDict):
    line_id: str          # UUID as string
    batch_code: str
    expiration_date: str | None    # ISO date string or None


class PurchaseOrderLineRow(TypedDict):
    id: str               # UUID as string
    purchase_order_id: str
    product_id: str
    quantity: Any         # Decimal (serialized as string on wire per SPEC §2.5)
    unit_cost: Any        # Decimal (serialized as string on wire per SPEC §2.5)
    created_at: Any       # datetime


class PurchaseOrderRow(TypedDict):
    id: str               # UUID as string
    owner_id: int
    supplier_name: str
    supplier_contact: str | None
    status: str           # 'draft' | 'received'
    received_at: Any      # datetime | None
    created_at: Any       # datetime
    updated_at: Any       # datetime
    lines: list[PurchaseOrderLineRow]
