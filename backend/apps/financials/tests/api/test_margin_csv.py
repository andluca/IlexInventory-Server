"""API tests for GET /api/v1/financials/margin?format=csv (ILEX-009 step 6)."""

from __future__ import annotations

import os
import types
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

# Wide range covering today, within 365-day limit
_FROM = (date.today() - timedelta(days=180)).isoformat()
_TO = date.today().isoformat()

_URL = "/api/v1/financials/margin"


# ---------------------------------------------------------------------------
# Seed helpers
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


def _client(user: types.SimpleNamespace) -> APIClient:
    c = APIClient()
    c.force_authenticate(user=user)
    return c


def _seed_product(owner_id: int, name: str = "Widget") -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO products (id, owner_id, sku, name, description, base_unit) VALUES (%s,%s,%s,%s,'','unit')",
            (product_id, owner_id, f"MCSV-{product_id[:8]}", name),
        )
    return product_id


def _seed_batch(owner_id: int, product_id: str, quantity: str, unit_cost: str = "1.0000") -> str:
    batch_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO batches (id, owner_id, product_id, batch_code, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (batch_id, owner_id, product_id, f"MB-{batch_id[:8]}", Decimal(unit_cost)),
        )
        conn.execute(
            "INSERT INTO stock_movements (owner_id, batch_id, kind, signed_quantity) VALUES (%s,%s,'receipt',%s)",
            (owner_id, batch_id, Decimal(quantity)),
        )
    return batch_id


def _seed_committed_so(
    owner_id: int, product_id: str, batch_id: str,
    quantity: str, sell_price: str, unit_cost: str,
) -> str:
    so_id = str(uuid.uuid4())
    sol_id = str(uuid.uuid4())
    qty = Decimal(quantity)
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at) VALUES (%s,%s,'Customer','committed',NOW())",
            (so_id, owner_id),
        )
        conn.execute(
            "INSERT INTO sales_order_lines (id, owner_id, sales_order_id, product_id, quantity, sell_price) VALUES (%s,%s,%s,%s,%s,%s)",
            (sol_id, owner_id, so_id, product_id, qty, Decimal(sell_price)),
        )
        conn.execute(
            "INSERT INTO sale_allocations (owner_id, sales_order_line_id, batch_id, allocated_quantity, unit_cost) VALUES (%s,%s,%s,%s,%s)",
            (owner_id, sol_id, batch_id, qty, Decimal(unit_cost)),
        )
    return so_id


def _collect_csv(response) -> str:
    return b"".join(response.streaming_content).decode("utf-8")


# ---------------------------------------------------------------------------
# Happy path: brief fixture — 100 units @ $10 / $1 COGS
# ---------------------------------------------------------------------------

def test_margin_csv_brief_fixture(db):
    """1 SO, 100 units @ $10 revenue / $1 COGS → CSV row with expected values."""
    user = _make_user(9601)
    pid = _seed_product(user.id, name="Widget")
    bid = _seed_batch(user.id, pid, quantity="100.0000", unit_cost="1.0000")
    _seed_committed_so(user.id, pid, bid, quantity="100.0000", sell_price="10.0000", unit_cost="1.0000")

    resp = _client(user).get(_URL, {"from": _FROM, "to": _TO, "format": "csv"})
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv; charset=utf-8"

    body = _collect_csv(resp)
    lines = body.splitlines()
    assert lines[0] == "product_id,product_name,units_sold,revenue,cogs,profit,margin_pct"
    assert len(lines) == 2

    fields = lines[1].split(",")
    # Header positions: product_id=0, product_name=1, units_sold=2, revenue=3, cogs=4, profit=5, margin_pct=6
    assert fields[2] == "100.0000"   # units_sold
    assert fields[3] == "1000.0000"  # revenue
    assert fields[4] == "100.0000"   # cogs
    assert fields[5] == "900.0000"   # profit
    # margin_pct = (revenue - cogs) / cogs * 100 = 900; Decimal repr may vary
    assert Decimal(fields[6]) == Decimal("900")


# ---------------------------------------------------------------------------
# Row count matches JSON variant
# ---------------------------------------------------------------------------

def test_margin_csv_row_count_matches_json_variant(db):
    """Row count in CSV matches item count in JSON (limit=100, cursor=null)."""
    user = _make_user(9602)
    for i in range(3):
        pid = _seed_product(user.id, name=f"Prod{i}")
        bid = _seed_batch(user.id, pid, quantity="10.0000")
        _seed_committed_so(user.id, pid, bid, quantity="10.0000", sell_price="5.0000", unit_cost="1.0000")

    resp_json = _client(user).get(_URL, {"from": _FROM, "to": _TO, "limit": 100})
    assert resp_json.status_code == 200
    json_count = len(resp_json.json()["items"])

    resp_csv = _client(user).get(_URL, {"from": _FROM, "to": _TO, "format": "csv"})
    assert resp_csv.status_code == 200
    body = _collect_csv(resp_csv)
    csv_data_lines = body.splitlines()[1:]  # strip header

    assert len(csv_data_lines) == json_count


# ---------------------------------------------------------------------------
# Empty range → header only
# ---------------------------------------------------------------------------

def test_margin_csv_empty_range_header_only(db):
    """No sales in range → CSV has header row only."""
    user = _make_user(9603)

    resp = _client(user).get(_URL, {"from": "2020-01-01", "to": "2020-12-31", "format": "csv"})
    assert resp.status_code == 200
    body = _collect_csv(resp)
    lines = body.splitlines()
    assert len(lines) == 1
    assert lines[0] == "product_id,product_name,units_sold,revenue,cogs,profit,margin_pct"
