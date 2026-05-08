# 005 — Implement procurement app (purchase orders)

## Overview

Full vertical for POs: schema cluster, draft CRUD, atomic receive. Receive creates one batch per line + receipt movements in a single transaction. Idempotency-Key required on receive. Received POs are immutable (BE-D6); corrections via reversal movements only.

**Scope:**
- `backend/migrations/0003_procurement.sql` — `purchase_orders` (header: supplier_name + nullable supplier_contact per BE-D10, status `draft|received`, owner_id), `purchase_order_lines` (product FK, quantity, unit_cost, owner_id); composite FK `(id, owner_id)` on every reference
- `apps/procurement/` full app structure
- 6 endpoints: list, detail, draft create, draft patch (replace-style for lines), draft delete, receive
- `receive_purchase_order(po_id, lines_with_batch_metadata)` service — transactional, creates batches + receipt movements (this writes to inventory tables defined in Issue 006; coordinate the migration order so 0003 doesn't depend on 0004 schema)
- Idempotency-Key middleware (or decorator) used here for the first time; cache the response keyed by (owner_id, key, endpoint)
- Tests at all four layers, including: receive on already-received PO returns cached response (idempotent retry); patch/delete on received PO returns 409

**Endpoints:**
- GET `/purchase-orders`, POST `/purchase-orders`
- GET `/purchase-orders/{id}`, PATCH `/purchase-orders/{id}`, DELETE `/purchase-orders/{id}`
- POST `/purchase-orders/{id}/receive`

**Reference:** SPEC §3.3. BE-D0 (header + lines), BE-D6 (two states), BE-D10 (text supplier fields).

**Note on schema ordering:** `0003_procurement.sql` only creates the PO/line tables. The composite FK from `batches.purchase_order_line_id → purchase_order_lines.id` is added in `0004_inventory.sql` (Issue 006). The receive service can't actually run end-to-end until 006 lands; tests in this issue stub the inventory writes or skip until 006.

**Depends on:** 004 (PO lines reference products).
