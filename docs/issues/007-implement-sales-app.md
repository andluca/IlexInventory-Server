# 007 — Implement sales app (FEFO commit, allocations, void)

## Overview

Full vertical for SOs: schema for SOs, lines, and immutable allocations; FEFO walk on commit (consumes inventory's eligibility query); SO void via reversal movements. Commit accepts an optional explicit allocations list (BE-D11 admin override). Allocations are immutable post-commit (BE-D8); voids write `sale_void` reversal movements without touching original allocations.

**Scope:**
- `backend/migrations/0005_sales.sql` — `sales_orders` (status `draft|committed`, `voided_at`, customer text fields per BE-D10, `committed_at`), `sales_order_lines` (product FK, quantity, sell_price), `sale_allocations` (line FK, batch FK with composite `(batch_id, owner_id)` per BE-D4, allocated_quantity, unit_cost copied from batch); CHECK on stock_movements adds `kind='sale_void'` per BE-D8
- `apps/sales/` full app structure
- `commit_sales_order(so_id, allocations=None)` service:
  - With explicit allocations: validate ownership + product matches + per-line quantity sum; skip FEFO
  - Without: FEFO walk per line (locks eligible batches with `FOR UPDATE OF b`, greedy-allocate from earliest-expiring); rollback + 422 with shortfall on insufficient stock
  - Atomic transaction: insert allocations + sale movements + update status
- `void_sales_order(so_id)` service: insert `sale_void` reversal movements per allocation, set `voided_at`; idempotent if already voided
- `preview_so_allocations(so_id)` selector: runs the FEFO walk in a savepoint that rolls back; returns proposed allocations for FE preview UI
- 8 endpoints listed below
- Idempotency-Key required on commit; double-commit returns cached body
- Tests at all four layers:
  - Service: FEFO walk respects expiration order; expired/recalled batches invisible (Issue 006's fixtures); explicit allocations override FEFO; insufficient stock rollback; void writes correct reversals; voided SO disappears from `v_recall_report`
  - API: commit happy path matches the brief example end-to-end ($1,000 revenue, $100 COGS, $900 profit)

**Endpoints:**
- GET `/sales-orders`, POST `/sales-orders` (cursor pagination)
- GET `/sales-orders/{id}`, PATCH `/sales-orders/{id}`, DELETE `/sales-orders/{id}`
- POST `/sales-orders/{id}/preview`
- POST `/sales-orders/{id}/commit`
- POST `/sales-orders/{id}/void`

**Reference:** SPEC §3.5. BE-D6, BE-D8, BE-D9, BE-D11. Flows F7, F8.

**Depends on:** 006 (allocations reference batches; FEFO uses inventory query).
