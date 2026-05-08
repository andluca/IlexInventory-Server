# 006 — Implement inventory app (batches, movements, recall)

## Overview

The heaviest issue. Full vertical for inventory: schema for `batches` and the append-only `stock_movements` ledger, FEFO eligibility query, manual batch creation, movement recording (adjust + write-off), recall workflow with audit movements, recall report, batch metadata correction, and the cross-cutting movements audit endpoint. Schema enforces append-only via trigger; views power FEFO and recall reads.

**Scope:**
- `backend/migrations/0005_inventory.sql` (filename drift: issue text said `0004_inventory.sql`; `0004` is already taken by procurement — see status.md log entry for 2026-05-08T09:45Z):
  - `batches` (UUIDv7 PK, `owner_id`, `product_id`, `purchase_order_line_id` nullable per BE-D2, `batch_code`, `expiration_date` nullable, `unit_cost`, `is_recalled`, `recall_reason`, `recalled_at`, `archived_at`); UNIQUE `(owner_id, product_id, batch_code)`; composite FK to products and PO lines; UNIQUE `(id, owner_id)` hook for child FKs (sale_allocations in ILEX-007)
  - `stock_movements` (kind enum, signed_quantity, notes, reference_type, reference_id; CHECK constraints per kind binding sign and qty=0 rules per BE-D1, BE-D3, BE-D7); composite FK to batches
  - **Append-only TRIGGER** on `stock_movements`: forbid UPDATE/DELETE
- `backend/migrations/0006_views.sql` (inventory portion only — financials and sales add views in their own issues): `v_stock_by_batch` (`SUM(signed_quantity)` per batch), `v_recall_report` (joins `stock_movements` `kind='sale'` + sale_allocations + sales_orders, filters `voided_at IS NULL`), `v_expiring_soon`. The `v_recall_report` view references tables that don't exist until ILEX-007 (sales) — see Notes for the resolution.
- `apps/inventory/` full app structure (replacing the ILEX-005 stub-only layout)
- FEFO eligibility query in `apps/inventory/queries/batches.py::list_eligible_for_fefo(owner_id, product_id)` — used by Sales (ILEX-007); `ORDER BY expiration_date ASC NULLS LAST, created_at ASC`; `FOR UPDATE OF b`
- 9 endpoints listed below
- Tests at all four layers:
  - Schema: append-only trigger rejects UPDATE/DELETE; CHECK constraints reject invalid kind/sign combos
  - Query: FEFO eligibility ordering with NULLs last; recall_report excludes voided SOs (deferred to ILEX-007 once sales tables exist)
  - Service: recall idempotent on already-recalled; PATCH metadata writes audit movement; write-off rejects negative on-hand; FEFO walk respects expiration + recall
  - API: 9 endpoint integration tests

**Endpoints:**
- GET `/batches`, GET `/batches/{id}`
- POST `/batches` (manual entry)
- PATCH `/batches/{id}` (metadata correction — F12)
- POST `/batches/{id}/movements` (adjust, write_off)
- POST `/batches/{id}/recall`, POST `/batches/{id}/un-recall`
- GET `/batches/{id}/recall-report`
- GET `/movements` (cross-cutting audit; cursor pagination)

**Reference:** SPEC §3.4. BE-D1, BE-D2, BE-D3, BE-D7, BE-D9, BE-D11, BE-D12. Flows F4, F5, F6, F9, F10, F12.

**Depends on:** 005 (batches reference PO lines for procurement-sourced batches).

## Surface

- [x] backend/migrations
- [x] backend/apps/inventory (replaces stub)
- [x] backend/apps/catalog (restore `count_batches_for_product` + 3 deleted tests)
- [x] backend/apps/procurement (real `create_receipt_batches` body — caller already wired)
- [x] backend/urls.py (include `apps.inventory.urls`)
- [x] backend/settings/base.py (add `apps.inventory` to `INSTALLED_APPS`)
- [x] tests at unit / query / service / api layers
- [ ] frontend (no changes — OpenAPI regeneration in ILEX-010)

## Dependencies

- ILEX-005 (procurement, `0004_procurement.sql`) — completed; ships the `create_receipt_batches` stub + composite FK hook on `purchase_order_lines (id, owner_id)`. ILEX-006 replaces the stub body. Procurement's `receive_purchase_order` happy-path test must keep passing as-is.
- ILEX-004 (catalog) — completed; ships `count_batches_for_product` as an information_schema-probing stub. ILEX-006 replaces the body with a real `SELECT COUNT(*) FROM batches`. Three deleted catalog service tests (archive-with-batches, archive-already-archived, delete-with-batches) get restored as proper behavioral tests using real DB state.
- `apps.core` foundations: `@scoped` (D4 layer 1), `idempotent` view decorator, `DomainError` taxonomy, cursor pagination helpers, `db_test.pre_db/post_db`, UUIDv7 generator. All in place.

## Context

### What already exists

