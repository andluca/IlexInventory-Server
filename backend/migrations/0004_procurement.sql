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

    -- Money/qty positivity (SPEC §2.5; brief: positive quantities and non-negative costs).
    CONSTRAINT pol_quantity_positive CHECK (quantity > 0),
    CONSTRAINT pol_unit_cost_nonneg  CHECK (unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS pol_owner_po_idx
    ON purchase_order_lines (owner_id, purchase_order_id);

CREATE INDEX IF NOT EXISTS pol_owner_product_idx
    ON purchase_order_lines (owner_id, product_id);
