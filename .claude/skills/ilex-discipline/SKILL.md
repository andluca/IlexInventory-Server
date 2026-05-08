---
name: ilex-discipline
description: Coding rules and layer adherence for the Ilex backend (no ORM, raw psycopg, services + selectors + queries layering, owner-scope, money/qty discipline). Use whenever editing or planning code under backend/apps/ or backend/migrations/. Do NOT use for frontend code or other repos.
---

# Ilex backend discipline

Architecture in [`docs/architecture.md`](../../../docs/architecture.md). Decisions in [`docs/decisions.md`](../../../docs/decisions.md). This skill is the rule set.

## Hard invariants

CI fails on violation:

1. No Django ORM. `from django.db.models` is forbidden anywhere in `backend/`.
2. No SQL outside `apps/{app}/queries/`. No `cursor.execute` in services, selectors, or APIs.
3. Money and quantity are `Decimal` in Python, `numeric(14, 4)` in DB. Never `float`.
4. Owner-scoped queries use `@scoped` from `apps.core.owner_scope`. Cross-owner access returns 404, never 403 (D4).
5. `stock_movements` is append-only. No UPDATE, no DELETE. Corrections are new rows.
6. Imports go at the top of the module. Function-local `from apps.X import Y` is **forbidden** unless a single-line comment names the circular import being broken (e.g. `# break cycle: apps.core.idempotency → apps.core.errors → apps.core.idempotency`). Lazy loading for performance is not a valid reason — Python caches modules. `grep -nE "^\s+(from|import) apps\." backend/apps/**/*.py` (excluding `tests/`) returns only commented breaks.

## Layer rules

Data flows API → Service | Selector → Queries → Schema. No imports upward.

### API (`apis.py`, `serializers.py`)

- One `APIView` class per operation. No ViewSets.
- Validate input via a `*Request` serializer; shape output via a `*Response` serializer.
- Annotate every endpoint with `@extend_schema` (drf-spectacular).
- Map service exceptions to HTTP status via the project exception handler. Don't catch and re-raise.
- Cross-owner returns 404 with an empty body.

### Service (`services.py`)

- Functions only. Kwarg-only past the first arg. Type-annotated.
- Wrap multi-row mutations in `@transaction.atomic`.
- Accept typed Python data; return typed Python data. Never `request` objects, never SQL strings.
- Raise typed exceptions from `apps/{app}/errors.py`.

### Selector (`selectors.py`)

- Read-only functions. Compose query functions.
- Prefer reading from views (`v_*`) when the projection exists.

### Queries (`queries/{aggregate}.py`)

- One module per aggregate. Each function is one parameterized SQL statement.
- Decorate every owner-scoped function with `@scoped`.
- No business logic. No conditionals beyond what one query needs.
- Caller provides the cursor; transactional context belongs to the service.

### Schema (`backend/migrations/*.sql`)

- Plain SQL files, sliced by domain cluster.
- Composite FKs `(id, owner_id)` on every owner-scoped reference.
- CHECK constraints bind `kind` to `signed_quantity` sign.
- Append-only triggers on `stock_movements`.

## Errors

Each app defines exceptions in `apps/{app}/errors.py` extending `apps.core.errors.{NotFoundError, ConflictError, ValidationError}`. The DRF exception handler maps them: `NotFoundError → 404`, `ConflictError → 409`, `ValidationError → 400`.

## File layout per app

```
apps/{app}/
├── apis.py
├── serializers.py
├── services.py
├── selectors.py
├── queries/{aggregate}.py
├── errors.py
├── types.py
├── urls.py
└── tests/{unit,query,service,api}/
```

## Naming

| Item | Convention |
|---|---|
| API class | `{Noun}{Operation}Api` |
| Service function | `{verb}_{noun}` |
| Selector function | `{noun}_{filter}` |
| Query function | `{verb}_{noun}` |
| Error class | `{Noun}{Reason}` |
| Test file | `test_{thing}.py` |
| Migration | `NNNN_{cluster}.sql` |

## CI gates

- `pytest` all green.
- `grep -R "from django.db.models" backend/` returns empty.
- `grep -RE "cursor\.execute" backend/apps/*/services.py backend/apps/*/selectors.py backend/apps/*/apis.py` returns empty.
- Every owner-scoped query function in `apps/{app}/queries/*.py` is decorated with `@scoped`.
- No floats in money or quantity paths.
- No function-local `from apps.…` / `import apps.…` outside `tests/`, except lines that carry a `# break cycle: …` comment.
- OpenAPI regenerates without errors.
