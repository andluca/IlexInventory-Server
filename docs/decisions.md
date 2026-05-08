# Decisions

Why the project looks the way it does. One entry per load-bearing technical decision, listed in numerical order. Numbers are stable: a decision keeps its number even if it later gets superseded.

## D0 — Procurement: header + lines

`purchase_orders` + `purchase_order_lines`. Sales mirror this.

POs are multi-product in real F&B procurement; flat would force supplier/dates/status to repeat on every line and break aggregation under drift. Batches FK to a line, not a PO.

Rejected: flat single table.

## D1 — `stock_movements.quantity` is signed

Positive = stock in, negative = stock out. On-hand = `SUM(quantity)`. CHECK constraints per kind (`kind='sale' → qty<0`, etc.) plug the integrity gap. Tilts toward signed because the agent's allowlisted views in `product.md` stay CASE-free.

Rejected: unsigned quantity with sign derived via CASE on kind.

## D2 — Manual stock entries skip the PO tables

`batches.purchase_order_line_id` is nullable. Manual entry creates a batch with NULL FK + a receipt movement (`reference_type='manual'`). PO tables stay reserved for real procurement.

Rejected: synthetic "manual" POs (would pollute every PO listing/report).

## D3 — Recall: flag + qty=0 audit movements

`is_recalled` lives on `batches` for O(1) FEFO check. Recall events are `stock_movements` rows with `kind='recall_block'` / `'recall_unblock'` and `signed_quantity=0`. Single audit trail; aggregations filter qty=0.

Rejected: separate `batch_events` table (two audit trails, UNION on batch-history queries).

## D4 — Owner isolation: composite FKs + denormalized owner_id

Every owner-scoped table carries `owner_id`. FKs reference `(id, owner_id)` composites — e.g. `sale_allocations (batch_id, owner_id) → batches (id, owner_id)`. Cross-owner data fusion bugs fail at FK check on insert. Service-layer owner injection is the primary line of defense; composite FKs are the safety net for bugs the service alone can't catch.

Rejected: service-only (silent on cross-owner data fusion); RLS (catches forgot-to-filter but not cross-table consistency, and adds per-connection ceremony).

## D5 — Primary keys: UUIDv7

Time-ordered UUIDs. Opaque (no row-count leak), client-generatable, don't collide across instances. Pairs with D4's defense-in-depth and the agent's `selected_ids` flow. Postgres 16 needs a ~10-line Python helper for generation; insert locality nearly matches bigserial because of the time-ordered prefix.

Rejected: bigserial (exposes row counts in URLs/logs); UUIDv4 (poor B-tree locality); dual bigserial PK + UUID external_id (two ID columns per table, more index overhead).

## D6 — PO/SO: two states, terminal is immutable

`purchase_orders.status`: `draft | received`. `sales_orders.status`: `draft | committed`. Drafts mutate freely and write nothing to the ledger. Terminal states write the ledger and freeze the document. Corrections after terminal use reversal movements (D8), not state flips.

Out of scope (v1): partial receipts (PO arrives 3 of 5 lines).

Rejected: live-on-creation (every line edit pollutes the ledger); explicit `void` state (redundant with reversal + `voided_at`); multi-stage workflow (out of v1 scope per `product.md`).

## D7 — Single `kind='adjustment'`

Direction comes from signed quantity (D1); reason comes from `notes` (free text, required by service for adjustments). One enum value covers shrinkage, found stock, and corrections. If reason-based analytics become needed, add a `reason_code` column — additive.

