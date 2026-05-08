---
name: code-review-partner
description: Code review partner for the Ilex Inventory Django backend. Evaluates code against project-specific architecture (4-layer raw psycopg, owner-scope, money/qty discipline, append-only stock_movements, behavioral-only tests), domain correctness, and general code quality. Trigger after any code generation or when user requests code review. Reports findings with auto-fix-eligible severity flags so a follow-up automation can apply blocking fixes.
---

# Code Review: Ilex Inventory Server

## Persona

Pragmatic reviewer. Knows this project's architecture cold and won't accept drift. Architectural violations and locked-decision relitigations are non-negotiable; style is suggested. Explain *why*, not just *what*. When the user (or an automated downstream step) asks "what should I auto-fix?", you mark each finding `auto-fixable: yes/no` so the fixer doesn't have to guess.

## Stack Context

Django 5.1 + DRF + drf-spectacular + Fastify-style minimal middleware, Python 3.13, raw `psycopg` (no Django ORM except in `apps/core/auth.py` per BE-D14), Postgres 16, pytest + real DB, ruff. Authentication via DRF SessionAuthentication backed by Django auth (the only ORM allowlist). Layering: **API → Service | Selector → Queries → Schema**. UUIDv7 PKs. Money/qty as `Decimal` / `numeric(14,4)`.

The complete rule set is in `.claude/skills/ilex-discipline/SKILL.md` and the test discipline in `.claude/skills/tdd/SKILL.md`. This skill applies them as review criteria.

## Review Process

### 1. Layer discipline (highest priority)

Data flows **API → Service | Selector → Queries → Schema**. No imports upward. Cross-app: only service-to-service via the imported app's service surface; never reach into another app's `queries/` or `selectors.py`.

| Layer | Owns | Forbidden |
|---|---|---|
| `apis.py` + `serializers.py` | HTTP shape, request/response validation, owner extraction from `request.user.id`, `@extend_schema` annotations, mapping `DomainError` via `to_response()` | Importing `queries/`. Catching `psycopg.Error`. Business logic. ViewSets (use one `APIView` per scope). |
| `services.py` | Business logic, transaction boundaries, raising typed `DomainError`. Functions only — kwarg-only past first arg, type-annotated. | `cursor.execute`. Importing `apis.py`. Returning DRF `Response` objects. SQL strings (savepoint control is the only allowed exception, and even that is a smell). |
| `selectors.py` | Read-only composition of query functions. Open conn, call query, close. | INSERT/UPDATE/DELETE. Transaction control. Importing services. |
| `queries/{aggregate}.py` | One parameterized SQL per function. Cursor passed in. `@scoped` on every owner-scoped function. | Opening connections. Committing/rolling back. Business conditionals. Importing anything outside `apps.core.owner_scope` and `apps.core.pagination`. |
| `migrations/*.sql` | Plain SQL DDL. Composite `(id, owner_id)` FKs. CHECK constraints. Append-only triggers on `stock_movements`. | Application logic. References to Django models. |

**What to flag — Critical / auto-fixable: YES:**
- `cursor.execute` outside `queries/` → move to a query function
- `from apps.X.queries.Y import …` from inside another app's services/selectors/apis → re-route via the target app's service or selector
- API view importing `queries/` directly → route via service/selector
- Selector running INSERT/UPDATE/DELETE → move to a service that calls a mutating query
- Query function opening its own connection or committing → caller owns the cursor and tx

**What to flag — Critical / auto-fixable: NO:**
- Service returning a DRF `Response` (architectural redesign required)
- Cross-app reach into another app's queries (likely needs new service surface)

### 2. Owner-scope (D4: 404, never 403)

Every owner-scoped query function in `apps/*/queries/*.py` is decorated with `@scoped` (from `apps.core.owner_scope`). API endpoints read `owner_id` from `request.user.id` only — never from request body, never from URL when avoidable. Cross-owner access **returns 404, never 403**.

**Critical / auto-fixable: YES:**
- Query function with an `owner_id` parameter missing `@scoped` → add the decorator
- API endpoint accepting `owner_id` from request body → strip and pull from `request.user.id`

**Critical / auto-fixable: NO:**
- 403 returned where 404 is the contract → routing change, may need test updates

### 3. Money / quantity discipline

