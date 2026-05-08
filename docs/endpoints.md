# Endpoints Catalog

All v1 endpoints, grouped by app. Each row's description is the contract until a full Endpoint spec lands under `docs/specs/`.

**Conventions:**
- All paths prefixed `/api/v1/`
- All endpoints require auth except the Auth section
- Cross-owner access returns 404 (BE-D4)
- `Idem?` — `✓` means the endpoint requires `Idempotency-Key` header; the server caches the response and returns the cached body on retry
- `Pag` — pagination strategy for list endpoints (`cursor` or `offset`)
- CSV export — endpoints marked **F11** support `?format=csv` (DRF content negotiation); response streams as `text/csv`

---

## Auth (apps/core)

Uses `django.contrib.auth` + DRF `SessionAuthentication`. Cookie session per BE-D? (auth decision pending lock).

| Verb | Path | Description |
|---|---|---|
| POST | /auth/signup | Create account: email + password. No email verification, no password reset (v1) |
| POST | /auth/login | Set session cookie |
| POST | /auth/logout | Clear session |
| GET | /auth/me | Current user info (consumed by app shell, ⌘K, agent context) |

---

## Catalog (apps/catalog) — products

| Verb | Path | Realizes | Pag | Idem? | Description |
|---|---|---|---|---|---|
| GET | /products | R1 | offset | — | List; search by name/SKU; filter `archived={true,false}`; includes derived on-hand totals |
| POST | /products | F2 | — | — | Register product (name, SKU unique per owner, description, base unit) |
| GET | /products/{id} | R1, R6 | — | — | Detail with batches summary |
| PATCH | /products/{id} | F2 | — | — | Edit name / description; SKU locked once first batch exists |
| POST | /products/{id}/archive | F2 | — | — | Soft delete (sets `archived_at`); only when product has batches |
| DELETE | /products/{id} | F2 | — | — | Hard delete; only when product has no batches |
| POST | /products/import | F2, F11 | — | ✓ | CSV import of products |

---

## Procurement (apps/procurement) — purchase orders

| Verb | Path | Realizes | Pag | Idem? | Description |
|---|---|---|---|---|---|
| GET | /purchase-orders | R5 | offset | — | List; filter by status (`draft` / `received`), supplier search, date range |
| POST | /purchase-orders | F3 | — | — | Create draft (supplier name + optional contact, lines) |
| GET | /purchase-orders/{id} | R5 | — | — | Detail; includes lines and (post-receive) batches created |
| PATCH | /purchase-orders/{id} | F3 | — | — | Edit draft (replace-style: full lines payload). 409 post-receive (BE-D6) |
| DELETE | /purchase-orders/{id} | F3 | — | — | Delete draft. 409 post-receive |
| POST | /purchase-orders/{id}/receive | F3 | — | ✓ | Terminal: one batch per line + receipt movements, atomic. Immutable thereafter |

---

## Inventory (apps/inventory) — batches, movements, recall

| Verb | Path | Realizes | Pag | Idem? | Description |
|---|---|---|---|---|---|
| GET | /batches | R1, R2 | offset | — | List; filter by product, recall status, `expiring_within={N}` days. Includes derived on-hand |
| GET | /batches/{id} | R1, R6 | — | — | Detail (on-hand, recall flag, expiration, source PO line if any) |
| POST | /batches | F4 | — | ✓ | Create manual batch + initial receipt movement (BE-D2: NULL PO-line FK, `reference_type='manual'`) |
| PATCH | /batches/{id} | F12 | — | — | Correct typos in `batch_code` or `expiration_date` only. Other fields rejected (use adjustment / recall endpoints). Writes a `metadata_correction` movement (qty=0) for audit. Naturally idempotent (no-op when value unchanged) |
| POST | /batches/{id}/movements | F5, F6 | — | partial | Record movement. Body `{kind, signed_quantity, notes}`. `kind` ∈ `adjustment` (BE-D7), `write_off`. Idempotency required for `write_off`, not for `adjustment` |
| POST | /batches/{id}/recall | F9 | — | ✓ | Set `is_recalled=true`; write `recall_block` movement (qty=0); reason required. Idempotent by design (BE-D3) |
| POST | /batches/{id}/un-recall | F10 | — | ✓ | Reverse recall; write `recall_unblock` movement |
| GET | /batches/{id}/recall-report | R7, F11 | offset | — | Customers who received units from this batch via committed, non-voided SOs |
| GET | /movements | R6, F11 | cursor | — | Cross-cutting audit; filter by batch, product, period, kind |

