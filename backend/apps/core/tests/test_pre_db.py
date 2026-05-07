"""Tests for pre_db — port of epic-test/db-test/tests/predb.test.ts plus
Postgres-specific cases (FK deferral, TRUNCATE CASCADE)."""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from apps.core.tests.db_test import pre_db


def _select_all(db, table: str) -> list[dict]:
    with db.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY id")
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# --- TS port ---


def test_wipes_and_inserts(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}],
    })
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "carol"}],
    })
    assert _select_all(db, "tt_users") == [{"id": 1, "name": "carol"}]


def test_resets_identity_on_wipe(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO tt_users (name) VALUES ('alice'), ('bob')")
    db.commit()

    pre_db(db, {"tt_users": []})

    with db.cursor() as cur:
        cur.execute("INSERT INTO tt_users (name) VALUES ('carol') RETURNING id")
        new_id = cur.fetchone()[0]
    assert new_id == 1


def test_wipe_false_appends(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    pre_db(db, {
        "tt_users": [{"id": 2, "name": "bob"}],
    }, wipe=False)
    assert _select_all(db, "tt_users") == [
        {"id": 1, "name": "alice"},
        {"id": 2, "name": "bob"},
    ]


def test_only_targets_subset(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
        "tt_decimals": [{"id": 1, "amount": Decimal("10.5000")}],
    })
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "bob"}],
        "tt_decimals": [{"id": 99, "amount": Decimal("999.0000")}],
    }, only=["tt_users"])

    assert _select_all(db, "tt_users") == [{"id": 1, "name": "bob"}]
    assert _select_all(db, "tt_decimals") == [
        {"id": 1, "amount": Decimal("10.5000")}
    ]


def test_raises_on_nonexistent_table(db):
    with pytest.raises(psycopg.errors.UndefinedTable):
        pre_db(db, {"tt_nonexistent": []})
    db.rollback()  # tx is aborted after the error


def test_empty_state_is_noop(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    pre_db(db, {})
    assert _select_all(db, "tt_users") == [{"id": 1, "name": "alice"}]


# --- Postgres-specific ---


def test_fk_deferral_allows_child_before_parent(db):
    pre_db(db, {
        "tt_items": [{"id": 1, "user_id": 1, "value": 100}],
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    assert _select_all(db, "tt_items") == [{"id": 1, "user_id": 1, "value": 100}]
    assert _select_all(db, "tt_users") == [{"id": 1, "name": "alice"}]


def test_truncate_cascade_wipes_unnamed_child(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
        "tt_items": [{"id": 1, "user_id": 1, "value": 100}],
    })
    pre_db(db, {"tt_users": []})

    assert _select_all(db, "tt_users") == []
    assert _select_all(db, "tt_items") == []


def test_handles_heterogeneous_row_keys(db):
    """Each row's own keys drive its INSERT.

    Regression: previously the lib computed columns once from rows[0] and
    re-used that SQL for every row, silently dropping keys that appeared
    only in later rows.
    """
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
        "tt_items": [
            {"id": 1, "value": 100},                  # row 0 — no user_id
            {"id": 2, "user_id": 1, "value": 200},    # row 1 — has user_id
        ],
    })
    with db.cursor() as cur:
        cur.execute("SELECT id, user_id FROM tt_items ORDER BY id")
        assert cur.fetchall() == [(1, None), (2, 1)]
