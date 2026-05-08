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

---

## Surface

- [x] backend/ — schema (`0004_procurement.sql`), `apps/procurement/` full vertical
- [ ] frontend/
- [x] docs/ — `docs/issues/status.md` execution log

## Dependencies

- 004 — `products` table must exist for PO lines to FK against `(id, owner_id)`.
- 003 — auth required for owner injection (`request.user.id` → `owner_id: int`).
- Pre-existing: `apps/core/idempotency.py` (`@idempotent` decorator, already used by ILEX-004 catalog import), `apps/core/owner_scope.py` (`@scoped`), `apps/core/errors.py` (`DomainError` + `to_response`), `apps/core/tests/db_test.py` (`pre_db`/`post_db`).

---

## Context

### What already exists

- `backend/migrations/0001_init.sql` — `pgcrypto`, `uuidv7()` SQL fn, `idempotency_keys`.
- `backend/migrations/0002_auth_fk.sql` — retypes `idempotency_keys.owner_id → INT` and adds FK to `auth_user(id)`. **Owner FKs are `INT REFERENCES auth_user(id)` everywhere.**
- `backend/migrations/0003_catalog.sql` — `products` table with `UNIQUE(id, owner_id)` composite hook so child tables can FK against `(product_id, owner_id)` per D4.
- `backend/apps/core/owner_scope.py` — `@scoped` runtime guard (asserts `owner_id` present in `params`).
- `backend/apps/core/idempotency.py` — `@idempotent(endpoint="...")` view decorator. **Already wired and tested; reuse verbatim, no changes needed.** Endpoint identifier for receive is `"purchase_orders.receive"` per the docstring.
- `backend/apps/core/errors.py` — `DomainError`, `NotFound`, `Conflict`, `ValidationError`, `Unprocessable` + `to_response`. Reuse verbatim.
- `backend/apps/core/exceptions.py` — DRF exception handler.
- `backend/apps/catalog/services.py`, `apps/catalog/queries/products.py`, `apps/catalog/apis.py` — pattern reference for the four-layer flow + serializer-rejected unknown keys + `psycopg.connect(settings.DATABASE_URL)` per service call.
- `backend/apps/catalog/tests/conftest.py` — pattern for per-app session fixture that runs `manage.py migrate` (auth/contenttypes/sessions) + `migrate_sql` once. Mirror this in `apps/procurement/tests/conftest.py`.
- `backend/apps/core/tests/db_test.py` — `pre_db` / `post_db`. **Foundation for every DB-touching test in this issue.**
- `backend/apps/core/tests/api/test_idempotency.py` — pattern for DRF `APIRequestFactory` + `force_authenticate` + cached-body assertion. Reuse the `_make_auth_user` helper shape.
- `backend/apps/core/tests/api/test_auth_api.py` — pattern for end-to-end DRF `APIClient` signup-then-act flow used in API tests.
- `backend/settings/base.py` — append `"apps.procurement"` to `INSTALLED_APPS`.
- `backend/urls.py` — root urlconf; add `path("api/v1/", include("apps.procurement.urls"))`.

### Spec reference

- SPEC §3.3 — endpoint table, receive flow, validation envelope.
- SPEC §2.6 — Idempotency-Key required on `POST /purchase-orders/{id}/receive`; offset pagination for `/purchase-orders`; error envelope `{ "error", "detail"?, "fields"? }`; cross-owner = 404.
- SPEC §2.5 — money/qty are `Decimal` in Python and `numeric(14, 4)` in DB. `unit_cost` and `quantity` columns on PO lines are money/qty paths.
- SPEC §4 (Procurement row) — "PO draft CRUD works; receive creates batches + movements atomically; received PO is immutable (PATCH/DELETE return 409); idempotency key prevents double-receive on retry."
- `docs/decisions.md` — D0, D4, D6, D10, D14.
- `docs/architecture/architecture.md` §"File Locations", §"Naming Conventions".

### Decisions already made that affect this issue

- **D0** — Header (`purchase_orders`) + lines (`purchase_order_lines`). Multi-product POs. Batches FK to a line, not a PO.
- **D4** — Owner isolation: `owner_id INT NOT NULL REFERENCES auth_user(id)` on every owner-scoped table. Composite UNIQUE `(id, owner_id)` on `purchase_orders` AND `purchase_order_lines` so future tables compose `(line_id, owner_id) → purchase_order_lines(id, owner_id)`. `purchase_order_lines` FK to `products` is composite `(product_id, owner_id) → products(id, owner_id)`. Cross-owner returns 404, never 403.
- **D6** — Two states: `draft | received`. PATCH/DELETE on `received` → 409. Corrections after terminal use reversal movements (Issue 006/007 territory).
- **D10** — `supplier_name TEXT NOT NULL`, `supplier_contact TEXT NULL`. No separate `suppliers` table.
- **D14** — No Django ORM. Owner is `INT` referencing `auth_user(id)`.
- **Idempotency-Key required only on `POST /purchase-orders/{id}/receive`** (SPEC §2.6). Draft create/patch/delete/list/detail are not idempotent (clients can retry safely on 409 after duplicate creation).
- **Migration numbering correction:** issue body says `0003_procurement.sql` but `0003_catalog.sql` shipped in ILEX-004. **Actual filename is `0004_procurement.sql`.** Subsequent issues shift by one (`0005_inventory.sql`, `0006_sales.sql`, …). Already flagged in ILEX-004 Notes; restated here for the executor. Not blocking.

---

## Plan

### Schema and SQL — `backend/migrations/0004_procurement.sql`