Rejected: split into `adjustment_in` / `adjustment_out` (redundant with D1's signed quantity); reason-as-kind enums (`cycle_count`, `damaged`, etc. — conflates structure with content, schema migration per new reason).

## D8 — Allocations immutable; voids via reversal movements

`sale_allocations` rows never UPDATE or DELETE post-commit. Voiding an SO inserts reversal `stock_movements` (`kind='sale_void'`, positive qty back to the batch) and sets `voided_at` on the SO header. Allocation rows stay as historical record.

`sale_void` is a distinct kind so void reversals don't pollute shrinkage analytics. `v_recall_report` filters `WHERE so.voided_at IS NULL` — in v1, voided SOs mean units never effectively left the warehouse.

Out of scope (v1): partial returns ("customer returned 5 of 30 cans"). Per-line `voided_at` granularity would solve it.

Rejected: versioned allocations with `effective_until` / `superseded_by` (overkill for v1); direct UPDATE on allocations (destroys ledger integrity).

## D9 — Recall blocks future sales only

A recalled batch is invisible to FEFO. Past sales appear in `v_recall_report` for the owner to act on out-of-band. Reversing past sales is **not** automatic — that's an explicit SO void (D8) initiated by the owner.

Consistent with D3 (recall = flag + audit, no stock effect) and D8 (corrections are explicit user events).

Rejected: auto-reversing past allocations on recall (would rewrite committed SOs without explicit consent and pollute the ledger with phantom undo events).

## D10 — Customer/supplier as text + nullable contact

`sales_orders.customer_name` (text, required), `sales_orders.customer_contact` (text, nullable). Symmetric on POs: `purchase_orders.supplier_name` (required), `purchase_orders.supplier_contact` (nullable). Service warns at SO commit if `customer_contact` is empty: "no contact info — this customer won't appear in the recall report."

Rejected: separate customers/suppliers tables (out of v1 scope per `product.md`); hard NOT NULL on contact (some sales channels legitimately lack contact info — soft warning over hard enforce).

## D11 — FEFO ignores expired batches; admin overrides explicitly

FEFO filters `expiration_date IS NULL OR expiration_date >= CURRENT_DATE`. Expired batches become ghost stock — not auto-allocatable. Admin clears them via write-off or by passing a manual `allocations` list on SO commit (which bypasses FEFO).

F&B compliance leans toward never selling expired by accident. No "saleable-when-expired" flag — the explicit allocation list IS the opt-in.

Rejected: letting FEFO sell expired stock with only a UI warning. Too easy to oversee by accident.

## D12 — Backend layering: APIs → Services + Selectors → Queries → Schema

Four layers. APIs (DRF, thin) call Services (writes, transactions) or Selectors (reads); both call Queries (typed Python wrapping psycopg). Queries hit the Schema (plain SQL migrations + views).

Adapts the HackSoft Django Styleguide (`github.com/HackSoftware/Django-Styleguide`) to our no-ORM constraint. HackSoft splits business logic into Services (writes) and Selectors (reads), keeps APIs thin, and explicitly rejects the Repository pattern: *"trying to place all of your business logic in a custom manager is not a great idea."* Their pattern assumes the ORM absorbs SQL via models; we don't have that, so we add an explicit Queries layer to host parameterized SQL functions per aggregate.

Rejected: 3-layer (HTTP → Service-with-inline-SQL → DB) — services bloat with SQL strings, hard to grep/audit, no place for the agent's allowlisted-view functions to live cleanly. Rejected: Repository pattern (HTTP → Service → Repository → DB) — imports DDD/Java vocabulary that doesn't fit Django culture; per HackSoft, services-vs-selectors is the idiomatic Django split for the same problem.

## D14 — `django.contrib.auth.User` is the only ORM-managed model

`django.contrib.auth.User` (and the auth app's session/migration tables) are the **only** Django ORM-managed entities in the project. Every business model — products, POs, batches, stock_movements, SOs, allocations, idempotency keys — is raw SQL via psycopg per D12.

Why the carve-out: writing our own users table forces us to re-implement password hashing, session management, and the auth middleware Django ships with — for no v1 benefit. The architecture's "no Django ORM" rule exists to keep business logic out of model layers, not to forbid using Django's built-in auth.

**Boundary:** the `auth_user` table is provisioned by Django's standard migration (`python manage.py migrate auth`). Our raw-SQL migrations under `backend/migrations/` reference `auth_user.id` via composite FK `(owner_id, ...)` patterns; the FK target is `auth_user(id)`. No business code imports `User.objects` — services receive `owner_id` as a UUID parameter from the API layer, never a Django model instance.

CI grep gate is updated: `from django.db.models` is forbidden **except** in `apps/core/auth.py` (which is allowed to `from django.contrib.auth import authenticate, login, logout, get_user_model`). All other imports of Django ORM machinery fail the gate.

Rejected: a bespoke users table written in raw SQL. Would re-implement Django's password hashers, session machinery, CSRF, and auth views — work that adds no v1 value and risks security bugs in our hand-rolled crypto/session code.

`profit_margin = (revenue − COGS) / COGS × 100%`. Matches the take-home brief's worked example exactly: `$1,000` revenue − `$100` cost = `$900` profit / `$100` cost = **900%**. Reported in API and UI as "Profit Margin".

Standard "profit margin" in finance textbooks is `(revenue − COGS) / revenue × 100%` (which would give 90% on the same example) — that definition is **not** what the brief expects. We label our metric "Profit Margin" to match the brief's wording but compute it as markup / return-on-cost.

Rejected: textbook gross-margin formula (would silently disagree with the brief's evaluation example); reporting both side-by-side (clutters the dashboard for no v1 benefit).