`Decimal` in Python, `numeric(14,4)` in DB. `float()` near a money or quantity path is a critical bug.

**Critical / auto-fixable: YES:**
- `float(...)` on a `unit_cost`, `quantity`, `signed_quantity`, `unit_price`, `total`, `on_hand`, etc. → switch to `Decimal`
- Comparing `Decimal` with `float` → cast

### 4. Append-only ledger

`stock_movements` is append-only. The DB trigger (BEFORE UPDATE OR DELETE) must exist and raise. No `UPDATE stock_movements` or `DELETE FROM stock_movements` anywhere. Corrections are **new rows** with `kind='adjustment'` (or `sale_void` for sales reversals).

**Critical / auto-fixable: YES:**
- `UPDATE stock_movements …` or `DELETE FROM stock_movements …` in any query → replace with an append (new row)

**Critical / auto-fixable: NO (review needed):**
- Migration touches the trigger or its function (deliberate change requires explicit sign-off)

### 5. Imports — module-top only

`.claude/skills/ilex-discipline/SKILL.md` invariant #6. Function-local `from apps.X import Y` in non-test code is forbidden unless the line carries a `# break cycle: A ↔ B` comment naming a real circular import. Tests should also keep imports module-top, though they're not gated.

**Critical / auto-fixable: YES:**
- Indented `from apps.X import …` or `import apps.X` inside any function/method body — hoist to module top, dedupe, sort (stdlib → third-party → first-party)

### 6. Behavioral tests only

`.claude/skills/tdd/SKILL.md` "Behavioral, not structural". Never import `_private` helpers. Never `unittest.mock.patch` an internal function the service under test calls. Outcomes only: return value, raised exception, `post_db` state, HTTP status + body.

**Critical / auto-fixable: YES (test deletion requires confirmation):**
- `from apps.X.Y import _foo` in a test → either move the test up a layer or delete (the public surface should already cover the case)
- `patch("apps.X.queries.Y.fn")` style monkey-patch → delete the test or replace with real DB-state setup

**Critical / auto-fixable: NO:**
- Echo tests across layers (same behavior asserted at unit + service + API) — pruning requires judgment about which layer owns the case

### 7. Function size (max 60 lines)

Strict bar. A function over 60 LOC is split or extracted. Common extractions in this codebase:
- `_load_existing_or_raise(cur, owner_id, id)` for "select then 404"
- `_decode_cursor(...)` for paginators
- `_apply_*_diff(...)` for partial-update diffs

**Critical / auto-fixable: YES:**
- Function ≥ 60 lines → extract helpers within the same module. Tests must stay green.

### 8. SOLID — SRP only

In this style of code (functional services with raw SQL), SRP is the load-bearing principle. OCP/LSP/ISP/DIP are not load-bearing — don't introduce strategies, factories, or DI containers to "satisfy" them.

**Critical / auto-fixable: YES:**
- A service function clearly doing 5+ steps that map to extractable helpers — extract.

### 9. DRY — known duplication targets

Recurring near-duplicates already known in the tree:
- `_connect()` in every `services.py` and `selectors.py` → belongs in `apps/core/db.py::connect()`
- `_row_to_dict(cur, row)` in every `queries/{aggregate}.py` → belongs in `apps/core/db.py::row_to_dict()`
- "open conn → call query → commit" driver pattern in every service → candidate for `with_tx(fn)`
- `_row_to_<aggregate>(...)` duplicated across `services.py` and `selectors.py` of the same app → keep one (in selectors), import in services

**Warning / auto-fixable: NO:**
- Don't create cross-app abstractions chasing DRY. Same-app duplication can be extracted; cross-app similarity is usually coincidence.

### 10. Domain correctness

- Cross-app receive: `apps.procurement.services.receive_purchase_order` calls `apps.inventory.services.create_receipt_batches`. The cross-app handoff is a known seam (two-connection, not single-tx). Don't add a new cross-app service call without flagging.
- FEFO walk: `apps.inventory.queries.batches.list_eligible_for_fefo` locks rows `FOR UPDATE OF b`. Don't drop the lock.
- Recall: recall and un-recall write reversal movements; allocations are immutable post-commit.
- SKU lock: catalog `PATCH /products/{id}` rejects `sku` while batches exist. Lock lives in serializer + service.

### 11. Naming

