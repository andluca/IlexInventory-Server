"""API tests for GET /batches/{id} and PATCH /batches/{id}."""

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
    email = f"bd_{uid}@test.invalid"
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
            (pid, owner_id, f"BD-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, code: str) -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,2.0)",
            (bid, owner_id, product_id, code),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',10)",
            (owner_id, bid),
        )
    return bid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_get_batch_returns_on_hand_and_recall_flag():
    user = _make_user(8101)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "BD-001")

    resp = _client(user).get(f"/api/v1/batches/{bid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["batch_code"] == "BD-001"
    assert data["is_recalled"] is False
    # on_hand should be "10.0000" (receipt of 10)
    assert data["on_hand"] == "10.0000"


def test_get_cross_owner_returns_404_not_403():
    user_a = _make_user(8102)
    user_b = _make_user(8103)
    pid = _seed_product(user_a.id)
    bid = _seed_batch(user_a.id, pid, "BD-CROSS")

    resp = _client(user_b).get(f"/api/v1/batches/{bid}")
    assert resp.status_code == 404
