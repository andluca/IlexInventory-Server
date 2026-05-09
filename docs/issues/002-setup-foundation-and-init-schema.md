> **Status:** ✅ Done — shipped in [`80c0b39`](../../commit/80c0b39) as `feat(core): foundation helpers and 0001_init schema (ILEX-002)`.

# ILEX-002 Setup foundation helpers and 0001_init schema

Lay the substrate every later issue depends on: shared Python helpers in `apps/core/`, the initial Postgres migration with `pgcrypto` + UUIDv7 SQL function + cross-cutting `idempotency_keys` table, a concrete migration runner (`manage.py migrate_sql`), the owner-scope decorator, cursor pagination, idempotency-key middleware, and a domain-error hierarchy.

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.1, §2.2, §2.3, §2.4, §2.6 (Idempotency-Key list), §4 Validation Gates. Decisions: BE-D4 (owner isolation), BE-D5 (UUIDv7), BE-D12 (4-layer architecture).


# Specification

## Operation: migrate_sql
File: `backend/apps/core/management/commands/migrate_sql.py`

Apply plain `.sql` files from `backend/migrations/` in numeric order, tracking applied filenames in `_sql_migrations` so re-runs are idempotent. Replaces Django's `manage.py migrate` for our raw-SQL schema (BE-D14: `migrate` is reserved for `auth.User` only).

### Preconditions

* Django settings load (`DJANGO_SETTINGS_MODULE=settings.dev`)
* `DATABASE_URL` resolves to a reachable Postgres
* `backend/migrations/*.sql` files exist and are numbered (`0001_init.sql`, ...)

### Primary Use Case — fresh database

#### Input
```
python manage.py migrate_sql
```

#### Workflow
* Open psycopg connection from `settings.DATABASE_URL`
* `CREATE TABLE IF NOT EXISTS _sql_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())`
* List `backend/migrations/*.sql`, sorted by filename
* For each file not in `_sql_migrations`: execute file contents in a transaction, then `INSERT INTO _sql_migrations (filename) VALUES (...)`
* Print `applied: 0001_init.sql` per applied file; `up to date` if nothing applied

#### Output
```
applied: 0001_init.sql
```

### Re-run on already-migrated database

#### Workflow
* Same command runs against a DB where `_sql_migrations` already lists every file
* No SQL executes; no rows inserted
* Exit 0 with `up to date`

### Migration file contains invalid SQL

#### Workflow
* Transaction rolls back; `_sql_migrations` row is NOT inserted for the failed file
* Error message includes the filename and Postgres error
* Exit code: 1 (non-zero so CI fails fast)

## Function: migrate_sql.Command.handle
File: `backend/apps/core/management/commands/migrate_sql.py`
Input: `(self, *args, **options) -> None`
Returns: `None` (writes to `self.stdout` and `self.stderr`; exits 1 on error)

Django `BaseCommand` subclass. Owns the migration loop; delegates the per-file apply to a helper for testability.

### Implementation

* Resolve migrations directory: `Path(__file__).resolve().parents[4] / "migrations"` (i.e. `backend/migrations/`)
* Open psycopg connection with `autocommit=False`
* Ensure `_sql_migrations` exists (idempotent `CREATE TABLE IF NOT EXISTS`)
* `SELECT filename FROM _sql_migrations` → set of applied
* Glob `*.sql`, sort lexicographically; skip already-applied
* For each pending file: open transaction, `cur.execute(file.read_text())`, insert tracking row, commit
* On `psycopg.Error`: rollback, print error, `sys.exit(1)`

## Lib: 0001_init schema
File: `backend/migrations/0001_init.sql`

The DB-side substrate every other migration sits on. Adds extensions, the UUIDv7 SQL function (companion to the Python helper), and the `idempotency_keys` table consumed by the Idempotency-Key middleware.

### Contents

