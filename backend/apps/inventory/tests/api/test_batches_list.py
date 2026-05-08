"""API tests for GET /batches."""

from __future__ import annotations

import os
import types
import uuid

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
_URL = "/api/v1/batches"


def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"bl_{uid}@test.invalid"
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
            (pid, owner_id, f"BL-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, code: str, expiry=None, recalled: bool = False) -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        if recalled:
            conn.execute(
                """INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost,
                            expiration_date, is_recalled, recall_reason, recalled_at)
                   VALUES (%s,%s,%s,%s,1.0,%s,TRUE,'test',NOW())""",
                (bid, owner_id, product_id, code, expiry),
            )
        else:
            conn.execute(
                "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost, expiration_date) VALUES (%s,%s,%s,%s,1.0,%s)",
                (bid, owner_id, product_id, code, expiry),
            )
    return bid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_list_returns_paginated_batches_for_owner():
    user = _make_user(8001)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid, "BL-A")
    _seed_batch(user.id, pid, "BL-B")

    resp = _client(user).get(_URL)
    assert resp.status_code == 200
    data = resp.json()
    codes = [b["batch_code"] for b in data["items"]]
    assert "BL-A" in codes
    assert "BL-B" in codes


def test_list_filter_by_product_id():
    user = _make_user(8002)
    pid1 = _seed_product(user.id)
    pid2 = _seed_product(user.id)
    _seed_batch(user.id, pid1, "BL-P1")
    _seed_batch(user.id, pid2, "BL-P2")

    resp = _client(user).get(_URL, {"product_id": pid1})
    assert resp.status_code == 200
    codes = [b["batch_code"] for b in resp.json()["items"]]
    assert "BL-P1" in codes
    assert "BL-P2" not in codes


def test_list_filter_is_recalled_true_only():
    user = _make_user(8003)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid, "BL-ACTIVE")
    _seed_batch(user.id, pid, "BL-RECALLED", recalled=True)

    resp = _client(user).get(_URL, {"is_recalled": "true"})
    assert resp.status_code == 200
    codes = [b["batch_code"] for b in resp.json()["items"]]
    assert "BL-RECALLED" in codes
    assert "BL-ACTIVE" not in codes


def test_list_filter_expiring_within_days():
    user = _make_user(8004)
    pid = _seed_product(user.id)
    _seed_batch(user.id, pid, "BL-SOON", expiry="2026-05-15")  # ~7 days from 2026-05-08
    _seed_batch(user.id, pid, "BL-FAR", expiry="2026-07-08")

    resp = _client(user).get(_URL, {"expiring_within": 20})
    assert resp.status_code == 200
    codes = [b["batch_code"] for b in resp.json()["items"]]
    assert "BL-SOON" in codes
    assert "BL-FAR" not in codes


def test_list_unauthenticated_returns_401():
    resp = APIClient().get(_URL)
    assert resp.status_code == 401


def test_list_does_not_show_other_owners_batches():
    user_a = _make_user(8005)
    user_b = _make_user(8006)
    pid = _seed_product(user_a.id)
    _seed_batch(user_a.id, pid, "BL-OWNER-A")

    resp = _client(user_b).get(_URL)
    assert resp.status_code == 200
    codes = [b["batch_code"] for b in resp.json()["items"]]
    assert "BL-OWNER-A" not in codes
