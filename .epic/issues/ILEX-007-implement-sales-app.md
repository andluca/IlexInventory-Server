---
id: ILEX-007
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-006]
---

# ILEX-007 Implement sales app (FEFO commit, allocations, void)

Full vertical for SOs: schema for SOs, lines, and immutable allocations; FEFO walk on commit (consumes inventory's eligibility query); SO void via reversal movements. Commit accepts an optional explicit allocations list (BE-D11 admin override). Allocations are immutable post-commit (BE-D8); voids write `sale_void` reversal movements without touching original allocations. Also adds `v_recall_report` view + the recall report endpoint that ILEX-006 deferred.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.5. BE-D6, BE-D8, BE-D9, BE-D11. Flows F7, F8.

## Scope

- `backend/migrations/0005_sales.sql` — `sales_orders` (status `draft|committed`, `voided_at`, customer text fields per BE-D10, `committed_at`), `sales_order_lines` (product FK, quantity, sell_price), `sale_allocations` (line FK, batch FK with composite `(batch_id, owner_id)` per BE-D4, allocated_quantity, unit_cost copied from batch)
- `backend/migrations/0006_views.sql` extension: `v_recall_report` (joins `sale_allocations` + `sales_orders` + `sales_order_lines` + `batches`; filters `voided_at IS NULL` per BE-D8)
- `apps/sales/` full app structure
- `commit_sales_order(so_id, allocations=None)` service:
  - With explicit allocations: validate ownership + product matches + per-line quantity sum; skip FEFO
  - Without: FEFO walk per line (locks eligible batches with `FOR UPDATE OF b`, greedy-allocate from earliest-expiring); rollback + 422 with shortfall on insufficient stock
  - Atomic: insert allocations + sale movements + update status
- `void_sales_order(so_id)` service: insert `sale_void` reversal movements per allocation, set `voided_at`; idempotent if already voided
- `preview_so_allocations(so_id)` selector: runs FEFO walk in a savepoint that rolls back; returns proposed allocations for FE preview UI
- Idempotency-Key required on commit
- Add `GET /batches/{id}/recall-report` endpoint (lives in `apps/inventory/apis.py`; selector reads `v_recall_report`)

## Endpoints

| Method | Route | Realizes | Description |
|---|---|---|---|
| GET | `/sales-orders` | R4 | List; cursor pagination |
| POST | `/sales-orders` | F7 | Create draft |
| GET | `/sales-orders/{id}` | R4 | Detail (lines + post-commit allocations + voided_at) |
| PATCH | `/sales-orders/{id}` | F7 | Edit draft (replace-style). 409 post-commit |
| DELETE | `/sales-orders/{id}` | F7 | Delete draft. 409 post-commit |
| POST | `/sales-orders/{id}/preview` | F7 | FEFO dry-run; returns proposed allocations |
| POST | `/sales-orders/{id}/commit` | F7 | Terminal: FEFO walk + allocations + movements. Idempotency-Key required. Body may include explicit allocations (BE-D11) |
| POST | `/sales-orders/{id}/void` | F8 | Reversal movements + `voided_at`. Allocations remain. Idempotent |
| GET | `/batches/{id}/recall-report` | R7, F11 | (Lives in `apps/inventory`) Customers who received units via committed, non-voided SOs. CSV export support added in ILEX-009 |

## Tests

- Service: FEFO walk respects expiration order; expired/recalled batches invisible; explicit allocations override FEFO; insufficient stock rollback; void writes correct reversals; voided SO disappears from `v_recall_report`
- API: commit happy path matches the brief example end-to-end ($1,000 revenue, $100 COGS, $900 profit); recall report excludes voided SOs

## Dependencies

1. ILEX-006 (allocations reference batches; FEFO uses inventory query; `v_recall_report` joins sales + inventory tables)
