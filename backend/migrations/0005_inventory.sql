-- 0005_inventory.sql
-- batches + stock_movements + append-only trigger.
-- Implements BE-D1, BE-D2, BE-D3, BE-D4, BE-D7, BE-D11.

-- batches: per-product lots with optional PO line link, FEFO-routable.
CREATE TABLE IF NOT EXISTS batches (
    id                       UUID            PRIMARY KEY DEFAULT uuidv7(),
    owner_id                 INT             NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    product_id               UUID            NOT NULL,
    purchase_order_line_id   UUID            NULL,
    batch_code               TEXT            NOT NULL,
    expiration_date          DATE            NULL,
    unit_cost                NUMERIC(14, 4)  NOT NULL,
    is_recalled              BOOLEAN         NOT NULL DEFAULT FALSE,
    recall_reason            TEXT            NULL,
    recalled_at              TIMESTAMPTZ     NULL,
    archived_at              TIMESTAMPTZ     NULL,
    created_at               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4 composite FKs (validates cross-table ownership at DB level)
    CONSTRAINT batches_product_owner_fkey
        FOREIGN KEY (product_id, owner_id) REFERENCES products (id, owner_id),
    CONSTRAINT batches_pol_owner_fkey
        FOREIGN KEY (purchase_order_line_id, owner_id)
        REFERENCES purchase_order_lines (id, owner_id),

    -- composite hook for sale_allocations (ILEX-007)
    CONSTRAINT batches_id_owner_unique UNIQUE (id, owner_id),

    -- batch_code unique per product per owner (D2: manual + procured share namespace)
    CONSTRAINT batches_owner_product_code_unique UNIQUE (owner_id, product_id, batch_code),

    -- Money discipline: unit_cost must be non-negative
    CONSTRAINT batches_unit_cost_nonneg CHECK (unit_cost >= 0),

    -- Recall consistency: is_recalled <-> recalled_at + recall_reason
    CONSTRAINT batches_recall_consistency CHECK (
        (is_recalled = FALSE AND recalled_at IS NULL AND recall_reason IS NULL)
        OR (is_recalled = TRUE AND recalled_at IS NOT NULL AND length(trim(recall_reason)) > 0)
    ),
    CONSTRAINT batches_code_not_blank CHECK (length(trim(batch_code)) > 0)
);

CREATE INDEX IF NOT EXISTS batches_owner_product_idx
    ON batches (owner_id, product_id);

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
    reference_type    TEXT            NULL,   -- 'purchase_order_line' | 'manual' | 'sale_allocation' | NULL
    reference_id      UUID            NULL,
    created_at        TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4 composite FK to batches (validates cross-table ownership)
    CONSTRAINT sm_batch_owner_fkey
        FOREIGN KEY (batch_id, owner_id) REFERENCES batches (id, owner_id),

    -- D1 + D7: kind enum
    CONSTRAINT sm_kind_chk CHECK (kind IN (
        'receipt', 'adjustment', 'write_off',
        'sale', 'sale_void',
        'recall_block', 'recall_unblock',
        'metadata_correction'
    )),

    -- Per-kind sign / qty rules (D1, D3, D7, F12)
    CONSTRAINT sm_sign_chk CHECK (
        (kind = 'receipt'                AND signed_quantity > 0)
        OR (kind = 'adjustment'          AND signed_quantity <> 0)
        OR (kind = 'write_off'           AND signed_quantity < 0)
        OR (kind = 'sale'                AND signed_quantity < 0)
        OR (kind = 'sale_void'           AND signed_quantity > 0)
        OR (kind = 'recall_block'        AND signed_quantity = 0)
        OR (kind = 'recall_unblock'      AND signed_quantity = 0)
        OR (kind = 'metadata_correction' AND signed_quantity = 0)
    ),

    -- D7: adjustment requires non-empty notes
    CONSTRAINT sm_adjustment_notes_chk CHECK (
        kind <> 'adjustment' OR (notes IS NOT NULL AND length(trim(notes)) > 0)
    )
);

CREATE INDEX IF NOT EXISTS sm_batch_idx
    ON stock_movements (batch_id);

CREATE INDEX IF NOT EXISTS sm_owner_created_idx
    ON stock_movements (owner_id, created_at DESC, id DESC);


-- Append-only enforcement (ilex-discipline invariant #5; D3)
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