* `CREATE EXTENSION IF NOT EXISTS pgcrypto` — needed for `gen_random_bytes` inside the UUIDv7 fn
* `CREATE OR REPLACE FUNCTION uuidv7() RETURNS uuid` — returns a v7 UUID composed of `EXTRACT(EPOCH FROM clock_timestamp()) * 1000` (48-bit ms timestamp) + 12 random bits + 62 random bits, with version (`0x7`) and variant (`0b10`) bits set per RFC 9562
* `CREATE TABLE idempotency_keys`:
  ```
  owner_id        UUID        NOT NULL,
  key             TEXT        NOT NULL,
  endpoint        TEXT        NOT NULL,
  response_status INT         NOT NULL,
  response_body   JSONB       NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (owner_id, key, endpoint)
  ```
  TTL cleanup deferred to a later issue. No `auth_user` FK yet — `auth_user` table only exists post-`migrate auth` in ILEX-003; we deliberately keep `owner_id` as a bare UUID column here so 0001 stays self-contained.
* `CREATE TABLE _sql_migrations` is **not** here — the runner creates it programmatically (chicken-and-egg: the runner needs the table before running the first migration).

## Lib: UUIDv7 generator (Python)
File: `backend/apps/core/ids.py`

Python-side companion to the SQL `uuidv7()` function. Used by tests and any service that needs to generate a PK before insert (e.g., to return the ID in the response without a `RETURNING` round-trip when batching inserts).

### Functions

* `uuidv7() -> uuid.UUID`: returns a UUIDv7 — 48 bits of millisecond timestamp + 4-bit version (`7`) + 12 random bits + 2-bit variant (`10`) + 62 random bits, packed per RFC 9562

## Lib: Domain errors
File: `backend/apps/core/errors.py`

Single error hierarchy raised by services and selectors; the API layer catches `DomainError` and maps to HTTP. Locked here once so every later app shares one contract.

### Classes

* `DomainError(Exception)` — base; `code: str`, `detail: str | None`, `fields: dict | None`
* `NotFound(DomainError)` — `code = "NotFound"` → HTTP 404 (also raised on cross-owner per BE-D4)
* `ValidationError(DomainError)` — `code = "ValidationError"` → HTTP 400
* `Conflict(DomainError)` — `code = "Conflict"` → HTTP 409 (used for SKU lock, terminal-state PATCH/DELETE)
* `Unprocessable(DomainError)` — `code = "Unprocessable"` → HTTP 422 (FEFO shortfall, write-off-into-negative)

### Functions

* `to_response(exc: DomainError) -> tuple[dict, int]`: returns `({"error": code, "detail"?: ..., "fields"?: ...}, http_status)` matching SPEC §2.6 error envelope

## Lib: Owner-scope decorator
File: `backend/apps/core/owner_scope.py`

Wraps query functions so `owner_id` is mandatory and injected into the parameter dict. CI grep gate (added in a later issue) fails on owner-scoped query functions that bypass it. BE-D4.

### Functions

* `@scoped`: decorator. Inspects the wrapped function's `params: dict` argument; raises `ValueError` if `owner_id` key is missing or `None`. Pass-through otherwise — the decorator is a runtime guard, not a SQL rewriter (the query SQL itself must include `WHERE owner_id = %(owner_id)s`)

## Lib: Cursor pagination
File: `backend/apps/core/pagination.py`

Encodes `(UUIDv7, created_at)` into an opaque base64 cursor; decodes safely with bad-cursor fallback. Consumed by `/sales-orders` (ILEX-007), `/movements` (ILEX-006), `/financials/margin` (ILEX-008) per SPEC §2.6.

### Functions

* `encode_cursor(uuid: UUID, created_at: datetime) -> str`: `base64url(f"{uuid}|{created_at.isoformat()}")`
* `decode_cursor(cursor: str | None) -> tuple[UUID, datetime] | None`: returns `None` for `None` or malformed input (caller treats `None` as "first page")

## Lib: Idempotency-Key middleware
File: `backend/apps/core/idempotency.py`

