"""Combined workflow + Postgres-specific tests.

Port of epic-test/db-test/tests/db-test.test.ts plus the Postgres-only
cases the SQLite suite doesn't cover (Decimal precision, timestamptz)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from apps.core.tests.db_test import post_db, pre_db


# --- TS combined workflow ---


def test_pre_then_mutate_then_post(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    with db.cursor() as cur:
        cur.execute("UPDATE tt_users SET name = 'ALICE' WHERE id = 1")
    post_db(db, {
        "tt_users": [{"id": 1, "name": "ALICE"}],
    })


def test_subset_assertion_after_pre(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}],
    })
    # Only verify that two rows with these names exist; ignore ids.
    post_db(db, {
        "tt_users": [{"name": "alice"}, {"name": "bob"}],
    })


def test_detects_old_value_fails_new_value_passes(db):
    pre_db(db, {
        "tt_users": [{"id": 1, "name": "alice"}],
    })
    with db.cursor() as cur:
        cur.execute("UPDATE tt_users SET name = 'updated' WHERE id = 1")

    # Old value no longer matches.
    with pytest.raises(AssertionError):
        post_db(db, {"tt_users": [{"id": 1, "name": "alice"}]})

    # New value matches.
    post_db(db, {"tt_users": [{"id": 1, "name": "updated"}]})


# --- Postgres-specific: Decimal ---


def test_decimal_strict_match_with_storage_precision(db):
    pre_db(db, {
        "tt_decimals": [{"id": 1, "amount": Decimal("100.0000")}],
    })
    post_db(db, {
        "tt_decimals": [{"id": 1, "amount": Decimal("100.0000")}],
    })


def test_decimal_loose_mode_to_string(db):
    pre_db(db, {
        "tt_decimals": [{"id": 1, "amount": Decimal("100.0000")}],
    })
    # In loose mode, expected can be a string of the same canonical form.
    post_db(db, {
        "tt_decimals": [{"id": 1, "amount": "100.0000"}],
    }, loose=True)


# --- Postgres-specific: timestamptz ---


def test_timestamptz_roundtrip(db):
    ts = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    pre_db(db, {
        "tt_events": [{"id": 1, "occurred_at": ts}],
    })
    # Strict mode: both expected and actual normalize to ISO via _normalize_value.
    post_db(db, {
        "tt_events": [{"id": 1, "occurred_at": ts}],
    })


def test_timestamptz_iso_string_in_loose_mode(db):
    ts = datetime(2026, 5, 7, 12, 0, 0, tzinfo=timezone.utc)
    pre_db(db, {
        "tt_events": [{"id": 1, "occurred_at": ts}],
    })
    # Expected as ISO string; loose mode coerces both sides to str.
    post_db(db, {
        "tt_events": [{"id": 1, "occurred_at": ts.isoformat()}],
    }, loose=True)
