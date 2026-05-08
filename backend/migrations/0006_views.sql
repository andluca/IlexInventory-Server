-- 0006_views.sql
-- Inventory views: v_stock_by_batch, v_expiring_soon.
-- v_recall_report is intentionally NOT here — it joins sale_allocations and
-- sales_orders which land in ILEX-007. ILEX-007 appends v_recall_report.
-- ILEX-008 (financials) appends v_margin_by_product.
-- All views use CREATE OR REPLACE to be idempotent on re-run.

-- v_stock_by_batch: per-batch on-hand quantity.
-- On-hand = SUM(signed_quantity) across all movements for the batch.
-- Powers FEFO, list endpoints, and catalog on-hand projection (ILEX-008).
CREATE OR REPLACE VIEW v_stock_by_batch AS
SELECT
    b.id                                                AS batch_id,
    b.owner_id                                          AS owner_id,
    b.product_id                                        AS product_id,
    COALESCE(SUM(m.signed_quantity), 0)::NUMERIC(14, 4) AS on_hand
FROM batches b
LEFT JOIN stock_movements m
       ON m.batch_id  = b.id
      AND m.owner_id  = b.owner_id
GROUP BY b.id, b.owner_id, b.product_id;


-- v_expiring_soon: batches with a known expiration date, not recalled,
-- and with positive on-hand stock. N days parameterized by caller filtering
-- on days_until_expiry.
CREATE OR REPLACE VIEW v_expiring_soon AS
SELECT
    b.id              AS batch_id,
    b.owner_id        AS owner_id,
    b.product_id      AS product_id,
    b.batch_code      AS batch_code,
    b.expiration_date AS expiration_date,
    (b.expiration_date - CURRENT_DATE) AS days_until_expiry,
    v.on_hand
FROM batches b
JOIN v_stock_by_batch v
  ON v.batch_id  = b.id
 AND v.owner_id  = b.owner_id
WHERE b.expiration_date IS NOT NULL
  AND b.is_recalled = FALSE
  AND v.on_hand > 0;
