# 004 — Implement catalog app (products)

## Overview

Full vertical for products: schema cluster, queries, services, selectors, APIs, CSV import. SKU is locked once the first batch references the product. Products with batches archive (soft delete); products without batches hard-delete.

**Scope:**
- `backend/migrations/0003_catalog.sql` — `products` table; columns per SPEC §3.2; unique `(owner_id, sku)`; `archived_at TIMESTAMPTZ NULL`; UUIDv7 PK; `owner_id` for D4 isolation
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

---

## Context

### What already exists

- `backend/migrations/0001_init.sql` — pgcrypto extension, `uuidv7()` SQL function, `idempotency_keys` table.
- `backend/migrations/0002_auth_fk.sql` — retypes `idempotency_keys.owner_id` to INT and adds FK to `auth_user(id)`. **Owner FKs in this project are `INT REFERENCES auth_user(id)`, not UUID.** Catalog must follow the same convention.
- `backend/apps/core/owner_scope.py` — `@scoped` decorator that asserts `owner_id` is present in params. Catalog query functions wrap their SQL with this.
- `backend/apps/core/ids.py` — Python `uuidv7()` helper. Available if we ever need to mint IDs in Python; the SQL `uuidv7()` function is preferred when the row is inserted server-side.
- `backend/apps/core/idempotency.py` — `@idempotent(endpoint="...")` view decorator. Already wired to `idempotency_keys`. CSV import uses `endpoint="catalog.products_import"`.
- `backend/apps/core/errors.py` — `DomainError` hierarchy with `NotFound`, `ValidationError`, `Conflict`, `Unprocessable`, `Unauthorized`. `to_response(exc)` maps them to `(body, status)`. Reuse verbatim.
- `backend/apps/core/exceptions.py` — DRF exception handler that converts `NotAuthenticated` to 401.
- `backend/apps/core/auth.py` — single ORM allowlist file. Catalog does **not** import from there; catalog services receive `owner_id: int` as a parameter from views (`request.user.id`).
- `backend/apps/core/serializers.py`, `backend/apps/core/apis.py`, `backend/apps/core/urls.py` — pattern for one APIView per operation, inline `@extend_schema`, lazy imports inside `post`/`get` to avoid module-level cycles. Mirror this in catalog.
- `backend/apps/core/tests/db_test.py` — `pre_db` / `post_db`. **Foundation for all DB-touching tests in this issue.**
- `backend/apps/core/tests/api/conftest.py` and `backend/apps/core/tests/unit/conftest.py` — apply Django ORM migrations (auth/contenttypes/sessions) and `manage.py migrate_sql` once per session against the `db` fixture. Catalog tests reuse the same pattern (their app-level `conftest.py` will rely on the existing session-scoped fixtures via shared `db` fixture in `backend/conftest.py`).
- `backend/apps/core/tests/api/test_auth_api.py` — DRF `APIClient` happy-path + 4xx pattern using `_unique_email`. Catalog API tests should sign up a user in-test to get a session cookie, then exercise products endpoints.
- `backend/apps/core/tests/api/test_idempotency.py` — `@idempotent` decorator round-trip test against real DB. Mirrors what catalog's CSV import API test must verify (second call with the same key returns the cached body without re-executing).
- `backend/apps/core/management/commands/migrate_sql.py` — applies `*.sql` files from `backend/migrations/` lexicographically. **Adding `0003_catalog.sql` is enough; no command edits needed.**
- `backend/settings/base.py` — `INSTALLED_APPS` lists `apps.core` only; catalog must be appended. `ROOT_URLCONF = "urls"`.
- `backend/urls.py` — root urlconf currently mounts `apps.core.urls` under `/api/v1/`. Catalog mounts the same way: `path("api/v1/", include("apps.catalog.urls"))`.
- `backend/apps/core/pagination.py` — cursor pagination helpers. **Not used by catalog** (products list is offset per SPEC §2.6). Mentioned for the contrast.

### Spec reference

- SPEC §3.2 — endpoint table, validation rules, CSV import partial-success contract.
- SPEC §2.6 — offset pagination on `/products`; Idempotency-Key required for `POST /products/import`; error envelope shape `{ "error": "...", "detail"?: "...", "fields"?: { ... } }`.
- SPEC §2.5 — money/qty as `Decimal`. (Catalog has no money columns, but `base_unit` validation lives here.)
- SPEC §4 — phase-specific gates: "Product CRUD works; SKU locked after first batch (PATCH returns 409); archive vs delete enforced; CSV import handles malformed rows with detailed error response."
- `docs/architecture.md` §"File Locations" — exact module names per layer.
- `docs/decisions.md` D4, D6, D14 — owner isolation + state semantics + ORM carve-out.

