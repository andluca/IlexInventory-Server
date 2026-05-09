"""API tests for POST /batches/{id}/movements."""

from __future__ import annotations

import os
import types
import uuid
from decimal import Decimal

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")


def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"bmv_{uid}@test.invalid"
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
            (pid, owner_id, f"BMV-{pid[:8]}", f"Prod {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, code: str, qty: str = "20") -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,1.0)",
            (bid, owner_id, product_id, code),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, bid, qty),
        )
    return bid


def _client(user) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _mv_url(bid: str) -> str:
    return f"/api/v1/batches/{bid}/movements"


def test_post_adjustment_returns_200_and_records_movement():
    user = _make_user(8401)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-ADJ")

    resp = _client(user).post(_mv_url(bid), {
        "kind": "adjustment",
        "signed_quantity": "-2.0000",
        "notes": "shrinkage",
    }, format="json")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "adjustment"


def test_post_adjustment_blank_notes_returns_400():
    user = _make_user(8402)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-BLANK")

    resp = _client(user).post(_mv_url(bid), {
        "kind": "adjustment",
        "signed_quantity": "1.0000",
        "notes": "   ",
    }, format="json")
    assert resp.status_code == 400


def test_post_write_off_within_on_hand_returns_200():
    user = _make_user(8403)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-WO-OK")

    resp = _client(user).post(_mv_url(bid), {
        "kind": "write_off",
        "signed_quantity": "-5.0000",
    }, format="json", HTTP_IDEMPOTENCY_KEY="wo-ok-1")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "write_off"


def test_post_write_off_into_negative_returns_422_with_shortfall_body():
    user = _make_user(8404)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-WO-NEG", qty="5")

    resp = _client(user).post(_mv_url(bid), {
        "kind": "write_off",
        "signed_quantity": "-10.0000",
    }, format="json", HTTP_IDEMPOTENCY_KEY="wo-neg-1")
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_post_write_off_requires_idempotency_key():
    """SPEC §2.6: write_off (a stock-debiting destructive operation) requires
    an Idempotency-Key. ILEX-016 §1.2 wired the header check via a
    kind-conditional @idempotent on `_post_write_off`. Adjustments still skip.
    """
    user = _make_user(8405)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-WO-IDM")

    # Missing key → 400 ValidationError per @idempotent contract.
    resp = _client(user).post(_mv_url(bid), {
        "kind": "write_off",
        "signed_quantity": "-1.0000",
    }, format="json")
    assert resp.status_code == 400
    assert resp.json()["error"] == "ValidationError"
    assert "Idempotency-Key" in resp.json()["detail"]


def test_post_write_off_retry_with_same_key_returns_cached_response():
    """Retrying a write_off with the same Idempotency-Key must NOT double-debit.
    Second call hits the cache; on_hand reflects only one write_off, not two.
    """
    user = _make_user(8409)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-WO-RETRY", qty="20")

    payload = {"kind": "write_off", "signed_quantity": "-5.0000"}
    headers = {"HTTP_IDEMPOTENCY_KEY": "wo-retry-1"}

    resp1 = _client(user).post(_mv_url(bid), payload, format="json", **headers)
    resp2 = _client(user).post(_mv_url(bid), payload, format="json", **headers)
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json() == resp2.json(), "Cached response must match the first one byte-for-byte"

    # Only one write_off must be recorded — on_hand = 20 - 5 = 15
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        on_hand = conn.execute(
            "SELECT COALESCE(SUM(signed_quantity), 0) FROM stock_movements WHERE batch_id=%s",
            (bid,),
        ).fetchone()[0]
    assert Decimal(str(on_hand)) == Decimal("15.0000")


def test_post_adjustment_does_not_require_idempotency_key():
    """Adjustment is an audit-correction kind and does NOT require the header
    (SPEC §2.6 lists only write_off, not adjustment, as idempotency-keyed).
    """
    user = _make_user(8410)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-ADJ-OK")

    resp = _client(user).post(_mv_url(bid), {
        "kind": "adjustment",
        "signed_quantity": "+1.0000",
        "notes": "Stock-take overage",
    }, format="json")
    assert resp.status_code == 200
    assert resp.json()["kind"] == "adjustment"


def test_post_invalid_kind_returns_400():
    """kind='sale' is rejected by the serializer ChoiceField."""
    user = _make_user(8406)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MV-INV")

    resp = _client(user).post(_mv_url(bid), {
        "kind": "sale",
        "signed_quantity": "-1.0000",
    }, format="json")
    assert resp.status_code == 400


def test_post_cross_owner_batch_returns_404():
    user_a = _make_user(8407)
    user_b = _make_user(8408)
    pid = _seed_product(user_a.id)
    bid = _seed_batch(user_a.id, pid, "MV-CROSS")

    resp = _client(user_b).post(_mv_url(bid), {
        "kind": "adjustment",
        "signed_quantity": "1.0000",
        "notes": "test",
    }, format="json")
    assert resp.status_code == 404
