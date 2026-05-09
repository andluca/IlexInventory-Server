---
id: ILEX-016
github_id: null
status: completed
assignee: null
state: Done
type: item
depends_on: [ILEX-011]
---

# ILEX-016 Polish v1 MVP and fundament Phase 3 (agent)

Close out the v1 MVP with a single, deliberate polish pass: fix the silent ledger bug surfaced by code review, close the three idempotency / 404-envelope drifts, hoist the cross-app SQL violation back into the queries layer, retire the SOLID/DRY tax that has accreted across six apps, and ship the documents at the quality the schema commitments deserve. The pass also makes the agent (Phase 3) the explicit next step — not by starting it, but by **proving the foundation is ready**: the read-only role can be added, the view rewrites can swap in, and the explanation skills can read what they need without surprises. Nothing in this issue ships a new endpoint. It is the seam between "this works" and "this can carry the agent."

This is the final v1 MVP issue. After it, ILEX-012 (`apps/agent/` foundation + read-only role) is unblocked.

References: [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.6 (idempotency, error envelope), §3.5 (SO commit semantics), [`docs/specs/agent.md`](../../docs/specs/agent.md) §2.3 (database substrate), §6 (validation gates), [`docs/decisions.md`](../../docs/decisions.md) D1, D4, D6, D8, D11, D12, [`.claude/skills/code-review-partner/SKILL.md`](../../.claude/skills/code-review-partner/SKILL.md).

---

# Specification

The work splits into four pillars. They are not parallelizable end-to-end — the bug fixes (Pillar 1) come first because they are the only changes that alter observable behavior; everything else is structural or documentary and rests on the bugs being closed.

## Pillar 1 — Bugs (P0, behavioral)

These are not lint findings. Each one alters or restores correctness on a path the system actually runs.

### 1.1 FEFO double-allocation across lines of the same SO

[`backend/apps/sales/services.py:128`](../../backend/apps/sales/services.py#L128) — `_fefo_walk` calls `list_eligible_for_fefo` once per line and decides each line's allocations against the **untouched on-hand snapshot**. Two lines of the same SO that reference the same product both see the same `on_hand` and both plan to drain the same batch. The DB does not stop them: `stock_movements` has CHECKs on `kind` ↔ sign of `signed_quantity`, but no constraint on cumulative on-hand. A single committed SO can drive a batch's on_hand negative.

**Fix.** Thread a running `batch_usage: dict[str, Decimal]` (keyed by `batch_id`) through the per-line loop. For each line, compute `available[batch] = batch.on_hand - batch_usage.get(batch.id, Decimal("0"))` before the greedy take, and accumulate `batch_usage[batch.id] += take` after. Tests must include: (a) two SO lines, same product, demand sums to less than total on-hand → both get allocated correctly without overlap, (b) two SO lines, same product, demand sums to more than total on-hand → InsufficientStock with shortfall computed across both lines.

**Why it's silent today.** No SO test exercises two lines for the same product. The `_validate_explicit_allocations` path enforces per-batch caps on the explicit-allocations admin override (D11), so the bug only fires on the FEFO default path.

### 1.2 `write_off` lacks `Idempotency-Key` enforcement

[`backend/apps/inventory/apis.py:185`](../../backend/apps/inventory/apis.py#L185) — `BatchMovementsApi.post` accepts both `kind=adjustment` and `kind=write_off` on a single endpoint. SPEC §2.6 requires an `Idempotency-Key` header on `POST /batches/{id}/movements (write_off)`. The endpoint has no `@idempotent` decorator. A retry of a write_off can double-debit stock; the existing skip-rationale comment in [`backend/apps/inventory/tests/api/test_batches_movements.py:120-146`](../../backend/apps/inventory/tests/api/test_batches_movements.py#L120-L146) acknowledges this and ducked the test.

**Fix (option A, preferred).** Split the endpoint into two routes — `POST /batches/{id}/adjustments` (no idempotency) and `POST /batches/{id}/write-offs` (with `@idempotent("inventory.write_off")`). This matches the spec's two-key separation and keeps the decorator declarative.

**Fix (option B).** Keep the single endpoint, wrap the view body in a kind-conditional dispatch (`if kind == "write_off": return idempotent_write_off(self, request, *args, **kwargs)`), and decorate the inner function. Keeps URLs stable but adds plumbing.

Plan picks (A). Spec §3.4 will need a one-line update to reflect the URL split.

### 1.3 Idempotency cache crash on Decimal/datetime/UUID bodies

[`backend/apps/core/idempotency.py:138`](../../backend/apps/core/idempotency.py#L138) — `json.dumps(body)` is called on a DRF `response.data` dict that may contain `Decimal`, `datetime`, or `UUID` objects (anywhere money/qty/timestamps/ids appear). Default `json.dumps` raises `TypeError` on those types. The `except psycopg.Error` block does not catch `TypeError`, so the cache silently never persists for `commit_sales_order`, `receive_purchase_order`, `record_movement`, `recall_batch`, `un_recall_batch`, `void_sales_order`, or `import_products_csv`. Idempotency is a no-op on the critical path it was built for.

**Fix.** Render the response before serializing the body for cache:
```python
response.render() if hasattr(response, "render") and not response.is_rendered else None
body = response.content.decode("utf-8") if response.is_rendered else "{}"
```
…and store as text (the column type is already `jsonb`). Or pass `default=str` to `json.dumps`, which is permissive but lossy for Decimal precision.

Plan picks the first. Tests must include: (a) commit an SO twice with the same key, the second response is byte-for-byte identical to the first (cache hit), (b) commit an SO with a Decimal in the response, no `TypeError` is raised, the second call hits the cache.

### 1.4 Empty `{}` 404 body — error envelope drift in three sites

[`backend/apps/inventory/apis.py:142`](../../backend/apps/inventory/apis.py#L142) (`BatchDetailApi.get`), [`backend/apps/inventory/apis.py:356`](../../backend/apps/inventory/apis.py#L356) (`BatchRecallReportApi.get`), and [`backend/apps/sales/apis.py:134`](../../backend/apps/sales/apis.py#L134) (`SalesOrderDetailApi.get`) all `return Response({}, status=status.HTTP_404_NOT_FOUND)`. SPEC §2.6 mandates `{"error": "<Code>", "detail": "<msg>"}`. The frontend type generation derives error-shape types from this contract; an empty body breaks the discriminated union.

**Fix.** Each site:
```python
body, http_status = to_response(<Code>NotFound(detail=f"<resource> {id} not found."))
return Response(body, status=http_status)
```
The right code per site:

| Site | Code | Lives in |
|---|---|---|
| `inventory/apis.py:142` | `BatchNotFound` | `apps/inventory/errors.py` (already defined) |
| `inventory/apis.py:356` | `BatchNotFound` | same |
| `sales/apis.py:134` | `SalesOrderNotFound` | `apps/sales/errors.py` (already defined) |

### 1.5 Layer violation — raw SQL inside `apps.sales.services`

[`backend/apps/sales/services.py:220`](../../backend/apps/sales/services.py#L220) — inside `_validate_explicit_allocations`, a `cur.execute("SELECT b.*, COALESCE(v.on_hand, 0) AS on_hand FROM batches b LEFT JOIN v_stock_by_batch v ...")` reaches into the inventory schema directly. The query function `select_batch_by_id` in [`backend/apps/inventory/queries/batches.py:45`](../../backend/apps/inventory/queries/batches.py#L45) already returns a batch + on_hand projection, but the field name there is different from what `_validate_explicit_allocations` expects.

**Fix.** Add a new query function in inventory's queries module:
```python
@scoped
def select_batch_with_on_hand(cur, *, params: dict) -> dict | None:
    """Return batch row + COALESCE(on_hand, 0). Used by sales validation."""
    ...
```
Import it at the top of `apps/sales/services.py`:
```python
from apps.inventory.queries.batches import select_batch_with_on_hand
```
Cross-app import is *only* allowed service→service or `service→target-app's queries` if the target query function is exported as part of that app's public surface. We accept this as service-to-`queries`-but-public — the alternative (a thin selector wrapper in `apps/inventory/selectors.py`) opens a connection per call and is wrong for a function that runs inside another service's transaction. Add a `# cross-app: sales.services → inventory.queries (one-statement read-only, no tx ownership)` comment on the import line.

### 1.6 `apps/sales/selectors.py` imports a private name from `apps/sales/services.py`

[`backend/apps/sales/selectors.py:29`](../../backend/apps/sales/selectors.py#L29) — `from apps.sales.services import _row_to_so`. Two violations: selector imports from service (upward layer dependency), and the imported name is private (`_`). The same issue exists in procurement (`_row_to_po` is local to `apps/procurement/selectors.py`, but services imports from selectors there — the inverse leak).

**Fix.** Hoist `_row_to_so` to a sibling module without layering obligations: `apps/sales/_assemble.py`, exporting `row_to_sales_order(header, lines, allocations)`. Both `services.py` and `selectors.py` import from it. Same for procurement (`row_to_purchase_order`) and any app that has the duplication.

### 1.7 `apps/core/management/commands/check_env.py:24` — bare function-local import

[`backend/apps/core/management/commands/check_env.py:24`](../../backend/apps/core/management/commands/check_env.py#L24) — `import settings.prod` inside `handle()`, with `# noqa: F401 — side-effect: validates all required vars at import` but no `# break cycle: …` comment per `.claude/skills/ilex-discipline/SKILL.md` invariant #6.

**Fix.** Either hoist (probably impossible because importing `settings.prod` at module top would break the `migrate_sql` command that imports `apps.core.management.commands.check_env` at startup), or add the `# break cycle: …` annotation explaining the cycle:
```python
# break cycle: settings.prod imports django.conf which has not finished
# loading at module-top time of any management command. Side-effect import
# is intentional — settings.prod's module body raises ImproperlyConfigured
# on missing required env vars.
import settings.prod  # noqa: F401
```

## Pillar 2 — Polish (P1, structural)

These do not change behavior. They make the codebase honest about its shape.

### 2.1 Function-size compliance — 16 functions over 60 LOC

The TDD/discipline skill mandates ≤ 60 LOC per function. The current high-water marks:

| Rank | File:Line | LOC | Function | Extraction strategy |
|---|---|---|---|---|
| 1 | `apps/sales/services.py:180` | 115 | `_validate_explicit_allocations` | 5 helpers (see § below) |
| 2 | `apps/sales/services.py:352` | 90 | `update_sales_order_draft` | `_load_so_for_update_or_raise`, `_replace_lines` |
| 3 | `apps/inventory/queries/movements.py:72` | 90 | `list_movements` | `_decode_cursor`, `_build_filter_sql` |
| 4 | `apps/procurement/services.py:278` | 86 | `receive_purchase_order` | `_load_po_for_update_or_raise`, `_build_receipt_lines` |
| 5 | `apps/procurement/services.py:155` | 86 | `update_purchase_order_draft` | shares `_load_po_for_update_or_raise` |
| 6 | `apps/sales/services.py:527` | 82 | `commit_sales_order` | extract `_run_fefo_walk_with_locking`, `_persist_allocations_and_movements` |
| 7 | `apps/sales/queries/sales_orders.py:157` | 79 | `list_sales_orders` | `_decode_cursor`, `_build_filter_sql` (mirror of inventory) |
| 8 | `apps/financials/apis.py:52` | 79 | `MarginByProductApi.get` | extract `_parse_query_params` |
| 9 | `apps/inventory/services.py:212` | 78 | `update_batch_metadata` | `_apply_metadata_diff`, `_assemble_audit_notes` |
| 10 | `apps/sales/services.py:610` | 72 | `void_sales_order` | shares `_load_so_for_update_or_raise` |
| 11 | `apps/financials/serializers.py:36` | 70 | `validate` | extract `_validate_date_range`, `_apply_defaults` |
| 12 | `apps/procurement/serializers.py:72` | 69 | `validate` | shape — leave |
| 13 | `apps/inventory/apis.py:279` | 69 | `MovementListApi.get` | extract `_parse_query_params` |
| 14 | `apps/catalog/services.py:230` | 65 | `import_products_csv` | extract `_savepoint(conn, name)` helper |
| 15 | `apps/inventory/services.py:291` | 61 | `record_movement` | borderline — leave |
| 16 | `apps/financials/queries/margin.py:51` | 61 | `select_margin_by_product` | borderline — leave |

Target: zero functions over 60 LOC. Borderline (61–69 LOC) functions get a judgment call from the executor — leave if extraction adds more weight than it removes.

### 2.2 `_validate_explicit_allocations` decomposition (ranked #1, 115 LOC)

The worst function in the codebase. Decompose into 5 helpers + a 25-LOC orchestrator:

1. `_index_lines_by_id(lines: list[dict]) -> dict[str, dict]` — pure, builds the lookup dict.
2. `_load_batch_with_on_hand(cur, *, owner_id, batch_id) -> dict` — calls the new query function from §1.5; raises `InvalidAllocation` on miss.
3. `_validate_batch_eligible_for_line(batch, line) -> None` — pure, raises `InvalidAllocation` on product mismatch / recalled / expired.
4. `_track_per_batch_usage(usage: dict, batch_id: str, qty: Decimal, on_hand: Decimal) -> None` — mutates the running dict, raises if `cumulative > on_hand`.
5. `_validate_per_line_sums(line_sums: dict, lines: list[dict]) -> None` — raises if any line is uncovered or sums mismatch.

Orchestrator: load lines lookup, loop over allocations calling (2)/(3)/(4) accumulating both the batch usage dict and a per-line sum dict, then call (5) at the end. Each helper independently testable as a unit test (pure or single-statement DB read).

### 2.3 DRY tax — 90 LOC of recurring duplication

| Pattern | Sites | Cost | Fix |
|---|---|---|---|
| `def _connect()` | catalog/services, catalog/selectors, procurement/services, procurement/selectors, inventory/services, inventory/selectors, sales/services, sales/selectors, financials/selectors | 9 × 2 LOC = 18 | Move to `apps/core/db.py::connect()`, import everywhere. |
| `def _row_to_dict(cur, row)` | catalog/queries/products, inventory/queries/batches, inventory/queries/movements, procurement/queries/purchase_orders, procurement/queries/purchase_order_lines, sales/queries/sales_orders, sales/queries/sales_order_lines, sales/queries/sale_allocations, sales/queries/recall_report, financials/queries/margin | 10 × 4 LOC = 40 | Move to `apps/core/db.py::row_to_dict(cur, row)`, import. |
| `_row_to_<aggregate>` duplicated across services + selectors of the same app | sales (`_row_to_so`), procurement (`_row_to_po`), inventory (`_row_to_batch`), catalog (`_row_to_product`) | 4 × 8 LOC = 32 | Per `§1.6`, hoist each to `apps/{app}/_assemble.py`. |

Scope: ~90 LOC removed, single PR, mechanical.

### 2.4 Procurement → inventory cross-app transaction split

[`apps/procurement/services.py:340`](../../backend/apps/procurement/services.py#L340) — `receive_purchase_order` commits the PO header *before* calling `apps/inventory/services.py:110`'s `create_receipt_batches`. Two transactions. If inventory fails, the PO is `received` with zero batches — and once `received`, the PO is immutable per D6, so there is no API recovery path; only manual SQL.

**Fix.** Invert the order or unify the transaction. Cleanest path:

1. `create_receipt_batches` is refactored to accept a `cur: psycopg.Cursor` (passed in) instead of opening its own connection. Cross-app cursor sharing is a smell, so document it explicitly with a comment.
2. `receive_purchase_order` opens one connection, opens one cursor, calls `create_receipt_batches(cur, ...)` first, then the procurement query that flips status. One commit, atomic.

If single-cursor sharing is rejected as too coupled, fallback: extract the actual SQL (3 inserts: batch row + receipt movement) into a shared helper at `apps/core/inventory_writes.py::create_batch_with_receipt(cur, ...)` that both apps can call. Either way, the PO state and the batches state are consistent or both rolled back.

### 2.5 Cursor pagination — UUID lexicographic-vs-binary mismatch

[`apps/financials/queries/margin.py:67`](../../backend/apps/financials/queries/margin.py#L67) and [`apps/sales/queries/sales_orders.py:203`](../../backend/apps/sales/queries/sales_orders.py#L203) — `(timestamp, id::text) < (cursor_ts, cursor_id)` compares the id as text but the `ORDER BY` is on the native UUID. Lexicographic vs binary UUID order can disagree on adjacent UUIDv7s (e.g. `01900000-...-9` vs `01900000-...-a`), causing pagination to skip a row at boundaries.

**Fix.** Cast both sides to a single representation. Either:
```sql
ORDER BY agg.product_id::text DESC -- text on both sides
```
or
```sql
WHERE (agg.revenue, agg.product_id) < (%(cursor_revenue)s, %(cursor_product_id)s::uuid)
```
Plan picks the second. Add a unit test that pages through 50 sequentially-generated UUIDv7 ids with `limit=10` and asserts no row is skipped or repeated.

### 2.6 Catalog `except Exception` in CSV import — too broad

[`apps/catalog/services.py:281`](../../backend/apps/catalog/services.py#L281) — `except Exception as exc: ... failed.append(FailedRow(error="Error", detail=str(exc)))`. Catches `psycopg.OperationalError` (connection drop) and converts it into a per-row failure, masking infra problems as data problems. Narrow to `psycopg.Error`.

### 2.7 Update-`None`-not-clear in procurement

[`apps/procurement/services.py:198`](../../backend/apps/procurement/services.py#L198) — `update_purchase_order_draft` only sets `supplier_contact` when the param is non-None, so PATCH `{"supplier_contact": null}` cannot clear it. Sales solves this with a `customer_contact_set: bool` sentinel pattern (`apps/sales/services.py:380`). Mirror the pattern.

### 2.8 Dead `except Exception: conn.rollback(); raise`

[`apps/sales/services.py:603-605`, `:676-678`, `:399-401`](../../backend/apps/sales/services.py#L399) — `except Exception: conn.rollback(); raise` after `with _connect() as conn:` is dead: `with` already rolls back on exception. Strip.

## Pillar 3 — Documentation polish

The schema commitments and architectural decisions deserve documents that read as if a careful reader and a future contributor will find every answer they need without asking. Today the docs are good. After this issue they are reference-grade.

### 3.1 [`README.md`](../../README.md)

| Section | Action |
|---|---|
| Header / Quickstart | Add the `epic project-build` workflow as the canonical contributor onboarding (after the `make dev` block). |
| **Architecture overview** | Add a 1-paragraph "What ships in v1 vs. Phase 3" block linking to `docs/agent.md`. Today the README treats Phase 3 as a forward-looking note; promote it to a first-class section. |
| **Layering rules summary** | Pull a 5-line summary of `.claude/skills/ilex-discipline/SKILL.md` rules (no ORM, no SQL outside queries/, owner-scope, money/qty discipline, append-only ledger) — readers should not have to chase the skill file to know the discipline. |
| **CI gates** | List the gates that CI runs (`pytest`, `ruff`, `check_no_orm.sh`, `check_openapi_drift.sh`, `migrate_sql`) and what each catches. Currently buried in `.github/workflows/ci.yml`. |
| **Deploy** | Already added in ILEX-011; verify the Fly.io commands and add a "rollback" subsection. |

### 3.2 [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md)

| Action | Why |
|---|---|
| Update §3.4 (movements endpoint) to reflect the URL split from §1.2 (`/adjustments` vs `/write-offs`). | Spec must match implementation. |
| Add §2.6 a one-line clarification: every error 404/409/422 body uses the `{"error", "detail"}` envelope; no empty `{}`. | Lock the contract that §1.4 fixes. |
| Update §2.6 idempotency-key list: drop `(write_off)` and add the explicit endpoint name. | Mirror the URL split. |
| Add §3.5 SO commit subsection: "FEFO walk allocates per-line cumulatively across all lines of the same SO". | Document the §1.1 fix as part of the contract, not just a bug fix. |
| Update §2.8 (response envelope) to call out that all monetary and quantity fields render as **strings** in JSON (Decimal serialization), not numbers. | Frontend type generation needs this. |

### 3.3 [`docs/decisions.md`](../../docs/decisions.md)

Adds to track:

- **D15 — Read-only Postgres role for the agent.** The agent connects as `ilex_agent_ro` with SELECT only on `v_*` views. Owner filtering is via `current_setting('app.current_owner_id')::uuid` set per request. Already drafted in `docs/specs/agent.md` §2.3 + §8 — promote to a first-class decision so the schema commitment is referenceable from anywhere.
- **D16 — Cross-app service boundaries are service→queries when the target is one read-only statement, service→service otherwise.** Document the policy that ILEX-016 §1.5 codifies, with the `apps.sales.services → apps.inventory.queries` example.
- **D17 — Idempotency cache stores rendered response bytes.** Codify the §1.3 fix.

### 3.4 [`docs/agent.md`](../../docs/agent.md)

User-facing runtime walkthrough for the agent. Adds:

- A **"Why this is buildable now"** sidebar listing the v1 commitments that fundament Phase 3 (read-only views, append-only ledger, immutable allocations, `v_recall_report`, etc.). One sentence each. The point: a reader should leave knowing this is not aspirational, every dependency is shipped.
- A worked example for **Explain mode**: starting from "Why did Cold Brew margin drop 8% this month?", show the three SQL queries the agent would run (using the existing views), the cost-layer math, and the final natural-language answer. Concrete. Demonstrative.

### 3.5 [`docs/specs/agent.md`](../../docs/specs/agent.md)

Foundation spec. Already 271 lines, already detailed. Adds:

- A new §2.7 "Foundation status" block listing every commitment from §2.3 and §2.4 with a "✓ shipped in ILEX-NNN" annotation against each. After this issue, all v1 commitments are ✓; ILEX-012 then ships the agent-specific ones.
- A new §6.1 "Validation gates pre-Phase-3" listing exactly what must be true before ILEX-012 starts: green pytest, green migrate_sql, all v_* views present and projecting owner_id, no UPDATE/DELETE on stock_movements, idempotency cache works for Decimal/datetime bodies, no empty 404 envelopes. Each item is an executable assertion the executor of ILEX-012 can run.

### 3.6 [`docs/architecture/architecture.md`](../../docs/architecture/architecture.md)

Walk the file. If it predates ILEX-009/010/011, update the deploy and OpenAPI sections.

## Pillar 4 — Phase 3 fundament

The point of this pillar is not to start the agent. It is to make the executor of ILEX-012 walk into a working substrate without surprises.

### 4.1 Foundation invariants — the agent's contract with the schema

Every agent capability rests on a v1 commitment. After this issue, the mapping is explicit and testable:

| Agent capability | v1 commitment that makes it work | Locked in |
|---|---|---|
| Query mode (read-only) | Allowlisted `v_*` views: `v_stock_by_batch`, `v_expiring_soon`, `v_margin_by_product`, `v_recall_report` exist and project `owner_id`. | ILEX-006 (views split), ILEX-007 (recall_report), ILEX-008 (margin_by_product) |
| Owner isolation | Composite FKs `(id, owner_id)` (D4 substrate); `@scoped` on every query function. Views project owner_id so a session-GUC `WHERE owner_id = current_setting(…)` rewrite is one ALTER VIEW away. | ILEX-002, every domain migration thereafter. |
| Explain mode (cost-layer narratives) | Append-only `stock_movements` (D1) + immutable `sale_allocations` (D8) → cost layers are reconstructable from the ledger. The trigger on `stock_movements` blocks UPDATE/DELETE. | ILEX-006 (ledger), ILEX-007 (allocations). |
| Recall narratives | `v_recall_report` filters committed + non-voided SOs (D9). | ILEX-007. |
| Draft mode | `apps.sales.services.preview_sales_order` runs the same FEFO walk the human commit path uses. | ILEX-007. |
| Idempotency on agent-confirmed actions | Existing `@idempotent` decorator + cache that handles Decimal/datetime bodies. | ILEX-016 §1.3. |
| Read-only role isolation | The `ilex_agent_ro` role is a strict subset of public-schema permissions. The schema's view-only access pattern is the safety perimeter. | ILEX-012 (foundation issue). |

The skill files for the agent (`apps/agent/skills/`) load this contract as documentation:

- `schema.md` documents each `v_*` view's columns and meaning. ILEX-013 ships the first version; this issue prepares the schema fixtures by ensuring every view's column comment is filled in (`COMMENT ON COLUMN v_*.* IS '...'`).
- `cost-layers.md` documents how `batches.unit_cost` × `sale_allocations` form FIFO cost layers. The narrative depends on `sale_allocations` being immutable post-commit, which is enforced by the absence of an UPDATE path and the spec's explicit D8 statement.
- `fefo.md` documents the FEFO predicate. The predicate lives in `list_eligible_for_fefo` — exactly the same query the human commit uses.
- `recall-procedure.md` documents recall behavior — recalled batches are excluded from FEFO; un-recall writes a reversal movement.
- `onboarding.md` (ILEX-015) documents the empty-state cues — depends on the routes already mounted.

This issue does not write the skill files. It writes the **documentation layer above them** — the §2.7 foundation-status block in `docs/specs/agent.md` and the §3.4 fundament sidebar in `docs/agent.md`.

### 4.2 Pre-Phase-3 checklist (executable)

A checklist that, when fully ticked, certifies the executor of ILEX-012 starts on solid ground. The plan section translates each into a test or grep that runs in CI.

- [ ] Pytest 493+ passing (cumulative, no `--ignore`).
- [ ] `migrate_sql` clean from a fresh DB (`drop + create + migrate_sql` exits 0, all 9 migrations applied).
- [ ] Every `v_*` view returns rows scoped by an `owner_id` projection and is queryable as a public-schema name.
- [ ] No `UPDATE`/`DELETE` on `stock_movements` outside test code that asserts the trigger blocks them.
- [ ] Idempotency cache survives a Decimal/datetime body (test: commit an SO twice with the same key, second response identical to first byte-for-byte).
- [ ] No empty `{}` 404 body anywhere in `apps/*/apis.py`.
- [ ] Every `apps/*/queries/*.py` function with an `owner_id` parameter is `@scoped`.
- [ ] No function over 60 LOC outside the agreed borderline list (61–69 LOC functions left intentionally).
- [ ] No SQL outside `apps/*/queries/` except savepoint control (with comment) and `apps/core/management/commands/migrate_sql.py`.
- [ ] OpenAPI snapshot up to date: `scripts/check_openapi_drift.sh` exits 0.
- [ ] Ruff clean.
- [ ] No-ORM gate clean.

The plan section will translate each item into a pytest test or shell assertion.

---

# Validation gates

The validation gates for this issue are the executable checklist in §4.2 above, plus the surface-specific tests that come with each fix (one per P0 item, plus the new tests for cumulative-FEFO §1.1, idempotency-Decimal §1.3, and pagination-UUID-cursor §2.5).

Run on every cycle:

```bash
cd backend && uv run pytest --tb=line                # full suite
uv run ruff check backend/                           # lint
bash scripts/check_no_orm.sh                         # discipline
bash scripts/check_openapi_drift.sh                  # OpenAPI snapshot
```

Plus one new gate added by this issue:

```bash
# Validate the v_* views project owner_id (D4 substrate readiness for agent)
psql "$DATABASE_URL" -c "
  SELECT viewname FROM pg_views
   WHERE schemaname='public' AND viewname LIKE 'v_%'
" | xargs -I{} psql "$DATABASE_URL" -c \
  "SELECT 1 FROM information_schema.columns
    WHERE table_name='{}' AND column_name='owner_id'
   HAVING COUNT(*) = 1"
```

(Wrapped into a `scripts/check_view_owner_id.sh`.)

# Notes

## What this issue is NOT

- **Not the agent itself.** No `apps/agent/`, no `claude-agent-sdk` dep, no `/agent/chat` endpoint, no skill files. ILEX-012 is the agent foundation issue. This one ships the seam.
- **Not a new feature.** Every change is a fix or a polish; no behavior is added that the spec didn't already mandate.
- **Not a refactor of stable code.** Catalog (ILEX-004), procurement (ILEX-005) and core (ILEX-001/002/003) are touched only at the points the bugs and DRY targets land. Their tests do not need rewriting.

## Migration filename

No new migration files. All schema is set; the polish is application-side. The `0008_agent_role.sql` migration (read-only role + view rewrites) is part of ILEX-012, not this issue.

## Ordering

Pillars run in order. Pillar 1 first (bugs are the only behavioral change). Pillar 2 next (function extractions are gated on tests still passing — bugs must be closed before refactor). Pillar 3 (docs) and Pillar 4 (Phase 3 fundament) can run in parallel once Pillars 1–2 are committed.

## Out of scope

- New endpoints or new database objects.
- Changes to the test framework itself (the autouse wipe fixture from `backend/conftest.py` already shipped in commit `8e9e498`).
- Changes to the `epic-cli` tooling (the verify-step bug surfaced in ILEX-007/008/011 is an upstream tool issue, not in this repo).
- Frontend work (lives in `IlexInventory-Web`).
- The `_validate_explicit_allocations` 115-LOC function decomposition includes #1.5's SQL move; combine those two changes in the same commit so the orchestrator doesn't reference the old SQL transiently.

## Suggested commit shape

One commit per pillar, four total:

1. `fix(api): close P0 bugs — FEFO double-allocate, write_off idempotency, idempotency body cache, 404 envelopes (ILEX-016)`
2. `refactor(core): extract apps/core/db.py + per-app _assemble.py + split functions ≥60 LOC (ILEX-016)`
3. `docs: polish README + SPEC + decisions + architecture for v1 (ILEX-016)`
4. `docs(agent): fundament Phase 3 — v2.7 foundation status + worked Explain example (ILEX-016)`

# References

- [`docs/specs/SPEC.md`](../../docs/specs/SPEC.md) §2.6 (idempotency, error envelope), §3.4 (movements split), §3.5 (SO commit cumulative FEFO).
- [`docs/specs/agent.md`](../../docs/specs/agent.md) §2.3 (read-only role), §2.4 (architecture), §2.7 (foundation status — to be added), §6.1 (validation gates pre-Phase-3 — to be added).
- [`docs/decisions.md`](../../docs/decisions.md) D1 (ledger), D4 (owner-scope), D6 (PO immutability post-receive), D8 (allocation immutability + sale_void), D11 (FEFO + recall predicates), D12 (layering), and D15–D17 (to be added).
- [`docs/agent.md`](../../docs/agent.md) "The three modes" + new "Why this is buildable now" sidebar.
- [`.claude/skills/code-review-partner/SKILL.md`](../../.claude/skills/code-review-partner/SKILL.md) — review criteria applied here.
- [`.claude/skills/ilex-discipline/SKILL.md`](../../.claude/skills/ilex-discipline/SKILL.md) invariant #6 (function-local imports), §1 (no ORM), §2 (no SQL outside queries).
- [`.claude/skills/tdd/SKILL.md`](../../.claude/skills/tdd/SKILL.md) "Behavioral, not structural" + 60-LOC ceiling.
