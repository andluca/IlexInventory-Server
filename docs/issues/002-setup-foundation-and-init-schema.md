# 002 — Setup foundation helpers and 0001_init schema

## Overview

Lay the substrate every app depends on: shared Python helpers in `apps/core/` and the initial Postgres migration with extensions and the UUIDv7 SQL function.

**Scope:**
- `backend/migrations/0001_init.sql`:
  - `pgcrypto` extension
  - UUIDv7 SQL function (companion to the Python helper)
  - `idempotency_keys` table — `(owner_id UUID, key TEXT, endpoint TEXT, response_status INT, response_body JSONB, created_at TIMESTAMPTZ, PRIMARY KEY (owner_id, key, endpoint))` — used by the Idempotency-Key cache for `POST /receive`, `POST /commit`, `POST /batches`, `POST /movements (kind=write_off)`. TTL cleanup deferred (manual or cron later).
- `apps/core/ids.py` — UUIDv7 Python generator (BE-D5)
- `apps/core/owner_scope.py` — `@scoped` decorator that injects `owner_id = %(owner_id)s` into queries (BE-D4)
- `apps/core/errors.py` — `DomainError` base + `NotFound`, `ValidationError`, `Conflict` subclasses; HTTP mapping helper used by API layer
- `apps/core/types.py` — placeholder for shared dataclasses / TypedDicts
- `apps/core/pagination.py` — cursor pagination helper. Encodes `(UUIDv7, created_at)` tuples; decodes safely with bad-cursor handling. Used by `/sales-orders` (Issue 007), `/movements` (Issue 006), `/financials/margin` (Issue 008).
- `apps/core/idempotency.py` — Idempotency-Key middleware/decorator. Reads `Idempotency-Key` header, looks up `(owner_id, key, endpoint)` in `idempotency_keys`, returns cached body on hit; on miss, executes the request and stores the response.
- Migration runner: Django management command `python manage.py migrate_sql` (custom command in `apps/core/management/commands/migrate_sql.py`) that applies plain `.sql` files from `backend/migrations/` in numeric order, tracking applied migrations in a small `_sql_migrations` table. Idempotent: re-running skips already-applied files.
- Tests:
  - Unit: UUIDv7 monotonicity over 1000 generations; `@scoped` raises if `owner_id` missing; cursor encode/decode round-trip; idempotency middleware cache hit / miss / per-owner isolation
  - Query: Postgres UUIDv7 fn returns valid UUID with v7 variant bits set; `idempotency_keys` PK constraint rejects duplicate `(owner_id, key, endpoint)`
  - Integration: `migrate_sql` applies `0001_init.sql` cleanly to a fresh database; re-run is a no-op

**Reference:** SPEC §2.1, §2.2, §2.3, §2.4. BE-D4, BE-D5.

**Depends on:** 001.
