# Ilex Inventory — Server

Backend for an inventory management system built natively for **F&B CPG brands**. Django 5 + DRF, PostgreSQL 16, **raw parameterized SQL via psycopg — no Django ORM**. Append-only `stock_movements` ledger, FIFO cost layers, FEFO routing on sales commit, owner-driven recall with traceability.

Pairs with the [`IlexInventory-Client`](../IlexInventory-Client) frontend (React + TanStack Query + Mantine + types generated from this server's OpenAPI).

> Take-home challenge submission for **Kaizntree**. The original brief is preserved in [`docs/takehome-challenge.md`](docs/takehome-challenge.md); product context that goes beyond the brief lives in [`docs/product.md`](docs/product.md).

---

## What makes it different

Five technical choices that separate Ilex from a generic CRUD inventory app:

| | |
|---|---|
| **Stock as a ledger** | Every change is an append-only row in `stock_movements`. Current stock is a derived `SUM(signed_quantity)`, never a stored column. Free audit trail, point-in-time queries, corrections without destroying history. |
| **FIFO cost layers (true COGS)** | Each batch is a cost layer with its original unit cost. Sales consume layers in expiration order (FEFO) and write `sale_allocations` linking each consumed quantity back to the batch. COGS = sum of `qty × allocation.unit_cost`, not last-purchase-price. |
| **Batches + FEFO + recall** | F&B-native. Every PO line creates a batch with code, expiration, and original cost. Sales draw FEFO. One-click recall sets a flag + writes a `recall_block` audit row; the report lists every customer who received units. |
| **Owner isolation, three layers** | Service-layer injection + composite FKs `(id, owner_id)` + `@scoped` query helper. Cross-owner access returns **404, not 403** — don't leak existence. |
| **No Django ORM, raw psycopg** | All persistence is parameterized SQL. Migrations are plain `.sql` files. CI grep gates fail on `from django.db.models` outside the one allowlisted file (auth — see [BE-D14](docs/decisions.md)). |

**Plus** an agent (Phase 3): "Ask Ilex" — three modes (Query / Draft / Explain) running against a read-only Postgres role (`ilex_agent_ro`), allowlisted views only, owner-filtered via session GUC, 5s statement timeout, 1000-row cap. The schema decisions (ledger, immutable allocations, FEFO, allowlisted views) exist partly to make Explain mode trustworthy. See [`docs/agent.md`](docs/agent.md) for the runtime story and [`docs/specs/agent.md`](docs/specs/agent.md) for the spec.

---

## Quick start

```bash
# 1. Clone and enter
git clone <repo-url> ilex-server && cd ilex-server

# 2. Start Postgres
docker compose -f deploy/docker-compose.yml up -d

# 3. Python env (3.12+)
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 4. Environment
cp .env.example .env   # adjust DATABASE_URL if your Postgres differs

# 5. Migrate
python manage.py migrate auth        # Django's auth_user table (BE-D14 exception)
python manage.py migrate_sql         # raw-SQL migrations from backend/migrations/*.sql

# 6. Run
python manage.py runserver

# 7. Verify
curl localhost:8000/api/v1/health
# {"status": "ok", "checks": {"postgres": "ok"}}
```

OpenAPI 3.1 schema at `/api/v1/openapi.json`; Swagger UI at `/api/v1/docs` (dev only).

---

## Architecture

Four layers, top-to-bottom data flow only:

```
+---------------------------+
|         API LAYER         |  apis.py + serializers
|     (HTTP, DRF, thin)     |
+---------------------------+
              |
              v
+---------------------------+
|    BUSINESS LOGIC LAYER   |  services.py (writes, transactions)
|                           |  selectors.py (reads, projections)
+---------------------------+
              |
              v
+---------------------------+
|       QUERIES LAYER       |  queries/{aggregate}.py
|   (typed psycopg wrappers)|
+---------------------------+
              |
              v
+---------------------------+
|       SCHEMA LAYER        |  migrations/*.sql + views
|       (PostgreSQL)        |
+---------------------------+
```

Diagram: [`docs/architecture/architecture.svg`](docs/architecture/architecture.svg). Schema: [`docs/architecture/database-schema.png`](docs/architecture/database-schema.png). Full layer responsibilities, import rules, and CI gates: [`docs/architecture/architecture.md`](docs/architecture/architecture.md).

---

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| HTTP | Django 5 + DRF (no `ViewSet`s — one API class per operation) |
| DB | PostgreSQL 16+, raw parameterized SQL via `psycopg` 3 |
| Migrations | plain `.sql` files, run via `manage.py migrate_sql` (custom command) |
| Money / qty | `numeric(14, 4)` in DB, `Decimal` in Python — never floats |
| OpenAPI | `drf-spectacular` (3.1) → `openapi-typescript` on the FE |
| Auth | DRF `SessionAuthentication` + cookie session (Django's `auth.User` is the only ORM-managed model — [BE-D14](docs/decisions.md)) |
| Tests | `pytest` + `pytest-django`, real Postgres (no DB mocks); `pre_db` / `post_db` state pattern in [`backend/apps/core/tests/db_test.py`](backend/apps/core/tests/db_test.py) |
| Lint | `ruff`, `mypy` |

---

## API

36 endpoints across 7 apps. Full catalog with verb / path / flow / idempotency / pagination in [`docs/endpoints.md`](docs/endpoints.md).

Sample (recall a batch, F9):

```bash
curl -X POST localhost:8000/api/v1/batches/{batch_id}/recall \
  -H "Content-Type: application/json" \
  -H "Cookie: sessionid=..." \
  -d '{"reason": "Listeria — supplier email 2026-05-04"}'

# Response:
# { "batch": { "id": "...", "is_recalled": true, "recalled_at": "...", "recall_reason": "..." } }
```

Future FEFO allocations skip the batch immediately ([BE-D9](docs/decisions.md)). Past sales surface in `GET /api/v1/batches/{id}/recall-report` (R7) but are **not** auto-reversed — voiding past sales is an explicit `POST /api/v1/sales-orders/{id}/void` action ([BE-D8](docs/decisions.md)).

---

## Tests

```bash
pytest                                # all tests
pytest backend/apps/core/tests/unit   # pure-logic unit tests
pytest backend/apps/core/tests/api    # integration: HTTP → service → real Postgres
```

CI gates per [`docs/specs/SPEC.md`](docs/specs/SPEC.md):

```bash
mypy backend/                                                                    # type check
ruff check backend/                                                              # lint
scripts/check_no_orm.sh                                                          # 0 ORM imports outside auth.py (BE-D14 carve-out)
grep -RE "cursor\.execute" backend/apps/*/services.py backend/apps/*/apis.py     # 0 (BE-D12)
```

---

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/takehome-challenge.md`](docs/takehome-challenge.md) | Original Kaizntree brief (read first if reviewing) |
| [`docs/product.md`](docs/product.md) | Product context, positioning, "Ask Ilex" agent, brand, out-of-scope list |
| [`docs/architecture/architecture.md`](docs/architecture/architecture.md) | Four-layer model, hard invariants, file locations, naming, testing strategy |
| [`docs/decisions.md`](docs/decisions.md) | 15 numbered architectural decisions (D0–D14), each with rationale + rejected alternatives |
| [`docs/specs/SPEC.md`](docs/specs/SPEC.md) | Full project specification: foundation, features per app, validation gates, phases, decisions table |
| [`docs/endpoints.md`](docs/endpoints.md) | Endpoint catalog (36 endpoints, by app) with idempotency + pagination columns |
| [`docs/issues/`](docs/issues/) | Implementation issue breakdown — 11 v1 MVP issues + 4 Phase 3 agent issues derived from the specs |
| [`docs/agent.md`](docs/agent.md) | "Ask Ilex" agent — runtime narrative, three modes, why the schema decisions enable Explain mode |
| [`docs/specs/agent.md`](docs/specs/agent.md) | Agent implementation spec (Phase 3): foundation, modes, validation gates, decisions D15–D16 |

---

## Implementation status

15 issues total (see [`docs/issues/status.md`](docs/issues/status.md)). Each ships a complete vertical: schema → queries → services → API → tests.

**v1 MVP** (11 issues):

| # | Issue | Status |
|---|---|---|
| 001 | Bootstrap Django project | ✅ done |
| 002 | Foundation helpers + `0001_init` schema | ✅ done |
| 003 | Auth (signup, login, logout, /me) | 🔄 in progress |
| 004 | Catalog (products) | ⏳ pending |
| 005 | Procurement (POs) | ⏳ pending |
| 006 | Inventory (batches, movements, recall) | ⏳ pending |
| 007 | Sales (FEFO commit, allocations, void) | ⏳ pending |
| 008 | Financials (dashboard, margin, D13 markup formula) | ⏳ pending |
| 009 | CSV exports + `0007_indexes` | ⏳ pending |
| 010 | OpenAPI + FE handoff | ⏳ pending |
| 011 | Deploy (Docker, CI) | ⏳ pending |

**Phase 3 — Agent** (4 issues, post-MVP):

| # | Issue | Status |
|---|---|---|
| 012 | Agent foundation + `ilex_agent_ro` read-only role + view rewrites | ⏳ pending |
| 013 | `/agent/chat` endpoint + Query mode + SSE streaming | ⏳ pending |
| 014 | Draft mode + domain skill files | ⏳ pending |
| 015 | Onboarding skill + empty-state integration | ⏳ pending |

The agent is out of v1 MVP, but its schema commitments (read-only role, owner-filtered views) ship from day one so the agent can be turned on later without migrating data.

---

## Layout

```
backend/
  manage.py
  asgi.py | wsgi.py | urls.py
  settings/                       <- base / dev / prod / _env
  migrations/                     <- plain .sql files (numeric prefix)
  apps/
    core/                         <- ids, owner-scope, errors, types, pagination, idempotency, auth, health
    catalog/                      <- products
    procurement/                  <- purchase orders
    inventory/                    <- batches, movements, recall
    sales/                        <- sales orders, allocations
    financials/                   <- dashboard, margin
deploy/
  docker-compose.yml              <- dev Postgres
docs/
  architecture/                   <- architecture.md + diagrams
  specs/SPEC.md                   <- full project spec
  decisions.md
  endpoints.md
  product.md
  takehome-challenge.md
  issues/                         <- 11-issue breakdown
```

---

## Author

André Lucas Loubet Souza · `contact.andreloubet@gmail.com`
