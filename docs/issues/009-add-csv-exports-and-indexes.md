> **Status:** ✅ Done — shipped in [`461bac1`](../../commit/461bac1) as `feat(core): streaming CSV export helper + 0009_indexes (ILEX-009)`.

# ILEX-009 Add CSV exports and 0007_indexes

Cross-cutting polish: ship `backend/migrations/0007_indexes.sql` for the indexes that ILEX-005/0007/0008 deferred (movements audit + status-scoped SO list ordering), wire `?format=csv` content negotiation as a streamed `text/csv` response across the four supporting read endpoints, and route `GET /batches/{id}/recall-report` (deferred from ILEX-006/ILEX-007). Endpoints affected: `/financials/dashboard`, `/financials/margin`, `/movements`, `/batches/{id}/recall-report`.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.6, §3.4, §3.6, §3.7. Flow F11.

## Operation: get-batch-recall-report
Route: `GET /api/v1/batches/{id}/recall-report`

Customers who received units from this batch via committed, non-voided sales orders. Backed by `v_recall_report` (defined in `0007_sales.sql`). Offset-paginated. Supports `?format=csv` for streaming export.

### Preconditions
* User is authenticated (DRF SessionAuthentication).
* Migrations through `0008_financials.sql` are applied. Batch belongs to the requesting owner.

### Primary Use Case (JSON)

#### Input
```
GET /api/v1/batches/<batch_id>/recall-report?limit=50&offset=0
```

#### Workflow
* API reads `request.user.id` and `batch_id`. Validate `batch_id` resolves to an owned, non-archived batch (404 otherwise).
* Selector calls `select_recall_report_for_batch` (already in `apps/sales/queries/recall_report.py`) which reads from `v_recall_report` (D8: voided SOs filtered out at the view).
* Returns `{ items: [...], total: N, limit, offset }`.

#### Output
```json
{
  "items": [
    {"sale_order_id": "...", "customer_name": "Acme", "customer_contact": "ops@acme",
     "quantity_received": "12.0000", "sale_committed_at": "2026-04-08T14:20:00Z"}
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

### CSV Export

#### Input
```
GET /api/v1/batches/<batch_id>/recall-report?format=csv
```

#### Workflow
* API detects `format=csv`; bypasses pagination caps and streams every matching row.
* `apps.core.csv_export.stream_csv` writes a header row (`sale_order_id,customer_name,customer_contact,quantity_received,sale_committed_at`) followed by one CSV row per `items[]` entry.
* Dates ISO-8601; quantities as `str(Decimal)` (e.g., `"12.0000"`).

#### Output
```
HTTP/1.1 200 OK
Content-Type: text/csv; charset=utf-8
Content-Disposition: attachment; filename="recall-report-<batch_id>.csv"

