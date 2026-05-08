# Ilex Inventory Server — Architecture

> A four-layer model that separates HTTP routing, business logic, data access, and the database substrate.

For *what* the product is, see [`product.md`](product.md). For *why* specific choices were made, see [`decisions.md`](decisions.md). For the spec format used to describe individual endpoints, services, and queries, see [`specification.md`](specification.md).

## Architecture Overview

```
+---------------------------+
|         API LAYER         |
|     apis.py + serializers |
|       (HTTP routing)      |
+---------------------------+
              |
              v
+---------------------------+
|    BUSINESS LOGIC LAYER   |
|  services.py (writes)     |
|  selectors.py (reads)     |
|  (orchestration + tx)     |
+---------------------------+
              |
              v
+---------------------------+
|       QUERIES LAYER       |
|   queries/{aggregate}.py  |
|  (typed functions wrapping|
|        psycopg)           |
+---------------------------+
              |
              v
+---------------------------+
|       SCHEMA LAYER        |
|  migrations/*.sql + views |
|       (PostgreSQL)        |
+---------------------------+
```

**Critical Rule**: Data flows top to bottom only. No layer may import from layers above it.

---

## Hard Invariants

These are not preferences. CI gates and code review enforce them because Django's defaults would otherwise quietly violate them.

1. **Stock is a ledger.** Every change is an append-only row in `stock_movements`. Current stock is a derived query; no `stock_quantity` columns anywhere. *Brief mapping: what the take-home brief calls "Stock" maps to our `batches` table (the stock items — each with a unique `batches.id`, UUIDv7) plus `stock_movements` (the history); on-hand is derived from movements, never stored.*
2. **No Django ORM.** All persistence is parameterized SQL via psycopg. Migrations are plain `.sql` files.
3. **No SQL outside `queries/`.** Services, selectors, and APIs never call `cursor.execute`.
4. **Owner-scoped queries route through the `@scoped` helper.** Cross-owner access returns 404 (D4). Composite FKs `(id, owner_id)` are the DB-level safety net.

---

## Layer Responsibilities

### API Layer

| Component | Responsibility |
|-----------|----------------|
| **API class** | One per operation (Create / List / Detail / Update / Commit / etc.) |
| **Serializers** | Input validation + output shaping; nested in the API class |
| **OpenAPI annotation** | `@extend_schema` per endpoint via drf-spectacular |

**Location**: `apps/{app}/apis.py`, `apps/{app}/serializers.py`

**Must only**:
- Validate request input via DRF serializers
- Authenticate (DRF permission classes)
- Call services or selectors with typed kwargs
- Map service exceptions → HTTP status
- Serialize the response