DDL sketch:

```sql
-- 0004_procurement.sql — purchase_orders + purchase_order_lines.
--
-- Owner isolation (D4):
--   - owner_id INT NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE
--   - UNIQUE (id, owner_id) on both tables (composite hook for child FKs)
--   - lines FK to products via composite (product_id, owner_id) → products(id, owner_id)
--   - lines FK to purchase_orders via composite (purchase_order_id, owner_id)
--
-- Lifecycle (D6): two states — draft | received. Terminal is immutable.
--   Service layer enforces immutability (PATCH/DELETE on received → 409).
--   Schema enforces the enum via CHECK.
--
-- Supplier (D10): text supplier_name (NOT NULL), nullable supplier_contact.
--
-- Money/qty (SPEC §2.5): numeric(14, 4) for quantity and unit_cost.
--
-- received_at: NULL while draft; NOW() when receive succeeds.
-- Composite FK from batches.purchase_order_line_id is added in 0005_inventory.sql
-- (Issue 006), not here — keeps 0004 independent of 0005.

CREATE TABLE IF NOT EXISTS purchase_orders (
    id                UUID         PRIMARY KEY DEFAULT uuidv7(),
    owner_id          INT          NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    supplier_name     TEXT         NOT NULL,
    supplier_contact  TEXT         NULL,
    status            TEXT         NOT NULL DEFAULT 'draft',
    received_at       TIMESTAMPTZ  NULL,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT purchase_orders_id_owner_unique UNIQUE (id, owner_id),
    CONSTRAINT purchase_orders_status_chk CHECK (status IN ('draft', 'received')),
    -- received_at must be NULL for drafts and non-NULL once received
    CONSTRAINT purchase_orders_received_at_chk
        CHECK ((status = 'draft' AND received_at IS NULL)
            OR (status = 'received' AND received_at IS NOT NULL)),
    CONSTRAINT purchase_orders_supplier_name_not_blank
        CHECK (length(trim(supplier_name)) > 0)
);

CREATE INDEX IF NOT EXISTS purchase_orders_owner_status_idx
    ON purchase_orders (owner_id, status);

CREATE INDEX IF NOT EXISTS purchase_orders_owner_created_idx
    ON purchase_orders (owner_id, created_at DESC);


CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id                  UUID            PRIMARY KEY DEFAULT uuidv7(),
    owner_id            INT             NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    purchase_order_id   UUID            NOT NULL,
    product_id          UUID            NOT NULL,
    quantity            NUMERIC(14, 4)  NOT NULL,
    unit_cost           NUMERIC(14, 4)  NOT NULL,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4 composite FK: line stays inside the PO's owner.
    CONSTRAINT pol_po_owner_fkey
        FOREIGN KEY (purchase_order_id, owner_id)
        REFERENCES purchase_orders (id, owner_id)
        ON DELETE CASCADE,

    -- D4 composite FK: line's product stays inside the same owner's catalog.
    CONSTRAINT pol_product_owner_fkey
        FOREIGN KEY (product_id, owner_id)
        REFERENCES products (id, owner_id),

    -- Composite hook for batches (Issue 006): batches FK against (line_id, owner_id).
    CONSTRAINT pol_id_owner_unique UNIQUE (id, owner_id),

    -- Money/qty positivity (SPEC §2.5; brief: positive sell prices and quantities).
    CONSTRAINT pol_quantity_positive CHECK (quantity > 0),
    CONSTRAINT pol_unit_cost_nonneg  CHECK (unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS pol_owner_po_idx
    ON purchase_order_lines (owner_id, purchase_order_id);

CREATE INDEX IF NOT EXISTS pol_owner_product_idx
    ON purchase_order_lines (owner_id, product_id);
```

Round-trip / constraint tests expected (`tests/query/`):
- Insert minimal `purchase_orders` row → defaults populate (`status='draft'`, `received_at IS NULL`, timestamps non-NULL).
- `status` CHECK rejects `'shipped'`.
- `received_at` CHECK rejects `(status='draft', received_at=NOW())` and `(status='received', received_at=NULL)`.
- Composite UNIQUE `(id, owner_id)` introspectable via `pg_constraint`.
- Inserting a line with `(purchase_order_id, owner_id)` mismatched against the PO's owner is rejected by the composite FK (cross-owner data fusion bug fails at INSERT, not silently — D4 substrate).
- Inserting a line with `(product_id, owner_id)` not matching a product the owner owns is rejected by the composite FK.
- Inserting a line with `quantity = 0` or `unit_cost = -1` rejected by CHECKs.

### Service layer — `backend/apps/procurement/services.py`

All functions kwarg-only (past `owner_id` / `po_id`), type-annotated, raise typed exceptions from `apps/procurement/errors.py`. Transactional services use `with conn.transaction():`.

```python
def create_purchase_order_draft(
    *,
    owner_id: int,
    supplier_name: str,
    supplier_contact: str | None,
    lines: list[NewLine],     # [{product_id, quantity, unit_cost}]
) -> PurchaseOrderRow: ...

def update_purchase_order_draft(
    *,
    owner_id: int,
    po_id: UUID,
    supplier_name: str | None = None,
    supplier_contact: str | None = None,
    lines: list[NewLine] | None = None,    # replace-style; if provided, replaces ALL lines
) -> PurchaseOrderRow: ...

def delete_purchase_order_draft(
    *,
    owner_id: int,
    po_id: UUID,
) -> None: ...

def receive_purchase_order(
    *,
    owner_id: int,
    po_id: UUID,
    line_metadata: list[ReceiveLineMeta],   # [{line_id, batch_code, expiration_date?}]
) -> PurchaseOrderRow: ...
```

