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

## Test types

| Type | Location | Tests | DB |
|---|---|---|---|
| Unit | `apps/{app}/tests/unit/` | Pure logic. | No |
| Query | `apps/{app}/tests/query/` | One query — SQL round-trip, NULL, view shape. | Yes |
| Service | `apps/{app}/tests/service/` | Composition — transactions, FEFO, cross-owner = 404. | Yes |
| API | `apps/{app}/tests/api/` | HTTP round-trip via DRF test client. | Yes |

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

## Run

```bash
pytest                                              # full suite
pytest apps/sales/tests/service/                    # one layer
pytest apps/sales/tests/service/test_commit.py -x   # one file, fail fast
pytest -k fefo                                      # by name
```
