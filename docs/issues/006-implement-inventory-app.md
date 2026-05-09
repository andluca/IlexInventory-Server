> **Status:** ✅ Done — shipped in [`9188d58`](../../commit/9188d58) as `feat(inventory): batches/movements/recall vertical + 0005_inventory + 0006_views (ILEX-006)`.

# ILEX-006 Implement inventory app (batches, movements, recall)

The heaviest issue. Full vertical for inventory: schema for `batches` and the append-only `stock_movements` ledger, FEFO eligibility query, manual batch creation, movement recording (adjust + write-off), recall workflow with audit movements, recall report stub, batch metadata correction, and the cross-cutting movements audit endpoint. Schema enforces append-only via trigger; views power FEFO and recall reads.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.4. BE-D1, BE-D2, BE-D3, BE-D7. Flows F4, F5, F6, F9, F10, F12.

## Scope

- `backend/migrations/0004_inventory.sql`:
  - `batches` (UUIDv7 PK, `owner_id`, `product_id`, `purchase_order_line_id` nullable per BE-D2, `batch_code`, `expiration_date` nullable, `unit_cost`, `is_recalled`, `recall_reason`, `recalled_at`, `archived_at`); UNIQUE `(owner_id, product_id, batch_code)`; composite FK to products and PO lines
  - `stock_movements` (kind enum, `signed_quantity`, `notes`, `reference_type`, `reference_id`; CHECK constraints per kind binding sign and qty=0 rules per BE-D1, BE-D3, BE-D7); composite FK to batches
  - **Append-only TRIGGER** on `stock_movements`: forbid UPDATE/DELETE
- `backend/migrations/0006_views.sql` (inventory portion): `v_stock_by_batch` (`SUM(signed_quantity)` per batch), `v_expiring_soon`. (`v_recall_report` joins sales tables — added in ILEX-007.)
- `apps/inventory/` full app structure
- FEFO eligibility query in `apps/inventory/queries/batches.py::list_eligible_for_fefo(owner_id, product_id)` — used by Sales (ILEX-007); ORDER BY expiration ASC NULLS LAST, created_at ASC; `FOR UPDATE OF b`

## Endpoints

| Method | Route | Realizes | Description |
|---|---|---|---|
| GET | `/batches` | R1, R2 | List; offset; filter by product, recall status, `expiring_within={N}` |
| GET | `/batches/{id}` | R1, R6 | Detail (on-hand, recall flag, expiration, source PO line) |
| POST | `/batches` | F4 | Manual batch + initial receipt movement (NULL PO-line FK). Idempotency-Key required |
| PATCH | `/batches/{id}` | F12 | Correct typos in `batch_code` or `expiration_date` only. Writes `metadata_correction` movement (qty=0). Naturally idempotent |
| POST | `/batches/{id}/movements` | F5, F6 | Body `{kind, signed_quantity, notes}`. `kind` ∈ `adjustment`, `write_off`. Idempotency-Key required for `write_off` |
| POST | `/batches/{id}/recall` | F9 | Set `is_recalled=true`; write `recall_block` movement. Idempotent by design |
| POST | `/batches/{id}/un-recall` | F10 | Reverse recall; write `recall_unblock` movement |
| GET | `/movements` | R6, F11 | Cross-cutting audit; cursor pagination. Filter by `batch_id`, `product_id`, `from`, `to`, `kind` |

`GET /batches/{id}/recall-report` is deferred to ILEX-007 since `v_recall_report` joins sales tables.

## Tests

- Schema: append-only trigger rejects UPDATE/DELETE; CHECK constraints reject invalid kind/sign combos
- Query: FEFO eligibility ordering with NULLs last; `v_stock_by_batch` returns correct totals
- Service: recall idempotent on already-recalled; PATCH metadata writes audit movement; write-off rejects negative on-hand outcomes
- API: 8 endpoint integration tests + cross-owner 404

## Dependencies

1. ILEX-005 (batches reference PO lines for procurement-sourced batches)