`PurchaseOrderRow` (`apps/procurement/types.py`):

```python
class PurchaseOrderLineRow(TypedDict):
    id: str
    purchase_order_id: str
    product_id: str
    quantity: str        # Decimal serialized as string (SPEC §2.5)
    unit_cost: str
    created_at: Any

class PurchaseOrderRow(TypedDict):
    id: str
    owner_id: int
    supplier_name: str
    supplier_contact: str | None
    status: str          # 'draft' | 'received'
    received_at: Any
    created_at: Any
    updated_at: Any
    lines: list[PurchaseOrderLineRow]
```

Behavior summary:

| Service | Reads | Writes | Errors |
|---|---|---|---|
| `create_purchase_order_draft` | none beyond input | INSERT header + N lines (single tx) | `ValidationError` if `lines` empty; composite-FK `ForeignKeyViolation` on cross-owner / unknown product mapped to `ProductNotFound` (404, D4 — owner cannot see other owners' products) |
| `update_purchase_order_draft` | SELECT header by `(id, owner_id)` | UPDATE header fields; if `lines` provided, DELETE then INSERT all lines (replace-style) — single tx | `PurchaseOrderNotFound` (404); `PurchaseOrderNotDraft` (409) when `status='received'`; `ValidationError` on empty `lines`; `ProductNotFound` (404) on FK violation |
| `delete_purchase_order_draft` | SELECT header by `(id, owner_id)` | DELETE header (lines cascade) | `PurchaseOrderNotFound` (404); `PurchaseOrderNotDraft` (409) when received |
| `receive_purchase_order` | SELECT header + lines `FOR UPDATE`; verify `line_metadata` matches lines 1:1 | UPDATE header `status='received', received_at=NOW()`; **delegate batch + movement creation to `apps.inventory.services.create_receipt_batches` once it exists in Issue 006**; until then this code path is unreachable end-to-end (see "Implementation phasing" below) | `PurchaseOrderNotFound`; `PurchaseOrderAlreadyReceived` (409); `ValidationError` on empty `batch_code` / mismatched line ids / invalid date format |

**Critical layering decision — receive's coupling to inventory:**

The receive flow writes to three tables: `purchase_orders` (header status), `batches` (one per line), `stock_movements` (one receipt per batch). `batches` and `stock_movements` are owned by `apps.inventory` and don't exist (table-wise or service-wise) until Issue 006.

Two options:

1. **Inline the SQL in `apps.procurement.services.receive_purchase_order` now**, deferring the actual writes via `if INVENTORY_TABLES_EXIST:` probe (mirroring the catalog `count_batches_for_product` stub pattern). **Rejected** — couples procurement to inventory's table shapes, and Issue 006 would have to delete the procurement-side SQL and re-add it as an `apps.inventory` service. Wastes one round-trip of design.

2. **Plan receive as a public seam now and defer the inventory-touching half to Issue 006.** In ILEX-005, `receive_purchase_order` performs its own header transition (`status='received', received_at=NOW()`) and validates `line_metadata` shape, then **calls a yet-to-exist `apps.inventory.services.create_receipt_batches(owner_id, lines_with_metadata)`** which is imported at module top per the discipline rule. To keep ILEX-005 testable end-to-end, ship a minimal `apps/inventory/services.py` stub in this issue that exposes `create_receipt_batches(...)` returning `[]` and raises `NotImplementedError` if the `batches` table is absent. Issue 006 replaces the body and lands the schema. **Chosen.** See "Implementation phasing".

`apps/inventory/__init__.py` and `apps/inventory/services.py` are pre-created in this issue with the minimal stub; the discipline gate (`grep -nE "^\s+(from|import) apps\." backend/apps/**/*.py`) stays clean because the import is module-top.

**Owner-scope handling** — every service receives `owner_id: int` from the API layer. Query functions (`apps/procurement/queries/*.py`) wrap their SQL with `@scoped` and use `WHERE owner_id = %(owner_id)s`. The SELECTs return None on cross-owner; service maps to `PurchaseOrderNotFound`.

### Queries layer — `backend/apps/procurement/queries/`

Two modules, one per aggregate:

**`apps/procurement/queries/purchase_orders.py`** — header-level:

- `insert_purchase_order(cur, *, params)` — `INSERT INTO purchase_orders (...) VALUES (...) RETURNING *`. Params: `owner_id, supplier_name, supplier_contact`. Status defaults to `'draft'`.
- `select_purchase_order_by_id(cur, *, params)` — `SELECT * FROM purchase_orders WHERE id = %(id)s AND owner_id = %(owner_id)s`. Returns `dict | None`.
- `select_purchase_order_for_update(cur, *, params)` — same SELECT with `FOR UPDATE` (used by receive to lock row during the receive transaction).
- `update_purchase_order_header(cur, *, params)` — UPDATE `supplier_name`/`supplier_contact` on `(id, owner_id)`. Composes SQL based on which fields are non-None (matches catalog `update_product_fields` pattern). Returns `dict | None`.
- `mark_purchase_order_received(cur, *, params)` — `UPDATE ... SET status='received', received_at=NOW(), updated_at=NOW() WHERE id=... AND owner_id=... AND status='draft' RETURNING *`. Returns None if no row matched (already received OR cross-owner OR missing) — caller distinguishes via prior SELECT.
- `delete_purchase_order(cur, *, params)` — `DELETE FROM purchase_orders WHERE id=... AND owner_id=... AND status='draft'`. Returns rowcount. Service reads status before calling so the service can return the precise error code (`PurchaseOrderNotFound` vs `PurchaseOrderNotDraft`).
- `list_purchase_orders(cur, *, params)` — paginated SELECT with optional `status` filter, supplier ILIKE search, `from`/`to` date range. `ORDER BY created_at DESC, id DESC LIMIT/OFFSET`. Returns `(rows, total)`.

**`apps/procurement/queries/purchase_order_lines.py`** — line-level:

- `insert_purchase_order_line(cur, *, params)` — INSERT one line. RETURNING *. Params: `owner_id, purchase_order_id, product_id, quantity, unit_cost`.
- `delete_lines_for_purchase_order(cur, *, params)` — `DELETE FROM purchase_order_lines WHERE purchase_order_id = %(purchase_order_id)s AND owner_id = %(owner_id)s`. Used by replace-style PATCH.
- `select_lines_for_purchase_order(cur, *, params)` — `SELECT * FROM purchase_order_lines WHERE purchase_order_id=... AND owner_id=... ORDER BY created_at ASC, id ASC`. Returns list of dicts.
- `select_lines_for_update(cur, *, params)` — same SELECT with `FOR UPDATE` (locks lines while receive is in flight).

Every function decorated `@scoped`. Named-param SQL (`%(owner_id)s`). Caller (service) provides cursor and owns the transaction.

**Money/qty in queries:** `quantity` and `unit_cost` are passed as Python `Decimal` in the params dict; psycopg adapts `Decimal` → `numeric` natively. Never `float()`.

### Serializers — `backend/apps/procurement/serializers.py`

DRF strict mode (reject unknown body keys via `validate(attrs)` raising `ValidationError`):

- `LineCreateRequest` — `product_id` (UUID), `quantity` (`DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))`), `unit_cost` (`DecimalField(..., min_value=Decimal("0"))`).
- `PurchaseOrderCreateRequest` — `supplier_name` (CharField, non-blank), `supplier_contact` (optional, allow_blank=True, allow_null=True), `lines` (`ListField(child=LineCreateRequest, min_length=1)`).
- `PurchaseOrderUpdateRequest` — all fields optional; `lines` optional but if present, replace-style with `min_length=1`. Reject any unknown body key (e.g. `status`, `received_at`).
- `ReceiveLineRequest` — `line_id` (UUID), `batch_code` (non-blank), `expiration_date` (optional ISO date or null).
- `PurchaseOrderReceiveRequest` — `lines` (`ListField(child=ReceiveLineRequest, min_length=1)`).
- `PurchaseOrderLineResponse` — `id`, `product_id`, `quantity` (string), `unit_cost` (string), `created_at`.
- `PurchaseOrderResponse` — `id`, `supplier_name`, `supplier_contact`, `status`, `received_at`, `created_at`, `updated_at`, `lines: [PurchaseOrderLineResponse]`. `quantity`/`unit_cost` serialize as JSON strings (SPEC §2.5).
- `PurchaseOrderListResponse` — `{ items, total, limit, offset }`.

Use `DecimalField(coerce_to_string=True)` so the wire format is a string per SPEC §2.5.

### APIs — `backend/apps/procurement/apis.py`

One `APIView` class per resource scope. All `@extend_schema`-annotated (drf-spectacular). All `permission_classes = [IsAuthenticated]`. All read `owner_id` from `request.user.id`.

- `PurchaseOrderListApi` — GET `/purchase-orders` (offset pagination + `?status=`, `?search=`, `?from=`, `?to=`, `?limit=`, `?offset=`); POST `/purchase-orders` (create draft).
- `PurchaseOrderDetailApi` — GET / PATCH / DELETE `/purchase-orders/{po_id}`. PATCH validates body via `PurchaseOrderUpdateRequest`; DELETE returns 204.
- `PurchaseOrderReceiveApi` — POST `/purchase-orders/{po_id}/receive`. Decorated with `@idempotent("purchase_orders.receive")`. Validates body via `PurchaseOrderReceiveRequest`. Calls `services.receive_purchase_order(...)`.

Pattern: validate serializer → call service → catch `DomainError` → `to_response`. Response body shaped via `PurchaseOrderResponse`.

### Selectors — `backend/apps/procurement/selectors.py`

Read-only composition over query functions. No transactions.

- `purchase_order_by_id(*, owner_id, po_id)` → `PurchaseOrderRow | None`. Reads header + lines, assembles the nested response shape.
- `list_purchase_orders(*, owner_id, status, search, date_from, date_to, limit, offset)` → `{ items, total, limit, offset }`. The list response includes lines for each PO (cheap because POs are typically small — 1 to ~20 lines; if perf becomes an issue, add a separate "summary" projection later, flagged in Notes).

### Errors — `backend/apps/procurement/errors.py`

```python
from apps.core.errors import Conflict, NotFound, ValidationError

class PurchaseOrderNotFound(NotFound):
    code = "PurchaseOrderNotFound"

class PurchaseOrderNotDraft(Conflict):
    code = "PurchaseOrderNotDraft"

class PurchaseOrderAlreadyReceived(Conflict):
    code = "PurchaseOrderAlreadyReceived"

class ProductNotFound(NotFound):
    code = "ProductNotFound"   # Re-raised when a line's product_id is unknown for the owner

class ReceiveLinesMismatch(ValidationError):
    code = "ReceiveLinesMismatch"   # body's line_ids don't match the PO's lines exactly
```

(`ProductNotFound` is also defined in `apps.catalog.errors`. We deliberately introduce a second class with the same `code` here to avoid an `apps.procurement → apps.catalog` import; the wire-level error code is identical so clients can't distinguish, which is the point. Alternative considered: import from `apps.catalog.errors`. Either is fine; planning chooses the local definition to keep procurement self-contained. Flag in Notes.)

### URL routing — `backend/apps/procurement/urls.py`

```python
urlpatterns = [
    path("purchase-orders", PurchaseOrderListApi.as_view(), name="po-list"),
    path("purchase-orders/<uuid:po_id>", PurchaseOrderDetailApi.as_view(), name="po-detail"),
    path("purchase-orders/<uuid:po_id>/receive", PurchaseOrderReceiveApi.as_view(), name="po-receive"),
]
```

Mount in `backend/urls.py` — one new line:

```python
path("api/v1/", include("apps.procurement.urls")),
```

### Tests (write FIRST per TDD)

Mirror catalog's tree: `apps/procurement/tests/{unit,query,service,api}/`. Local `conftest.py` reuses the catalog/core pattern to apply ORM migrations + `migrate_sql` once per session (copy from `apps/catalog/tests/conftest.py` verbatim).

#### Unit (`apps/procurement/tests/unit/`)

Pure-logic only. No DB.

- `test_serializers.py`:
  - `PurchaseOrderCreateRequest` rejects empty `lines` (400).
  - `LineCreateRequest` rejects `quantity <= 0` and `unit_cost < 0`.
  - `PurchaseOrderUpdateRequest` rejects unknown body key (e.g. `status`, `received_at`) via custom `validate()`.
  - `ReceiveLineRequest` rejects blank `batch_code`; accepts `null` `expiration_date`; rejects malformed date string.
  - `PurchaseOrderResponse` serializes `quantity`/`unit_cost` as string (`"10.0000"`) not number.
- `test_errors.py`:
  - `to_response(PurchaseOrderNotDraft())` → `({"error": "PurchaseOrderNotDraft"}, 409)`.
  - `to_response(PurchaseOrderNotFound())` → `({"error": "PurchaseOrderNotFound"}, 404)`.

#### Query (`apps/procurement/tests/query/`)

Real Postgres. Uses `pre_db`/`post_db`. Behavioral — describe SQL behavior at the public function level, not internal SQL strings.

- `test_purchase_orders_queries.py`:
  - `test_insert_purchase_order_round_trip` — pre_db `auth_user`; insert via `insert_purchase_order`; `post_db` checks header columns + defaults (`status='draft'`, `received_at IS NULL`).
  - `test_status_chk_rejects_invalid_value` — direct INSERT with `status='shipped'` raises `psycopg.errors.CheckViolation` matching `purchase_orders_status_chk`.
  - `test_received_at_chk_rejects_inconsistent_state` — INSERTing `(status='draft', received_at=NOW())` and `(status='received', received_at=NULL)` both raise `CheckViolation`.
  - `test_id_owner_unique_present` — `pg_constraint` introspection asserts `purchase_orders_id_owner_unique` exists.
  - `test_select_returns_none_for_cross_owner` — insert PO for owner A; SELECT with owner B → None.
  - `test_mark_received_only_from_draft` — call once → row updated; call again → returns None (idempotency at the SQL level; service distinguishes).
  - `test_list_paginates_and_filters_by_status` — seed 3 drafts + 2 received for owner A, 1 draft for owner B; assert filtering and isolation.
  - `test_scoped_decorator_blocks_missing_owner` — call any function without `owner_id` → ValueError.
- `test_purchase_order_lines_queries.py`:
  - `test_insert_line_round_trip` — pre_db PO; insert line; post_db row matches; `quantity` and `unit_cost` round-trip as `Decimal` (no float drift).
  - `test_line_composite_fk_to_po_owner` — INSERT a line where `(purchase_order_id, owner_id)` doesn't match the PO's `(id, owner_id)` (e.g. owner_id mismatch) → `ForeignKeyViolation` matching `pol_po_owner_fkey`. **Substrate test for D4.**
  - `test_line_composite_fk_to_product_owner` — INSERT a line where `(product_id, owner_id)` is a product belonging to a different owner → `ForeignKeyViolation` matching `pol_product_owner_fkey`.
  - `test_line_quantity_positive_chk` — `quantity = 0` → CheckViolation.
  - `test_line_unit_cost_nonneg_chk` — `unit_cost = -1` → CheckViolation.
  - `test_delete_lines_cascade_via_po_delete` — delete PO; lines gone via `ON DELETE CASCADE`.
  - `test_select_lines_returns_only_owner_scope` — pre_db two POs (one per owner) each with 1 line; `select_lines_for_purchase_order(owner=A, po_id=A's PO)` returns 1 line; same call with owner=B against A's PO returns `[]` (D4).

#### Service (`apps/procurement/tests/service/`)

Real Postgres. Behavioral — assert on return value + `post_db`. Owner-scope cross-owner = 404.

- `test_create_purchase_order_draft.py`:
  - happy path: 2 lines → header inserted with `status='draft'`; lines persisted; return value's `lines` array matches input order.
  - empty `lines` → `ValidationError`.
  - cross-owner product (line references a product owned by another user) → `ProductNotFound` (the composite FK violation maps to 404, never 403). State unchanged (pre_db == post_db).
- `test_update_purchase_order_draft.py`:
  - update `supplier_name` only → header changes, lines untouched.
  - replace lines (provide `lines`) → old lines deleted, new lines inserted; counts match.
  - update on received PO → `PurchaseOrderNotDraft`; pre_db == post_db.
  - cross-owner update → `PurchaseOrderNotFound` (D4).
  - replace with empty `lines` → `ValidationError`.
- `test_delete_purchase_order_draft.py`:
  - delete draft → header gone, lines cascade.
  - delete received → `PurchaseOrderNotDraft`.
  - cross-owner delete → `PurchaseOrderNotFound`; pre_db == post_db.
- `test_receive_purchase_order.py`:
  - receive on missing PO → `PurchaseOrderNotFound`.
  - receive on already-received PO → `PurchaseOrderAlreadyReceived` (409).
  - receive with `line_metadata` whose `line_id`s don't match the PO's lines exactly → `ReceiveLinesMismatch` (400).
  - cross-owner receive → `PurchaseOrderNotFound`.
  - **happy path is deferred to ILEX-006.** The header transition + delegation to `apps.inventory.services.create_receipt_batches` is real, but `create_receipt_batches` doesn't write batches/movements until 006. The "received_at populated, status flipped to 'received'" assertion still works in this issue against the procurement-only effects; **the batch + movement post_db assertions are out of scope here and are added in 006's service tests.** Document this seam in the test docstring with a TODO referencing ILEX-006.

  Specifically, the ILEX-005 happy-path test asserts:
  - return value has `status='received'`, `received_at IS NOT NULL`.
  - `post_db` of `purchase_orders` shows the row updated.
  - **no assertion about batches/movements — those tables don't exist yet.**

  When 006 lands, that test is amended (not replaced) to add the batches/movements `post_db` block.

  **Behavioral discipline:** no `unittest.mock.patch("apps.inventory.services.create_receipt_batches")` and no monkey-patching. The real function is called; its 005-version is a no-op stub that returns an empty list. The test exercises real code, which is what TDD's behavioral rule demands.

#### API (`apps/procurement/tests/api/`)

Real DRF `APIClient`. Each test signs up a fresh user via `/api/v1/auth/signup` to get a session cookie (pattern from `apps/core/tests/api/test_auth_api.py`).

- `test_purchase_orders_crud.py`:
  - `POST /purchase-orders` happy path with 2 lines → 200 + `status='draft'` + lines echoed.
  - `POST /purchase-orders` with empty `lines` → 400 `ValidationError`.
  - `POST /purchase-orders` with cross-owner `product_id` (signup user B, post under user A's session referencing B's product — but wait, the product MUST belong to the session user; impossible to reference cross-owner product since there's no way to obtain B's id without the user's catalog. Test variant: post a random UUID as `product_id` → composite FK violation → service maps to `ProductNotFound` → 404 with `{"error":"ProductNotFound"}`.
  - `GET /purchase-orders/{id}` cross-owner → 404 `PurchaseOrderNotFound`. **Mandatory owner-scope test.**
  - `PATCH /purchase-orders/{id}` on received → 409 `PurchaseOrderNotDraft` (set up by calling receive in the test then PATCH).
  - `DELETE /purchase-orders/{id}` on received → 409.
  - `DELETE /purchase-orders/{id}` on draft → 204; subsequent `GET` → 404.
- `test_purchase_orders_list.py`:
  - empty → `{"items":[], "total":0, ...}`.
  - mix of draft + received → `?status=draft` filters correctly.
  - `?search=acme` matches `supplier_name` ILIKE.
  - pagination: `?limit=1&offset=1` returns the second item.
- `test_purchase_orders_receive.py`:
  - missing `Idempotency-Key` header → 400 `ValidationError` ("Idempotency-Key header required").
  - receive a draft → 200, `status='received'`, `received_at` non-null. **The batch + movement assertions are deferred to ILEX-006 API tests** (since the inventory service is a no-op stub here). This issue's API test asserts only the response shape and the procurement-side state.
  - receive an already-received PO with the same `Idempotency-Key` → cached body returned (status code identical, no double-execution; assert via a counter on the service or via direct DB inspection that `received_at` didn't change between two retries with the same key).
  - receive an already-received PO with a *different* `Idempotency-Key` → 409 `PurchaseOrderAlreadyReceived`.
  - cross-owner receive → 404.
- `test_purchase_orders_auth.py`:
  - any procurement endpoint without session → 401.

#### Behavioral discipline checklist for these tests

Per the tightened `tdd/SKILL.md`:

- No `unittest.mock.patch` of `apps.procurement.queries.*` or `apps.inventory.services.*`. Tests exercise real code.
- No imports of `_private` helpers. Every test's import statement only references public symbols (`from apps.procurement.services import receive_purchase_order`, etc.).
- No call-counter spies on internal procurement functions. Idempotency is asserted via observable state: `post_db` of `purchase_orders` (`received_at` unchanged across two retries with the same key) and the cached HTTP body matching byte-for-byte.
- The "with batches" / receive-end-to-end ledger assertion is wrong-layered for ILEX-005 (the underlying feature doesn't exist yet) and is deferred to ILEX-006. Per the rule: "If an edge case is only reachable through a private helper or a monkey-patch, the test belongs at a higher layer (service or HTTP) where the case is real — or the case must be deferred until the underlying feature exists." We pick "deferred" — explicitly.

### Implementation phasing (TDD red-green-refactor)

Order respects layer-flow rules. Imports go at module top throughout per `ilex-discipline/SKILL.md` invariant #6 — no function-local `from apps.X import Y` anywhere in non-test code.

1. **Schema** — write `0004_procurement.sql`. `manage.py migrate_sql` against scratch DB. `\d+ purchase_orders` and `\d+ purchase_order_lines` confirm columns + constraints.
2. **Inventory stub** — pre-create `backend/apps/inventory/__init__.py` and `backend/apps/inventory/services.py` with one function:

   ```python
   # backend/apps/inventory/services.py
   from __future__ import annotations
   from typing import Any
   def create_receipt_batches(*, owner_id: int, lines: list[dict[str, Any]]) -> list[dict]:
       """Stub. Issue 006 implements batch + receipt-movement creation."""
       return []
   ```

   This file ships in ILEX-005 specifically so `apps.procurement.services` can `from apps.inventory.services import create_receipt_batches` at module top and the discipline gate stays clean. Issue 006 replaces the body and lands `0005_inventory.sql`.
3. **Errors + types** — `apps/procurement/errors.py`, `apps/procurement/types.py`.
4. **Query layer** — write `tests/query/test_*.py` (red); implement `queries/purchase_orders.py` and `queries/purchase_order_lines.py` (green); refactor (extract `_row_to_dict` if duplicated; otherwise keep inline).
5. **Service layer** — write `tests/service/test_*.py` (red); implement `services.py` (green). Imports at module top: `from apps.inventory.services import create_receipt_batches`. Refactor: factor out a `_load_po_with_lines` helper if read paths in update/delete/receive duplicate.
6. **Selectors** — `selectors.py`. Tests live in service layer (selectors are thin).
7. **Serializers** — write `tests/unit/test_serializers.py` (red); implement `serializers.py`.
8. **APIs** — write `tests/api/test_*.py` (red); implement `apis.py`, `urls.py`. Wire root `urls.py`.
9. **OpenAPI smoke** — `python manage.py spectacular --file /tmp/openapi.json` succeeds; the 6 procurement operations appear.
10. **Refactor pass** — collapse duplicated psycopg-connect boilerplate if reused 2+ times. Confirm no function-local imports. Confirm no `cursor.execute` outside `queries/`.

### Integration / wiring

- `backend/settings/base.py` — append `"apps.procurement"` to `INSTALLED_APPS`. Append `"apps.inventory"` (the stub from step 2). The inventory stub does not register URLs in this issue.
- `backend/urls.py` — add `path("api/v1/", include("apps.procurement.urls"))`.
- `backend/migrations/0004_procurement.sql` — new file; runner picks it up automatically.
- OpenAPI: drf-spectacular auto-generates from `@extend_schema`-annotated views. No FE work in this issue (Issue 010).
- TanStack Query keys / hooks: N/A (FE separate repo, type regen in Issue 010).

### Documentation to update

- `docs/issues/status.md` — flip ILEX-005 to `planned`; append Execution Log entry summarizing this plan.
- **No `docs/specs/SPEC.md` rewrite.** SPEC §3.3 is correct; the migration-numbering drift (now `0004_procurement.sql` instead of `0003_procurement.sql`) is cosmetic and was already flagged in ILEX-004 Notes. A docs cleanup pass at the end of Phase 2 will reconcile §2.2's example list.
- **No `docs/decisions.md` change** — D0/D4/D6/D10 cover this issue.
- **No `.claude/CLAUDE.md` change** — no new convention introduced.

---

## Files involved

Created:
- `backend/migrations/0004_procurement.sql`
- `backend/apps/procurement/__init__.py`
- `backend/apps/procurement/apis.py`
- `backend/apps/procurement/serializers.py`
- `backend/apps/procurement/services.py`
- `backend/apps/procurement/selectors.py`
- `backend/apps/procurement/errors.py`
- `backend/apps/procurement/types.py`
- `backend/apps/procurement/urls.py`
- `backend/apps/procurement/queries/__init__.py`
- `backend/apps/procurement/queries/purchase_orders.py`
- `backend/apps/procurement/queries/purchase_order_lines.py`
- `backend/apps/procurement/tests/__init__.py`
- `backend/apps/procurement/tests/conftest.py`
- `backend/apps/procurement/tests/unit/__init__.py`
- `backend/apps/procurement/tests/unit/test_serializers.py`
- `backend/apps/procurement/tests/unit/test_errors.py`
- `backend/apps/procurement/tests/query/__init__.py`
- `backend/apps/procurement/tests/query/test_purchase_orders_queries.py`
- `backend/apps/procurement/tests/query/test_purchase_order_lines_queries.py`
- `backend/apps/procurement/tests/service/__init__.py`
- `backend/apps/procurement/tests/service/test_create_purchase_order_draft.py`
- `backend/apps/procurement/tests/service/test_update_purchase_order_draft.py`
- `backend/apps/procurement/tests/service/test_delete_purchase_order_draft.py`
- `backend/apps/procurement/tests/service/test_receive_purchase_order.py`
- `backend/apps/procurement/tests/api/__init__.py`
- `backend/apps/procurement/tests/api/test_purchase_orders_crud.py`
- `backend/apps/procurement/tests/api/test_purchase_orders_list.py`
- `backend/apps/procurement/tests/api/test_purchase_orders_receive.py`
- `backend/apps/procurement/tests/api/test_purchase_orders_auth.py`
- `backend/apps/inventory/__init__.py`
- `backend/apps/inventory/services.py` (stub — body filled in by ILEX-006)

Modified:
- `backend/settings/base.py` (append `apps.procurement` and `apps.inventory` to `INSTALLED_APPS`)
- `backend/urls.py` (include `apps.procurement.urls`)
- `docs/issues/status.md`

---

## Acceptance criteria

Spec gates (SPEC §4 "Procurement" row):
- PO draft CRUD works.
- Receive flips status to `received`, populates `received_at`. **Atomic batch + movement creation deferred to ILEX-006** — flagged in Notes.
- Received PO is immutable: PATCH/DELETE return 409 `PurchaseOrderNotDraft`.
- Idempotency-Key prevents double-receive on retry (cached body returned; `received_at` unchanged across retries).

Universal gates:
- `pytest backend/apps/procurement/` all green.
- Pre-existing suite stays green: `pytest backend/apps/{core,catalog}/` unchanged.
- `grep -RE "from django.db.models" backend/apps/procurement/` returns empty.
- `grep -RE "from django.contrib.auth" backend/apps/procurement/` returns empty.
- `grep -RE "cursor\.execute" backend/apps/procurement/services.py backend/apps/procurement/selectors.py backend/apps/procurement/apis.py` returns empty.
- `grep -nE "^\s+(from|import) apps\." backend/apps/procurement/**/*.py` returns no results outside `tests/` (no function-local imports).
- Every owner-scoped query function in `apps/procurement/queries/*.py` is decorated `@scoped`.
- No `float(` near money/qty paths in procurement (`Decimal` end-to-end).
- `python manage.py spectacular --file /tmp/openapi.json` runs without errors and includes the 6 procurement operations.

Specific test gates (named):
- Cross-owner GET / PATCH / DELETE / receive on `/purchase-orders/{id}` returns 404 `{"error":"PurchaseOrderNotFound"}` and zero state change.
- `Idempotency-Key` retry on `/purchase-orders/{id}/receive` does not re-execute the handler — cached body returned, `received_at` unchanged.
- Substrate D4 query test: line INSERT with mismatched owner on `(purchase_order_id, owner_id)` raises `ForeignKeyViolation` matching `pol_po_owner_fkey`.
- Substrate D4 query test: line INSERT with cross-owner `(product_id, owner_id)` raises `ForeignKeyViolation` matching `pol_product_owner_fkey`.
- `quantity = 0` and `unit_cost = -1` rejected by CHECK constraints.
- `status` CHECK rejects `'shipped'`; `received_at` CHECK rejects mismatched `(status, received_at)` pairs.

---

## Notes

### Deviations and seams flagged for human input

1. **Migration numbering drift restated.** Issue body says `0003_procurement.sql`; actual filename is `0004_procurement.sql` because `0003_catalog.sql` shipped in ILEX-004. Plan uses `0004_procurement.sql`. The full sequence going forward: `0004_procurement, 0005_inventory, 0006_sales, 0007_views, 0008_indexes`. Already flagged in ILEX-004 Notes; restated here for the executor. **Not blocking.**

2. **Receive's atomic batch + movement creation deferred to ILEX-006.** The receive flow per SPEC §3.3 step 3 inserts into three tables atomically: `purchase_orders` (header), `batches` (one per line), `stock_movements` (one receipt per batch). `batches` and `stock_movements` schemas don't exist until `0005_inventory.sql` (ILEX-006). Plan: ship `apps/inventory/services.py` as a stub returning `[]` from `create_receipt_batches(...)`. ILEX-005's `receive_purchase_order` performs the header transition + validation + delegates to `create_receipt_batches` (real call, real code path, no monkey-patching). ILEX-006 replaces the stub body with real INSERTs + amends ILEX-005's receive service test to add the `batches`/`stock_movements` `post_db` block. **This is the cleanest seam given the issue dependency chain. Not blocking.**

   Alternative considered (rejected): inline batch/movement SQL in `apps.procurement.services` now via `if INVENTORY_TABLES_EXIST` probe. Rejected because it (a) couples procurement to inventory's table shapes prematurely, (b) duplicates work in 006 (delete from procurement, re-add in inventory), and (c) puts SQL in the wrong app's `queries/` directory.

3. **`@idempotent` cache + 409 path interplay.** When the same `Idempotency-Key` is replayed against an already-received PO:
   - On the first retry, the cache hit returns the original 200 OK with the original body.
   - On a *fresh* `Idempotency-Key` against the same already-received PO, the service raises `PurchaseOrderAlreadyReceived` → 409.

   Both paths are tested. The behavior matches SPEC §2.6's intent: idempotency keys cache the response *as-is*, including business semantics. **No spec change needed.**

4. **`ProductNotFound` is defined twice.** Once in `apps.catalog.errors`, once in `apps.procurement.errors` — both with `code = "ProductNotFound"` so wire-level error envelopes are identical. Reason: avoids a cross-app import (`apps.procurement → apps.catalog`) which the layering rule does not forbid (apps may import each other's errors), but keeps procurement self-contained. If the executor prefers the cross-app import, that is also acceptable — both options preserve the wire contract. **Not blocking; flag for executor preference.**

5. **List endpoint includes lines.** SPEC §3.3 says detail returns "lines + post-receive batches"; doesn't specify what list returns. Plan: list returns headers + lines (typical PO has 1–20 lines). If perf is ever a concern, add a `?fields=summary` query param later. **Not blocking.**

6. **Detail endpoint omits "post-receive batches" projection.** The same reason as ILEX-004 Notes #2 (`v_stock_by_batch` view): the `batches` table doesn't exist until ILEX-006. ILEX-006 amends `selectors.purchase_order_by_id` to include `batches: [...]` for received POs. **Not blocking.**

7. **No locked decision (D0–D14) needs relitigating. No hard constraint from `docs/product.md` is at risk.**
