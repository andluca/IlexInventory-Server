# 006 — Implement inventory app (batches, movements, recall)

## Overview

The heaviest issue. Full vertical for inventory: schema for `batches` and the append-only `stock_movements` ledger, FEFO eligibility query, manual batch creation, movement recording (adjust + write-off), recall workflow with audit movements, recall report, batch metadata correction, and the cross-cutting movements audit endpoint. Schema enforces append-only via trigger; views power FEFO and recall reads.

**Scope:**
- `backend/migrations/0004_inventory.sql`:
  - `batches` (UUIDv7 PK, `owner_id`, `product_id`, `purchase_order_line_id` nullable per BE-D2, `batch_code`, `expiration_date` nullable, `unit_cost`, `is_recalled`, `recall_reason`, `recalled_at`, `archived_at`); UNIQUE `(owner_id, product_id, batch_code)`; composite FK to products and PO lines
  - `stock_movements` (kind enum, signed_quantity, notes, reference_type, reference_id; CHECK constraints per kind binding sign and qty=0 rules per BE-D1, BE-D3, BE-D7); composite FK to batches
  - **Append-only TRIGGER** on `stock_movements`: forbid UPDATE/DELETE
- `backend/migrations/0006_views.sql` (inventory portion): `v_stock_by_batch` (`SUM(signed_quantity)` per batch), `v_recall_report` (joins `stock_movements` `kind='sale'` + sale_allocations + sales_orders, filters `voided_at IS NULL`), `v_expiring_soon`
- `apps/inventory/` full app structure
- FEFO eligibility query in `apps/inventory/queries/batches.py::list_eligible_for_fefo(owner_id, product_id)` — used by Sales (Issue 007); ORDER BY expiration ASC NULLS LAST, created_at ASC; `FOR UPDATE OF b`
- 9 endpoints listed below
- Tests at all four layers:
  - Schema: append-only trigger rejects UPDATE/DELETE; CHECK constraints reject invalid kind/sign combos
  - Query: FEFO eligibility ordering with NULLs last; recall_report excludes voided SOs
  - Service: recall idempotent on already-recalled; PATCH metadata writes audit movement; write-off rejects negative on-hand
  - API: 9 endpoint integration tests

**Endpoints:**
- GET `/batches`, GET `/batches/{id}`
- POST `/batches` (manual entry)
- PATCH `/batches/{id}` (metadata correction — F12)
- POST `/batches/{id}/movements` (adjust, write_off)
- POST `/batches/{id}/recall`, POST `/batches/{id}/un-recall`
- GET `/batches/{id}/recall-report`
- GET `/movements` (cross-cutting audit; cursor pagination)

**Reference:** SPEC §3.4. BE-D1, BE-D2, BE-D3, BE-D7. Flows F4, F5, F6, F9, F10, F12.

**Depends on:** 005 (batches reference PO lines for procurement-sourced batches).
