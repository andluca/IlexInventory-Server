# Scratch — Requirements brainstorm

Working notes from the requirements brainstorm. **NOT a spec artifact.** Captures resolved decisions + open questions until they land in formal specs (flows, endpoints, decisions.md). Delete or move when superseded.

Uncommitted; lives outside the spec system.

---

## Resolved (this session)

| # | Topic | Decision |
|---|---|---|
| 1 | Auth | Session cookies for users (DRF default). Agent uses Claude Max OAuth token. |
| 2 | Sign-up | In scope. Email + password (simplest). |
| 3 | API versioning | `/api/v1/` |
| 4 | Pagination | Cursor for SO list and movement audit; offset for product list |
| 5 | Idempotency keys | `POST /receive`, `POST /commit`, manual stock entry, write-off |
| 6 | Batch code | Owner-input, validated unique per `(product, owner)`; system fallback if blank |
| 7 | Expiration date | Nullable; FEFO sorts NULLs last |
| 8 | Product mutability | SKU locked once first batch exists; name/description always editable |
| 9 | Soft delete | Products with batches: archive only. Without batches: hard delete OK |
| 10 | Recall report scope | Batch-only v1 (defer by-PO and by-supplier) |
| 11 | Notifications | Out v1 — dashboard widget IS the channel |
| 12 | CSV import / OCR | CSV import in v1; invoice OCR deferred |

---

## Flows (catalog from brainstorm)

### Write flows

| # | Flow | Trigger | Terminal state |
|---|---|---|---|
| F1 | Onboard | Sign-up / first login | Owner has 1 product + 1 batch |
| F2 | Catalog mgmt | Add / edit products | Product registered |
| F3 | Procure | PO draft → receive | PO `received`; batches + receipt movements |
| F4 | Manual stock entry | Stock without PO | Batch with NULL PO-line FK + receipt movement |
| F5 | Adjust | Count drift / shrinkage / found | `adjustment` movement (signed, reason in notes) |
| F6 | Write off | Remove unsaleable stock | `write_off` movement (negative) |
| F7 | Sell | SO draft → commit | SO `committed`; allocations + sale movements (FEFO) |
| F8 | Void sale | Mistake / return / recall fallout | `sale_void` reversals; `voided_at` set |
| F9 | Recall | Contamination notice | `is_recalled=true`; `recall_block` movement |
| F10 | Un-recall | False alarm | `is_recalled=false`; `recall_unblock` movement |
| F11 | Export report (CSV) | Owner clicks "Export" | Read-only CSV download (no state change) |
| F12 | Correct batch metadata | Owner notices a typo on `batch_code` or `expiration_date` | Fields updated; `metadata_correction` movement (qty=0) written for audit |

### Read flows

| # | Flow | Surface |
|---|---|---|
| R1 | Stock list | By product, by batch |
| R2 | Expiring within N days | Widget + dedicated view |
| R3 | Financial dashboard | Revenue, COGS, profit, margin per product |
| R4 | SO history | List, detail with allocations |
| R5 | PO history | List, detail with batches created |
| R6 | Movement audit | Per batch / product / period |
| R7 | Recall report | Per batch — customers who received units |

### Agent flows

| # | Mode | Side effect | Example |
|---|---|---|---|
| A1 | Query | None | "What's expiring next week?" |
| A2 | Draft | Returns object to UI for confirmation | "Create SO for Acme — 20 cans Cold Brew" |
| A3 | Explain | None (composes multiple read queries) | "Why did Cold Brew margin drop 8%?" |

### Auth flows

| # | Flow |
|---|---|
| X1 | Log in / log out |
| X2 | Sign up (email + password) |

---

## NFRs likely to become decisions (D13+)

- Agent guardrails: 5s statement timeout, 1000-row cap, allowlisted views only
- p95 latency budgets — propose 200ms read / 500ms commit
- Currency hard-coded USD v1
- Storage UTC; display browser-local

---

## Open (still TBD)

- CSV import schema for manual stock / POs (products schema known; others deferred)
- Agent action log retention
- Cursor encoding for paginated lists (UUIDv7 + tiebreaker)
- Rate limiting per endpoint vs global

---

## Resolved follow-ups

| Topic | Decision |
|---|---|
| Manual stock entry UI surface | From batch detail page; F4 still creates a new batch per BE-D2 (existing batch is the UI starting context, not the target) |
| Sign-up confirmation | Trust + accept (no email verification) |
| Password reset | Out v1 |

---

## Pages (FE — full mapping in `../../IlexInventory-Client/docs/product.md`)

Public: `/login`, `/signup`.

Authenticated: `/` (Dashboard), `/products`, `/products/:id`, `/purchase-orders` (+ `/new`, `/:id/edit`, `/:id`), `/sales-orders` (+ `/new`, `/:id/edit`, `/:id`), `/stock`, `/batches/:id` (+ `/recall-report`), `/settings`.

Cross-cutting modals: CSV import, agent chat panel.
