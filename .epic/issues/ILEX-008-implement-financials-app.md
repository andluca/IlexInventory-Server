---
id: ILEX-008
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-007]
---

# ILEX-008 Implement financials app (dashboard, margin)

Read-only financials app. Adds `v_margin_by_product` (joins committed, non-voided `sale_allocations` with `batches.unit_cost` and `sales_order_lines.sell_price`) and two endpoints: aggregated dashboard (revenue, COGS, profit, margin + top products) and per-product margin (cursor-paginated). Profit margin uses BE-D13 markup formula `(revenue − COGS) / COGS × 100%` — matches the brief's worked example exactly: $1,000 revenue + $100 COGS = $900 profit + 900% margin.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.6. BE-D13. Flow R3, F11.

## Operation: get-financials-dashboard
Route: `GET /api/v1/financials/dashboard`

Aggregated revenue / COGS / profit / margin totals + top-N product breakdown for a date range.

### Preconditions
* User is authenticated (DRF SessionAuthentication).
* `0008_financials.sql` is applied (creates `v_margin_by_product`).

### Primary Use Case

#### Input
```
GET /api/v1/financials/dashboard?from=2026-04-08&to=2026-05-08&top=5
```

#### Workflow
* API reads `request.user.id`, `from`, `to`, `top` (default 5, capped 50).
* Default range: last 30 days from today when `from`/`to` omitted.
* Validate `from <= to` and `(to - from) <= 365 days`.
* Selector `dashboard_for_owner` queries `v_margin_by_product` filtered by `committed_at BETWEEN from AND to`, sums revenue/COGS, computes margin in Python (Decimal), returns top-N products sorted by revenue DESC.

#### Output
```json
{
  "from": "2026-04-08",
  "to": "2026-05-08",
  "totals": {
    "revenue": "1000.0000",
    "cogs": "100.0000",
    "profit": "900.0000",
    "margin_pct": "900.0000"
  },
  "top_products": [
    {"product_id": "...", "product_name": "Widget", "revenue": "1000.0000", "cogs": "100.0000", "profit": "900.0000", "margin_pct": "900.0000"}
  ]
}
```

### Edge Cases
* No sales in range → totals all `"0"`, `top_products: []`, `margin_pct: null` (COGS=0 → division undefined).
* `from > to` → 400 `ValidationError` (`"from must be <= to"`).
* `(to - from) > 365 days` → 400 `ValidationError` (`"date range exceeds 1 year"`).

## Operation: list-margin-by-product
Route: `GET /api/v1/financials/margin`

Per-product margin detail rows, cursor-paginated.

### Preconditions
* User is authenticated.
* Same date-range params as dashboard.

### Primary Use Case

#### Input
```
GET /api/v1/financials/margin?from=2026-04-08&to=2026-05-08&cursor=<opaque>&limit=50
```

#### Workflow
* API validates date range (same rules as dashboard).
* Selector `list_margin_by_product` runs cursor-paginated query against `v_margin_by_product`.
* Ordering: `revenue DESC, product_id DESC` (stable for cursor pagination).
* Computes `profit` and `margin_pct` per row (Python Decimal). `margin_pct` is `null` when COGS=0.

#### Output
```json
{
  "items": [
    {"product_id": "...", "product_name": "Widget", "units_sold": "100.0000",
     "revenue": "1000.0000", "cogs": "100.0000", "profit": "900.0000", "margin_pct": "900.0000"}
  ],
  "next_cursor": null
}
```

### Edge Cases
* No sales in range → `{"items": [], "next_cursor": null}`.
* Cross-owner data never appears (owner-scoped at the view via `sa.owner_id` filter).

## View: v_margin_by_product
File: `backend/migrations/0008_financials.sql`

Joins `sale_allocations` (committed, non-voided SOs) with `sales_order_lines.sell_price`, `batches.unit_cost`, and `products.name`. One row per `(owner_id, product_id, sales_order_id)` — committed_at is preserved so the selector can filter by date range.

### Columns
* `owner_id INT`
* `product_id UUID`
* `product_name TEXT`
* `sales_order_id UUID`
* `committed_at TIMESTAMPTZ` (from `sales_orders.committed_at`; selector filters on this)
* `units_sold NUMERIC(14, 4)` — `SUM(sa.allocated_quantity)` per SO+product
* `revenue NUMERIC(14, 4)` — `SUM(sa.allocated_quantity * sol.sell_price)`
* `cogs NUMERIC(14, 4)` — `SUM(sa.allocated_quantity * sa.unit_cost)`

### Filter
* `so.status = 'committed' AND so.voided_at IS NULL` (D8: voided units are treated as never sold)

The selector aggregates these per-SO rows up to per-product totals at query time, scoped by date range.

## Function: dashboard_for_owner
File: `backend/apps/financials/selectors.py`
Input: `(*, owner_id: int, date_from: date, date_to: date, top_n: int = 5) -> dict`
Returns: `{"from": str, "to": str, "totals": {...}, "top_products": [...]}`