DRF view decorator that reads the `Idempotency-Key` header, looks up `(owner_id, key, endpoint)` in `idempotency_keys`, returns the cached body on hit; on miss, runs the view and stores `(status, body)` before returning. Consumed by `POST /receive`, `POST /commit`, `POST /batches`, `POST /movements (kind=write_off)` and the always-idempotent endpoints per SPEC §2.6.

### Functions

* `@idempotent(endpoint: str)`: view decorator. Reads `Idempotency-Key` header (400 if required and missing — caller decides per-endpoint policy via separate flag); reads `request.user.id` as `owner_id`; on cache hit, returns `Response(body, status=cached_status)`; on miss, executes the view, then `INSERT INTO idempotency_keys ... ON CONFLICT DO NOTHING` (race-safe under concurrent retries). Endpoint string is the route identifier (e.g. `"purchase_orders.receive"`), not the URL path

## Lib: Shared types stub
File: `backend/apps/core/types.py`

Placeholder module for `TypedDict` / `dataclass` definitions shared across apps. Empty in this issue; populated only when a second consumer appears (per "build iteratively" rule). Shipping the file now keeps later imports stable.

## External Dependencies

### pgcrypto (Postgres extension)
Used for: `gen_random_bytes(n)` inside the UUIDv7 SQL function (random bits)
Loaded via: `CREATE EXTENSION IF NOT EXISTS pgcrypto` in `0001_init.sql`

* No new Python dependency; psycopg already bundled in ILEX-001
* Available on every supported Postgres host (RDS, Railway, local docker)


# Plan

Each step is independently shippable: after step N, `pytest` is green, `ruff check backend/` clean, `python manage.py check` exits 0. Tests written first inside each step (TDD red → green → refactor).

1. **UUIDv7 Python helper (`apps/core/ids.py`)**
   - Why: zero-dependency, zero-DB. Lands the BE-D5 contract first; every later test fixture and seed-data helper imports from it.
   - [ ] Write unit test `backend/apps/core/tests/unit/test_ids.py`: `uuidv7()` returns a `UUID` with `version == 7`; 1000 sequential calls produce strictly increasing values when sorted by their 48-bit timestamp prefix
   - [ ] Implement `uuidv7()` per RFC 9562 (ms timestamp + version + random + variant + random)
   - [ ] Smoke: `python -c "from apps.core.ids import uuidv7; print(uuidv7())"` prints a v7 UUID

2. **0001_init.sql + `migrate_sql` runner**
   - Why: the schema and the tool that applies it ship as one unit — the runner is what makes the migration testable end-to-end. After this step every later issue can `manage.py migrate_sql` from a clean slate.
   - [ ] Write integration test `backend/apps/core/tests/api/test_migrate_sql.py`: subprocess `python manage.py migrate_sql` against the fresh `db` fixture creates `_sql_migrations`, applies `0001_init.sql`, and a re-run is a no-op (`_sql_migrations` row count stays at 1)
   - [ ] Write query test `backend/apps/core/tests/unit/test_uuidv7_sql.py`: `SELECT uuidv7()` returns a UUID; `SELECT (uuidv7()::text)::uuid` round-trips; the version nibble (13th hex char) equals `'7'`
   - [ ] Write query test in same file: `idempotency_keys` PK rejects a duplicate `(owner_id, key, endpoint)` row with `psycopg.errors.UniqueViolation`
   - [ ] Write `backend/migrations/0001_init.sql`: `CREATE EXTENSION pgcrypto`, `uuidv7()` function, `idempotency_keys` table with composite PK
   - [ ] Write `backend/apps/core/management/commands/migrate_sql.py` (and `__init__.py` files for `management/`, `management/commands/`)
   - [ ] Verify migration is forward-only: re-applying 0001 to a populated DB does nothing (the `_sql_migrations` skip path catches it before any SQL runs)

