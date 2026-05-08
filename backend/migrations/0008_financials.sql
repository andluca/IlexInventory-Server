-- 0008_financials.sql
-- Financials view: v_margin_by_product.
-- Joins sale_allocations with sales_order_lines.sell_price, batches.unit_cost,
-- and products.name. One row per (owner_id, product_id, sales_order_id).
-- Implements BE-D13, Flow R3, F11.

-- v_margin_by_product: per-(owner, product, sales_order) revenue and COGS.
-- Filter: committed, non-voided SOs only (D8: voided treated as never sold).
-- Selector aggregates these rows up to per-product totals at query time.
CREATE OR REPLACE VIEW v_margin_by_product AS
SELECT
    sa.owner_id                                                     AS owner_id,
    sol.product_id                                                  AS product_id,
    p.name                                                          AS product_name,
    so.id                                                           AS sales_order_id,
    so.committed_at                                                 AS committed_at,
    SUM(sa.allocated_quantity)::NUMERIC(14, 4)                      AS units_sold,
    SUM(sa.allocated_quantity * sol.sell_price)::NUMERIC(14, 4)     AS revenue,
    SUM(sa.allocated_quantity * sa.unit_cost)::NUMERIC(14, 4)       AS cogs
FROM sale_allocations sa
JOIN sales_order_lines sol
  ON sol.id       = sa.sales_order_line_id
 AND sol.owner_id = sa.owner_id
JOIN sales_orders so
  ON so.id        = sol.sales_order_id
 AND so.owner_id  = sol.owner_id
JOIN products p
  ON p.id         = sol.product_id
 AND p.owner_id   = sol.owner_id
WHERE so.status    = 'committed'
  AND so.voided_at IS NULL
GROUP BY
    sa.owner_id,
    sol.product_id,
    p.name,
    so.id,
    so.committed_at;

-- Index to support date-range filtering by the selector.
CREATE INDEX IF NOT EXISTS so_committed_at_idx
    ON sales_orders (owner_id, committed_at DESC);
