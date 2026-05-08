"""Shared typed data structures for apps.sales."""

from __future__ import annotations

from typing import Any, TypedDict


class NewSaleLine(TypedDict):
    product_id: str           # UUID as string
    quantity: Any             # Decimal
    sell_price: Any           # Decimal


class SalesOrderLineRow(TypedDict):
    id: str
    owner_id: int
    sales_order_id: str
    product_id: str
    quantity: Any             # Decimal
    sell_price: Any           # Decimal
    created_at: Any           # datetime


class AllocationRow(TypedDict):
    id: str
    owner_id: int
    sales_order_line_id: str
    batch_id: str
    allocated_quantity: Any   # Decimal
    unit_cost: Any            # Decimal
    created_at: Any           # datetime


class SalesOrderRow(TypedDict):
    id: str
    owner_id: int
    customer_name: str
    customer_contact: str | None
    status: str               # 'draft' | 'committed'
    committed_at: Any         # datetime | None
    voided_at: Any            # datetime | None
    created_at: Any           # datetime
    updated_at: Any           # datetime
    lines: list[SalesOrderLineRow]
    allocations: list[AllocationRow]


class ExplicitAllocation(TypedDict):
    """Admin-override allocation item from the request body (D11)."""

    line_id: str              # UUID as string
    batch_id: str             # UUID as string
    quantity: Any             # Decimal


class ProposedAllocation(TypedDict):
    """One entry in the FEFO preview result."""

    line_id: str              # UUID as string
    batch_id: str             # UUID as string
    batch_code: str
    quantity: Any             # Decimal
    unit_cost: Any            # Decimal
    expiration_date: Any      # date | None


class RecallReportRow(TypedDict):
    batch_id: str
    sale_order_id: str
    owner_id: int
    customer_name: str
    customer_contact: str | None
    quantity_received: Any    # Decimal
    sale_committed_at: Any    # datetime
