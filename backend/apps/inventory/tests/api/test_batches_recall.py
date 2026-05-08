"""API tests for POST /batches/{id}/recall and POST /batches/{id}/un-recall."""

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
    email = f"brcl_{uid}@test.invalid"
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
            (pid, owner_id, f"BRCL-{pid[:8]}", f"Prod {pid[:8]}"),
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


def test_post_recall_returns_200_sets_flag_writes_movement():
    user = _make_user(8501)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "RCALL-API-001")

    resp = _client(user).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "contamination"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rcall-key-8501",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_recalled"] is True

    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id=%s AND kind='recall_block'", (bid,)
        ).fetchone()[0]
    assert count == 1


def test_post_recall_blank_reason_returns_400():
    user = _make_user(8502)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "RCALL-BLANK")

    resp = _client(user).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "   "},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rcall-blank-8502",
    )
    assert resp.status_code == 400


def test_post_recall_idempotency_key_required():
    user = _make_user(8503)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "RCALL-NOIDM")

    resp = _client(user).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "defect"},
        format="json",
    )
    assert resp.status_code == 400


def test_post_recall_idempotent_second_call_is_no_op():
    user = _make_user(8504)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "RCALL-IDMP")

    _client(user).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "contamination"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rcall-idmp-8504",
    )
    # Second call — same idempotency key → cached
    resp2 = _client(user).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "contamination"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rcall-idmp-8504",
    )
    assert resp2.status_code == 200

    with psycopg.connect(_DB_URL) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM stock_movements WHERE batch_id=%s AND kind='recall_block'", (bid,)
        ).fetchone()[0]
    assert count == 1


def test_post_un_recall_returns_200_clears_flag():
    user = _make_user(8505)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "UNRCALL-001")

    _client(user).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "precaution"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rcall-un-1-8505",
    )

    resp = _client(user).post(
        f"/api/v1/batches/{bid}/un-recall",
        format="json",
        HTTP_IDEMPOTENCY_KEY="unrcall-8505",
    )
    assert resp.status_code == 200
    assert resp.json()["is_recalled"] is False


def test_post_recall_cross_owner_returns_404():
    user_a = _make_user(8506)
    user_b = _make_user(8507)
    pid = _seed_product(user_a.id)
    bid = _seed_batch(user_a.id, pid, "RCALL-CROSS")

    resp = _client(user_b).post(
        f"/api/v1/batches/{bid}/recall",
        {"reason": "test"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="rcall-cross-8507",
    )
    assert resp.status_code == 404