### Decisions already made that affect this issue

- D4 — owner isolation: every owner-scoped row carries `owner_id`; cross-owner returns 404 (never 403). Composite FK `(id, owner_id)` is the substrate-level safety net for child tables; on `products` itself the FK is just `owner_id → auth_user(id)`. **`products` must expose a UNIQUE(`id`, `owner_id`) so future tables (`batches`, etc.) can FK against it as a composite per D4.**
- D6 — products have no draft/terminal states; only `archived_at`. Archive vs delete is gated by "does this product have any batch yet?" (Issue 006 lands `batches`; until then the SKU-lock check has nothing to query against — see Notes).
- D14 — no Django ORM in catalog. Owner is `INT` referencing `auth_user(id)` (matches the `0002_auth_fk.sql` convention).
- **Locked here, not yet a numbered decision (per SPEC §6 "locked here"):** `base_unit` is one of `g`, `ml`, `unit` — base units only. The display layer (FE) maps kg ↔ g and L ↔ ml. The server never sees kg.
- Idempotency-Key required only on `POST /products/import` per SPEC §2.6 (not on `POST /products` create — only catalog imports are idempotent in catalog).
- `PATCH /products/{id}` allows only `name` and `description` per SPEC §3.2. Any other key (including `sku`) → 409 if there are any batches, else `sku` is allowed (D6 + SPEC §3.2). See Notes for the seam with Issue 006.

---

## Plan

### Schema and SQL — `backend/migrations/0003_catalog.sql`

DDL sketch:

```sql
-- 0003_catalog.sql — products (owner-scoped, UUIDv7 PK, archive-soft-delete).

CREATE TABLE IF NOT EXISTS products (
    id           UUID        PRIMARY KEY DEFAULT uuidv7(),
    owner_id     INT         NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    sku          TEXT        NOT NULL,
    name         TEXT        NOT NULL,
    description  TEXT        NOT NULL DEFAULT '',
    base_unit    TEXT        NOT NULL,
    archived_at  TIMESTAMPTZ NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- D4: SKU unique per owner (not globally).
    CONSTRAINT products_owner_sku_unique UNIQUE (owner_id, sku),

    -- D4 substrate hook: future child tables (batches) compose composite FK
    -- against (id, owner_id). UNIQUE on (id, owner_id) makes that legal.
    CONSTRAINT products_id_owner_unique UNIQUE (id, owner_id),

    -- base_unit allowlist (g / ml / unit per product.md §1.4).
    CONSTRAINT products_base_unit_chk CHECK (base_unit IN ('g', 'ml', 'unit'))
);

-- Search/filter access path: list endpoint filters on owner_id and may
-- search by name/sku. A composite index on (owner_id, archived_at) supports
-- the "archived={true,false}" filter; a trigram or btree on lower(name)
-- can wait until 0007_indexes.sql.
CREATE INDEX IF NOT EXISTS products_owner_archived_idx
    ON products (owner_id, archived_at);
```

- File path: `backend/migrations/0003_catalog.sql`. The migration runner (`migrate_sql`) picks it up on lex order. **The issue body said `0002_catalog.sql` but `0002_auth_fk.sql` already shipped in ILEX-003; this file is `0003_catalog.sql`.** Updated filename matches reality; update SPEC §2.2's example list in a follow-up if the build wants tidy numbering (flagged in Notes).
- Round-trip test in `tests/query/test_products_queries.py` checks: insert minimal row → SELECT → all columns round-trip; `archived_at` defaults to NULL; `description` defaults to `''`; UNIQUE `(owner_id, sku)` rejects a second row; UNIQUE `(id, owner_id)` allowed (sanity).

### Service layer — `backend/apps/catalog/services.py`

Functions (kwarg-only, type-annotated, raise `apps.catalog.errors.*`):

