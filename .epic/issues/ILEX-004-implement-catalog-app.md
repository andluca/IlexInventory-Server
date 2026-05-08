---
id: ILEX-004
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-003]
---

# ILEX-004 Implement catalog app (products)

Full vertical for products: schema cluster, queries, services, selectors, APIs, CSV import. SKU is locked once the first batch references the product. Products with batches archive (soft delete); products without batches hard-delete.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §3.2.

## Scope

- `backend/migrations/0002_catalog.sql` — `products` table; columns per SPEC §3.2; UNIQUE `(owner_id, sku)`; `archived_at TIMESTAMPTZ NULL`; UUIDv7 PK; `owner_id` for D4 isolation
- `apps/catalog/` full structure: `apis.py`, `services.py`, `selectors.py`, `serializers.py`, `urls.py`, `errors.py`, `types.py`, `queries/products.py`
- 7 endpoints: list (offset pagination, search, archived filter), detail, create, patch (name/description), archive, delete, CSV import (multipart/form-data)

## Endpoints

| Method | Route | Realizes | Description |
|---|---|---|---|
| GET | `/products` | R1 | List; offset; search by name/SKU; filter `archived={true,false}`; on-hand totals |
| POST | `/products` | F2 | Create (name, SKU unique per owner, description, base_unit ∈ `g`/`ml`/`unit`) |
| GET | `/products/{id}` | R1, R6 | Detail with batches summary |
| PATCH | `/products/{id}` | F2 | Edit `name`, `description`. SKU locked once first batch exists |
| POST | `/products/{id}/archive` | F2 | Soft delete; 409 if no batches (use DELETE) |
| DELETE | `/products/{id}` | F2 | Hard delete; 409 if any batch exists |
| POST | `/products/import` | F2, F11 | CSV import. Idempotency-Key required. multipart/form-data with columns `name, sku, description, base_unit` |

## Tests

- Unit: serializer validation (`base_unit` enum, SKU non-empty)
- Query: round-trip products, NULL handling on `archived_at`
- Service: SKU lock after first batch (mock batch existence here; full coverage in ILEX-006)
- API: full CRUD; CSV import partial-success behavior (failed rows reported by index, committed rows persist); cross-owner returns 404

## Dependencies

1. ILEX-003 (auth required for owner injection on all writes)