3. **Domain errors + types stub (`apps/core/errors.py`, `apps/core/types.py`)**
   - Why: every later service raises `NotFound`/`Conflict`/`Unprocessable`; lock the envelope shape (SPEC §2.6) once so apps don't drift. `types.py` lands as an empty stub now to fix the import path before its first consumer.
   - [ ] Write unit test `backend/apps/core/tests/unit/test_errors.py`: `to_response(NotFound("missing", detail="..."))` returns `({"error": "NotFound", "detail": "..."}, 404)`; `to_response(ValidationError(fields={"sku": "required"}))` returns 400 with `fields` populated; non-`DomainError` exception raises (caller is responsible for mapping framework errors)
   - [ ] Implement `errors.py`: `DomainError` base + 4 subclasses + `to_response` mapping
   - [ ] Create `types.py` with module docstring only (placeholder)

4. **Owner-scope decorator (`apps/core/owner_scope.py`)**
   - Why: BE-D4. CI grep gate in later issues looks for `@scoped` on owner-scoped query functions; the decorator must exist before any of them ships.
   - [ ] Write unit test `backend/apps/core/tests/unit/test_owner_scope.py`: `@scoped` wrapped function raises `ValueError` if `params={}` or `params={"owner_id": None}`; passes through when `params={"owner_id": <uuid>, ...}`; positional/keyword call signatures both work
   - [ ] Implement `@scoped` as a runtime guard (no SQL rewriting — the query SQL still owns the `WHERE owner_id = %(owner_id)s` clause)
   - [ ] Add a one-line comment in the file explaining the runtime-guard role and pointing at BE-D4

5. **Cursor pagination helper (`apps/core/pagination.py`)**
   - Why: locks the cursor format once. `/sales-orders`, `/movements`, `/financials/margin` (3 later issues) all decode with the same helper, so format drift is impossible.
   - [ ] Write unit test `backend/apps/core/tests/unit/test_pagination.py`: `decode_cursor(encode_cursor(u, t)) == (u, t)` for a UUIDv7 + UTC `created_at`; `decode_cursor(None) is None`; `decode_cursor("not-base64")` returns `None` (no exception); `decode_cursor("dmFsaWRiNjQ=")` (valid b64 but wrong shape) returns `None`
   - [ ] Implement `encode_cursor` / `decode_cursor` using `base64.urlsafe_b64encode` and a `|` separator
   - [ ] Confirm the helper does NOT log on bad cursor (silent fallback per SPEC §2.6 "user-supplied input")

6. **Idempotency-Key middleware (`apps/core/idempotency.py`)**
   - Why: 4 mutating terminal endpoints in later issues (SPEC §2.6 table) plus the always-idempotent recall + void all need the same cache contract. Land it before any of them so the contract can't drift.
   - [ ] Write API test `backend/apps/core/tests/api/test_idempotency.py` using a tiny stub view: first `POST` with `Idempotency-Key: abc` runs the handler (asserts side-effect counter incremented to 1); second `POST` with same key returns the cached 200 body **and the counter stays at 1** (handler skipped)
   - [ ] Same test file: missing `Idempotency-Key` on a `@idempotent` view returns 400 with `{"error": "ValidationError", "detail": "Idempotency-Key header required"}`
   - [ ] Same test file: per-owner isolation — owner A's cached row is NOT visible to owner B (different `request.user.id` → cache miss → handler runs)
   - [ ] Implement `@idempotent(endpoint=...)` decorator using `INSERT ... ON CONFLICT DO NOTHING` for race-safety; cache hit branch returns `Response(body, status=cached_status)`
   - [ ] Add a one-line comment pointing at the SPEC §2.6 endpoint table


# Notes