---

## Sales (apps/sales) — sales orders

| Verb | Path | Realizes | Pag | Idem? | Description |
|---|---|---|---|---|---|
| GET | /sales-orders | R4 | cursor | — | List; filter by status, voided, customer search, date range |
| POST | /sales-orders | F7 | — | — | Create draft (customer name + optional contact, lines with sell price) |
| GET | /sales-orders/{id} | R4 | — | — | Detail; includes lines and (post-commit) allocations |
| PATCH | /sales-orders/{id} | F7 | — | — | Edit draft (replace-style). 409 post-commit (BE-D6) |
| DELETE | /sales-orders/{id} | F7 | — | — | Delete draft. 409 post-commit |
| POST | /sales-orders/{id}/preview | F7 | — | — | FEFO dry-run: returns proposed allocations without committing. Used by FE for the preview |
| POST | /sales-orders/{id}/commit | F7 | — | ✓ | Terminal: walks FEFO; writes allocations + sale movements; immutable. Body may include explicit allocation list (BE-D11 admin override) |
| POST | /sales-orders/{id}/void | F8 | — | ✓ | Reversal movements + `voided_at`; allocations remain. Idempotent by design (BE-D8) |

---

## Financials (apps/financials)

| Verb | Path | Realizes | Pag | Idem? | Description |
|---|---|---|---|---|---|
| GET | /financials/dashboard | R3, F11 | — | — | Revenue, COGS, profit, margin totals + top-product breakdown. Params: `from`, `to` (default last 30 days) |
| GET | /financials/margin | R3, F11 | offset | — | Per-product margin detail. Same date-range params |

**Profit margin formula** (per BE-D13): `(revenue − COGS) / COGS × 100%`. Matches the take-home brief's worked example exactly: `$1,000` revenue − `$100` cost = `$900` profit / `$100` cost = **900%**. This is the markup / return-on-cost definition; we label the metric "Profit Margin" to match the brief's wording.

---

## Agent (apps/agent) — Phase 3 (out of v1 BE MVP)

Single endpoint; internal tools (allowlisted-view query, SO draft assembly) live behind it as service-layer functions, not public endpoints.

| Verb | Path | Realizes | Description |
|---|---|---|---|
| POST | /agent/chat | A1, A2, A3 | Body `{message, context: {route, filters, selected_ids}}`. Returns `{reply, drafts?}`. Auth via Claude Max OAuth token (BE-D? pending) |

---

## Health & meta

| Verb | Path | Description |
|---|---|---|
| GET | /health | Liveness + DB connectivity |
| GET | /openapi.json | drf-spectacular schema (consumed by FE type generation) |
| GET | /docs | Swagger UI (dev only) |

---

## Counts

v1 (excluding agent + meta): **36 endpoints**

| App | Count |
|---|---|
| Auth | 4 |
| Catalog | 7 |
| Procurement | 6 |
| Inventory | 9 |
| Sales | 8 |
| Financials | 2 |
| Agent (Phase 3) | 1 |
| Health/meta | 3 |

---

## Open / TBD

- Cursor encoding for paginated lists (UUIDv7 ordering + tiebreaker on `created_at`)
- CSV import shape for manual stock entries and POs (currently products only — could land later)
- Rate limiting (probably one global limit v1; per-endpoint deferred)
- Agent OAuth-token validation flow (BE-D? to be locked when agent app starts)
- Whether `/openapi.json` and `/docs` live under `/api/v1/` or root (`/openapi.json`)
