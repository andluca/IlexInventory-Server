"""TypedDicts for apps.financials.

Defined here as the single source of truth for return shapes.
Used by selectors and serializers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict


class MarginRow(TypedDict):
    """Per-product margin row returned by selectors."""

    product_id: str
    product_name: str
    units_sold: Decimal
    revenue: Decimal
    cogs: Decimal
    profit: Decimal
    margin_pct: Decimal | None


class DashboardTotals(TypedDict):
    """Aggregate totals across all products in the date range."""

    revenue: Decimal
    cogs: Decimal
    profit: Decimal
    margin_pct: Decimal | None


class Dashboard(TypedDict):
    """Full dashboard response shape."""

    date_from: str
    date_to: str
    totals: DashboardTotals
    top_products: list[MarginRow]