Compose `select_margin_aggregates` (totals across the whole range) and `select_margin_by_product` (top-N rows, no cursor).

### Implementation
* Open psycopg connection (read-only).
* Call query function returning `(total_revenue, total_cogs, total_units)` over the range.
* Call query function returning top-N product rows ordered by revenue DESC.
* Compute `profit` = `revenue - cogs` and `margin_pct` per BE-D13 (None when cogs=0).
* Return assembled dict; serialize Decimals as strings via DRF.

## Function: list_margin_by_product
File: `backend/apps/financials/selectors.py`
Input: `(*, owner_id: int, date_from: date, date_to: date, cursor: str | None, limit: int) -> dict`
Returns: `{"items": [...], "next_cursor": str | None}`

Cursor-paginated read against the view, aggregated per product.

### Implementation
* Decode opaque cursor (revenue + product_id tuple) via `apps.core.pagination`.
* Run aggregated SQL with `LIMIT n+1` to detect `has_more`.
* Encode next cursor when `has_more`.

## Utils: queries
File: `backend/apps/financials/queries/margin.py`

### Functions
* `select_margin_aggregates`: total revenue/COGS/units across the date range. One row.
* `select_margin_by_product`: per-product aggregation; supports `top_n` (no cursor) OR `cursor` + `limit` (paginated). Two arg shapes, one SQL skeleton.

Both `@scoped`. Owner filter on `sa.owner_id`.

## Lib: shared helpers (no new lib package)

Reuse existing infrastructure unchanged:
* `apps.core.owner_scope.scoped` — query decoration.
* `apps.core.pagination.{encode_cursor,decode_cursor}` — for `/financials/margin`. Cursor key = `(revenue, product_id)`. Reuse decode helper but the encoder needs a small variant: existing `encode_cursor` takes `(uuid, datetime)`. We add a sibling `encode_decimal_cursor`/`decode_decimal_cursor` OR reuse a JSON-base64 inline pair (decision in step 4 below).
* `apps.core.errors.{DomainError,ValidationError,to_response}` — date-range error mapping.

## External Dependencies

None. Financials reads only DB views. No service-layer mutations.

# Plan

Each step ends with green `pytest`, `mypy`, `ruff`, and discipline grep gates. Steps are independently shippable.

1. **Migration `0008_financials.sql` (`v_margin_by_product`) + view query tests**
   - Why: schema is the foundation for selectors; pinning the view shape with behavioral tests means later steps just glue Python around it.
   - [ ] Add `backend/migrations/0008_financials.sql` with `CREATE OR REPLACE VIEW v_margin_by_product AS …` joining `sale_allocations + sales_order_lines + sales_orders + batches + products`; filtered by `so.status='committed' AND so.voided_at IS NULL`; one row per `(owner_id, product_id, sales_order_id)`.
   - [ ] Bump `_EXPECTED_MIGRATIONS` from 7 to 8 in `backend/apps/core/tests/api/test_migrate_sql.py`.
   - [ ] Test (`apps/financials/tests/query/test_v_margin_by_product.py`): hand-seed brief example (1 product, 1 PO with 100 units @ $1, 1 SO with 100 @ $10, FEFO commit) → assert one row with `revenue=1000.0000`, `cogs=100.0000`, `units_sold=100.0000`.
   - [ ] Test: voided SO disappears from the view (commit → assert row present → void → assert no row).
   - [ ] Test: cross-owner sales never appear (seed two owners, query filtered by one, assert isolation).

2. **Financials app skeleton + read selectors**
   - Why: the heavy lift is the SQL aggregation; isolating it behind two pure-read selectors lets the API steps be thin glue.
   - [ ] `apps/financials/__init__.py`, `apps/financials/queries/__init__.py`.
   - [ ] `apps/financials/queries/margin.py`: `select_margin_aggregates` (totals over range) + `select_margin_by_product` (per-product, supports both `top_n` and cursor+limit paths). Both `@scoped`.
   - [ ] `apps/financials/types.py`: `MarginRow`, `DashboardTotals`, `Dashboard` TypedDicts.
   - [ ] `apps/financials/errors.py`: re-export `ValidationError` from core; no new error codes (date validation lives in API layer per existing pattern).
   - [ ] `apps/financials/selectors.py`: `dashboard_for_owner`, `list_margin_by_product`. Compute `profit` and `margin_pct` (D13) in Python; `margin_pct = None` when `cogs = 0`.
   - [ ] Add `apps/financials/tests/conftest.py` mirroring `apps/sales/tests/conftest.py` (run ORM migrations + `migrate_sql` once per session).
   - [ ] Test (`apps/financials/tests/unit/test_margin_formula.py`): `margin_pct` for `revenue=1000, cogs=100` returns `Decimal('900.0000')`; `cogs=0` returns `None`. Behavioral — call selector via real DB seed, no `_private` imports.

