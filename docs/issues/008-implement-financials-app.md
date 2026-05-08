# 008 — Implement financials app (dashboard, margin)

## Overview

Read-only financials: aggregated dashboard (revenue, COGS, profit, margin) and per-product margin paginated by cursor. Profit margin formula uses markup `(revenue − COGS) / COGS × 100%` per BE-D13 — matches the brief's worked example exactly: $1,000 revenue, $100 COGS, $900 profit, 900% margin.

**Scope:**
- `v_margin_by_product` view added (extends `0006_views.sql` or its own migration alongside): joins `sale_allocations` (committed, non-voided SOs) with `batches.unit_cost` and `sales_order_lines.sell_price` per product
- `apps/financials/` — selectors + APIs only (no services since the app is read-only)
- 2 endpoints: dashboard (totals + top-product breakdown) and per-product margin detail; date-range params `from`, `to` (default last 30 days; rejects `from > to` and ranges > 1 year)
- Tests:
  - Query: view returns expected aggregates with the brief example fixture (1 product, 1 PO, 1 SO)
  - Selector: D13 formula computed in SQL or Python — verify 900% on the example
  - API: dashboard JSON shape; cursor pagination on margin endpoint

**Endpoints:**
- GET `/financials/dashboard`
- GET `/financials/margin`

**Reference:** SPEC §3.6. BE-D13.

**Depends on:** 007 (margin reads from committed, non-voided allocations).
