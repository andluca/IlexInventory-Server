---
id: ILEX-007
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-006]
---

# ILEX-007 Implement sales app (FEFO commit, allocations, void)

Full vertical for sales orders: schema for SOs, lines, immutable allocations; FEFO walk on commit (consumes inventory's `list_eligible_for_fefo`); SO void via `sale_void` reversal movements. Commit accepts an optional explicit allocations list (BE-D11 admin override). Allocations are immutable post-commit (BE-D8); voids write reversal movements without touching original allocations. Adds `v_recall_report` view + the `GET /batches/{id}/recall-report` endpoint deferred from ILEX-006.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.5, §3.4 (recall report). BE-D4, BE-D6, BE-D8, BE-D9, BE-D10, BE-D11. Flows F7, F8, F11.

## Operation: list-sales-orders
Route: `GET /api/v1/sales-orders`

List sales orders for the authenticated owner, cursor-paginated.

### Preconditions
* User is authenticated (DRF SessionAuthentication).
* `0007_sales.sql` is applied.

### Primary Use Case

#### Input
```
GET /api/v1/sales-orders?status=committed&voided=false&search=acme&from=2026-01-01&to=2026-05-08&cursor=...&limit=50
```

#### Workflow
* API reads `request.user.id`, query params.
* Selector `list_sales_orders` runs cursor-paginated query with `voided_at IS NULL` when `voided=false`, ILIKE on `customer_name` when `search` set.
* Returns `{items, next_cursor}` with each item including lines + allocations (allocations only when `status='committed'`).

#### Output
```json
{ "items": [{"id": "...", "customer_name": "...", "status": "committed", "voided_at": null, "lines": [...], "allocations": [...]}], "next_cursor": "..." }
```

## Operation: create-sales-order
Route: `POST /api/v1/sales-orders`

Create a draft SO with one or more lines.

### Preconditions
* User is authenticated.
* Every `lines[].product_id` belongs to the owner (D4 composite FK).

### Primary Use Case

#### Input
```json
{ "customer_name": "Acme Corp", "customer_contact": "ops@acme.test",
  "lines": [{"product_id": "...", "quantity": "100.0000", "sell_price": "10.0000"}] }
```

#### Workflow
* Validate non-empty `customer_name`, non-empty `lines`, positive `quantity` and `sell_price`.
* INSERT `sales_orders (status='draft')` + N `sales_order_lines` in one tx.
* Return draft SO + lines (no allocations yet).

#### Output
```json
{ "id": "...", "status": "draft", "customer_name": "Acme Corp", "lines": [...], "allocations": [] }
```

### Error Flows
* Empty `lines` → 400 `ValidationError`.
* Cross-owner `product_id` → 404 `ProductNotFound`.
* `quantity <= 0` or `sell_price <= 0` → 400.

## Operation: get-sales-order
Route: `GET /api/v1/sales-orders/{id}`

Detail view with lines + allocations (post-commit) + `voided_at`.

### Workflow
* `selectors.sales_order_by_id`; cross-owner returns None → 404.

## Operation: update-sales-order
Route: `PATCH /api/v1/sales-orders/{id}`

Replace-style edit on a draft. 409 once committed (D6).

### Workflow
* Lock SO header. If `status != 'draft'` → 409 `SalesOrderNotDraft`.
* If `lines` provided: DELETE all lines, INSERT replacement set.
* Optional `customer_name`/`customer_contact` partial update.

## Operation: delete-sales-order
Route: `DELETE /api/v1/sales-orders/{id}`

Hard-delete a draft. 409 post-commit.

## Operation: preview-sales-order
Route: `POST /api/v1/sales-orders/{id}/preview`

FEFO dry-run: returns proposed allocations without committing.

### Workflow
* Open tx, open `SAVEPOINT preview`.
* Run the same FEFO walk used by commit (no inserts).
* `ROLLBACK TO preview` and return proposed allocations.

#### Output
```json
{ "allocations": [{"line_id": "...", "batch_id": "...", "batch_code": "B-001", "quantity": "60.0000", "unit_cost": "1.0000", "expiration_date": "2026-08-01"}] }
```

### Error Flow
* Insufficient on-hand → 422 with `{ "error": "InsufficientStock", "shortfall": {"product_id": "...", "required": "100", "available": "60"} }`.

## Operation: commit-sales-order
Route: `POST /api/v1/sales-orders/{id}/commit`

Terminal transition: writes allocations + sale movements; immutable. `Idempotency-Key` header required.

### Preconditions
* SO is in `draft` for this owner.
* `Idempotency-Key` header present.

### Primary Use Case (FEFO)

#### Input
```
POST /api/v1/sales-orders/{id}/commit
Idempotency-Key: <uuid>
Body: {} or omitted
```

#### Workflow
* Lock SO header `FOR UPDATE`. If not `draft` → 409.
* Per line: call `list_eligible_for_fefo(owner_id, product_id)` (locks eligible batches `FOR UPDATE OF b`); greedy-allocate from earliest-expiring; rollback + 422 with shortfall on insufficient stock.
* Per (line, batch) pair: INSERT `sale_allocations` with `unit_cost = batch.unit_cost`.
* Per allocation: INSERT `stock_movements` with `kind='sale'`, `signed_quantity = -allocated_qty`, `reference_type='sales_order_line'`, `reference_id=line.id`.
* UPDATE `sales_orders SET status='committed', committed_at=NOW()`.

### Admin-Override Use Case (D11)

#### Input
```json
{ "allocations": [{"line_id": "...", "batch_id": "...", "quantity": "60.0000"}, ...] }
```

#### Workflow
* Validate every batch exists for owner, `batch.product_id == line.product_id`, batch is not recalled, batch is not expired, batch on-hand ≥ requested per-line cumulative; per-line `SUM(quantity)` equals `line.quantity`.
* Skip FEFO; insert allocations + movements directly.

#### Output (both cases)
```json
{ "id": "...", "status": "committed", "committed_at": "...",
  "lines": [...],
  "allocations": [{"id": "...", "line_id": "...", "batch_id": "...", "quantity": "...", "unit_cost": "..."}] }
```

### Error Flows
* Missing `Idempotency-Key` → 400.
* SO not in draft → 409 `SalesOrderNotDraft`.
* Insufficient on-hand (FEFO) → 422 with shortfall body.
* Explicit allocation references ineligible batch (recalled / expired / cross-product / cross-owner / over-on-hand) → 422 `InvalidAllocation`.
* Per-line allocation sum mismatch → 422.

## Operation: void-sales-order
Route: `POST /api/v1/sales-orders/{id}/void`

Reversal movements + `voided_at`. Allocations untouched. Idempotent.

### Workflow
* Lock SO header. If `status != 'committed'` → 409 `SalesOrderNotCommitted`.
* If `voided_at IS NOT NULL` → return current state (idempotent, no writes).
* For each existing `sale_allocation`: INSERT `stock_movements` with `kind='sale_void'`, `signed_quantity = +allocation.quantity`, `reference_type='sale_allocation'`, `reference_id=allocation.id`.
* UPDATE `sales_orders SET voided_at=NOW()`.

## Operation: get-recall-report
Route: `GET /api/v1/batches/{id}/recall-report` (lives in `apps.inventory.apis`)

Customers who received units from this batch via committed, non-voided SOs (R7, F11). Offset pagination. CSV export deferred to ILEX-009.

### Workflow
* Validate batch exists for owner.
* Selector `recall_report_for_batch` reads `v_recall_report` filtered by `batch_id` and `voided_at IS NULL`.

#### Output
```json
{ "items": [{"sale_order_id": "...", "customer_name": "...", "customer_contact": "...", "quantity_received": "60.0000", "sale_committed_at": "..."}], "total": 3 }
```

## Function: commit_sales_order
File: `backend/apps/sales/services.py`
Input: `(*, owner_id: int, so_id: str, allocations: list[ExplicitAllocation] | None = None) -> SalesOrderRow`

Commit a draft SO atomically — FEFO walk by default, explicit allocations on admin override.

### Implementation
* Open one psycopg connection / one transaction.
* `SELECT ... FOR UPDATE` SO header; reject non-draft (409).
* Load lines for the SO.
* If `allocations is None`: per line, call `list_eligible_for_fefo` (locks rows), greedy-walk earliest-expiring; raise `InsufficientStock` (422) on shortfall.
* If `allocations` provided: validate ownership + product match + per-line sum + batch eligibility; raise `InvalidAllocation` (422) on any failure.
* INSERT `sale_allocations` rows (unit_cost copied from batch).
* INSERT one `stock_movements` row per allocation (`kind='sale'`, negative qty).
* UPDATE SO to `committed`.
* Commit and return assembled row.

## Function: void_sales_order
File: `backend/apps/sales/services.py`
Input: `(*, owner_id: int, so_id: str) -> SalesOrderRow`

Void a committed SO; idempotent if already voided.

### Implementation
* Open tx; lock SO header.
* Reject non-committed (409).
* If `voided_at` already set: rollback + return current.
* For each `sale_allocation`: insert `sale_void` movement (positive qty).
* UPDATE `voided_at = NOW()`.

## Function: preview_so_allocations
File: `backend/apps/sales/services.py`
Input: `(*, owner_id: int, so_id: str) -> list[ProposedAllocation]`

Run FEFO inside a savepoint and roll back. No mutations persist.

### Implementation
* Open tx; `SAVEPOINT preview`.
* For each line: walk `list_eligible_for_fefo`, build proposed allocations.
* `ROLLBACK TO SAVEPOINT preview`.
* Return proposed allocations (or raise `InsufficientStock` 422).

## Function: create_sales_order_draft / update_sales_order_draft / delete_sales_order_draft
File: `backend/apps/sales/services.py`

Mirror `apps.procurement.services` patterns: `_load_so_with_lines`, replace-style line edits, owner-scoped via composite FKs, raise typed errors.

## Utils: queries
File: `backend/apps/sales/queries/`

Module-per-aggregate query layer. Every owner-scoped function is `@scoped`.

### Files
* `sales_orders.py`: `insert_sales_order`, `select_sales_order_by_id`, `select_sales_order_for_update`, `update_sales_order_header`, `mark_sales_order_committed`, `set_sales_order_voided`, `delete_sales_order`, `list_sales_orders` (cursor-paginated).
* `sales_order_lines.py`: `insert_sales_order_line`, `select_lines_for_sales_order`, `delete_lines_for_sales_order`.
* `sale_allocations.py`: `insert_sale_allocation`, `select_allocations_for_sales_order`.
* `recall_report.py`: `select_recall_report_for_batch` (reads `v_recall_report`, filters `voided_at IS NULL`).

## Lib: shared helpers (no new lib package)

Reuse existing infrastructure unchanged:
* `apps.core.owner_scope.scoped` — query decoration.
* `apps.core.idempotency.idempotent` — `@idempotent("sales_orders.commit")` and `@idempotent("sales_orders.void")`.
* `apps.core.pagination.{encode_cursor,decode_cursor}` — for SO list.
* `apps.core.errors.{DomainError,to_response}` — error mapping.
* `apps.inventory.queries.batches.list_eligible_for_fefo` — FEFO walk source of truth.

## External Dependencies

### apps.inventory
Used for: FEFO eligibility (`list_eligible_for_fefo`), batch ownership/eligibility checks for explicit-allocation override.
* Sales imports the query function at module top (no function-local imports).
* Composite FK `(batch_id, owner_id) → batches(id, owner_id)` on `sale_allocations` enforces the cross-table ownership invariant.

### Postgres view `v_recall_report`
Defined in `0007_sales.sql` (CREATE OR REPLACE). Joins `sale_allocations + sales_orders + sales_order_lines + batches`. Filtered by caller on `batch_id` and `voided_at IS NULL`.

# Plan

Each step is independently shippable: each ends with a green `pytest`, `mypy`, `ruff`, and discipline grep gates.

1. **Migration `0007_sales.sql` + schema constraint tests** — DONE
   - Why: schema is the foundation every later step writes against; constraint tests pin behavior the service layer relies on.
   - [x] Add `0007_sales.sql`: `sales_orders` (`status`, `committed_at`, `voided_at`, customer text fields per D10, composite UNIQUE `(id, owner_id)`, status CHECK `draft|committed`, committed/voided timestamp consistency CHECKs).
   - [x] Same file: `sales_order_lines` (composite FKs to `sales_orders` and `products` per D4, `quantity > 0`, `sell_price >= 0`, composite UNIQUE `(id, owner_id)`).
   - [x] Same file: `sale_allocations` (composite FKs to `sales_order_lines` and `batches`, `allocated_quantity > 0`, `unit_cost >= 0` copied from batch).
   - [x] Same file: `CREATE OR REPLACE VIEW v_recall_report` joining allocations + SOs + lines + batches; only emit rows where `so.voided_at IS NULL` and `so.status='committed'`.
   - [x] Tests under `backend/apps/sales/tests/query/test_schema_constraints.py`: composite FK rejects cross-owner inserts; CHECK rejects non-positive quantity; status CHECK rejects unknown values.
   - [x] Tests: `v_recall_report` returns expected join shape on a hand-seeded fixture.

2. **Sales draft CRUD vertical (no commit/void yet)** — DONE
   - Why: lets the FE wire SO drafts before the heavier commit logic lands; mirrors the procurement pattern.
   - [x] `apps/sales/__init__.py`, `errors.py` (`SalesOrderNotFound`, `SalesOrderNotDraft`, `SalesOrderNotCommitted`, `ProductNotFound`, `InsufficientStock`, `InvalidAllocation`, `ValidationError`).
   - [x] `apps/sales/types.py`: `NewSaleLine`, `SalesOrderRow`, `ExplicitAllocation`, `ProposedAllocation`, `RecallReportRow`.
   - [x] `apps/sales/queries/sales_orders.py` + `sales_order_lines.py` (insert/select/update/delete; replace-style line edit).
   - [x] `apps/sales/services.py`: `create_sales_order_draft`, `update_sales_order_draft`, `delete_sales_order_draft`, `list_sales_orders_for_owner`.
   - [x] `apps/sales/selectors.py`: `sales_order_by_id`, `list_sales_orders` (cursor pagination).
   - [x] `apps/sales/serializers.py`: `SalesOrderCreateRequest`, `SalesOrderUpdateRequest`, `SalesOrderResponse`, `SalesOrderListResponse`.
   - [x] `apps/sales/apis.py`: `SalesOrderListApi` (GET/POST), `SalesOrderDetailApi` (GET/PATCH/DELETE).
   - [x] `apps/sales/urls.py`; wire into `backend/urls.py`.
   - [x] Service tests: draft create + cross-owner product 404; PATCH replaces lines; DELETE rejects non-draft; list cursor pagination ordering.
   - [x] API tests: 400 on empty lines + non-positive qty/price.

3. **FEFO commit + preview (the heart of the issue)** — DONE
   - Why: this is the differentiator from the brief; preview reuses the commit walk, so they ship together.
   - [x] `apps/sales/queries/sale_allocations.py`: `insert_sale_allocation`, `select_allocations_for_sales_order`.
   - [x] `apps/sales/services.py`: `commit_sales_order(owner_id, so_id, allocations=None)`. Module-top imports `list_eligible_for_fefo` and `insert_movement`.
   - [x] `apps/sales/services.py`: `preview_so_allocations(owner_id, so_id)` using `SAVEPOINT preview` + `ROLLBACK TO`.
   - [x] `apps/sales/apis.py`: `SalesOrderPreviewApi` (POST), `SalesOrderCommitApi` (POST, `@idempotent("sales_orders.commit")`).
   - [x] Wire URLs.
   - [x] Service test: FEFO commit on the brief example — receive 100 units @ $1, sell 100 @ $10, assert 1 allocation, COGS line `unit_cost=1.0000`, total movement signed_quantity=-100, status flips to `committed`.
   - [x] Service test: FEFO walks earliest-expiring first (two batches, one expiring sooner — assert it's drained first).
   - [x] Service test: expired and recalled batches invisible to FEFO (raises `InsufficientStock` if they were the only inventory).
   - [x] Service test: insufficient on-hand → 422-mappable error with shortfall payload; no allocations or movements written.
   - [x] Service test: explicit `allocations` body skips FEFO; per-line sum mismatch raises `InvalidAllocation`.
   - [x] Service test: explicit allocation referencing recalled batch raises `InvalidAllocation`.
   - [x] API test: commit happy path — full brief example end-to-end ($1,000 revenue line, $100 COGS via allocations, $900 gross — verified via `v_stock_by_batch` (on-hand = 0) and `sale_allocations.unit_cost`).
   - [x] API test: missing `Idempotency-Key` → 400; duplicate key → cached response.
   - [x] API test: preview returns proposed allocations and writes nothing (verify `v_stock_by_batch` unchanged).

4. **Void + recall report endpoint** — REMAINING
   - Why: closes F8; unblocks the recall report deferred from ILEX-006; voided SOs must disappear from `v_recall_report` (D8). Services + sales-side query already exist; what remains is the inventory-side route + the void/recall behavioral tests.
   - [x] `apps/sales/services.py`: `void_sales_order(owner_id, so_id)`; idempotent on already-voided.
   - [x] `apps/sales/apis.py`: `SalesOrderVoidApi` (POST, `@idempotent("sales_orders.void")`).
   - [x] `apps/sales/queries/recall_report.py`: `select_recall_report_for_batch` reading `v_recall_report`.
   - [ ] `apps/inventory/selectors.py`: add `recall_report_for_batch(owner_id, batch_id, limit, offset)` — calls `apps.sales.queries.recall_report.select_recall_report_for_batch` (module-top import). Validates batch ownership first; returns `(items, total)` or `None` on miss.
   - [ ] `apps/inventory/serializers.py`: `RecallReportItem` + `RecallReportResponse` (`items[]`, `total`).
   - [ ] `apps/inventory/apis.py`: `BatchRecallReportApi` (GET) — reads `limit`/`offset` query params; 404 on cross-owner batch.
   - [ ] `apps/inventory/urls.py`: wire `batches/<str:batch_id>/recall-report`.
   - [ ] Service test (`tests/service/test_void.py`): void writes one `sale_void` movement per allocation with positive qty; allocations row count unchanged; `v_stock_by_batch.on_hand` returns to pre-commit value.
   - [ ] Service test: void on already-voided returns same SO with no extra `stock_movements` rows (idempotent at the DB layer, in addition to the `@idempotent` cache).
   - [ ] Service test: voided SO disappears from `v_recall_report` (commit → recall query returns the customer row → void → recall query returns empty).
   - [ ] API test (`apps/inventory/tests/api/test_batches_recall_report.py`): commit an SO that drew from batch X → `GET /batches/{X}/recall-report` returns the customer row + `total=1`; cross-owner batch returns 404; voided SO is excluded from the response.
   - [ ] API test: void endpoint — happy path returns `voided_at` set; second call with same `Idempotency-Key` returns cached response; calling on a draft SO returns 409 `SalesOrderNotCommitted`.

# Notes

- **Migration numbering diverges from `docs/specs/SPEC.md`.** SPEC §2.2 lists `0005_sales.sql` + `0006_views.sql`, but ILEX-006 already shipped `0005_inventory.sql` and `0006_views.sql`. New file is `0007_sales.sql`; `v_recall_report` lives in that same file (CREATE OR REPLACE — idempotent). Update SPEC §2.2 in a docs-only follow-up.
- **D8 (immutability):** `sale_allocations` rows are never UPDATEd or DELETEd. Voids only append to `stock_movements`. Append-only enforcement on `stock_movements` already in place via the trigger from ILEX-006.
- **D11 (admin override):** admin override goes through the same commit endpoint with an `allocations` body — no separate "force commit" route. Validation is strict; an override that picks a recalled batch fails with `InvalidAllocation`.
- **Idempotency on void:** void is naturally idempotent (D8), but the `@idempotent` decorator is still applied for client uniformity (SPEC §2.4).
- **Customer fields are text only** (D10). No `customers` table.
- **Recall report ownership:** the route lives under `/batches/...` in `apps.inventory.apis`, but the view + query function live in `apps.sales` (sales owns the `v_recall_report` shape). `apps.inventory.selectors` calls into the sales query. This is the only inventory→sales import in the codebase; document it at the call site.
- **Cursor pagination on `/sales-orders`:** mirror `apps.inventory.queries.movements.list_movements` — order `created_at DESC, id DESC`; opaque base64 cursor.
- **Test data scaffold:** factor a small helper in `apps/sales/tests/conftest.py` that seeds (owner, product, PO, received batch with N units) — every commit/void test starts from this state. Behavioral, no `_private` imports.
- **Brief example as anchor test:** SPEC §1 worked example — receive 100 @ $1, sell 100 @ $10 → revenue $1,000, COGS $100, profit $900. The commit API test asserts these three numbers materialize (revenue from `sales_order_lines.sell_price * quantity`, COGS from `SUM(sale_allocations.unit_cost * allocated_quantity)`).

# Journal

- 2026-05-08 14:15 [executor] — Step 1 complete: `0007_sales.sql` (sales_orders + sales_order_lines + sale_allocations + v_recall_report), 13 schema constraint + view tests green; migrate_sql count updated to 7; 376/376 total green; ruff/no-ORM/no-SQL-in-views gates clean.
- 2026-05-08 14:50 [executor] — Step 2 complete: draft CRUD vertical — errors.py, types.py, 4 query modules, services.py (draft CRUD + commit/void/preview stubs), selectors.py, serializers.py, apis.py, urls.py wired; 23 service+API tests; 399/399 total green; all discipline gates clean.
