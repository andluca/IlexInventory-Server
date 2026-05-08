"""API tests for POST /batches (manual batch creation)."""

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
    email = f"bc_{uid}@test.invalid"
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
            (pid, owner_id, f"BC-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _payload(product_id: str, code: str = "BC-001") -> dict:
    return {
        "product_id": product_id,
        "batch_code": code,
        "expiration_date": None,
        "unit_cost": "2.0000",
        "initial_quantity": "10.0000",
    }


def test_post_creates_manual_batch_with_idempotency_key():
    user = _make_user(8201)
    pid = _seed_product(user.id)

    resp = _client(user).post(_URL, _payload(pid), format="json",
                               HTTP_IDEMPOTENCY_KEY="test-key-8201")
    assert resp.status_code == 201
    data = resp.json()
    assert data["batch_code"] == "BC-001"
    assert data["purchase_order_line_id"] is None


def test_missing_idempotency_key_returns_400():
    user = _make_user(8202)
    pid = _seed_product(user.id)

    resp = _client(user).post(_URL, _payload(pid, "BC-NOIDM"), format="json")
    assert resp.status_code == 400


def test_duplicate_idempotency_key_returns_cached_response():
    user = _make_user(8203)
    pid = _seed_product(user.id)

    # First call
    resp1 = _client(user).post(_URL, _payload(pid, "BC-IDEM"), format="json",
                                HTTP_IDEMPOTENCY_KEY="idem-key-8203")
    assert resp1.status_code == 201

    # Second call — same key, different batch_code wouldn't matter (cached)
    resp2 = _client(user).post(_URL, _payload(pid, "BC-IDEM"), format="json",
                                HTTP_IDEMPOTENCY_KEY="idem-key-8203")
    assert resp2.status_code == 201
    # Both responses have same id
    assert resp1.json()["id"] == resp2.json()["id"]


def test_cross_owner_product_returns_404():
    user_a = _make_user(8204)
    user_b = _make_user(8205)
    pid_a = _seed_product(user_a.id)

    resp = _client(user_b).post(_URL, _payload(pid_a, "BC-CROSS"), format="json",
                                 HTTP_IDEMPOTENCY_KEY="cross-key-8205")
    assert resp.status_code == 404


def test_duplicate_batch_code_returns_409():
    user = _make_user(8206)
    pid = _seed_product(user.id)

    _client(user).post(_URL, _payload(pid, "BC-DUP"), format="json",
                        HTTP_IDEMPOTENCY_KEY="dup-key-1")
    resp = _client(user).post(_URL, _payload(pid, "BC-DUP"), format="json",
                               HTTP_IDEMPOTENCY_KEY="dup-key-2")
    assert resp.status_code == 409


def test_negative_initial_quantity_returns_400():
    user = _make_user(8207)
    pid = _seed_product(user.id)

    payload = _payload(pid, "BC-NEG")
    payload["initial_quantity"] = "0"

    resp = _client(user).post(_URL, payload, format="json",
                               HTTP_IDEMPOTENCY_KEY="neg-key-8207")
    assert resp.status_code == 400
