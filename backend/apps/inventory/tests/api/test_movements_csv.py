"""API tests for GET /movements?format=csv (ILEX-009 step 4)."""

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
_URL = "/api/v1/movements"


# ---------------------------------------------------------------------------
# Seed helpers (same pattern as test_movements_audit.py)
# ---------------------------------------------------------------------------

def _make_user(uid: int) -> types.SimpleNamespace:
    email = f"mcsv_{uid}@test.invalid"
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
            (pid, owner_id, f"MCV-{pid[:8]}", f"MCSVProd {pid[:8]}"),
        )
    return pid


def _seed_batch(owner_id: int, product_id: str, code: str = "MCSV-B") -> str:
    bid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (bid, owner_id, product_id, code, Decimal("1.0000")),
        )
    return bid


def _seed_movement(owner_id: int, batch_id: str, kind: str = "receipt", qty: str = "10.0000") -> str:
    mid = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        if kind == "adjustment":
            conn.execute(
                "INSERT INTO stock_movements (id, owner_id, batch_id, kind, signed_quantity, notes) VALUES (%s,%s,%s,%s,%s,'adj note')",
                (mid, owner_id, batch_id, kind, qty),
            )
        else:
            conn.execute(
                "INSERT INTO stock_movements (id, owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,%s,%s,%s)",
                (mid, owner_id, batch_id, kind, qty),
            )
    return mid


def _client(user: types.SimpleNamespace) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _collect_csv(response) -> str:
    return b"".join(response.streaming_content).decode("utf-8")


# ---------------------------------------------------------------------------
# Happy path: 3 movements → 4 lines (header + 3)
# ---------------------------------------------------------------------------

def test_movements_csv_returns_header_plus_rows(db):
    """3 seeded movements → CSV has 4 lines (header + 3 data rows)."""
    user = _make_user(9401)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MCSV-A")

    for _ in range(3):
        _seed_movement(user.id, bid, "receipt", "10.0000")

    resp = _client(user).get(_URL, {"format": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv; charset=utf-8"

    body = _collect_csv(resp)
    lines = body.splitlines()
    assert lines[0] == "id,owner_id,batch_id,kind,signed_quantity,notes,reference_type,reference_id,created_at"
    assert len(lines) == 4  # header + 3 rows


def test_movements_csv_row_count_matches_json_variant(db):
    """Row count in CSV matches item count in JSON variant (no cursor, limit=100)."""
    user = _make_user(9402)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MCSV-B2")

    for _ in range(5):
        _seed_movement(user.id, bid, "receipt", "1.0000")

    resp_json = _client(user).get(_URL, {"batch_id": bid, "limit": 100})
    assert resp_json.status_code == 200
    json_count = len(resp_json.json()["items"])

    resp_csv = _client(user).get(_URL, {"batch_id": bid, "format": "csv"})
    assert resp_csv.status_code == 200
    csv_lines = _collect_csv(resp_csv).splitlines()
    csv_data_lines = csv_lines[1:]  # strip header

    assert len(csv_data_lines) == json_count


# ---------------------------------------------------------------------------
# Decimal preservation
# ---------------------------------------------------------------------------

def test_movements_csv_decimal_preservation(db):
    """signed_quantity of Decimal("12.0000") round-trips as "12.0000" in CSV."""
    user = _make_user(9403)
    pid = _seed_product(user.id)
    bid = _seed_batch(user.id, pid, "MCSV-DEC")
    _seed_movement(user.id, bid, "receipt", "12.0000")

    resp = _client(user).get(_URL, {"batch_id": bid, "format": "csv"})
    assert resp.status_code == 200
    body = _collect_csv(resp)
    lines = body.splitlines()
    # signed_quantity is column index 4
    data_line = lines[1]
    fields = data_line.split(",")
    assert fields[4] == "12.0000"


# ---------------------------------------------------------------------------
# Filter passthrough
# ---------------------------------------------------------------------------

def test_movements_csv_filter_by_batch_id(db):
    """?batch_id=<id>&format=csv returns only that batch's rows."""
    user = _make_user(9404)
    pid = _seed_product(user.id)
    bid1 = _seed_batch(user.id, pid, "MCSV-F1")
    bid2 = _seed_batch(user.id, pid, "MCSV-F2")
    _seed_movement(user.id, bid1, "receipt", "5.0000")
    _seed_movement(user.id, bid1, "receipt", "5.0000")
    _seed_movement(user.id, bid2, "receipt", "5.0000")

    resp = _client(user).get(_URL, {"batch_id": bid1, "format": "csv"})
    assert resp.status_code == 200
    body = _collect_csv(resp)
    lines = body.splitlines()
    data_lines = lines[1:]
    # batch_id is column index 2
    batch_ids = [line.split(",")[2] for line in data_lines]
    assert all(b == bid1 for b in batch_ids)
    assert len(data_lines) == 2


# ---------------------------------------------------------------------------
# Unauthenticated → 401
# ---------------------------------------------------------------------------

def test_movements_csv_unauthenticated_returns_401(db):
    """Unauthenticated CSV request returns 401."""
    resp = APIClient().get(_URL, {"format": "csv"})
    assert resp.status_code == 401
