"""Tests for pre_db_from_file / post_db_from_file."""

from __future__ import annotations

from pathlib import Path

from apps.core.tests.db_test import (
    post_db_from_file,
    pre_db_from_file,
)

FIXTURE = str(Path(__file__).parent / "fixtures" / "test_state.json")


def test_pre_db_from_file_loads_and_inserts(db):
    pre_db_from_file(db, FIXTURE)

    with db.cursor() as cur:
        cur.execute("SELECT id, name FROM tt_users ORDER BY id")
        assert cur.fetchall() == [(1, "alice"), (2, "bob")]
        cur.execute("SELECT id, user_id, value FROM tt_items ORDER BY id")
        assert cur.fetchall() == [(1, 1, 100), (2, 2, 200)]


def test_post_db_from_file_asserts_state(db):
    pre_db_from_file(db, FIXTURE)
    post_db_from_file(db, FIXTURE)