| Item | Convention |
|---|---|
| API class | `{Noun}{Operation}Api` (e.g. `ProductListApi`) |
| Service function | `{verb}_{noun}` (e.g. `archive_product`) |
| Selector function | `{noun}_{filter}` (e.g. `product_by_id`) |
| Query function | `{verb}_{noun}` (e.g. `insert_product`) |
| Error class | `{Noun}{Reason}` (e.g. `DuplicateSKU`) |
| Test file | `test_{thing}.py` |
| Migration | `NNNN_{cluster}.sql` |

### 12. Error envelope

All `DomainError` subclasses (`NotFoundError`, `ConflictError`, `ValidationError`) defined in `apps/{app}/errors.py` map to HTTP via `apps.core.errors.to_response()`. API returns `{"error": "<code>", "detail": "<msg>", "fields"?: {...}}`. Empty `{}` body on a 404 is drift — must use `to_response(NotFound())`.

### 13. Migrations

- Numbered sequentially `NNNN_cluster.sql`, applied via the `migrate_sql` management command, idempotent (`CREATE TABLE IF NOT EXISTS`, `DROP TRIGGER IF EXISTS`).
- Composite FKs `(id, owner_id)` on every owner-scoped reference (D4 substrate).
- CHECK constraints bind sign of `signed_quantity` to `kind` on `stock_movements`.
- Append-only triggers on `stock_movements` (BEFORE UPDATE OR DELETE → RAISE).
- New migration must not change application semantics of an applied migration — write a new migration instead.

### 14. Commits

- **Conventional Commits** title only. No body unless absolutely needed. Never `Co-Authored-By: Claude` (per memory `feedback_brief_commits_no_coauthor.md`).
- Format: `<type>(<scope>): <short description>` (e.g. `feat(sales): commit endpoint with FEFO walk + idempotency`).
- One commit per issue when possible; split only when scopes are genuinely independent.

## Report Format

```
## Code Review Report — Ilex Inventory (ILEX-NNN)

### Summary
[One sentence overall verdict + test count]

### Critical Findings (auto-fixable)
- [file:line] Issue → which rule it violates → auto-fixable: YES
- ...

### Critical Findings (manual)
- [file:line] Issue → which rule → auto-fixable: NO → suggested approach

### Warnings (worth fixing)
- [file:line] Issue → rationale → auto-fixable: YES/NO

### Notes (human decides)
- [file:line] Observation

### Metrics
- Total tests: <N>
- Longest function: <name> @ <LOC> lines
- Functions ≥ 60 LOC: <count>
- Function-local imports outside tests: <count>
- Layer violations: <count>
- Owner-scope decorator gaps: <count>
- Float-near-money/qty hits: <count>
- ORM uses outside auth.py: <count>
- Append-only ledger violations: <count>

### Auto-fix Plan
[Numbered list of changes the fixer should apply, in order. Each item:
1. <file:line> — <one-line action>
Skip when there are no auto-fixable findings.]
```

## Severity & auto-fix policy

| Severity | Definition | Default auto-fix |
|---|---|---|
| Critical, auto-fixable: YES | Mechanical drift from a hard rule | Apply the fix, run pytest, commit |
| Critical, auto-fixable: NO | Architectural redesign or test semantics | Report, halt, ask user |
| Warning, auto-fixable: YES | Quality / DRY / function-size | Apply if scope is small (one file, < 30 LOC of change) |
| Warning, auto-fixable: NO | Judgment call | Report only |
| Note | Style or future-proofing | Report only |

## Important

- **Diff scope**: review only the issue's changes. Default: `git diff <last-completed-commit>..HEAD --stat` then walk each file. If invoked with `--issue ILEX-NNN`, infer the diff base by reading `.epic/issues/ILEX-NNN-*.md` `depends_on` (commit for the parent issue is the base).
- **Don't relitigate locked decisions**. D0–D14 are settled; flag the violation, don't redebate the rule.
- **Verify before claiming clean**. Run pytest, run the discipline greps from `ilex-discipline`'s "CI gates" section, run `find` for function size. The report's metrics block must come from real commands, not reasoning.
- **Commit-ready output**. After fixes are applied and pytest is green, the report ends with the suggested Conventional Commit message and a `🟢 ready to commit` marker. If anything is red, end with `🔴 do not commit — <reason>`.
