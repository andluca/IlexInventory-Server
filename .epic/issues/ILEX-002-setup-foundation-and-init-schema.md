---
id: ILEX-002
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-001]
---

# ILEX-002 Setup foundation helpers and 0001_init schema

Lay the substrate every app depends on: shared Python helpers in `apps/core/`, the initial Postgres migration with extensions and the UUIDv7 SQL function, the cross-cutting `idempotency_keys` table, the cursor pagination helper, and a concrete migration runner.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.1, §2.2, §2.3, §2.4. BE-D4 (owner isolation), BE-D5 (UUIDv7).

## Scope

- `backend/migrations/0001_init.sql`:
  - `pgcrypto` extension
  - UUIDv7 SQL function (companion to the Python helper)
  - `idempotency_keys` table — `(owner_id UUID, key TEXT, endpoint TEXT, response_status INT, response_body JSONB, created_at TIMESTAMPTZ, PRIMARY KEY (owner_id, key, endpoint))`. Used by the Idempotency-Key cache for `POST /receive`, `POST /commit`, `POST /batches`, `POST /movements (kind=write_off)`. TTL cleanup deferred.
  - `_sql_migrations` table for the runner to track applied files
- `apps/core/ids.py` — UUIDv7 Python generator (BE-D5)
- `apps/core/owner_scope.py` — `@scoped` decorator that injects `owner_id = %(owner_id)s` into queries (BE-D4)
- `apps/core/errors.py` — `DomainError` base + `NotFound`, `ValidationError`, `Conflict` subclasses; HTTP mapping helper used by API layer
- `apps/core/types.py` — placeholder for shared dataclasses / TypedDicts
- `apps/core/pagination.py` — cursor pagination helper. Encodes `(UUIDv7, created_at)` tuples; decodes safely with bad-cursor handling. Used by `/sales-orders` (ILEX-007), `/movements` (ILEX-006), `/financials/margin` (ILEX-008).
- `apps/core/idempotency.py` — Idempotency-Key middleware/decorator. Reads `Idempotency-Key` header, looks up `(owner_id, key, endpoint)` in `idempotency_keys`, returns cached body on hit; on miss, executes the request and stores the response.
- Migration runner: Django management command `python manage.py migrate_sql` at `apps/core/management/commands/migrate_sql.py`. Applies plain `.sql` files from `backend/migrations/` in numeric order, tracking applied migrations in `_sql_migrations`. Idempotent: re-running skips already-applied files.

## Tests

- Unit: UUIDv7 monotonicity over 1000 generations; `@scoped` raises if `owner_id` missing; cursor encode/decode round-trip; idempotency middleware cache hit/miss/per-owner isolation
- Query: Postgres UUIDv7 fn returns valid UUID with v7 variant bits set; `idempotency_keys` PK rejects duplicate `(owner_id, key, endpoint)`
- Integration: `migrate_sql` applies `0001_init.sql` cleanly to a fresh database; re-run is a no-op

## Dependencies

1. ILEX-001 (Django + DRF must boot before management commands run)
