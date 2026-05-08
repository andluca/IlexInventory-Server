"""Read-only selectors for apps.financials.

Selectors compose query functions and return typed data.
They open their own psycopg connection (read-only semantics — no mutations).

No services.py: this is a read-only app per ilex-discipline.

Module-top imports only (ilex-discipline invariant #6).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Generator

import psycopg
from django.conf import settings

from apps.core.pagination import decode_decimal_cursor, encode_decimal_cursor
from apps.financials.queries.margin import (
    select_margin_aggregates,
    select_margin_by_product,
)
from apps.financials.types import Dashboard, DashboardTotals, MarginRow


def _connect() -> psycopg.Connection:
    return psycopg.connect(settings.DATABASE_URL)


def _compute_margin_pct(revenue: Decimal, cogs: Decimal) -> Decimal | None:
    """Compute markup margin: (revenue - cogs) / cogs * 100. None when cogs=0."""
    if cogs == Decimal("0"):
        return None
    return (revenue - cogs) / cogs * Decimal("100")


def _to_margin_row(row: dict) -> MarginRow:
    """Convert a query result row to a MarginRow TypedDict."""
    revenue = Decimal(str(row["revenue"]))
    cogs = Decimal(str(row["cogs"]))
    profit = revenue - cogs
    margin_pct = _compute_margin_pct(revenue, cogs)
    return MarginRow(
        product_id=str(row["product_id"]),
        product_name=row["product_name"],
        units_sold=Decimal(str(row["units_sold"])),
        revenue=revenue,
        cogs=cogs,
        profit=profit,
        margin_pct=margin_pct,
    )


def _date_to_exclusive(date_to: date) -> date:
    """Convert inclusive date_to to exclusive upper bound (next day)."""
    return date_to + timedelta(days=1)


def dashboard_for_owner(
    *,
    owner_id: int,
    date_from: date,
    date_to: date,
    top_n: int = 5,
) -> Dashboard:
    """Return aggregated dashboard totals + top-N products.

    Computes profit and margin_pct (BE-D13) in Python (Decimal).
    margin_pct is None when cogs=0.
    """
    date_to_exclusive = _date_to_exclusive(date_to)
    base_params = {
        "owner_id": owner_id,
        "date_from": date_from,
        "date_to_exclusive": date_to_exclusive,
    }

    with _connect() as conn:
        with conn.cursor() as cur:
            agg = select_margin_aggregates(cur, params=base_params)
            top_rows = select_margin_by_product(
                cur,
                params={**base_params, "top_n": top_n},
            )

    total_revenue = Decimal(str(agg["total_revenue"]))
    total_cogs = Decimal(str(agg["total_cogs"]))
    total_profit = total_revenue - total_cogs
    total_margin_pct = _compute_margin_pct(total_revenue, total_cogs)

    totals = DashboardTotals(
        revenue=total_revenue,
        cogs=total_cogs,
        profit=total_profit,
        margin_pct=total_margin_pct,
    )
    top_products = [_to_margin_row(r) for r in top_rows]

    return Dashboard(
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        totals=totals,
        top_products=top_products,
    )


def list_margin_by_product(
    *,
    owner_id: int,
    date_from: date,
    date_to: date,
    cursor: str | None,
    limit: int,
) -> dict:
    """Return cursor-paginated per-product margin rows.

    Returns: {"items": [...MarginRow], "next_cursor": str | None}
    """
    date_to_exclusive = _date_to_exclusive(date_to)
    base_params: dict = {
        "owner_id": owner_id,
        "date_from": date_from,
        "date_to_exclusive": date_to_exclusive,
        "limit": limit,
    }

    decoded = decode_decimal_cursor(cursor)
    if decoded is not None:
        cursor_revenue, cursor_product_id = decoded
        base_params["cursor_revenue"] = cursor_revenue
        base_params["cursor_product_id"] = str(cursor_product_id)

    with _connect() as conn:
        with conn.cursor() as cur:
            rows = select_margin_by_product(cur, params=base_params)

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_decimal_cursor(
            Decimal(str(last["revenue"])),
            uuid.UUID(str(last["product_id"])),
        )

    items = [_to_margin_row(r) for r in page_rows]
    return {"items": items, "next_cursor": next_cursor}


def stream_margin_by_product(
    *,
    owner_id: int,
    date_from: date,
    date_to: date,
) -> Generator[MarginRow, None, None]:
    """Yield all per-product margin rows with no pagination cap.

    Used by the CSV export path. Ordered revenue DESC, product_id DESC.
    Profit and margin_pct are computed here (same logic as _to_margin_row).
    """
    date_to_exclusive = _date_to_exclusive(date_to)
    params = {
        "owner_id": owner_id,
        "date_from": date_from,
        "date_to_exclusive": date_to_exclusive,
    }
    with _connect() as conn:
        with conn.cursor() as cur:
            rows = select_margin_by_product(cur, params=params)
    for row in rows:
        yield _to_margin_row(row)
