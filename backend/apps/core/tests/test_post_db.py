"""Tests for post_db — port of epic-test/db-test/tests/postdb.test.ts."""

from __future__ import annotations

from decimal import Decimal

import psycopg
import pytest

from apps.core.tests.db_test import post_db, pre_db


def test_asserts_exact_match_order_independent(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}],
    })
    # Expected list ordering swapped — multiset compare passes anyway.
    post_db(db, {
        "tt_users": [{"id": 2, "name": "bob"}, {"id": 1, "name": "alice"}],
    })


def test_raises_with_readable_diff_when_mismatched(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    with pytest.raises(AssertionError) as exc:
        post_db(db, {
            "tt_users": [{"id": 1, "name": "DIFFERENT"}],
        })
    msg = str(exc.value)
    assert "PostDB assertion failed" in msg
    assert "tt_users" in msg
    assert "Missing rows" in msg
    assert "Extra rows" in msg


def test_supports_subset_assertions(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    # Expected omits `id` — only `name` is checked.
    post_db(db, {
        "tt_users": [{"name": "alice"}],
    })


def test_allow_extra_rows(db):
    pre_db(db, {
        "tt_users": [
            {"id": 1, "name": "alice"},
            {"id": 2, "name": "bob"},
        ],
    })
    # Expected only mentions one row; allow_extra_rows tolerates the other.
    post_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    }, allow_extra_rows=True)


def test_loose_coerces_to_string(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    # Expected uses string "1" but DB returns int 1 — loose mode coerces both.
    post_db(db, {
        "tt_users": [{"id": "1", "name": "alice"}],
    }, loose=True)


def test_only_targets_subset(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
        "tt_decimals": [{"id": 1, "amount": Decimal("10.5000")}],
    })
    # Provide wrong expectation for tt_decimals, but only verify tt_users.
    post_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
        "tt_decimals": [{"id": 999, "amount": Decimal("999.0000")}],
    }, only=["tt_users"])


def test_raises_on_nonexistent_table(db):
    with pytest.raises(psycopg.errors.UndefinedTable):
        post_db(db, {"tt_nonexistent": [{"id": 1}]})
    db.rollback()


def test_empty_expected_fails_when_db_has_rows(db):
    pre_db(db, {"tt_users": [{"id": 1, "name": "alice"}]})
    with pytest.raises(AssertionError, match="PostDB assertion failed"):
        post_db(db, {"tt_users": []})


def test_empty_expected_passes_when_db_empty(db):
    # No rows in tt_users; expected says zero rows. Should pass.
    post_db(db, {"tt_users": []})