**Must NOT**:
- Execute SQL
- Contain business logic
- Use ViewSets (one operation = one APIView class — keeps each operation's serializers and permissions explicit)
- Hand-write OpenAPI docs (the spec is generated)

**Key principle**: APIs are the interface, not the logic. The same logic must be reachable from a non-HTTP caller (e.g. the agent's draft path) with no API code in the call stack.

---

### Business Logic Layer

| Component | Responsibility |
|-----------|----------------|
| **Services** | Write-side business logic, transactions, ledger mutations |
| **Selectors** | Read-side composition over views and queries |
| **Errors** | Typed exception classes (`DomainError` subclasses) |
| **Types** | Dataclasses / TypedDicts for inputs and outputs |

**Location**: `apps/{app}/services.py`, `apps/{app}/selectors.py`, `apps/{app}/errors.py`, `apps/{app}/types.py`

**Receives**: typed Python data from APIs. Never `request` objects.

**May**:
- Open transactions (`@transaction.atomic`)
- Call queries to read or write
- Call other services and selectors
- Raise typed exceptions
- Use `transaction.on_commit(...)` for side effects that depend on commit

**Must NOT**:
- Execute SQL directly
- Serialize HTTP responses
- Receive `request` objects
- Use floats for money or quantity (always `Decimal`)

**Key principle**: Services own transactions; selectors own projections. The split is by intent (writes vs reads), not by aggregate.

---

### Queries Layer

| Component | Responsibility |
|-----------|----------------|
| **Query function** | One parameterized SQL statement (or tightly-bound pair) wrapped in a typed Python function |
| **Owner-scope helper** | `@scoped` decorator on every owner-scoped function |

**Location**: `apps/{app}/queries/{aggregate}.py`

**Receives**: typed Python data from services or selectors. The cursor is provided by the caller's transaction.

**May**:
- Execute SQL via `cursor.execute(...)`
- Map rows to dataclasses / TypedDicts
- Use the owner-scope helper
- Reference views (e.g. `v_stock_by_batch`)

**Must NOT**:
- Open transactions
- Contain business conditionals
- Call services or selectors
- Construct HTTP responses

**Key principle**: This is the **only** layer that contains SQL strings. Functions are atomic and reusable across services. CI grep gate fails if `cursor.execute` appears outside `queries/`.

---

### Schema Layer

| Component | Responsibility |
|-----------|----------------|
| **Migrations** | Plain SQL files, sliced by domain cluster |
| **Views** | `v_*` read-only views the agent and selectors consume |
| **Constraints** | CHECK, UNIQUE, composite FK `(id, owner_id)`, append-only triggers |

**Location**: `backend/migrations/*.sql`, the database itself

**Owns**: table shapes, indexes, integrity rules.

**Boundaries**:

- DDL is plain SQL. No `models.py`. No ORM-generated migrations.
- Views are part of the schema, not "convenience layers." The agent's read-only role can `SELECT` only from views; tables are revoked.
- Constraints catch what application code can't easily catch — composite FKs catch cross-owner data fusion (D4); CHECK binds `kind` to `signed_quantity` sign (D1); triggers enforce append-only on `stock_movements`.

---

## Import Rules

| From / To | API | Business | Queries | Schema |
|-----------|---|---|---|---|
| **API** | Yes | Yes | No | No |
| **Business** | No | Yes | Yes | No (only via queries) |
| **Queries** | No | No | Yes | Yes (SQL strings + view names) |
| **Schema** | No | No | No | Yes (within `migrations/`) |

- APIs import services and selectors only
- Services and selectors import queries
- Queries import other queries and reference the schema (table/view names in SQL)
- No layer imports from layers above it

---

## File Locations

| Component | Location | File pattern |
|-----------|----------|--------------|
| API class | `apps/{app}/apis.py` | one class per operation |
| Serializers | `apps/{app}/serializers.py` | `{Operation}Request`, `{Operation}Response` |
| Services (writes) | `apps/{app}/services.py` | `{verb}_{noun}(...)` |
| Selectors (reads) | `apps/{app}/selectors.py` | `{noun}_for_{filter}(...)` |
| Queries | `apps/{app}/queries/{aggregate}.py` | one module per aggregate |
| Errors | `apps/{app}/errors.py` | `DomainError` subclasses |
| Types | `apps/{app}/types.py` | dataclasses, TypedDicts |
| URL routing | `apps/{app}/urls.py` | one path per API class |
| Migrations | `backend/migrations/` | `NNNN_{cluster}.sql` |
| Owner-scope helper | `apps/core/owner_scope.py` | shared |
| ID generator (UUIDv7) | `apps/core/ids.py` | shared |
| Tests | `apps/{app}/tests/{type}/` | `unit/`, `query/`, `service/`, `api/` |

---

## Repository Layout

```
backend/
  apps/
    core/                              <- shared cross-cutting helpers
      owner_scope.py                   <- @scoped decorator (D4 layer 1)
      ids.py                           <- UUIDv7 generator (D5)
      errors.py                        <- DomainError base
      types.py                         <- shared dataclasses
    catalog/                           <- products
      apis.py
      services.py
      selectors.py
      queries/
        products.py
      serializers.py
      errors.py
      types.py
      urls.py
      tests/
        unit/
        query/
        service/
        api/
    procurement/                       <- purchase_orders, purchase_order_lines
    inventory/                         <- batches, stock_movements, FEFO, recall
    sales/                             <- sales_orders, sales_order_lines, sale_allocations
    financials/                        <- margin, profit, dashboard read-side
  migrations/
    0001_init.sql
    0002_catalog.sql
    0003_procurement.sql
    0004_inventory.sql
    0005_sales.sql
    0006_views.sql
    0007_indexes.sql
  settings/
    base.py
    dev.py
    prod.py
  urls.py
  manage.py
  pyproject.toml
```

---

## Naming Conventions

| Item | Convention | Example |
|------|------------|---------|
| App | lowercase, single noun | `sales`, `inventory` |
| API class | `{Noun}{Operation}Api` | `SalesOrderCommitApi` |
| Service function | `{verb}_{noun}` | `commit_sales_order`, `recall_batch` |
| Selector function | `{noun}_{filter}` | `margin_per_product`, `expiring_within` |
| Query function | `{verb}_{noun}` | `list_eligible_for_fefo`, `insert_sale_movement` |
| Query module | `{aggregate}` | `batches.py`, `movements.py` |
| Error class | `{Noun}{Reason}` | `InsufficientStock`, `SalesOrderNotFound` |
| Migration file | `{NNNN}_{cluster}.sql` | `0004_inventory.sql` |
| Test file | `test_{thing}.py` | `test_commit_sales_order.py` |

---

## Testing Strategy

Four test types per app. **No DB mocks** — service-layer tests that touch SQL run against a real test Postgres.

| Type | Location | What it tests | Touches DB? |
|---|---|---|---|
| **Unit** | `apps/{app}/tests/unit/` | Pure logic — input validation, error formatting, helpers, anything that doesn't read or write data. | No |
| **Query** | `apps/{app}/tests/query/` | A single query function's SQL — round-trip correctness, parameter binding, NULL handling, view shape. | Yes |
| **Service** | `apps/{app}/tests/service/` | Service composition — transactions, FEFO walk math, recall blocks, cross-owner returns 404. | Yes |
| **API** | `apps/{app}/tests/api/` | Full HTTP round-trip via DRF test client — auth, owner scope, error responses, OpenAPI conformance. | Yes |

CI gates per the executor agent's contract:

- All tests pass
- No Django ORM imports anywhere (`grep -R "from django.db.models" backend/` returns nothing)
- No SQL outside `queries/` (`grep -RE "cursor\.execute" backend/apps/*/services.py backend/apps/*/selectors.py backend/apps/*/apis.py` returns nothing)
- No floats in money/qty paths
- Every owner-scoped query function uses `@scoped`

---

## Adding a New Endpoint

1. Decide which app it belongs to. If none fits, create a new app under `apps/`.
2. Write the **Endpoint spec** in `docs/specs/{app}-{operation}.md` per [`specification.md`](specification.md). Get alignment first; code follows the spec.
3. Add tests in TDD order:
   - Service test (`apps/{app}/tests/service/test_{operation}.py`)
   - Query test for any new SQL (`apps/{app}/tests/query/test_{aggregate}.py`)
   - API test (`apps/{app}/tests/api/test_{operation}.py`)
4. Implement bottom-up:
   - Add or alter SQL in `backend/migrations/NNNN_{cluster}.sql`
   - Add query function(s) in `apps/{app}/queries/{aggregate}.py`
   - Add service or selector in `apps/{app}/services.py` / `selectors.py`
   - Add the API class in `apps/{app}/apis.py` and route it in `apps/{app}/urls.py`
5. Run gates: `pytest`, OpenAPI regen, lint, no-ORM/no-SQL grep checks.

---

## Adding a New App

1. Create folder: `apps/{app}/` with `apis.py`, `services.py`, `selectors.py`, `serializers.py`, `errors.py`, `types.py`, `urls.py`, `queries/`, `tests/{unit,query,service,api}/`.
2. Register in `INSTALLED_APPS` (`backend/settings/base.py`) and include URLs in `backend/urls.py`.
3. Add a migration for the app's tables (if any) under `backend/migrations/NNNN_{app}.sql`.
4. Write the **App/Cluster spec** in `docs/specs/{app}.md` per [`specification.md`](specification.md).