- **No `auth_user` FK on `idempotency_keys` yet.** The `auth_user` table is created by `manage.py migrate auth` in ILEX-003, after this issue ships. Keep `owner_id UUID NOT NULL` here without a FK constraint; ILEX-003's migration adds `ALTER TABLE idempotency_keys ADD CONSTRAINT ... FOREIGN KEY (owner_id) REFERENCES auth_user(id)` once the target exists. Document the deferred FK in a comment in `0001_init.sql`.
- **`migrate_sql` is separate from `migrate`.** ILEX-003 will run **both** `manage.py migrate` (for `auth_user`/sessions ORM tables — BE-D14 carve-out) and `manage.py migrate_sql` (for our raw-SQL schema). The two trackers (`django_migrations` vs `_sql_migrations`) coexist in the same DB without conflict.
- **`_sql_migrations` is created by the runner, not by `0001_init.sql`.** Chicken-and-egg: the tracker table must exist before the runner can check whether `0001_init.sql` has been applied. `CREATE TABLE IF NOT EXISTS _sql_migrations ...` runs first, every time, idempotently.
- **UUIDv7 fn uses `clock_timestamp()`, not `now()`.** `now()` is constant within a transaction; `clock_timestamp()` increments on each call so multiple inserts in one transaction produce monotonic IDs.
- **Idempotency cache stores response body as JSONB.** Restricts the contract to JSON-serializable responses, which matches SPEC §2.6 (all 4xx errors and all 2xx success bodies are JSON). CSV export endpoints are not on the Idempotency-Key list — they're GETs.
- **Tests against the existing `db` fixture must rollback per test.** The session-scoped `db` fixture in `backend/conftest.py` wipes the database once at session start; per-test isolation comes from the `pre_db` / `post_db` pattern (already shipped). Idempotency tests must `conn.rollback()` between cases to avoid leaking `idempotency_keys` rows.
- **`@scoped` is a runtime guard, not a SQL rewriter.** The query function SQL still owns the `WHERE owner_id = %(owner_id)s` clause. The decorator only ensures `owner_id` is present in the params dict — the CI grep gate (added in a later issue) is what proves the SQL clause is actually present.
- **Out of scope:** `auth_user` ORM entry in `DATABASES` (ILEX-003), CI grep gates (ILEX-003), TTL cleanup of `idempotency_keys` rows (deferred), CSV renderer (ILEX-009), the `@idempotent` decorator's actual usage on real endpoints (each later issue wires it onto its own view).


# Journal

- 2026-05-08 00:00 [executor] — step 1: apps/core/ids.py + 4 unit tests (version=7, variant bits, monotonicity); pytest 4/4 green, ruff clean, manage.py check 0.
- 2026-05-08 00:01 [executor] — step 2: backend/migrations/0001_init.sql + management/commands/migrate_sql.py + unit/conftest.py; 5 new tests (migrate_sql idempotency, SQL uuidv7 version/round-trip, PK violation); pytest 57/57 green, ruff clean, manage.py check 0.
- 2026-05-08 00:02 [executor] — step 3: apps/core/errors.py (DomainError + 4 subclasses + to_response) + apps/core/types.py stub; 9 unit tests; pytest 66/66 green, ruff clean, manage.py check 0.
- 2026-05-08 00:03 [executor] — step 4: apps/core/owner_scope.py (@scoped runtime guard, BE-D4); 6 unit tests (empty params, None owner_id, pass-through, keyword/positional call, name preservation); pytest 72/72 green, ruff clean.
- 2026-05-08 00:04 [executor] — step 5: apps/core/pagination.py (encode_cursor/decode_cursor, base64url, silent bad-cursor fallback); 6 unit tests (roundtrip, None, invalid b64, wrong shape, too many pipes, no-log); pytest 78/78 green, ruff clean.
- 2026-05-08 00:05 [executor] — step 6: apps/core/idempotency.py (@idempotent decorator, ON CONFLICT DO NOTHING, per-owner isolation); api/conftest.py for schema setup; 4 API tests (first call, cache hit, missing header, owner isolation); pytest 82/82 green, ruff clean, manage.py check 0. Fresh-DB migrate_sql: "applied: 0001_init.sql"; re-run: "up to date".