- `backend/migrations/0001_init.sql` — pgcrypto + UUIDv7 fn
- `backend/migrations/0003_catalog.sql` — `products` table with `UNIQUE (id, owner_id)` composite hook
- `backend/migrations/0004_procurement.sql` — `purchase_order_lines` with `UNIQUE (id, owner_id)` composite hook (line 69), batches' composite FK target
- `backend/apps/inventory/services.py` — no-op stub for `create_receipt_batches(*, owner_id, lines) -> list[dict]`. **Replace body, keep signature.** Procurement imports it at module top (`apps/procurement/services.py:20`).
- `backend/apps/procurement/services.py:340-357` — caller of `create_receipt_batches`, builds the line dict shape: `{line_id, batch_code, expiration_date, product_id, quantity, purchase_order_line_id}`. Plan must accept this exact shape.
- `backend/apps/procurement/tests/service/test_receive_purchase_order.py` — comments at top (lines 7-13) flag that batch + movement `post_db` assertions land in ILEX-006. Must amend (not rewrite) to add those assertions on the happy path.
- `backend/apps/catalog/queries/products.py:181-212` — `count_batches_for_product` stub probing `information_schema`. Replace body with real owner-scoped count query against `batches`.
- `backend/apps/catalog/services.py:166-227` — `archive_product` and `delete_product` already call `count_batches_for_product`. No change needed in services; just real data flows once the stub is replaced.
- `backend/apps/catalog/tests/service/test_archive_product.py` — currently has 2 tests (no-batches and cross-owner). ILEX-004 cleanup deleted 2 more (with-batches, already-archived). Restore as behavioral tests using real `batches` rows seeded via `pre_db`.
- `backend/apps/catalog/tests/service/test_delete_product.py` — currently 2 tests; restore the deleted "with-batches → ProductHasBatches" test using real seeded batches.
- `backend/apps/core/idempotency.py` — `@idempotent("endpoint.slug")` decorator, already used by `PurchaseOrderReceiveApi`. Plan reuses for `batches.create`, `batches.write_off`, `batches.recall`, `batches.un_recall`.
- `backend/apps/core/owner_scope.py` — `@scoped` runtime guard. Required on every owner-scoped query function.
- `backend/apps/core/pagination.py` — `encode_cursor(uuid, datetime) -> str` / `decode_cursor(str | None)`. Used by `/movements` cursor pagination.
- `backend/apps/core/errors.py` — `NotFound`, `Conflict`, `Unprocessable` (422), `ValidationError` base classes. `to_response()` mapper.
- `backend/apps/core/tests/db_test.py` — `pre_db` / `post_db` state pattern; 28/28 green. Inventory tests follow this pattern.
- `backend/apps/procurement/queries/purchase_orders.py` — reference template for query module structure (`@scoped`, `_row_to_dict`, single-statement functions, ORDER BY pattern, optional dynamic WHERE composition).
- `backend/apps/procurement/services.py` — reference template for service structure (kwarg-only, `_connect()`, transactional context, exception mapping).
- `backend/apps/procurement/apis.py` — reference template for API class structure (`@extend_schema`, `IsAuthenticated`, `to_response` mapping, `@idempotent` placement).
- `backend/apps/core/management/commands/migrate_sql.py` — applies `migrations/*.sql` in order. New migration file is auto-picked up.

### Spec reference

- **SPEC §3.4** — full Inventory section with the 9 endpoints, FEFO predicate SQL, recall flow F9, metadata correction F12, validation rules.
- **D1** — `stock_movements.signed_quantity` is signed; positive = in, negative = out; on-hand = `SUM(signed_quantity)`.
- **D2** — manual batches have `purchase_order_line_id IS NULL` and `reference_type='manual'` on the receipt movement.
- **D3** — recall = flag on `batches` + qty=0 audit movement (`kind='recall_block'` / `'recall_unblock'`).
- **D4** — owner isolation: composite FKs `(id, owner_id)`, cross-owner returns 404 not 403.
- **D7** — single `kind='adjustment'`; reason via `notes` (required non-empty for adjustments).
- **D9** — recall blocks future sales only; recall report shows past sales for owner-driven action.
- **D11** — FEFO ignores expired and recalled batches.
- **architecture.md** — four-layer split, naming conventions, file layout.

### Decisions already made that affect this issue

