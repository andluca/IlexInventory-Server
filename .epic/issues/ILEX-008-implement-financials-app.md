---
id: ILEX-008
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-007]
---

# ILEX-008 Implement financials app (dashboard, margin)

Read-only financials: aggregated dashboard (revenue, COGS, profit, margin) and per-product margin paginated by cursor. Profit margin formula uses markup `(revenue − COGS) / COGS × 100%` per BE-D13 — matches the brief's worked example exactly: $1,000 revenue, $100 COGS, $900 profit, 900% margin.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.6. BE-D13.

## Scope

- `backend/migrations/0006_views.sql` extension: `v_margin_by_product` joins `sale_allocations` (committed, non-voided) with `batches.unit_cost` and `sales_order_lines.sell_price` per product
- `apps/financials/` — selectors + APIs only (no services since the app is read-only)
- 2 endpoints: dashboard (totals + top-product breakdown) and per-product margin detail; date-range params `from`, `to` (default last 30 days; rejects `from > to` and ranges > 1 year)

## Endpoints

| Method | Route | Realizes | Description |
|---|---|---|---|
| GET | `/financials/dashboard` | R3, F11 | Revenue, COGS, profit, margin totals + top-product breakdown. CSV export wiring in ILEX-009 |
| GET | `/financials/margin` | R3, F11 | Per-product margin detail. Cursor pagination |

## Tests

- Query: view returns expected aggregates with the brief example fixture (1 product, 1 PO, 1 SO)
- Selector: D13 formula computed in SQL or Python — verify 900% on the example
- API: dashboard JSON shape; cursor pagination on margin endpoint; date-range validation

## Dependencies

1. ILEX-007 (margin reads from committed, non-voided allocations)
