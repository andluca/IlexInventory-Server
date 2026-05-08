---
id: ILEX-005
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-004]
---

# ILEX-005 Implement procurement app (purchase orders)

Full vertical for POs: schema cluster, draft CRUD, atomic receive. Receive creates one batch per line + receipt movements in a single transaction. Idempotency-Key required on receive. Received POs are immutable (BE-D6); corrections via reversal movements only.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.3. BE-D0 (header + lines), BE-D6 (two states, terminal immutable), BE-D10 (text supplier fields).

## Scope

- `backend/migrations/0003_procurement.sql` — `purchase_orders` (header: supplier_name + nullable supplier_contact per BE-D10, status `draft|received`, owner_id), `purchase_order_lines` (product FK, quantity, unit_cost, owner_id); composite FK `(id, owner_id)` on every reference
- `apps/procurement/` full app structure
- 6 endpoints: list, detail, draft create, draft patch (replace-style for lines), draft delete, receive
- `receive_purchase_order(po_id, lines_with_batch_metadata)` service — transactional, creates batches + receipt movements (writes to inventory tables defined in ILEX-006; coordinate so `0003_procurement.sql` doesn't depend on `0004_inventory.sql` schema)
- Idempotency-Key middleware applied to receive endpoint for the first time (helper from ILEX-002)

## Endpoints

| Method | Route | Realizes | Description |
|---|---|---|---|
| GET | `/purchase-orders` | R5 | List; offset; filter by status, supplier search, date range |
| POST | `/purchase-orders` | F3 | Create draft |
| GET | `/purchase-orders/{id}` | R5 | Detail (lines + post-receive batches) |
| PATCH | `/purchase-orders/{id}` | F3 | Edit draft (replace-style). 409 post-receive |
| DELETE | `/purchase-orders/{id}` | F3 | Delete draft. 409 post-receive |
| POST | `/purchase-orders/{id}/receive` | F3 | Terminal: batches + receipt movements, atomic. Idempotency-Key required |

## Schema ordering note

`0003_procurement.sql` only creates the PO/line tables. The composite FK from `batches.purchase_order_line_id → purchase_order_lines.id` is added in `0004_inventory.sql` (ILEX-006). The `receive_purchase_order` service can't run end-to-end until ILEX-006 lands; tests in this issue stub the inventory writes or mark them pending until ILEX-006.

## Tests

- Query: round-trip PO + lines; status transitions
- Service: receive on already-received PO returns cached response (idempotent retry); patch/delete on received PO returns 409
- API: draft CRUD; receive happy path (after ILEX-006); cross-owner returns 404

## Dependencies

1. ILEX-004 (PO lines reference products)
