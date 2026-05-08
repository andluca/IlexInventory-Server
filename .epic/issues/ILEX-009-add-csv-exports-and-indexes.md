---
id: ILEX-009
github_id: null
status: open
assignee: null
state: Queued
type: item
depends_on: [ILEX-008]
---

# ILEX-009 Add CSV exports and 0007_indexes

Cross-cutting polish: wire `?format=csv` content negotiation across the supporting read endpoints, and land the indexes needed for FEFO walk performance, audit query performance, and cursor pagination.

# Specification

Reference: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.6, §3.7. Flow F11.

## Scope

- `backend/migrations/0007_indexes.sql`:
  - `(owner_id, product_id, expiration_date NULLS LAST, created_at)` on `batches` — FEFO walk
  - `(owner_id, batch_id, created_at DESC)` on `stock_movements` — audit queries
  - `(owner_id, status, created_at DESC)` on `sales_orders` — cursor pagination ordering
  - Confirm `(owner_id, sku)` UNIQUE on `products` is used for search
- DRF CSV renderer registered in `DEFAULT_RENDERER_CLASSES`; content negotiation wired via `?format=csv` query param
- Per-endpoint `Renderer` classes that flatten the JSON shape into rows: header row matching JSON keys, dates ISO-8601, money/qty as raw decimal strings
- Streaming response (`StreamingHttpResponse`) for large exports
- Endpoints affected: `/financials/dashboard`, `/financials/margin`, `/movements`, `/batches/{id}/recall-report`

## Tests

- CSV correctness: header row, row count matches JSON, decimal format preserved
- Index usage: `EXPLAIN ANALYZE` on FEFO query in fixtures shows the expected index scan

## Dependencies

1. ILEX-008 (all read endpoints supporting CSV must exist before wiring negotiation)
