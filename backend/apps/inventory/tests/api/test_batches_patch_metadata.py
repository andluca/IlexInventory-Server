"""API tests for PATCH /batches/{id}."""

from __future__ import annotations

import os
import types
import uuid

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"bpm_{uid}@test.invalid"
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO auth_user (id, username, email, password,
                                   is_superuser, is_staff, is_active,
                                   first_name, last_name, date_joined)
            VALUES (%s, %s, %s, 'unusable!', false, false, true, '', '', NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            (uid, email, email),
        )
    return types.SimpleNamespace(id=uid, is_authenticated=True, is_active=True)


def _seed_product(owner_id: int) -> str:
    pid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO products (id, owner_id, sku, name, description, base_unit) VALUES (%s,%s,%s,%s,'','unit')",
            (pid, owner_id, f"BPM-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, code: str) -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,1.0)",
            (bid, owner_id, product_id, code),
        )
    return bid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_patch_batch_code_returns_200_and_writes_audit_movement():
    user = _make_user(8301)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "OLD-CODE")

    resp = _client(user).patch(f"/api/v1/batches/{bid}", {"batch_code": "NEW-CODE"}, format="json")
    assert resp.status_code == 200
    assert resp.json()["batch_code"] == "NEW-CODE"

    # Verify audit movement written
    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id = %s AND kind = 'metadata_correction'",
            (bid,),
        ).fetchone()[0]
    assert count == 1


def test_patch_with_disallowed_field_returns_400():
    """PATCH with a non-allowlisted field like unit_cost returns 400."""
    user = _make_user(8302)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "CODE-DIS")

    resp = _client(user).patch(f"/api/v1/batches/{bid}", {"unit_cost": "99.0"}, format="json")
    assert resp.status_code == 400


def test_patch_idempotent_when_value_unchanged():
    user = _make_user(8303)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "SAME-CODE")

    # PATCH same batch_code → no movement written
    resp = _client(user).patch(f"/api/v1/batches/{bid}", {"batch_code": "SAME-CODE"}, format="json")
    assert resp.status_code == 200

    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id = %s AND kind = 'metadata_correction'",
            (bid,),
        ).fetchone()[0]
    assert count == 0


def test_patch_cross_owner_returns_404():
    user_a = _make_user(8304)
    user_b = _make_user(8305)
    pid = _seed_product(user_a.id)
    bid = _seed_batch(user_a.id, pid, "CROSS-PATCH")

    resp = _client(user_b).patch(f"/api/v1/batches/{bid}", {"batch_code": "NEW"}, format="json")
    assert resp.status_code == 404