```python
def create_product(*, owner_id: int, sku: str, name: str,
                   description: str, base_unit: str) -> ProductRow: ...

def update_product(*, owner_id: int, product_id: UUID,
                   name: str | None = None,
                   description: str | None = None) -> ProductRow: ...

def archive_product(*, owner_id: int, product_id: UUID) -> ProductRow: ...

def delete_product(*, owner_id: int, product_id: UUID) -> None: ...

def import_products_csv(*, owner_id: int, csv_bytes: bytes) -> ImportReport: ...
```

`ImportReport` is a `TypedDict` (in `apps/catalog/types.py`):

```python
class ImportReport(TypedDict):
    imported: int
    failed: list[FailedRow]   # [{"row_index": 2, "error": "ValidationError",
                              #   "detail": "...", "fields": {...}}]
```

Behavior summary:

| Service | Reads | Writes | Errors |
|---|---|---|---|
| `create_product` | uniqueness check via FK violation catch | INSERT | `Conflict` on duplicate SKU; `ValidationError` on unknown `base_unit` (defense in depth — serializer also validates) |
| `update_product` | exists check by `(id, owner_id)` | UPDATE name/description | `NotFound` if cross-owner or missing; future `Conflict` on SKU mutation when batches exist (see Notes) |
| `archive_product` | exists check; "has batches?" check | UPDATE `archived_at = NOW()` | `NotFound`; `Conflict` (uses 409 per SPEC §3.2) when product has zero batches — caller should `DELETE` instead |
| `delete_product` | exists check; "has batches?" check | DELETE | `NotFound`; `Conflict` when batches exist — caller should archive |
| `import_products_csv` | parse CSV; per-row validate | INSERTs in a single transaction with savepoints per row so failed rows don't abort the whole batch | always returns `ImportReport`; never raises for bad rows |

- All services that read/write open a single connection via a shared `apps/catalog/queries/_conn.py` helper or use a transaction context. Catalog uses `psycopg.connect(settings.DATABASE_URL)` per service call (matches `apps/core/idempotency.py` pattern). Wrap multi-statement services in `with conn.transaction():`.
- `archive_product` and `delete_product` need to ask "has any batch?" — but `batches` doesn't exist until Issue 006. **Plan:** services check via a probe query against `pg_class` first; if `batches` table is absent, treat "has batches?" as `False` and proceed. **Better seam (chosen):** define an internal Python boolean `BATCHES_TABLE_EXISTS` resolved at startup via `information_schema.tables`, cached. Issue 006 deletes that probe and replaces it with a real `SELECT 1 FROM batches WHERE product_id = %s LIMIT 1`. See Notes.
- All services receive `owner_id: int` from the API layer (via `request.user.id`). Never accept `owner_id` from the request body.

### Queries layer — `backend/apps/catalog/queries/products.py`

One module, one aggregate. Every function decorated with `@scoped` from `apps.core.owner_scope`. The cursor is provided by the caller (service owns the transaction). Functions:

- `insert_product(cur, *, params: dict) -> dict` — INSERT … RETURNING * with `(owner_id, sku, name, description, base_unit)`. On `psycopg.errors.UniqueViolation` for `products_owner_sku_unique`, the **service** maps to `Conflict("DuplicateSKU")` — the query function only raises the raw error.
- `select_product_by_id(cur, *, params: dict) -> dict | None` — `WHERE id = %(id)s AND owner_id = %(owner_id)s`. Returns None on miss (drives 404).
- `update_product_fields(cur, *, params: dict) -> dict | None` — UPDATE name/description on `(id, owner_id)`; RETURNING *. Caller passes only the fields supplied (NULLs are skipped — use `COALESCE` so a NULL means "leave alone", or compose SQL based on which fields are set; the second is cleaner — go with that).
- `set_archived_at(cur, *, params: dict) -> dict | None` — UPDATE `archived_at = NOW()` on `(id, owner_id)` WHERE `archived_at IS NULL`; RETURNING *. Idempotent (already-archived returns 0 rows; service maps to a fresh SELECT for response).
- `delete_product(cur, *, params: dict) -> int` — DELETE on `(id, owner_id)`; returns rowcount.
- `list_products(cur, *, params: dict) -> tuple[list[dict], int]` — paginated SELECT with optional `LIKE` on `name`/`sku`, optional `archived` filter (`IS NULL` / `IS NOT NULL`), `ORDER BY created_at DESC, id DESC`, `LIMIT %(limit)s OFFSET %(offset)s`. Returns `(rows, total)` with a separate `SELECT COUNT(*)` constrained by the same WHERE.
- `count_batches_for_product(cur, *, params: dict) -> int` — **stub returning 0 for now** (probes `information_schema.tables` for `batches` first; Issue 006 replaces the body).