3. **Dashboard endpoint (`GET /financials/dashboard`)**
   - Why: matches the brief's headline number; ships before pagination so the FE dashboard can render even before the detail list exists.
   - [ ] `apps/financials/serializers.py`: `DashboardResponse`, `MarginRowResponse`, `DateRangeQuery` (validates `from <= to` and range ≤ 365 days).
   - [ ] `apps/financials/apis.py`: `FinancialsDashboardApi(APIView)` — GET only, `IsAuthenticated`. Default range = last 30 days when params omitted. Returns `DashboardResponse`.
   - [ ] `apps/financials/urls.py`; wire into `backend/urls.py` under `api/v1/`.
   - [ ] API test (`apps/financials/tests/api/test_dashboard.py`): brief example end-to-end → `{totals: {revenue: "1000.0000", cogs: "100.0000", profit: "900.0000", margin_pct: "900.0000"}, top_products: [1 row]}`.
   - [ ] API test: empty range → `totals: {revenue: "0.0000", cogs: "0.0000", profit: "0.0000", margin_pct: null}`, `top_products: []`.
   - [ ] API test: `from > to` → 400 `ValidationError`.
   - [ ] API test: range > 1 year → 400 `ValidationError`.
   - [ ] API test: voided SO excluded — commit + void → totals all zero.

4. **Per-product margin endpoint (`GET /financials/margin`) + cursor pagination**
   - Why: enables FE to paginate through the long tail; reuses the same view + selectors but adds cursor encoding.
   - [ ] `apps/core/pagination.py`: add `encode_decimal_cursor(decimal_val: Decimal, uuid_val: UUID) -> str` + `decode_decimal_cursor(token) -> tuple[Decimal, UUID] | None` (mirror existing `encode_cursor`/`decode_cursor` shape).
   - [ ] Wire `select_margin_by_product` cursor path: `WHERE (revenue, product_id::text) < (%(cursor_rev)s, %(cursor_pid)s)` ordering by `revenue DESC, product_id DESC`.
   - [ ] `apps/financials/apis.py`: `FinancialsMarginListApi(APIView)`.
   - [ ] `apps/financials/urls.py`: register `financials/margin`.
   - [ ] API test (`apps/financials/tests/api/test_margin_list.py`): seed 3 products with distinct revenues → page with `limit=2` returns 2 items + non-null `next_cursor`; second page returns the third item + `next_cursor=null`.
   - [ ] API test: brief example shape — single committed SO → `items[0]` carries `product_id`, `product_name`, `units_sold="100.0000"`, `revenue="1000.0000"`, `cogs="100.0000"`, `profit="900.0000"`, `margin_pct="900.0000"`.
   - [ ] API test: same date-range validation as dashboard (one negative case is enough — `from > to` → 400).

# Notes

- **CSV export deferred to ILEX-009.** This issue ships JSON only; `?format=csv` is wired in the cross-cutting reports issue.
- **Migration filename divergence from SPEC §3.6.** The issue scope reads "`0006_views.sql` extension". We instead create a new file `0008_financials.sql` to match the per-issue migration convention already established by ILEX-007 (which put `v_recall_report` in `0007_sales.sql` rather than extending `0006_views.sql`). Reason: `migrate_sql` tracks applied state by filename, so editing an already-applied 0006 wouldn't re-run in deployed environments. CREATE OR REPLACE in a new file is safe and idempotent. Note in a docs-only follow-up.
- **D13 formula label.** API field is `margin_pct`, FE renders as "Profit Margin" matching the brief wording. Markup not gross-margin: `(revenue − COGS) / COGS × 100%`.
- **`margin_pct` null on zero COGS.** When a date range has revenue but zero COGS (impossible if data is consistent — every committed SO should have allocations with unit_cost) OR when the range is empty, `margin_pct` is `null` (not `0`, not `Infinity`). Avoids ZeroDivisionError and keeps the FE simple.
- **Cursor key choice (`revenue`, `product_id`).** Picked over `(product_name, product_id)` because the dashboard ordering is "biggest revenue first" — the same ordering the FE uses for the detail list. Pagination tail is stable as long as no two products tie on revenue *and* product_id (impossible given UUID PK).
- **No services.py.** Read-only app per ilex-discipline. Selectors call queries directly. Views don't import services.
- **Owner scope.** `sa.owner_id` filter in the view + `@scoped` on every query function. Cross-owner test in step 1 confirms the invariant at the view layer.
- **Performance.** `v_margin_by_product` aggregates per `(owner_id, product_id, sales_order_id)` — no materialization. For 10k+ committed SOs the index on `sa.owner_id` + `sales_orders.committed_at` carries the date filter. Add an index in step 1 only if a query test demonstrates need; otherwise defer.
- **Brief example as anchor test.** Same fixture used in ILEX-007's commit API test (100 units @ $1 received, 100 sold @ $10). Reuse the seed shape; the financials read should produce $1k / $100 / $900 / 900%.

# Journal
