# 004 — Implement catalog app (products)

## Overview

Full vertical for products: schema cluster, queries, services, selectors, APIs, CSV import. SKU is locked once the first batch references the product. Products with batches archive (soft delete); products without batches hard-delete.

**Scope:**
- `backend/migrations/0002_catalog.sql` — `products` table; columns per SPEC §3.2; unique `(owner_id, sku)`; `archived_at TIMESTAMPTZ NULL`; UUIDv7 PK; `owner_id` for D4 isolation
- `apps/catalog/` full structure: `apis.py`, `services.py`, `selectors.py`, `serializers.py`, `urls.py`, `errors.py`, `types.py`, `queries/products.py`
- 7 endpoints: list (offset pagination, search, archived filter), detail, create, patch (name/description), archive, delete, CSV import (multipart/form-data)
- Tests at all four layers (unit, query, service, api):
  - Query: round-trip products, NULL handling on `archived_at`
  - Service: SKU lock after first batch (Issue 006 will exercise this end-to-end; mock the batch existence here or skip)
  - API: full CRUD + CSV import partial-success behavior (failed rows reported by index, committed rows persist)

**Endpoints:**
- GET `/products`, POST `/products`
- GET `/products/{id}`, PATCH `/products/{id}`, DELETE `/products/{id}`
- POST `/products/{id}/archive`
- POST `/products/import`

**Reference:** SPEC §3.2.

**Depends on:** 003 (auth required for owner injection).