All functions use named-param SQL (`%(owner_id)s`) to keep `@scoped` simple.

### Serializers — `backend/apps/catalog/serializers.py`

- `ProductCreateRequest` — `sku`, `name`, `description` (optional, default ""), `base_unit` (`ChoiceField(choices=["g","ml","unit"])`).
- `ProductUpdateRequest` — `name` (optional), `description` (optional). Reject any other key with `extra_kwargs`/`Meta` strictness; alternative is custom `validate(attrs)` rejecting unknown body keys (DRF strict-mode).
- `ProductResponse` — `id` (UUID string), `sku`, `name`, `description`, `base_unit`, `archived_at` (nullable ISO), `created_at`, `updated_at`.
- `ProductListResponse` — `{ "items": [ProductResponse], "total": int, "limit": int, "offset": int }`.
- `ProductImportResponse` — `{ "imported": int, "failed": [ { "row_index", "error", "detail"?, "fields"? } ] }`.

### APIs — `backend/apps/catalog/apis.py`

One `APIView` class per operation. Pattern: lazy-import the service inside `post`/`get`; convert serializer errors to the 400 envelope with `fields`; map `DomainError` via `to_response`.

- `ProductListApi` — GET `/products`. Reads query params `?search=`, `?archived=true|false`, `?limit=`, `?offset=`. Default `limit=50`, `offset=0`. Calls `selectors.list_products(...)`. **Does not include on-hand totals in this issue** (the SPEC §3.2 "Includes derived on-hand totals from `v_stock_by_batch`" depends on Issue 006/007's view; document the seam in Notes).
- `ProductCreateApi` — POST `/products`. Validates body, calls `services.create_product(...)`. 200 + body.
- `ProductDetailApi` — GET `/products/{id}`. Calls `selectors.product_by_id(...)`; 404 on miss (cross-owner → 404).
- `ProductUpdateApi` — PATCH `/products/{id}`. Validates body, calls `services.update_product(...)`.
- `ProductArchiveApi` — POST `/products/{id}/archive`. Calls `services.archive_product(...)`.
- `ProductDeleteApi` — DELETE `/products/{id}`. Calls `services.delete_product(...)`. 204 on success.
- `ProductImportApi` — POST `/products/import`. Multipart parser. Reads `request.FILES["file"]` → bytes → `services.import_products_csv(...)`. Decorated with `@idempotent("catalog.products_import")`. Returns 200 + `ImportReport` (partial success). All-failed-rows still returns 200 with `imported=0` per SPEC §3.2 ("partial success is allowed").

`@extend_schema` annotations on every endpoint: request serializer (or `OpenApiTypes.BINARY` for the CSV upload), response shape, error responses (400/401/404/409). All endpoints permit `IsAuthenticated`; the multipart endpoint adds `parser_classes = [MultiPartParser]`.

### Selectors — `backend/apps/catalog/selectors.py`

- `list_products(*, owner_id, search, archived, limit, offset)` → `{items, total, limit, offset}`.
- `product_by_id(*, owner_id, product_id)` → `dict | None`. Returns `None` for both cross-owner and missing — the API maps `None` to 404.

Selectors open a connection, call query functions, close. They **do not** open transactions (read-only).

### Errors — `backend/apps/catalog/errors.py`

```python
from apps.core.errors import Conflict, NotFound, ValidationError

class ProductNotFound(NotFound):
    code = "ProductNotFound"

class DuplicateSKU(Conflict):
    code = "DuplicateSKU"

class ProductHasBatches(Conflict):
    code = "ProductHasBatches"

class ProductHasNoBatches(Conflict):
    code = "ProductHasNoBatches"

class CsvParseError(ValidationError):
    code = "CsvParseError"
```

### URL routing — `backend/apps/catalog/urls.py`

```python
urlpatterns = [
    path("products", ProductListApi.as_view(), name="products-list"),
    path("products/import", ProductImportApi.as_view(), name="products-import"),
    path("products/<uuid:product_id>", ProductDetailApi.as_view(),
         name="products-detail"),
    path("products/<uuid:product_id>/archive", ProductArchiveApi.as_view(),
         name="products-archive"),
    # PATCH/DELETE on /products/{id} are dispatched by ProductDetailApi too —
    # combine list/detail style: ProductDetailApi.get(), .patch(), .delete()
]
```

Mount in `backend/urls.py` (one new line):
```python
path("api/v1/", include("apps.catalog.urls")),
```

`POST /products` (create) is on `ProductListApi.post`. **Or** split into a separate `ProductCreateApi` mounted on the same path — the architecture rule is "one APIView per operation"; the cleanest read is two classes sharing the path via separate URL entries is impossible, so combine list+create on `ProductListApi` (GET+POST) and detail+update+delete on `ProductDetailApi` (GET+PATCH+DELETE). This matches DRF idiom and the architecture rule's intent (no ViewSets; methods on one class are explicit). Document the deviation as "one class per *resource scope* (collection vs item), each method explicit" in the API docstrings.

### Tests (write FIRST per TDD)

`backend/apps/catalog/tests/__init__.py`, plus four subfolders each with `__init__.py` and `conftest.py` (the `conftest.py` either re-exports from `apps.core.tests.api.conftest` or simply re-applies `_apply_init_schema_api` — the cleanest is to **import the existing fixture** by adding `pytest_plugins = ["apps.core.tests.api.conftest"]` at the root of `apps/catalog/tests/conftest.py` so we don't re-spawn `manage.py` subprocesses).

#### Unit (`apps/catalog/tests/unit/`)

- `test_serializers.py` — `ProductCreateRequest` rejects bad `base_unit`; `ProductUpdateRequest` accepts only `name`/`description`; CSV row validator rejects rows with missing columns / bad `base_unit` / blank `sku`.
- `test_csv_parser.py` — pure-function tests for `parse_products_csv(bytes) → (rows, errors)` (split out of `services.py` if helpful). Covers: BOM stripping, CRLF/LF, missing headers, extra columns ignored or rejected, empty file, header-only file.
- `test_errors.py` — `to_response(DuplicateSKU(...))` returns `("DuplicateSKU", 409)` (sanity that the subclass code wins).

#### Query (`apps/catalog/tests/query/`)

- `test_products_queries.py`:
  - `test_insert_and_select_round_trip` — pre_db an `auth_user`; call `insert_product(...)`; `post_db` checks `products` row matches.
  - `test_archived_at_defaults_to_null` — pre_db a row without `archived_at`; SELECT shows NULL.
  - `test_unique_owner_sku_violation_raises` — insert twice with same `(owner_id, sku)`; psycopg raises `UniqueViolation` with constraint name `products_owner_sku_unique`.
  - `test_unique_id_owner_constraint_present` — sanity: composite UNIQUE exists (introspect `pg_constraint`).
  - `test_set_archived_at_idempotent` — call twice; second returns 0 rows.
  - `test_list_products_filters_and_paginates` — seed 3 rows for owner A, 2 for owner B; assert list_products for A returns 3 only; offset=1, limit=1 returns 1 row; archived filter splits correctly.
  - `test_list_products_search_by_name_or_sku` — substring match.
  - `test_scoped_decorator_blocks_missing_owner` — call any query without `owner_id` → ValueError.

#### Service (`apps/catalog/tests/service/`)

- `test_create_product.py`:
  - happy path → row inserted; ID is UUIDv7 (version=7 nibble).
  - duplicate SKU same owner → raises `DuplicateSKU`; no extra row.
  - same SKU different owner → both rows persist (D4 isolation).
- `test_update_product.py`:
  - update `name` only → `description` untouched.
  - cross-owner update → `ProductNotFound` (D4: 404 not 403).
  - SKU mutation rejected at serializer level (covered in unit tests).
- `test_archive_product.py`:
  - **without batches probe stub** → `ProductHasNoBatches` (409); state unchanged.
  - **with batches probe stub** (monkey-patch `count_batches_for_product` to return 1) → `archived_at` set to NOW().
  - cross-owner → `ProductNotFound`.
  - already archived → idempotent return (selector reads after the no-op UPDATE).
- `test_delete_product.py`:
  - **without batches** → row gone.
  - **with batches** (stub returns 1) → `ProductHasBatches`; state unchanged.
  - cross-owner → `ProductNotFound`.
- `test_import_products_csv.py`:
  - all rows valid → `imported=N, failed=[]`.
  - mixed: 2 valid + 1 bad `base_unit` → `imported=2, failed=[{"row_index": 1, ...}]`; the 2 valid rows persist (savepoint per row).
  - duplicate SKU within same import → second row reported as failed with `DuplicateSKU`.
  - completely empty CSV → `imported=0, failed=[]`.
  - header-only CSV → `imported=0, failed=[]`.

Test pattern (mandatory per `.claude/skills/tdd/SKILL.md`):

```python
from apps.core.tests.db_test import pre_db, post_db
from apps.catalog.services import create_product

def test_create_product_inserts_row(db):
    pre_db(db, {"auth_user": [{"id": 1, "username": "a", "password": "x", ...}]})
    db.commit()
    p = create_product(owner_id=1, sku="SKU-1", name="Cold Brew",
                       description="", base_unit="ml")
    db.rollback()  # don't pollute next test
    post_db(db, {"products": [{"sku": "SKU-1", "name": "Cold Brew",
                                "owner_id": 1, "base_unit": "ml"}]})
```

(Reality: services open their own connection; the `db` fixture is a separate connection used for `pre_db`/`post_db` setup and assertion. Tests commit setup so the service's connection sees it.)

#### API (`apps/catalog/tests/api/`)

Each test signs up a fresh user (so it has an authenticated session cookie) and exercises the endpoints. Pattern from `apps/core/tests/api/test_auth_api.py`.

- `test_products_crud.py`:
  - `POST /products` happy path → 200 + body shape; SKU echoed.
  - `POST /products` duplicate SKU same owner → 409 `{"error": "DuplicateSKU"}`.
  - `POST /products` bad base_unit → 400 with `fields.base_unit`.
  - `GET /products/{id}` happy path.
  - `GET /products/{id}` cross-owner (signup user B, query user A's product id) → 404 `{"error": "ProductNotFound"}`. **Owner-scope mandatory test.**
  - `PATCH /products/{id}` updates name; description preserved.
  - `PATCH /products/{id}` with `sku` key in body → 400 (rejected by serializer, not 409 — SKU lock test belongs to Issue 006 once batches exist).
  - `POST /products/{id}/archive` without batches → 409 `ProductHasNoBatches`.
  - `DELETE /products/{id}` without batches → 204; `GET` after returns 404.
- `test_products_list.py`:
  - List endpoint: empty → `{"items": [], "total": 0, ...}`.
  - List endpoint: 3 products created, one archived → `archived=false` returns 2; `archived=true` returns 1.
  - List endpoint: `?search=cold` filters by name LIKE.
  - Pagination: `?limit=1&offset=1` returns the second item, `total=3`.
- `test_products_import.py`:
  - Multipart upload, all rows valid → 200, `imported=N`, persisted.
  - Mixed valid/invalid → 200, `imported=k`, `failed=[{...}]`; valid rows persisted.
  - Missing `Idempotency-Key` header → 400 `ValidationError` ("Idempotency-Key header required").
  - Same `Idempotency-Key` retried → cached response, no double-insert (count of products unchanged).
- `test_products_auth.py`:
  - Anonymous request to any catalog endpoint → 401.

### Implementation order (TDD red-green-refactor per skill)

1. **Schema.** Write `0003_catalog.sql`. Run `manage.py migrate_sql` against a scratch DB; verify with `\d products`.
2. **Query layer (red→green→refactor).** Write `tests/query/test_products_queries.py`; then write `queries/products.py` to make them pass.
3. **Errors + types.** `apps/catalog/errors.py`, `apps/catalog/types.py` (`ProductRow` TypedDict, `ImportReport`).
4. **Service layer.** Write `tests/service/test_*.py`; then write `services.py` (with the `count_batches_for_product` stub).
5. **Serializers + selectors.** Write `tests/unit/test_serializers.py`; implement `serializers.py` and `selectors.py`.
6. **API layer.** Write `tests/api/test_*.py`; implement `apis.py` and `urls.py`. Wire root urls.py.
7. **OpenAPI.** Run `python manage.py spectacular --file /tmp/openapi.json` and eyeball the 7 endpoints; verify schemas.
8. **Refactor pass.** Cross-cutting: extract per-row CSV parsing into a helper if `import_products_csv` is large; collapse duplicated psycopg-connect boilerplate into a `_with_connection` helper (only if reused 2+ times).

### Integration / wiring

- `backend/settings/base.py` — append `"apps.catalog"` to `INSTALLED_APPS`.
- `backend/urls.py` — add `path("api/v1/", include("apps.catalog.urls"))`.
- `backend/migrations/0003_catalog.sql` — new file; runner picks it up automatically.
- OpenAPI: drf-spectacular auto-generates from the new `@extend_schema`-annotated views. Smoke `GET /api/v1/openapi.json` shows the 7 catalog operations. Frontend type regen happens in Issue 010 — no FE work here.

### Documentation to update

- `docs/issues/status.md` — flip ILEX-004 to `planned`; append Execution Log entry.
- **No `docs/specs/SPEC.md` rewrite.** SPEC §3.2 is correct as-is. (Footnote: §2.2 lists migrations `0001_init … 0002_catalog … 0003_procurement …` — the actual numbering is `0001_init, 0002_auth_fk, 0003_catalog, 0004_procurement, …` post-ILEX-003. The drift is cosmetic and will be cleaned up at the end of Phase 2 by a documentation issue or follow-up commit; flagged in Notes, not silently rewritten.)
- `.claude/CLAUDE.md` — no convention changes introduced.

## Files involved

Created:
- `backend/migrations/0003_catalog.sql`
- `backend/apps/catalog/__init__.py`
- `backend/apps/catalog/apis.py`
- `backend/apps/catalog/serializers.py`
- `backend/apps/catalog/services.py`
- `backend/apps/catalog/selectors.py`
- `backend/apps/catalog/errors.py`
- `backend/apps/catalog/types.py`
- `backend/apps/catalog/urls.py`
- `backend/apps/catalog/queries/__init__.py`
- `backend/apps/catalog/queries/products.py`
- `backend/apps/catalog/tests/__init__.py`
- `backend/apps/catalog/tests/conftest.py`
- `backend/apps/catalog/tests/unit/__init__.py`
- `backend/apps/catalog/tests/unit/test_serializers.py`
- `backend/apps/catalog/tests/unit/test_csv_parser.py`
- `backend/apps/catalog/tests/unit/test_errors.py`
- `backend/apps/catalog/tests/query/__init__.py`
- `backend/apps/catalog/tests/query/test_products_queries.py`
- `backend/apps/catalog/tests/service/__init__.py`
- `backend/apps/catalog/tests/service/test_create_product.py`
- `backend/apps/catalog/tests/service/test_update_product.py`
- `backend/apps/catalog/tests/service/test_archive_product.py`
- `backend/apps/catalog/tests/service/test_delete_product.py`
- `backend/apps/catalog/tests/service/test_import_products_csv.py`
- `backend/apps/catalog/tests/api/__init__.py`
- `backend/apps/catalog/tests/api/test_products_crud.py`
- `backend/apps/catalog/tests/api/test_products_list.py`
- `backend/apps/catalog/tests/api/test_products_import.py`
- `backend/apps/catalog/tests/api/test_products_auth.py`

Modified:
- `backend/settings/base.py` (append `apps.catalog` to `INSTALLED_APPS`)
- `backend/urls.py` (include `apps.catalog.urls`)
- `docs/issues/status.md`

## Acceptance criteria

Spec gates (from SPEC §4 "Catalog" row):
- Product CRUD works.
- SKU locked after first batch (PATCH on `sku` returns 409). **Partially deferred:** SKU is rejected at serializer level (400) until Issue 006 lands `batches`. The 409 path is covered by service-level test once `count_batches_for_product` returns >0 (stubbed in this issue, real in 006).
- Archive vs delete enforced (`ProductHasNoBatches` / `ProductHasBatches`).
- CSV import handles malformed rows with detailed error response.

Universal gates:
- `pytest backend/apps/catalog/` all green; existing `backend/apps/core/` suite remains 110/110.
- `grep -RE "from django.db.models" backend/apps/catalog/` returns empty.
- `grep -RE "from django.contrib.auth" backend/apps/catalog/` returns empty.
- `grep -RE "cursor\.execute" backend/apps/catalog/services.py backend/apps/catalog/selectors.py backend/apps/catalog/apis.py` returns empty.
- Every owner-scoped query function in `apps/catalog/queries/products.py` is `@scoped`.
- No `float(` near money/qty paths (catalog has no money columns; this is vacuous but the meta test in `apps/core/tests/unit/test_no_orm.py` continues to pass repo-wide).
- `python manage.py spectacular --file /tmp/openapi.json` runs without errors and includes the 7 catalog operations.

Specific test gates:
- Cross-owner GET / PATCH / DELETE / archive on `/products/{id}` returns 404 with `{"error": "ProductNotFound"}` and zero state change.
- `Idempotency-Key` retry on `/products/import` does not re-execute the handler (counter assertion via `_call_counter` pattern — covered by `test_idempotency.py` already; catalog test only verifies the cache hit path end-to-end).
- `archive` on a product with no batches returns 409 `ProductHasNoBatches`.
- `delete` on a product with batches (stub) returns 409 `ProductHasBatches`.
- CSV import of `name,sku,description,base_unit\nA,SKU-1,,ml\nB,SKU-2,,GALLON` returns `imported=1, failed=[{"row_index":1, "error":"ValidationError", "fields":{"base_unit":[...]}}]`.

## Notes

### Deviations and seams flagged for human input

1. **Migration numbering drift.** Issue body says `0002_catalog.sql` but `0002_auth_fk.sql` already shipped in ILEX-003. Plan uses `0003_catalog.sql`. Subsequent issues shift by one (`0004_procurement.sql`, `0005_inventory.sql`, …). SPEC §2.2 example list is now stale — flagged for a docs-cleanup pass at the end of Phase 2. **Not blocking.**
2. **`v_stock_by_batch` integration deferred.** SPEC §3.2 says `GET /products` "Includes derived on-hand totals from `v_stock_by_batch`." The view doesn't exist until Issue 006 (`batches`) + Issue 008 (`v_*` views). For ILEX-004, the list endpoint omits the on-hand field; Issue 006 or 008 amends `selectors.list_products` to compose with the view. This matches the issue's own stated scope — it lists 7 endpoints and CSV import, not the on-hand projection. **Not blocking.**
3. **SKU lock seam with batches.** Issue body says "SKU is locked once the first batch references the product"; SPEC §3.2 says PATCH on `sku` returns 409 "once any batch references the product." In ILEX-004 there are no batches yet, so the strict 409-when-batches-exist test cannot be exercised end-to-end. Plan: serializer rejects `sku` in PATCH at the 400 level (out-of-allowlist key), and `count_batches_for_product` is a stub returning 0. Issue 006 will:
   - Replace the stub with a real query against `batches`.
   - Add a service-level path that allows `sku` mutation when count==0 and rejects with 409 (`SkuLocked`) when count>0.
   - Add API tests for the 409 case.
   This split keeps ILEX-004 vertical and unblocks ILEX-005/006. **Not blocking — this is the cleanest seam.**
4. **`PATCH /products/{id}` semantics for `sku`.** Two valid reads of SPEC §3.2: (a) `sku` is rejected at the request-validation layer when batches exist (409 with detail) or always (400 unknown key); (b) `sku` is allowed when no batches exist. Plan picks (a)+(b) hybrid: serializer is strict (no `sku` key), and Issue 006 widens it conditionally. If the user wants `sku` to be mutable in ILEX-004 even with batches stub, surface in pre-execute review.
5. **`archive` vs `delete` "with batches" coverage deferred to ILEX-006.** SPEC §3.2: archive returns 409 if no batches exist (use DELETE); delete returns 409 if any batch exists (use archive). With the stub returning 0, only the no-batches paths are reachable in ILEX-004. The original plan covered the with-batches paths via `unittest.mock.patch` on `count_batches_for_product`, but per the post-ILEX-004 behavioral-tests-only rule (`.claude/skills/tdd/SKILL.md`) those tests have been removed — they monkey-patched an internal function and would not survive a refactor. ILEX-006 will add real "with batches" service + API tests once the `batches` table exists.
6. **List endpoint does not return on-hand totals.** Documented in #2 above; restated here for the executor.
7. **`POST /products` does not require Idempotency-Key.** Per SPEC §2.6 the only catalog endpoint with Idempotency-Key is `POST /products/import`. Confirmed against the endpoint catalog. Create endpoint relies on the unique `(owner_id, sku)` constraint for retry safety: a duplicate retry returns 409, idempotent in effect.

No locked decision (D0–D14) needs relitigating. No hard constraint from `docs/product.md` is at risk.
