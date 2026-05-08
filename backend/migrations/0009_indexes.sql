-- 0009_indexes.sql
-- Cross-cutting composite indexes deferred from earlier migrations.
-- Uses CREATE INDEX IF NOT EXISTS so the file is idempotent under migrate_sql.
-- Implements ILEX-009.

-- ============================================================
-- VERIFIED ALREADY-PRESENT INDEXES (not re-created here)
-- ============================================================
--
-- batches
--   batches_owner_product_expiry_idx (owner_id, product_id, expiration_date NULLS LAST, created_at)
--     Source: 0005_inventory.sql — FEFO walk covering index
--
-- stock_movements
--   sm_owner_created_idx (owner_id, created_at DESC, id DESC)
--     Source: 0005_inventory.sql — global audit cursor pagination
--   sm_batch_idx (batch_id)
--     Source: 0005_inventory.sql — batch FK lookup
--
-- sales_orders
--   so_owner_created_idx (owner_id, created_at DESC, id DESC)
--     Source: 0007_sales.sql — SO list cursor pagination
--   so_owner_status_idx (owner_id, status)
--     Source: 0007_sales.sql — status-only filter (single-column, no ordering)
--   so_committed_at_idx (owner_id, committed_at DESC)
--     Source: 0008_financials.sql — financials date-range filter
--
-- products
--   (owner_id, sku) UNIQUE — catalog lookup
--     Source: 0003_catalog.sql
--
-- ============================================================
-- NEW COMPOSITE INDEXES ADDED IN THIS MIGRATION
-- ============================================================

-- stock_movements: composite index for batch-scoped audit queries.
-- Used by: GET /movements?batch_id=<id> and per-batch ledger reads in selectors.
-- Ordering: created_at DESC matches the query ORDER BY clause.
CREATE INDEX IF NOT EXISTS sm_owner_batch_created_idx
    ON stock_movements (owner_id, batch_id, created_at DESC);

-- sales_orders: composite index for status-filtered cursor pagination.
-- Used by: GET /sales-orders?status=draft&cursor=... pagination ordering.
-- Columns ordered (owner_id, status, created_at DESC) match the WHERE + ORDER BY.
CREATE INDEX IF NOT EXISTS so_owner_status_created_idx
    ON sales_orders (owner_id, status, created_at DESC);