sale_order_id,customer_name,customer_contact,quantity_received,sale_committed_at
b3...,Acme,ops@acme,12.0000,2026-04-08T14:20:00Z
```

### Edge Cases
* Cross-owner batch → 404.
* Batch with no committed SOs → JSON: `{items: [], total: 0, ...}`. CSV: header row only.
* Voided source SO → row absent from both JSON and CSV (filter is enforced by `v_recall_report`).

## Operation: csv-export-financials-dashboard
Route: `GET /api/v1/financials/dashboard?format=csv`

CSV variant of the dashboard. Emits the `top_products` rows only (totals omitted from CSV — they are a single object, not tabular; clients can read them from the JSON variant). Header row: `product_id,product_name,units_sold,revenue,cogs,profit,margin_pct`. `top` parameter still applies (default 5, capped 50).

## Operation: csv-export-financials-margin
Route: `GET /api/v1/financials/margin?format=csv`

CSV variant of the per-product margin list. Cursor pagination is bypassed when `format=csv` — the response streams every matching row in a single shot (ordered `revenue DESC, product_id DESC`, same as JSON). Header row matches `MarginRowResponse` keys: `product_id,product_name,units_sold,revenue,cogs,profit,margin_pct`.

## Operation: csv-export-movements
Route: `GET /api/v1/movements?format=csv`

CSV variant of the movements audit. Cursor pagination bypassed; full filtered set streamed. Header: `id,owner_id,batch_id,kind,signed_quantity,notes,reference_type,reference_id,created_at`. Filters (`batch_id`, `product_id`, `kind`, `from`, `to`) honored.

## Migration: 0007_indexes.sql
File: `backend/migrations/0007_indexes.sql`

Adds composite indexes that earlier migrations deferred. Each index uses `CREATE INDEX IF NOT EXISTS` so the file is naturally idempotent under `migrate_sql`.

### Indexes added

| Table | Columns | Purpose |
|---|---|---|
| `stock_movements` | `(owner_id, batch_id, created_at DESC)` | `/movements?batch_id=…` audit query and per-batch ledger reads in selectors |
| `sales_orders` | `(owner_id, status, created_at DESC)` | `/sales-orders?status=draft&cursor=…` cursor pagination ordering when status is filtered |

### Already-present indexes (verified, not re-created)

| Table | Index | Source |
|---|---|---|
| `batches` | `batches_owner_product_expiry_idx (owner_id, product_id, expiration_date NULLS LAST, created_at)` — FEFO walk | `0005_inventory.sql` |
| `stock_movements` | `sm_owner_created_idx (owner_id, created_at DESC, id DESC)` — global audit cursor | `0005_inventory.sql` |
| `sales_orders` | `so_owner_created_idx (owner_id, created_at DESC, id DESC)`, `so_owner_status_idx (owner_id, status)`, `so_committed_at_idx (owner_id, committed_at DESC)` | `0007_sales.sql`, `0008_financials.sql` |
| `products` | `(owner_id, sku)` UNIQUE — search lookup | `0003_catalog.sql` |

The `0007_indexes.sql` file documents the verified set inline as a leading comment block, so the migration also serves as the index audit record.

## Lib: csv_export
File: `backend/apps/core/csv_export.py`

Shared streaming-CSV helper used by every `?format=csv` branch.

### Functions
* `stream_csv(filename: str, header: list[str], rows: Iterable[Iterable[Any]]) -> StreamingHttpResponse` — returns a `StreamingHttpResponse` with `Content-Type: text/csv; charset=utf-8` and `Content-Disposition: attachment; filename="<filename>"`. Writes the header row first, then iterates `rows`, encoding each row via `csv.writer` against an `Echo()` pseudo-buffer (Django streaming CSV pattern). RFC 4180 quoting; UTF-8.
* `format_decimal(d: Decimal | None) -> str` — `""` when `None`, else `str(d)` (preserves trailing zeros from `NUMERIC(14,4)`).
* `format_datetime(dt: datetime | None) -> str` — `""` when `None`, else `dt.isoformat()`.
* `format_date(d: date | None) -> str` — `""` when `None`, else `d.isoformat()`.

The helper itself takes no opinions about row shape; each endpoint owns its flattener.

## Function: list_recall_report_for_batch
File: `backend/apps/sales/selectors.py`
Input: `(*, owner_id: int, batch_id: str, limit: int, offset: int) -> dict`
Returns: `{"items": [...], "total": int, "limit": int, "offset": int}`

Read-only selector that calls the existing `select_recall_report_for_batch` query function. Lives in `apps.sales.selectors` because it reads sales tables; the inventory APIView imports it. Module-top imports only.

## Function: BatchRecallReportApi
File: `backend/apps/inventory/apis.py`

GET-only `APIView`. `IsAuthenticated`. Branches on `request.query_params.get("format") == "csv"`:
* JSON path: validate `batch_id` exists for owner (404 otherwise via `batch_by_id` precheck), call `list_recall_report_for_batch`, return `RecallReportResponse`.
* CSV path: same precheck; iterate the full result set (no pagination cap), stream via `csv_export.stream_csv`.

Wire under `apps/inventory/urls.py` as `path("batches/<str:batch_id>/recall-report", ...)`.

## External Dependencies

None. Pure Python `csv` module + `django.http.StreamingHttpResponse`. No new pip packages.

# Plan

Each step ends with green `pytest`, `mypy`, `ruff`, and discipline grep gates. Steps are ordered so each one is independently shippable.

1. **Migration `0007_indexes.sql` + migrate_sql count bump**
   - Why: indexes are non-breaking and unblock EXPLAIN-based tests in later steps; landing them first means CSV branches can be tested against a realistic plan.
   - [ ] Add `backend/migrations/0007_indexes.sql` with `CREATE INDEX IF NOT EXISTS` for `stock_movements (owner_id, batch_id, created_at DESC)` and `sales_orders (owner_id, status, created_at DESC)`. Leading comment block documents the verified-already-present set.
   - [ ] Bump `_EXPECTED_MIGRATIONS` from 8 to 9 in `backend/apps/core/tests/api/test_migrate_sql.py`.
   - [ ] Test (`apps/inventory/tests/query/test_indexes.py`): seed batches/movements for one owner; `EXPLAIN (FORMAT JSON) SELECT … FROM stock_movements WHERE owner_id=%s AND batch_id=%s ORDER BY created_at DESC LIMIT 50` plan tree contains an `Index Scan` (or `Index Only Scan`) on the new `(owner_id, batch_id, created_at DESC)` index.
   - [ ] Test (`apps/sales/tests/query/test_indexes.py`): seed enough draft + committed SOs to defeat seq-scan heuristics (`SET LOCAL enable_seqscan = OFF` is acceptable as a deterministic toggle); `EXPLAIN` for the status-filtered cursor query uses the new `(owner_id, status, created_at DESC)` index.
   - [ ] Test (`apps/inventory/tests/query/test_indexes.py`): existing FEFO walk plan picks `batches_owner_product_expiry_idx` (regression guard for the index documented as already-present).

2. **`apps/core/csv_export.py` streaming helper**
   - Why: every later step depends on it; shipping in isolation means each endpoint diff is small and reviewable.
   - [ ] Add `apps/core/csv_export.py` with `stream_csv`, `format_decimal`, `format_datetime`, `format_date` per the Lib section above.
   - [ ] Test (`apps/core/tests/unit/test_csv_export.py`): header + 2 rows produce the expected wire bytes (header line, two data lines, RFC 4180 quoting on a value containing a comma); `format_decimal(None)`, `format_decimal(Decimal("12.0000"))`, `format_datetime(None)` return the documented strings.
   - [ ] Test: response carries `Content-Type: text/csv; charset=utf-8` and `Content-Disposition: attachment; filename="..."`.

3. **Wire `GET /batches/{id}/recall-report` (JSON only)**
   - Why: ILEX-006 and ILEX-007 both deferred this route; CSV negotiation in step 5 cannot land until the endpoint exists in the URL conf.
   - [ ] Add `list_recall_report_for_batch` selector to `apps/sales/selectors.py` calling the existing `select_recall_report_for_batch` query. Module-top import.
   - [ ] Add `BatchRecallReportApi(APIView)` to `apps/inventory/apis.py`. Pre-check ownership via `batch_by_id` (404 on miss). Returns `RecallReportResponse`.
   - [ ] Register route in `apps/inventory/urls.py` (`batches/<str:batch_id>/recall-report`). Remove the stale "deferred to ILEX-007" comment from the file header.
   - [ ] API test (`apps/inventory/tests/api/test_recall_report.py`): brief-shaped fixture (one committed SO of 100 units from one batch); `GET .../recall-report` returns `{items: [{sale_order_id, customer_name, customer_contact, quantity_received: "100.0000", sale_committed_at}], total: 1, limit: 50, offset: 0}`.
   - [ ] API test: voided SO disappears (commit + void → `items: []`).
   - [ ] API test: cross-owner batch → 404.

4. **CSV export on `/movements`**
   - Why: simplest list shape (all keys are scalar) and exercises the cursor-bypass path; landing first proves the helper integrates with a real APIView.
   - [ ] In `apps/inventory/apis.py::MovementsAuditApi.get`, branch on `format=csv`. CSV path calls a new `stream_movements_for_owner` helper in `apps/inventory/selectors.py` that yields rows from a server-side cursor (no `LIMIT`); JSON path is unchanged.
   - [ ] Header: `id,owner_id,batch_id,kind,signed_quantity,notes,reference_type,reference_id,created_at`. Decimals via `format_decimal`; timestamps via `format_datetime`; nullable text fields via `""`.
   - [ ] API test (`apps/inventory/tests/api/test_movements_csv.py`): seed 3 movements; `GET /movements?format=csv` returns 200, `Content-Type: text/csv; charset=utf-8`, body has 4 lines (header + 3 rows). First line equals header; row count matches the JSON variant called with no cursor + `limit=100`.
   - [ ] API test: decimal preservation — `signed_quantity` of `Decimal("12.0000")` round-trips as `"12.0000"` in the CSV cell, not `"12"`.
   - [ ] API test: filter passthrough — `?batch_id=<id>&format=csv` returns only that batch's rows; row count equals JSON variant with the same filter.

5. **CSV export on `/batches/{id}/recall-report`**
   - Why: shape is identical to `/movements` minus owner_id; reuses the same helper. Ships after the JSON route exists (step 3).
   - [ ] In `BatchRecallReportApi.get`, branch on `format=csv`. CSV path streams every row (no offset/limit cap).
   - [ ] Header: `sale_order_id,customer_name,customer_contact,quantity_received,sale_committed_at`. Filename: `recall-report-<batch_id>.csv`.
   - [ ] API test: brief fixture → CSV body has 2 lines (header + 1 row); decimal `quantity_received` preserved as `"100.0000"`; `sale_committed_at` is ISO-8601.
   - [ ] API test: empty result → header row only (1 line).
   - [ ] API test: cross-owner batch → 404 (CSV path must reuse the same precheck as JSON).

6. **CSV export on `/financials/margin`**
   - Why: exercises the bypass-cursor path on a list endpoint with computed columns (`profit`, `margin_pct`).
   - [ ] In `apps/financials/apis.py::FinancialsMarginListApi.get`, branch on `format=csv`. CSV path calls a new `stream_margin_by_product` selector that yields aggregated per-product rows with no cursor.
   - [ ] Header: `product_id,product_name,units_sold,revenue,cogs,profit,margin_pct`. `margin_pct` empty when `cogs=0`.
   - [ ] API test (`apps/financials/tests/api/test_margin_csv.py`): brief fixture (one committed SO, 100 units @ $10 / $1) → CSV row carries `units_sold=100.0000`, `revenue=1000.0000`, `cogs=100.0000`, `profit=900.0000`, `margin_pct=900.0000`.
   - [ ] API test: row count matches JSON variant called with `limit=100, cursor=null`.
   - [ ] API test: empty range → header row only.

7. **CSV export on `/financials/dashboard`**
   - Why: last endpoint; non-list shape forces an explicit choice (top_products only) and pins the convention in code.
   - [ ] In `FinancialsDashboardApi.get`, branch on `format=csv`. CSV path runs the same selector as JSON but emits `result["top_products"]` only.
   - [ ] Header: `product_id,product_name,units_sold,revenue,cogs,profit,margin_pct` (same as margin endpoint — consistent shape).
   - [ ] Filename: `dashboard-<from>-<to>.csv`.
   - [ ] API test (`apps/financials/tests/api/test_dashboard_csv.py`): brief fixture → CSV body has `header + N=top_products` lines; row matches JSON `top_products[i]` field-by-field.
   - [ ] API test: empty range → header row only.

# Notes

- **No third-party CSV renderer.** The issue scope reads "DRF CSV renderer registered in `DEFAULT_RENDERER_CLASSES`". We deviate: DRF's renderer pipeline buffers the full response before flushing, which defeats the streaming requirement for "large exports" stated in the same scope. Instead, each affected APIView branches on `?format=csv` and returns a `StreamingHttpResponse` directly (built via `apps.core.csv_export.stream_csv`). This bypasses DRF's renderer entirely on the CSV path; the JSON path is unchanged. No new dependency, no `DEFAULT_RENDERER_CLASSES` mutation. OpenAPI declares only `application/json` for these endpoints — clients use the `?format=csv` query param documented in `extend_schema`.
- **Dashboard CSV exports `top_products` only.** The dashboard JSON is `{date_from, date_to, totals: {...}, top_products: [...]}`. CSV cannot represent the nested totals object cleanly; clients that need totals can read the JSON variant. The `top_products` list is the only tabular payload and the one users will paste into a spreadsheet. Filename embeds the date range so the export is self-describing.
- **Cursor pagination is bypassed on CSV paths.** The whole point of CSV export is "give me everything"; emitting a paginated CSV would force the client to iterate cursors and concatenate files. We stream with no `LIMIT`, leaning on `StreamingHttpResponse` to keep memory bounded. If a future incident reveals slow streaming, add a hard cap (e.g., 100k rows) with a 422 — not in v1.
- **Recall-report endpoint deferred from two prior issues.** ILEX-006 deferred it citing "requires sales tables" and ILEX-007 silently dropped it. The query function (`select_recall_report_for_batch`) and serializers (`RecallReportItemResponse`, `RecallReportResponse`) already exist from those issues. This issue only adds the selector + APIView + URL row. The `inventory/urls.py` header comment "Recall-report endpoint is deferred to ILEX-007" is removed in step 3.
- **0007_indexes.sql is small — most indexes already shipped inline.** Earlier issues added indexes alongside their tables (FEFO in 0005, audit-by-owner-and-time in 0005, status-only and date-only on SOs in 0007/0008). The two indexes that did *not* fit any earlier per-table migration are the composite `(owner_id, batch_id, created_at DESC)` (used only when filtering audit by `batch_id`) and `(owner_id, status, created_at DESC)` (used only on status-filtered SO list). They land here so the index inventory has a single audit point.
- **EXPLAIN tests use `enable_seqscan = OFF` only when needed.** Postgres's planner picks index scans only when the cardinality justifies it. On tiny test fixtures it often prefers seq scan. Acceptable: gate the assertion on `SET LOCAL enable_seqscan = OFF` for the test transaction so the index choice is deterministic. The intent is "the index is reachable", not "the planner prefers it on 5 rows".
- **No CSV import in this issue.** CSV import for products already shipped in ILEX-004 (`POST /products/import`). PO/manual-stock CSV import is explicitly deferred per SPEC §3.7.
- **Owner scope on CSV path.** Every CSV branch must pass through the same selector that the JSON branch uses, so the `@scoped` query function applies the `owner_id` filter. No raw SQL in the API layer; no shortcut path for CSV.
- **Filename convention.** `<resource>-<scope>.csv` — `movements-<owner_id>.csv`, `recall-report-<batch_id>.csv`, `margin-<from>-<to>.csv`, `dashboard-<from>-<to>.csv`. Owner-scoped filenames embed the owner id rather than user-typed names (avoids needing to escape).

# Journal

- 2026-05-08 18:30 [executor] — Step 7 complete: FinancialsDashboardApi.get branches on format=csv; emits top_products rows only with filename dashboard-<from>-<to>.csv; 2 tests green (brief fixture field-by-field vs JSON, empty range header-only). Full suite: 465/465 green (33 new tests added vs 432 baseline).
- 2026-05-08 18:15 [executor] — Step 6 complete: stream_margin_by_product selector added to apps/financials/selectors.py; FinancialsMarginListApi.get branches on format=csv; 3 new tests green (brief fixture with exact values, row count == JSON, empty range header-only).
- 2026-05-08 18:00 [executor] — Step 5 complete: stream_recall_report_for_batch query + selector added; BatchRecallReportApi.get branches on format=csv; 3 tests green (brief fixture decimal/ISO-8601 check, empty result header-only, cross-owner 404).
- 2026-05-08 17:45 [executor] — Step 4 complete: stream_movements query added to queries/movements.py; stream_movements_for_owner selector added; MovementsAuditApi.get branches on format=csv and returns StreamingHttpResponse; REST_FRAMEWORK["URL_FORMAT_OVERRIDE"]=None set in settings/base.py (disables DRF format suffix interception so ?format=csv reaches view handlers); 5 new CSV tests green (header+rows, row count == JSON, decimal preservation, filter passthrough, 401).
- 2026-05-08 17:30 [executor] — Step 3 complete: list_recall_report_for_batch added to apps/sales/selectors.py; BatchRecallReportApi added to apps/inventory/apis.py; route wired in urls.py; "deferred" comment removed; RecallReportResponse extended with limit+offset fields; 4 API tests green (brief fixture, voided SO excluded, cross-owner 404, unauthenticated 401).
- 2026-05-08 17:15 [executor] — Step 2 complete: backend/apps/core/csv_export.py added (stream_csv, format_decimal, format_datetime, format_date); 13 unit tests in apps/core/tests/unit/test_csv_export.py all green; ruff clean.
- 2026-05-08 17:00 [executor] — Step 1 complete: backend/migrations/0009_indexes.sql added (sm_owner_batch_created_idx, so_owner_status_created_idx); _EXPECTED_MIGRATIONS bumped to 9; EXPLAIN tests green (inventory/tests/query/test_indexes.py × 2, sales/tests/query/test_indexes.py × 1, migrate_sql count test × 1). All 4 new tests passing.
