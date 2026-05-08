---
name: tdd
description: TDD cycle and test-type guide for the Ilex backend (pytest + real Postgres + pre_db/post_db state pattern). Use when writing or planning code under apps/, when adding a test, or when deciding which test type fits a feature. Do NOT use for frontend testing or other repos.
---

# TDD discipline — Ilex backend

## The cycle

1. **Red.** Write the smallest failing test that exercises one fact. Run it; confirm it fails for the right reason.
2. **Green.** Write the minimum code that passes. Hardcoded returns are fine on iteration one. Add the next fact's test; triangulate.
3. **Refactor.** Improve the design. By now you've walked the full logic and can see what wasn't visible from the empty file: the helper hiding inside, the conditional that's secretly the general rule, the provisional name, the interface that fights its caller. Tests staying green is the safety net; improving the code is the goal.

Skipping refactor turns TDD into iteration.

## Behavioral, not structural

Tests describe **what** the code does, not **how**. The contract: same inputs → same outputs and same observable DB state. Internal restructure (rename, split a function, swap an algorithm, replace `csv.DictReader` with a parser library) must leave the suite green. Specifically:

- **Never import a name starting with `_`.** Private helpers exist for the implementation; they are not the surface. If a private helper has behavior worth a test, the test belongs at the next layer up (where the helper is reachable through public surface), or the helper should be promoted.
- **Never assert which intermediate function ran.** No spies, no call-counters. Only outcomes: return value, raised exception, `post_db` state, HTTP status + body.
- **Never test through internal state.** `post_db` reads tables the schema declares; that's the contract. Reading a private dict, a cache, or a module-level variable is not.

If you cannot cover an edge case without one of the above, the case is wrong-layered — move it up.

## Test types

Each layer tests its own **public surface**. The unit below is the public boundary that callers above rely on.

| Type | Location | Public surface | DB |
|---|---|---|---|
| Unit | `apps/{app}/tests/unit/` | A public function/class exported from `serializers`/`errors`/`types`. Pure logic only. **Never a `_private` helper.** | No |
| Query | `apps/{app}/tests/query/` | One exported function from `apps/{app}/queries/{aggregate}.py`. Asserts on rows + `pg_constraint` introspection. | Yes |
| Service | `apps/{app}/tests/service/` | One exported function from `apps/{app}/services.py`. Asserts on return value + `post_db`. Cross-owner = 404. | Yes |
| API | `apps/{app}/tests/api/` | One HTTP route via DRF test client. Asserts on status code + JSON body. | Yes |

## State pattern

Use `pre_db` / `post_db` from [`apps.core.tests.db_test`](../../../backend/apps/core/tests/db_test.py). Tests describe state declaratively; spec `PreState` / `PostState` blocks (see [`docs/specification.md`](../../../docs/specification.md)) translate to arguments verbatim.

```python
from apps.core.tests.db_test import pre_db, post_db
from apps.inventory.services import recall_batch

def test_recall_marks_batch(db):
    pre_db(db, {
        "batches": [{"id": "B-1", "owner_id": "U-A", "is_recalled": False}],
    })
    recall_batch(batch_id="B-1", owner_id="U-A", reason="contamination")
    post_db(db, {
        "batches": [{"id": "B-1", "is_recalled": True}],
    })
```

## Mandatory tests

- Owner-scope: every owner-scoped function or endpoint gets a cross-owner variant asserting 404 (not 403 — D4) and unchanged state.
- Refactor pass: every Green has a follow-up commit that improves design without changing behavior.

## Test DB

Local: `docker compose up -d postgres`. CI: `postgres:16` service container. Schema built from `backend/migrations/*.sql` once per session via `conftest.py`. `pytest --reuse-db` after first run.

## Pitfalls

- Asserting on which queries ran instead of observable state.
- Mocking psycopg or the cursor.
- Building test state via the service under test.
- Skipping the cross-owner test.
- Importing a `_private` helper into a test (see "Behavioral, not structural"). If a test reads `_parse_csv_bytes` directly, it bound the test to a current implementation choice — the same edge case (BOM, CRLF, blank field) is reachable through the service or HTTP entry point.

## Run

```bash
pytest                                              # full suite
pytest apps/sales/tests/service/                    # one layer
pytest apps/sales/tests/service/test_commit.py -x   # one file, fail fast
pytest -k fefo                                      # by name
```