- `stock_movements` is **append-only** — no UPDATE, no DELETE. Corrections are new rows. Trigger enforces this at DB level (D3, ilex-discipline invariant #5).
- Money/qty: `Decimal` in Python, `numeric(14, 4)` in DB. No floats anywhere.
- Owner-scope: composite FKs on every reference, `@scoped` on every owner-scoped query, cross-owner = 404 with empty body.
- Receive flow signature: `create_receipt_batches(*, owner_id, lines)` — `lines` is a list of dicts with keys `{line_id, batch_code, expiration_date, product_id, quantity, purchase_order_line_id}`. Procurement's `receive_purchase_order` calls it **after** committing the header transition. ILEX-006 keeps that ordering and signature.
- The on-hand projection in `apps.catalog.selectors.list_products` was deferred from ILEX-004 to **ILEX-008 (financials)** per the status.md log entry for 2026-05-08 (ILEX-004 planned). It does **not** land in ILEX-006. ILEX-006 only ships `v_stock_by_batch`; the catalog selector consuming it is ILEX-008's job.
- Migration filename is `0005_inventory.sql` (not `0004_inventory.sql` as written in the original issue scope) — the spec authored the filenames before procurement took 0004.
- `v_recall_report` references `sale_allocations` and `sales_orders` which don't exist until ILEX-007. Two options:
  1. Define `v_recall_report` in ILEX-006 as planned, but its CREATE VIEW will fail until sales tables exist.
  2. Defer `v_recall_report` definition to ILEX-007's `0006_views.sql` slice; ILEX-006 ships only `v_stock_by_batch` and `v_expiring_soon`.

  **Decision: option 2.** ILEX-006 ships `v_stock_by_batch` + `v_expiring_soon` in `0006_views.sql`; the recall-report **endpoint** is also deferred to ILEX-007 alongside the view. Reason: the endpoint can't return data until committed sales exist anyway, and CREATE VIEW with forward-referenced tables is a foot-gun. The original scope listing `GET /batches/{id}/recall-report` in ILEX-006 is renegotiated here — see Notes.

## Plan

### Schema and SQL

#### `backend/migrations/0005_inventory.sql`

```sql
-- batches: per-product lots with optional PO line link, FEFO-routable.
CREATE TABLE IF NOT EXISTS batches (
    id                       UUID         PRIMARY KEY DEFAULT uuidv7(),
    owner_id                 INT          NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    product_id               UUID         NOT NULL,
    purchase_order_line_id   UUID         NULL,
    batch_code               TEXT         NOT NULL,
    expiration_date          DATE         NULL,
    unit_cost                NUMERIC(14, 4) NOT NULL,
    is_recalled              BOOLEAN      NOT NULL DEFAULT FALSE,
    recall_reason            TEXT         NULL,
    recalled_at              TIMESTAMPTZ  NULL,
    archived_at              TIMESTAMPTZ  NULL,
    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- D4 composite FKs
    CONSTRAINT batches_product_owner_fkey
        FOREIGN KEY (product_id, owner_id) REFERENCES products (id, owner_id),
    CONSTRAINT batches_pol_owner_fkey
        FOREIGN KEY (purchase_order_line_id, owner_id)
        REFERENCES purchase_order_lines (id, owner_id),

    -- composite hook for sale_allocations (ILEX-007)
    CONSTRAINT batches_id_owner_unique UNIQUE (id, owner_id),

    -- batch_code unique per product per owner (D2: manual + procured share namespace)
    CONSTRAINT batches_owner_product_code_unique UNIQUE (owner_id, product_id, batch_code),

    -- Money discipline
    CONSTRAINT batches_unit_cost_nonneg CHECK (unit_cost >= 0),

    -- Recall consistency: is_recalled ↔ recalled_at + recall_reason
    CONSTRAINT batches_recall_consistency CHECK (
        (is_recalled = FALSE AND recalled_at IS NULL AND recall_reason IS NULL)
        OR (is_recalled = TRUE AND recalled_at IS NOT NULL AND length(trim(recall_reason)) > 0)
    ),
    CONSTRAINT batches_code_not_blank CHECK (length(trim(batch_code)) > 0)
);

CREATE INDEX IF NOT EXISTS batches_owner_product_idx ON batches (owner_id, product_id);
-- FEFO access path; full FEFO covering index lands in 0007_indexes.sql (ILEX-009).
CREATE INDEX IF NOT EXISTS batches_owner_product_expiry_idx
    ON batches (owner_id, product_id, expiration_date NULLS LAST, created_at);

-- stock_movements: append-only ledger. On-hand = SUM(signed_quantity) per batch.
CREATE TABLE IF NOT EXISTS stock_movements (
    id                UUID            PRIMARY KEY DEFAULT uuidv7(),
    owner_id          INT             NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    batch_id          UUID            NOT NULL,
    kind              TEXT            NOT NULL,
    signed_quantity   NUMERIC(14, 4)  NOT NULL,
    notes             TEXT            NULL,
    reference_type    TEXT            NULL,   -- 'purchase_order_line' | 'manual' | 'sales_order_line' | 'sale_allocation' | NULL
    reference_id      UUID            NULL,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4 composite FK to batches
    CONSTRAINT sm_batch_owner_fkey
        FOREIGN KEY (batch_id, owner_id) REFERENCES batches (id, owner_id),

    -- D1 + D7: kind enum + sign rules
    CONSTRAINT sm_kind_chk CHECK (kind IN (
        'receipt', 'adjustment', 'write_off',
        'sale', 'sale_void',
        'recall_block', 'recall_unblock',
        'metadata_correction'
    )),
    -- Per-kind sign / qty rules (D1, D3, D7, F12).
    CONSTRAINT sm_sign_chk CHECK (
        (kind = 'receipt'             AND signed_quantity > 0)
        OR (kind = 'adjustment'       AND signed_quantity <> 0)
        OR (kind = 'write_off'        AND signed_quantity < 0)
        OR (kind = 'sale'             AND signed_quantity < 0)
        OR (kind = 'sale_void'        AND signed_quantity > 0)
        OR (kind = 'recall_block'     AND signed_quantity = 0)
        OR (kind = 'recall_unblock'   AND signed_quantity = 0)
        OR (kind = 'metadata_correction' AND signed_quantity = 0)
    ),
    -- D7: adjustment requires non-empty notes.
    CONSTRAINT sm_adjustment_notes_chk CHECK (
        kind <> 'adjustment' OR (notes IS NOT NULL AND length(trim(notes)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS sm_batch_idx        ON stock_movements (batch_id);
CREATE INDEX IF NOT EXISTS sm_owner_created_idx ON stock_movements (owner_id, created_at DESC, id DESC);

-- Append-only enforcement (ilex-discipline invariant #5; D3).
CREATE OR REPLACE FUNCTION stock_movements_no_mutate()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'stock_movements is append-only (% on row %)', TG_OP, OLD.id;
END;
$$;

DROP TRIGGER IF EXISTS sm_no_update_trg ON stock_movements;
CREATE TRIGGER sm_no_update_trg BEFORE UPDATE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION stock_movements_no_mutate();

DROP TRIGGER IF EXISTS sm_no_delete_trg ON stock_movements;
CREATE TRIGGER sm_no_delete_trg BEFORE DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION stock_movements_no_mutate();
```

#### `backend/migrations/0006_views.sql` (inventory portion)

```sql
-- v_stock_by_batch: per-batch on-hand. Powers FEFO + list endpoints + catalog
-- on-hand projection (deferred to ILEX-008).
CREATE OR REPLACE VIEW v_stock_by_batch AS
SELECT
    b.id           AS batch_id,
    b.owner_id     AS owner_id,
    b.product_id   AS product_id,
    COALESCE(SUM(m.signed_quantity), 0)::NUMERIC(14, 4) AS on_hand
FROM batches b
LEFT JOIN stock_movements m
       ON m.batch_id = b.id
      AND m.owner_id = b.owner_id
GROUP BY b.id, b.owner_id, b.product_id;

-- v_expiring_soon: batches with expiration within N days. N is parameterized
-- by the caller filtering on `days_until_expiry`.
CREATE OR REPLACE VIEW v_expiring_soon AS
SELECT
    b.id           AS batch_id,
    b.owner_id     AS owner_id,
    b.product_id   AS product_id,
    b.batch_code   AS batch_code,
    b.expiration_date,
    (b.expiration_date - CURRENT_DATE) AS days_until_expiry,
    v.on_hand
FROM batches b
JOIN v_stock_by_batch v ON v.batch_id = b.id AND v.owner_id = b.owner_id
WHERE b.expiration_date IS NOT NULL
  AND b.is_recalled = FALSE
  AND v.on_hand > 0;

-- v_recall_report intentionally NOT created here — it joins sale_allocations
-- and sales_orders which land in ILEX-007. ILEX-007's 0006_views.sql slice
-- (or a new 0006b file) appends v_recall_report.
```

**Round-trip / constraint tests expected** (in `tests/query/test_schema_constraints.py` — pure DB-level integrity):
- INSERT into `batches` with cross-owner `(product_id, owner_id)` mismatch → `ForeignKeyViolation`.
- INSERT `stock_movements` with `kind='receipt' AND signed_quantity = -1` → `CheckViolation` (`sm_sign_chk`).
- INSERT `stock_movements` with `kind='adjustment' AND notes IS NULL` → `CheckViolation` (`sm_adjustment_notes_chk`).
- UPDATE on any `stock_movements` row → trigger raises (append-only).
- DELETE on any `stock_movements` row → trigger raises (append-only).
- INSERT batch with `is_recalled=TRUE` but `recalled_at IS NULL` → `CheckViolation` (`batches_recall_consistency`).
- Duplicate `(owner_id, product_id, batch_code)` → `UniqueViolation`.

### Service layer

#### New module `apps/inventory/types.py`
TypedDicts:
- `BatchRow` (matches the columns of `batches` + derived `on_hand`)
- `MovementRow` (matches `stock_movements`)
- `NewMovement` (kwargs for `record_movement`: `{kind, signed_quantity, notes}`)
- `ReceiveLine` (matches the dict shape that procurement sends — already documented above)

#### New module `apps/inventory/errors.py`
- `BatchNotFound(NotFound)`
- `BatchAlreadyRecalled(Conflict)` — when callers want to act on the conflict, but recall itself is idempotent (D3) and does NOT raise this. Reserved for future explicit "must not be recalled" guards.
- `BatchHasMovements(Conflict)` — if a service ever wants to refuse to do something when movements exist.
- `WriteOffExceedsOnHand(Unprocessable)` — 422
- `InvalidMovementKind(ValidationError)` — 400
- `InvalidMetadataField(ValidationError)` — 400 (PATCH allowlist)
- `RecallReasonRequired(ValidationError)` — 400
- `BatchExists(Conflict)` — duplicate `(owner_id, product_id, batch_code)`
- `ProductNotFound(NotFound)` — manual batch references missing product

#### New module `apps/inventory/queries/batches.py`
All decorated with `@scoped`. Each is one SQL statement. Caller owns the cursor + transaction.

| Function | Statement | Purpose |
|---|---|---|
| `insert_batch(cur, *, params)` | `INSERT INTO batches ... RETURNING *` | Manual entry + procurement receipt |
| `select_batch_by_id(cur, *, params)` | `SELECT * FROM batches WHERE id=:id AND owner_id=:owner_id` | Detail + existence check |
| `select_batch_for_update(cur, *, params)` | `SELECT ... FROR UPDATE` | Lock during recall / movement record |
| `update_batch_metadata(cur, *, params)` | `UPDATE batches SET batch_code=COALESCE(...), expiration_date=COALESCE(...) ... RETURNING *` | F12 metadata correction |
| `set_recall_state(cur, *, params)` | `UPDATE batches SET is_recalled=:flag, recall_reason=..., recalled_at=...` | Recall + un-recall transition |
| `list_batches(cur, *, params)` | Paginated SELECT with filters (`product_id`, `is_recalled`, `expiring_within`); LEFT JOIN `v_stock_by_batch` | List endpoint |
| `list_eligible_for_fefo(cur, *, params)` | The SPEC §3.4 FEFO SQL with `FOR UPDATE OF b` | **Used by Sales (ILEX-007)** — exposed now |
| `count_batches_for_product(cur, *, params)` | `SELECT COUNT(*) FROM batches WHERE product_id AND owner_id` | **Note**: this duplicates `apps.catalog.queries.products.count_batches_for_product`. We keep the catalog version (it's already imported by catalog services); ILEX-006 only updates that one's body. We do NOT add a duplicate in inventory queries. |

#### New module `apps/inventory/queries/movements.py`
All decorated with `@scoped`.

| Function | Statement | Purpose |
|---|---|---|
| `insert_movement(cur, *, params)` | `INSERT INTO stock_movements ... RETURNING *` | All movement creations (receipt, adjust, write-off, recall, metadata) |
| `on_hand_for_batch(cur, *, params)` | `SELECT on_hand FROM v_stock_by_batch WHERE batch_id AND owner_id` | Pre-write-off check |
| `list_movements(cur, *, params)` | Cursor-paginated SELECT with filters (`batch_id`, `product_id` via JOIN, `from`, `to`, `kind`); ORDER BY `(created_at DESC, id DESC)` | `/movements` audit endpoint |

#### New module `apps/inventory/services.py` (replacing the stub)

Functions (all kwarg-only past the first arg, type-annotated, raise from `apps.inventory.errors`):

```python
def create_receipt_batches(*, owner_id: int, lines: list[ReceiveLine]) -> list[BatchRow]:
    """ILEX-006 real body. Procurement calls this AFTER receive_purchase_order
    commits the PO header transition. We open our own connection.

    For each line: INSERT batch (with purchase_order_line_id set, unit_cost
    pulled from the PO line's quantity/cost contract) + INSERT receipt
    movement (kind='receipt', signed_quantity = +line.quantity,
    reference_type='purchase_order_line', reference_id=line.line_id).

    Wraps both inserts per line in a single @transaction.atomic block — if any
    fails, no batches or movements persist for the receive.

    Note: procurement already committed the PO header before calling us.
    Per SPEC §3.3 the receive is "atomic" — if our writes fail, the PO is
    in 'received' state but has zero batches. This is a known seam from
    ILEX-005's split. Keep failure rare (idempotency-key prevents retries
    creating duplicates; uniqueness on (owner_id, product_id, batch_code)
    prevents double-receives at DB level).
    """

def create_manual_batch(*, owner_id, product_id, batch_code, expiration_date,
                        unit_cost: Decimal, initial_quantity: Decimal) -> BatchRow:
    """F4. INSERT batch (purchase_order_line_id=NULL) + receipt movement
    (reference_type='manual', reference_id=NULL). Atomic.

    Raises ProductNotFound on cross-owner / missing product (D4 → 404).
    Raises BatchExists on duplicate (owner_id, product_id, batch_code).
    """

def update_batch_metadata(*, owner_id, batch_id, batch_code: str | None,
                          expiration_date: date | None, allowed_fields: set[str]) -> BatchRow:
    """F12. Strict allowlist of {batch_code, expiration_date}. Service writes
    a metadata_correction movement (qty=0) capturing the diff in `notes`.
    No-op (idempotent) when the value is already current. Other fields
    rejected at the API serializer layer; service trusts the kwargs.

    Raises BatchNotFound on missing/cross-owner.
    """

def record_movement(*, owner_id, batch_id, kind: str, signed_quantity: Decimal,
                    notes: str | None) -> MovementRow:
    """F5/F6. kind ∈ {adjustment, write_off}. Locks the batch FOR UPDATE,
    reads on_hand, validates write-off doesn't drive negative, INSERTs the
    movement.

    Raises InvalidMovementKind for kinds outside the public allowlist.
    Raises ValidationError for adjustment with empty notes.
    Raises WriteOffExceedsOnHand (422) when on_hand + signed_quantity < 0.
    """

def recall_batch(*, owner_id, batch_id, reason: str) -> BatchRow:
    """F9. Idempotent (D3): if already recalled, no writes, return current.
    Otherwise UPDATE batches SET is_recalled=true, recall_reason, recalled_at
    + INSERT recall_block movement (kind='recall_block', signed_quantity=0,
    notes=reason).

    Raises BatchNotFound on missing/cross-owner.
    Raises ValidationError if reason is blank.
    """

def un_recall_batch(*, owner_id, batch_id) -> BatchRow:
    """F10. Idempotent: if not recalled, no writes, return current. Otherwise
    UPDATE batches SET is_recalled=false, recall_reason=NULL, recalled_at=NULL
    + INSERT recall_unblock movement.
    """
```

Selectors (read-only, in `apps/inventory/selectors.py`):
- `list_batches(*, owner_id, product_id, is_recalled, expiring_within, limit, offset)` → returns `{items, total, limit, offset}`
- `batch_by_id(*, owner_id, batch_id)` → `BatchRow | None`
- `list_movements(*, owner_id, batch_id, product_id, kind, date_from, date_to, cursor, limit)` → `{items, next_cursor}`

### Tests (write FIRST)

In strict TDD order. Each test is **behavioral**: outcomes only (return value, raised exception, post_db state, HTTP status + body). No `_private` imports. No `unittest.mock.patch` of internal functions. No call-counters or spies.

#### Schema / query layer

`backend/apps/inventory/tests/query/test_schema_constraints.py`
- `test_stock_movements_update_rejected_by_trigger` — `pre_db` a batch + receipt movement, `db.execute("UPDATE stock_movements SET notes='x' WHERE id=...")` → `psycopg.errors.RaiseException`.
- `test_stock_movements_delete_rejected_by_trigger` — same shape, DELETE → exception.
- `test_kind_sign_check_constraint` — INSERT receipt with negative qty → `CheckViolation`. INSERT recall_block with qty=5 → `CheckViolation`. INSERT adjustment with qty=0 → `CheckViolation`.
- `test_adjustment_notes_required` — INSERT adjustment with `notes IS NULL` → `CheckViolation`.
- `test_recall_consistency_check` — INSERT batch with `is_recalled=TRUE, recalled_at=NULL` → `CheckViolation`.
- `test_batches_owner_product_code_unique` — duplicate triple → `UniqueViolation`.
- `test_batches_cross_owner_product_fk_rejected` — `pre_db` product owned by user A, INSERT batch claiming user B owner with that product_id → `ForeignKeyViolation` (D4 cross-table fusion guard).

`backend/apps/inventory/tests/query/test_batches_queries.py`
- `test_insert_batch_returns_row_with_uuidv7_id`
- `test_select_batch_by_id_cross_owner_returns_none` (D4)
- `test_list_eligible_for_fefo_orders_by_expiry_then_created_at` — seed 3 batches: one with NULL expiration, one expiring earlier, one expiring later. ORDER BY `expiration_date ASC NULLS LAST, created_at ASC`. Recalled batch absent. Expired batch (expiration_date < CURRENT_DATE) absent. Zero-on-hand batch absent.
- `test_list_eligible_for_fefo_takes_for_update_lock` — open two connections, first does `SELECT ... FOR UPDATE` and holds; second's same query blocks. (Tested with `SELECT ... NOWAIT` in the second tx and asserting `LockNotAvailable`.)
- `test_list_batches_filter_expiring_within_30_days`
- `test_list_batches_filter_is_recalled`
- `test_count_batches_for_product_returns_real_count` — exercises the catalog query module's now-real implementation.

`backend/apps/inventory/tests/query/test_movements_queries.py`
- `test_insert_movement_returns_row`
- `test_on_hand_for_batch_via_view_sums_signed_quantity` — receipt +10, write-off -3 → on_hand=7.
- `test_list_movements_cursor_pagination_orders_desc` — seed 5 movements, page 1 returns latest 2, cursor advances to next 2.
- `test_list_movements_filter_by_kind_and_date_range`

#### Service layer

`backend/apps/inventory/tests/service/test_create_manual_batch.py`
- `test_creates_batch_and_receipt_movement` — `post_db` shows batch row + 1 movement with `kind='receipt'`, `reference_type='manual'`, `reference_id IS NULL`.
- `test_duplicate_batch_code_raises_batch_exists` (409)
- `test_cross_owner_product_raises_product_not_found` (D4 → 404)
- `test_initial_quantity_must_be_positive_raises_validation_error`

`backend/apps/inventory/tests/service/test_record_movement.py`
- `test_adjustment_writes_movement_and_changes_on_hand`
- `test_adjustment_with_blank_notes_raises_validation_error` (D7)
- `test_write_off_within_on_hand_succeeds`
- `test_write_off_into_negative_raises_write_off_exceeds_on_hand` (422)
- `test_kind_outside_allowlist_raises_invalid_movement_kind` — service rejects e.g. `kind='sale'` (callers shouldn't reach this from inventory's API).
- `test_cross_owner_batch_raises_batch_not_found` (D4)

`backend/apps/inventory/tests/service/test_update_batch_metadata.py`
- `test_changing_batch_code_writes_metadata_correction_movement` — `post_db` shows new batch_code + new movement row with `kind='metadata_correction'`, `signed_quantity=0`, `notes` carrying a diff string.
- `test_unchanged_value_is_idempotent_no_movement_written`
- `test_changing_expiration_date_to_null_works`
- `test_cross_owner_raises_batch_not_found`

`backend/apps/inventory/tests/service/test_recall_batch.py`
- `test_recall_sets_flag_and_writes_recall_block_movement` — post_db: `batches.is_recalled=true`, `recalled_at` set; one movement with `kind='recall_block', signed_quantity=0, notes=reason`.
- `test_recall_idempotent_on_already_recalled_no_writes` — call twice with same reason; movement count stays at 1, batch state unchanged after second call.
- `test_recall_with_blank_reason_raises_validation_error`
- `test_recall_cross_owner_raises_batch_not_found` (D4)

`backend/apps/inventory/tests/service/test_un_recall_batch.py`
- `test_un_recall_clears_flag_and_writes_recall_unblock_movement`
- `test_un_recall_idempotent_when_not_recalled`
- `test_un_recall_cross_owner_raises_batch_not_found`

`backend/apps/inventory/tests/service/test_create_receipt_batches.py`
- `test_creates_batch_per_line_with_purchase_order_line_id_set` — pass 2 lines, `post_db` shows 2 batches, each with `purchase_order_line_id` populated.
- `test_creates_receipt_movement_per_batch` — `post_db` shows 2 movements with `kind='receipt'`, `reference_type='purchase_order_line'`, `reference_id` matching the line_id.
- `test_zero_lines_returns_empty_list_no_writes` — defensive, but procurement caller never sends empty.
- `test_unit_cost_carried_from_line` — receipt movement and batch both record the line's `unit_cost`.
- `test_cross_owner_pol_id_raises_or_product_fkey` — passing a `purchase_order_line_id` from another owner → `ForeignKeyViolation` (the composite FK catches it).

#### API layer

`backend/apps/inventory/tests/api/test_batches_list.py`
- `test_list_returns_paginated_batches_for_owner`
- `test_list_filter_by_product_id`
- `test_list_filter_is_recalled_true_only`
- `test_list_filter_expiring_within_days`
- `test_list_unauthenticated_returns_401`
- `test_list_does_not_show_other_owners_batches`

`backend/apps/inventory/tests/api/test_batches_detail.py`
- `test_get_batch_returns_on_hand_and_recall_flag`
- `test_get_cross_owner_returns_404_not_403` (D4)

`backend/apps/inventory/tests/api/test_batches_create.py`
- `test_post_creates_manual_batch_with_idempotency_key`
- `test_missing_idempotency_key_returns_400`
- `test_duplicate_idempotency_key_returns_cached_response`
- `test_cross_owner_product_returns_404`
- `test_duplicate_batch_code_returns_409`
- `test_negative_initial_quantity_returns_400`

`backend/apps/inventory/tests/api/test_batches_patch_metadata.py`
- `test_patch_batch_code_returns_200_and_writes_audit_movement`
- `test_patch_with_disallowed_field_returns_400` — e.g. `unit_cost`, `product_id`
- `test_patch_idempotent_when_value_unchanged`
- `test_patch_cross_owner_returns_404`

`backend/apps/inventory/tests/api/test_batches_movements.py`
- `test_post_adjustment_returns_200_and_records_movement`
- `test_post_adjustment_blank_notes_returns_400`
- `test_post_write_off_within_on_hand_returns_200`
- `test_post_write_off_into_negative_returns_422_with_shortfall_body`
- `test_post_write_off_requires_idempotency_key`
- `test_post_invalid_kind_returns_400` — e.g. `kind='sale'` rejected at API
- `test_post_cross_owner_batch_returns_404`

`backend/apps/inventory/tests/api/test_batches_recall.py`
- `test_post_recall_returns_200_sets_flag_writes_movement`
- `test_post_recall_blank_reason_returns_400`
- `test_post_recall_idempotency_key_required`
- `test_post_recall_idempotent_second_call_is_no_op`
- `test_post_un_recall_returns_200_clears_flag`
- `test_post_recall_cross_owner_returns_404`

`backend/apps/inventory/tests/api/test_movements_audit.py`
- `test_get_movements_returns_paginated_results_cursor_advances`
- `test_get_movements_filter_by_batch_id`
- `test_get_movements_filter_by_product_id` — JOIN through batches
- `test_get_movements_filter_by_kind_and_date_range`
- `test_get_movements_does_not_show_other_owners_movements` (D4)
- `test_get_movements_unauthenticated_returns_401`

#### Restored catalog tests (from ILEX-004 cleanup)

`backend/apps/catalog/tests/service/test_archive_product.py` (amend, add):
- `test_archive_product_with_batches_sets_archived_at` — `pre_db` seeds product + 1 batch; `archive_product` succeeds; `post_db` shows `archived_at IS NOT NULL`.
- `test_archive_product_already_archived_is_idempotent` — `pre_db` seeds archived product + batch; calling `archive_product` again returns the same row, `archived_at` unchanged.

`backend/apps/catalog/tests/service/test_delete_product.py` (amend, add):
- `test_delete_product_with_batches_raises_product_has_batches` — `pre_db` seeds product + batch; `delete_product` raises `ProductHasBatches`; `post_db` shows product still present.

These three tests no longer monkey-patch `count_batches_for_product`; they exercise the **real** count query against real seeded `batches` rows. This is the cleanup item from the 2026-05-08T08:55Z log entry.

#### Procurement amendment

`backend/apps/procurement/tests/service/test_receive_purchase_order.py:test_receive_po_happy_path`:
- Add `post_db` assertions: 1 row in `batches` with `purchase_order_line_id` set, `unit_cost` matching the line; 1 row in `stock_movements` with `kind='receipt'`, `signed_quantity = +10`, `reference_type='purchase_order_line'`, `reference_id = line_id`.
- Remove the `TODO(ILEX-006)` comment block at the top of the file.

### Implementation

Step by step. Bottom-up; each step keeps the suite green.

1. **Schema.** Write `backend/migrations/0005_inventory.sql`. Run `python manage.py migrate_sql` against the test DB; verify tables + trigger via psql. Schema-constraint tests (red → green at this point).
2. **Inventory queries.** Create `apps/inventory/queries/batches.py` and `apps/inventory/queries/movements.py`. Each function `@scoped`, single-statement, top-level imports. Query-layer tests in `tests/query/` go red → green.
3. **Inventory views.** Write `backend/migrations/0006_views.sql` with `v_stock_by_batch` and `v_expiring_soon` only (no `v_recall_report` — see Notes). Re-run migrations. View tests (round-trip on `v_stock_by_batch`) go green.
4. **Catalog query update.** Replace the body of `count_batches_for_product` in `apps/catalog/queries/products.py` with the real `SELECT COUNT(*)`. The information_schema probe and the stub note are deleted. Existing catalog service/api tests stay green; new query test `test_count_batches_for_product_returns_real_count` goes green.
5. **Inventory errors + types.** Create `apps/inventory/errors.py` and `apps/inventory/types.py`. Module-top imports only.
6. **Inventory services — write side.**
   - `create_manual_batch` first (simplest atomic write). Service tests go green.
   - `record_movement` next (with locking + on-hand check via view).
   - `update_batch_metadata` (audit movement is the interesting bit).
   - `recall_batch` and `un_recall_batch` (idempotency, D3).
   - `create_receipt_batches` last — replaces the stub body. Procurement's `test_receive_po_happy_path` is amended in the same commit to add `post_db` batch + movement assertions.
7. **Restore catalog tests.** Add the 3 deleted tests as proper behavioral tests using `pre_db` to seed real batches. They pass against the real `count_batches_for_product`.
8. **Inventory selectors.** `apps/inventory/selectors.py` with `list_batches`, `batch_by_id`, `list_movements`. Each opens `_connect()`, calls queries, closes.
9. **Inventory serializers.** `apps/inventory/serializers.py` with request/response serializers per endpoint. Note: PATCH metadata uses an `extra_kwargs={"product_id": {"read_only": True}, ...}` pattern with strict allowlist — unknown fields trigger a `ValidationError` at the serializer layer (covered by `test_patch_with_disallowed_field_returns_400`).
10. **Inventory APIs.** `apps/inventory/apis.py` with one APIView class per operation per architecture.md. Use `@idempotent` on `POST /batches` (`batches.create`), write-off branch of `POST .../movements` (`batches.write_off`), `POST .../recall` (`batches.recall`), `POST .../un-recall` (`batches.un_recall`). Adjustment movements are NOT idempotency-keyed (per SPEC §2.6 table).
11. **URLs.** `apps/inventory/urls.py` with the 8 paths (recall-report deferred; see Notes). Wire into `backend/urls.py`.
12. **Settings.** Add `apps.inventory` to `INSTALLED_APPS` in `backend/settings/base.py`.
13. **Refactor pass.** After green: extract any duplication between `create_manual_batch` and `create_receipt_batches` (likely a private `_insert_batch_with_receipt` helper inside `services.py` — note: that helper is private, so it is NOT directly tested; behavior is tested through the public service surface per the tdd skill's "Behavioral, not structural" rule).

### Integration / wiring

- **`backend/urls.py`**: add `path("api/v1/", include("apps.inventory.urls"))`.
- **`backend/settings/base.py`**: append `"apps.inventory"` to `INSTALLED_APPS`.
- **OpenAPI (drf-spectacular)**: every API class carries `@extend_schema` annotations. Regenerating the OpenAPI schema picks up the 8 new endpoints automatically. (Frontend type regeneration is ILEX-010's job.)
- **No new Django settings or env vars.**
- **No new app registries or middleware.**
- **No `conftest.py` changes** — the existing `backend/conftest.py` session-scoped Postgres fixture applies the new migration via `migrate_sql` automatically.

### Documentation to update

- **`docs/issues/status.md`** — mark ILEX-006 `planned` now; on completion add an Execution Log entry summarizing the deltas (new migration files, new app vertical, restored catalog tests, recall-report deferral to ILEX-007).
- **No spec updates needed.** SPEC §3.4 already documents the 9 endpoints. ILEX-006 ships 8; the recall-report deferral to ILEX-007 is captured in this issue's Notes section, not by editing SPEC.
- **`.claude/CLAUDE.md`** — no new conventions introduced.
- **`README.md`** — no public surface changes (docs already list inventory endpoints).

## Files involved

**Created:**
- `backend/migrations/0005_inventory.sql`
- `backend/migrations/0006_views.sql`
- `backend/apps/inventory/__init__.py` (already exists, empty)
- `backend/apps/inventory/apis.py`
- `backend/apps/inventory/errors.py`
- `backend/apps/inventory/queries/__init__.py`
- `backend/apps/inventory/queries/batches.py`
- `backend/apps/inventory/queries/movements.py`
- `backend/apps/inventory/selectors.py`
- `backend/apps/inventory/serializers.py`
- `backend/apps/inventory/types.py`
- `backend/apps/inventory/urls.py`
- `backend/apps/inventory/tests/__init__.py`
- `backend/apps/inventory/tests/conftest.py` (if needed; otherwise rely on global)
- `backend/apps/inventory/tests/query/__init__.py`
- `backend/apps/inventory/tests/query/test_schema_constraints.py`
- `backend/apps/inventory/tests/query/test_batches_queries.py`
- `backend/apps/inventory/tests/query/test_movements_queries.py`
- `backend/apps/inventory/tests/service/__init__.py`
- `backend/apps/inventory/tests/service/test_create_manual_batch.py`
- `backend/apps/inventory/tests/service/test_record_movement.py`
- `backend/apps/inventory/tests/service/test_update_batch_metadata.py`
- `backend/apps/inventory/tests/service/test_recall_batch.py`
- `backend/apps/inventory/tests/service/test_un_recall_batch.py`
- `backend/apps/inventory/tests/service/test_create_receipt_batches.py`
- `backend/apps/inventory/tests/api/__init__.py`
- `backend/apps/inventory/tests/api/test_batches_list.py`
- `backend/apps/inventory/tests/api/test_batches_detail.py`
- `backend/apps/inventory/tests/api/test_batches_create.py`
- `backend/apps/inventory/tests/api/test_batches_patch_metadata.py`
- `backend/apps/inventory/tests/api/test_batches_movements.py`
- `backend/apps/inventory/tests/api/test_batches_recall.py`
- `backend/apps/inventory/tests/api/test_movements_audit.py`
- `backend/apps/inventory/tests/unit/__init__.py`
- `backend/apps/inventory/tests/unit/test_serializers.py` (allowlist behavior, sign rules at serializer layer)
- `backend/apps/inventory/tests/unit/test_errors.py` (code attributes + DRF mapping smoke)

**Modified:**
- `backend/apps/inventory/services.py` (replaces stub body; keeps `create_receipt_batches` signature)
- `backend/apps/catalog/queries/products.py` (replaces `count_batches_for_product` body)
- `backend/apps/catalog/tests/service/test_archive_product.py` (adds 2 restored tests)
- `backend/apps/catalog/tests/service/test_delete_product.py` (adds 1 restored test)
- `backend/apps/procurement/tests/service/test_receive_purchase_order.py` (adds post_db assertions on happy-path; removes TODO comment)
- `backend/urls.py` (include inventory urls)
- `backend/settings/base.py` (`INSTALLED_APPS += ["apps.inventory"]`)
- `docs/issues/status.md` (mark ILEX-006 planned → completed, append Execution Log)

## Acceptance criteria

**Specific tests passing:**
- All schema-constraint tests in `backend/apps/inventory/tests/query/test_schema_constraints.py` (append-only trigger, sign CHECK, recall consistency, unique).
- All FEFO tests in `test_batches_queries.py` (NULLS LAST ordering, expired excluded, recalled excluded, FOR UPDATE locks).
- `test_record_movement.py::test_write_off_into_negative_raises_write_off_exceeds_on_hand`.
- `test_recall_batch.py::test_recall_idempotent_on_already_recalled_no_writes`.
- `test_update_batch_metadata.py::test_changing_batch_code_writes_metadata_correction_movement`.
- `test_create_receipt_batches.py::test_creates_batch_per_line_with_purchase_order_line_id_set` and `test_creates_receipt_movement_per_batch`.
- All 7 batch + movement API test files (37 named tests) green.
- The 3 restored catalog tests (archive-with-batches, archive-already-archived, delete-with-batches) green against real seeded `batches` rows.
- `apps/procurement/tests/service/test_receive_purchase_order.py::test_receive_po_happy_path` keeps passing **and** now asserts post_db state for batches + movements.

**Universal gates:**
- `pytest backend/` — all green; total ≥ 262 + new inventory tests + 3 restored catalog tests.
- `ruff check backend/` clean (project lint config).
- `grep -R "from django.db.models" backend/apps/` returns empty (D14 carve-out for `apps/core/auth.py` only).
- `grep -RE "cursor\.execute" backend/apps/*/services.py backend/apps/*/selectors.py backend/apps/*/apis.py` returns empty (no SQL outside `queries/`).
- `grep -nE "^\s+(from|import) apps\." backend/apps/inventory/` (excluding `tests/`) returns only commented `# break cycle: ...` lines — must be zero in this issue (no real cycles between inventory and procurement; procurement imports inventory at module top, inventory does NOT import procurement).
- Every owner-scoped query function in `apps/inventory/queries/*.py` carries `@scoped`.
- No floats: all `unit_cost` and `signed_quantity` paths use `Decimal` in Python and `numeric(14, 4)` in SQL.
- Cross-owner access returns 404 with empty body across all 8 inventory endpoints (covered by per-endpoint cross-owner tests).
- `stock_movements` is verifiably append-only at the DB level (tested by trigger tests).
- OpenAPI regenerates without errors (`python manage.py spectacular --file /tmp/openapi.json --validate`).
- Behavioral test discipline: zero imports of `_private` helpers in tests; zero `unittest.mock.patch` calls in non-test code paths; zero call-counters or spies asserting which intermediate function ran.

## Notes

### Recall-report endpoint and view deferred to ILEX-007

The original ILEX-006 scope listed `GET /batches/{id}/recall-report` and the `v_recall_report` view. Both depend on `sale_allocations` and `sales_orders`, which land in ILEX-007. Two paths considered:

1. Define `v_recall_report` here with forward-referenced tables (won't compile).
2. Defer the view + endpoint to ILEX-007.

Choosing (2). ILEX-006 ships 8 of 9 endpoints. ILEX-007 will:
- Add `0006_views_sales.sql` (or extend `0006_views.sql`) with `v_recall_report`.
- Add `apps/inventory/apis.py::BatchRecallReportApi` and `apps/inventory/selectors.py::recall_report_for_batch`.
- Test it end-to-end against committed sales orders.

This is a renegotiation of the original issue scope, not a silent omission. Status.md log entry on completion should call this out so ILEX-007's planner picks it up.

### `0006_views.sql` is shared across issues

`docs/issues/status.md` says: *"0006 — views (split across Issues 006 and 008)"*. ILEX-006 creates `0006_views.sql` with `v_stock_by_batch` and `v_expiring_soon`. ILEX-007 appends `v_recall_report`. ILEX-008 (financials) appends `v_margin_by_product`. The migrate_sql command applies them in alphabetical order; subsequent issues use `CREATE OR REPLACE VIEW` to be idempotent if rerun. **No file rename is needed.**

### Restored catalog tests must use real `batches` rows, not monkey-patches

Per ILEX-004 cleanup (status.md 2026-05-08T08:55Z) and the tdd skill's "Behavioral, not structural" rule. The 3 restored tests seed `auth_user` + `products` + `batches` rows via `pre_db`, then call `archive_product` / `delete_product`. They assert outcomes (return value, raised exception, `post_db` state). They do **not** import private helpers, monkey-patch `count_batches_for_product`, or assert which queries ran.

### `create_receipt_batches` runs after the procurement transaction commits

Procurement's `receive_purchase_order` (services.py:333) commits the PO header transition before calling `create_receipt_batches` (services.py:340). This is a known seam — if the inventory write fails, the PO is in `received` state with zero batches. Mitigations:
- The `@idempotent` decorator on `POST /purchase-orders/{id}/receive` caches the response, so client retries return the cached body without re-executing — no double-receive risk.
- The `(owner_id, product_id, batch_code) UNIQUE` constraint catches accidental duplicates at DB level.
- Future hardening (out of v1 scope): merge the two transactions by passing a connection through. Punted to a later issue if observability flags it.

This split is **not** introduced by ILEX-006; it was the architectural choice made in ILEX-005. ILEX-006 just fills in the previously-stub second half.

### On-hand projection in catalog list endpoint stays deferred

ILEX-004's planner deferred the `v_stock_by_batch` join in `apps.catalog.selectors.list_products` to ILEX-008 (financials). ILEX-006 ships the view but does **not** modify the catalog selector. ILEX-008 picks it up with the dashboard view + per-product margin, all consuming the same view chain.

### Function-local imports

Per the ilex-discipline skill invariant #6, **all** new modules in `apps/inventory/` use module-top imports. No `from apps.X import Y` inside function bodies. Procurement → inventory direction is already at module top (`apps/procurement/services.py:20`); the inverse import is forbidden by layer rules anyway (sales → inventory will also be top-level when ILEX-007 lands). No real cycle exists; no `# break cycle: ...` comments are needed in this issue.

### Single open question — none

All forward references and deferrals are documented above. The plan can proceed to `/execute` without further human input.
