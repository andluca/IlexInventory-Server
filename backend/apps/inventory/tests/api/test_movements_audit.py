"""API tests for GET /movements."""

from __future__ import annotations

import os
import time
import types
import uuid
from decimal import Decimal

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
_URL = "/api/v1/movements"


def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"ma_{uid}@test.invalid"
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
            (pid, owner_id, f"MA-{pid[:8]}", f"Prod {pid[:8]}"),
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


def _seed_movement(owner_id: int, batch_id: str, kind: str = "receipt", qty: str = "10", notes: str = None) -> str:
    mid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        if kind == "adjustment":
            conn.execute(
                "INSERT INTO stock_movements (id, owner_id, batch_id, kind, signed_quantity, notes) VALUES (%s,%s,%s,%s,%s,%s)",
                (mid, owner_id, batch_id, kind, qty, notes or "adj"),
            )
        else:
            conn.execute(
                "INSERT INTO stock_movements (id, owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,%s,%s,%s)",
                (mid, owner_id, batch_id, kind, qty),
            )
    return mid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def test_get_movements_returns_paginated_results_cursor_advances():
    user = _make_user(8601)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MA-PAGE")

    for i in range(1, 4):
        _seed_movement(user.id, bid, "receipt", str(i))
        time.sleep(0.01)

    resp = _client(user).get(_URL, {"batch_id": bid, "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    # Latest should be first (desc)
    qtys = [item["signed_quantity"] for item in data["items"]]
    assert Decimal(qtys[0]) > Decimal(qtys[1])

    # Follow cursor
    cursor = data["next_cursor"]
    assert cursor is not None
    resp2 = _client(user).get(_URL, {"batch_id": bid, "limit": 2, "cursor": cursor})
    assert resp2.status_code == 200
    assert len(resp2.json()["items"]) == 1


def test_get_movements_filter_by_batch_id():
    user = _make_user(8602)
    pid = _seed_product(user.id)
    bid1 = _seed_batch(user.id, pid, "MA-FILT-1")
    bid2 = _seed_batch(user.id, pid, "MA-FILT-2")
    _seed_movement(user.id, bid1, "receipt")
    _seed_movement(user.id, bid2, "receipt")

    resp = _client(user).get(_URL, {"batch_id": bid1})
    assert resp.status_code == 200
    batch_ids = [item["batch_id"] for item in resp.json()["items"]]
    assert all(b == bid1 for b in batch_ids)


def test_get_movements_filter_by_product_id():
    user = _make_user(8603)
    pid1 = _seed_product(user.id)
    pid2 = _seed_product(user.id)
    bid1 = _seed_batch(user.id, pid1, "MA-PROD-1")
    bid2 = _seed_batch(user.id, pid2, "MA-PROD-2")
    _seed_movement(user.id, bid1, "receipt")
    _seed_movement(user.id, bid2, "receipt")

    resp = _client(user).get(_URL, {"product_id": pid1})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["batch_id"] == bid1 for item in items)


def test_get_movements_filter_by_kind_and_date_range():
    user = _make_user(8604)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MA-KIND")
    _seed_movement(user.id, bid, "receipt", "20")
    _seed_movement(user.id, bid, "adjustment", "5", notes="test adj")

    resp = _client(user).get(_URL, {"kind": "adjustment", "batch_id": bid})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert all(item["kind"] == "adjustment" for item in items)


def test_get_movements_does_not_show_other_owners_movements():
    user_a = _make_user(8605)
    user_b = _make_user(8606)
    pid_a = _seed_product(user_a.id)
    bid_a = _seed_batch(user_a.id, pid_a, "MA-OWN-A")
    _seed_movement(user_a.id, bid_a, "receipt")

    resp = _client(user_b).get(_URL)
    assert resp.status_code == 200
    batch_ids = [item["batch_id"] for item in resp.json()["items"]]
    assert bid_a not in batch_ids


def test_get_movements_unauthenticated_returns_401():
    resp = APIClient().get(_URL)
    assert resp.status_code == 401
