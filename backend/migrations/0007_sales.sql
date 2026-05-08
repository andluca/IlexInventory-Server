-- 0007_sales.sql
-- sales_orders + sales_order_lines + sale_allocations + v_recall_report.
-- Implements BE-D4, BE-D6, BE-D8, BE-D9, BE-D10, BE-D11; Flows F7, F8, F11.

-- sales_orders: header for a customer sale. status transitions: draft → committed.
-- voided_at is set on void (D8: allocations remain, reversal movements are appended).
CREATE TABLE IF NOT EXISTS sales_orders (
    id               UUID            PRIMARY KEY DEFAULT uuidv7(),
    owner_id         INT             NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    customer_name    TEXT            NOT NULL,
    customer_contact TEXT            NULL,       -- D10: text only, no customers table
    status           TEXT            NOT NULL DEFAULT 'draft',
    committed_at     TIMESTAMPTZ     NULL,
    voided_at        TIMESTAMPTZ     NULL,
    created_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4: composite hook for child tables (sales_order_lines composite FK)
    CONSTRAINT so_id_owner_unique UNIQUE (id, owner_id),

    -- D6: status must be draft or committed
    CONSTRAINT so_status_chk CHECK (status IN ('draft', 'committed')),

    -- Committed timestamp must be set when committed (and NULL when draft)
    CONSTRAINT so_committed_consistency_chk CHECK (
        (status = 'draft'     AND committed_at IS NULL)
        OR (status = 'committed' AND committed_at IS NOT NULL)
    ),

    -- voided_at requires committed (D8: only committed SOs can be voided)
    CONSTRAINT so_voided_requires_committed_chk CHECK (
        voided_at IS NULL OR status = 'committed'
    ),

    -- customer_name must be non-blank (D10)
    CONSTRAINT so_customer_name_not_blank CHECK (length(trim(customer_name)) > 0)
);

CREATE INDEX IF NOT EXISTS so_owner_created_idx
    ON sales_orders (owner_id, created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS so_owner_status_idx
    ON sales_orders (owner_id, status);


-- sales_order_lines: one row per (SO, product) pairing in the order.
-- Allocated after commit; allocations reference lines via composite FK.
CREATE TABLE IF NOT EXISTS sales_order_lines (
    id              UUID            PRIMARY KEY DEFAULT uuidv7(),
    owner_id        INT             NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    sales_order_id  UUID            NOT NULL,
    product_id      UUID            NOT NULL,
    quantity        NUMERIC(14, 4)  NOT NULL,
    sell_price      NUMERIC(14, 4)  NOT NULL,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4 composite FK to sales_orders (validates cross-table ownership)
    CONSTRAINT sol_so_owner_fkey
        FOREIGN KEY (sales_order_id, owner_id) REFERENCES sales_orders (id, owner_id),

    -- D4 composite FK to products (validates cross-table ownership)
    CONSTRAINT sol_product_owner_fkey
        FOREIGN KEY (product_id, owner_id) REFERENCES products (id, owner_id),

    -- Composite hook for sale_allocations (ILEX-007)
    CONSTRAINT sol_id_owner_unique UNIQUE (id, owner_id),

    -- qty must be positive; price non-negative (SPEC §3.5)
    CONSTRAINT sol_quantity_positive CHECK (quantity > 0),
    CONSTRAINT sol_sell_price_nonneg CHECK (sell_price >= 0)
);

CREATE INDEX IF NOT EXISTS sol_so_idx
    ON sales_order_lines (sales_order_id);


-- sale_allocations: immutable post-commit (D8). Voids append reversal movements,
-- never touch allocation rows. One allocation row per (line, batch) pairing.
CREATE TABLE IF NOT EXISTS sale_allocations (
    id                  UUID            PRIMARY KEY DEFAULT uuidv7(),
    owner_id            INT             NOT NULL REFERENCES auth_user(id) ON DELETE CASCADE,
    sales_order_line_id UUID            NOT NULL,
    batch_id            UUID            NOT NULL,
    allocated_quantity  NUMERIC(14, 4)  NOT NULL,
    unit_cost           NUMERIC(14, 4)  NOT NULL,   -- copied from batch at commit time
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- D4 composite FK to sales_order_lines (validates cross-table ownership)
    CONSTRAINT sa_sol_owner_fkey
        FOREIGN KEY (sales_order_line_id, owner_id)
        REFERENCES sales_order_lines (id, owner_id),

    -- D4 composite FK to batches (validates cross-table ownership)
    CONSTRAINT sa_batch_owner_fkey
        FOREIGN KEY (batch_id, owner_id) REFERENCES batches (id, owner_id),

    -- allocated_quantity must be positive
    CONSTRAINT sa_allocated_quantity_positive CHECK (allocated_quantity > 0),

    -- unit_cost must be non-negative (batch cost copied at commit time)
    CONSTRAINT sa_unit_cost_nonneg CHECK (unit_cost >= 0)
);

CREATE INDEX IF NOT EXISTS sa_line_idx
    ON sale_allocations (sales_order_line_id);

CREATE INDEX IF NOT EXISTS sa_batch_idx
    ON sale_allocations (batch_id);


-- v_recall_report: customers who received units from a given batch.
-- Filtered by caller on batch_id; emits only committed, non-voided SOs (R7, F11).
-- Lives here (not in 0006_views.sql) because it joins sales tables.
CREATE OR REPLACE VIEW v_recall_report AS
SELECT
    sa.batch_id                                                     AS batch_id,
    so.id                                                           AS sale_order_id,
    so.owner_id                                                     AS owner_id,
    so.customer_name                                                AS customer_name,
    so.customer_contact                                             AS customer_contact,
    SUM(sa.allocated_quantity)::NUMERIC(14, 4)                      AS quantity_received,
    so.committed_at                                                 AS sale_committed_at
FROM sale_allocations sa
JOIN sales_order_lines sol
  ON sol.id        = sa.sales_order_line_id
 AND sol.owner_id  = sa.owner_id
JOIN sales_orders so
  ON so.id         = sol.sales_order_id
 AND so.owner_id   = sol.owner_id
WHERE so.status    = 'committed'
  AND so.voided_at IS NULL
GROUP BY
    sa.batch_id,
    so.id,
    so.owner_id,
    so.customer_name,
    so.customer_contact,
    so.committed_at;
