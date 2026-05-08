-- 0003_catalog.sql — products (owner-scoped, UUIDv7 PK, archive-soft-delete).
--
-- Owner isolation (D4):
--   - UNIQUE(owner_id, sku)     → SKU is unique within an owner's catalog
--   - UNIQUE(id, owner_id)      → composite hook for child tables (batches etc.)
--     to FK against (product_id, owner_id) — prevents cross-owner batch references.
--
-- Archive semantics (D6):
--   - archived_at IS NULL  → active
--   - archived_at IS NOT NULL → archived (soft-deleted)
--   - Hard DELETE is allowed only when the product has no batches (enforced in service).
--
-- base_unit allowlist: g / ml / unit — display-layer unit conversion is FE's job.

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
