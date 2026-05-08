"""Service tests for draft CRUD: create, update, delete, list."""

from __future__ import annotations

import uuid
from decimal import Decimal

import os

import psycopg
import pytest

from apps.sales.errors import ProductNotFound, SalesOrderNotDraft, SalesOrderNotFound
from apps.sales.errors import ValidationError as SalesValidationError
from apps.sales.services import (
    create_sales_order_draft,
    delete_sales_order_draft,
    list_sales_orders_for_owner,
    update_sales_order_draft,
)

_DB_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_user(uid: int) -> None:
    email = f"svc_draft_{uid}@test.invalid"
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


def _seed_product(owner_id: int) -> str:
    product_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO products (id, owner_id, sku, name, description, base_unit)
            VALUES (%s, %s, %s, %s, '', 'unit')
            """,
            (product_id, owner_id, f"SVC-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


def _seed_committed_so(owner_id: int, product_id: str) -> str:
    """Create a committed SO directly (bypassing service — DB state setup)."""
    so_id = str(uuid.uuid4())
    with psycopg.connect(_DB_URL, autocommit=True) as conn:
        conn.execute(
            """
            INSERT INTO sales_orders (id, owner_id, customer_name, status, committed_at)
            VALUES (%s, %s, 'Test Customer', 'committed', NOW())
            """,
            (so_id, owner_id),
        )
        line_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO sales_order_lines
                   (id, owner_id, sales_order_id, product_id, quantity, sell_price)
            VALUES (%s, %s, %s, %s, 1.0000, 10.0000)
            """,
            (line_id, owner_id, so_id, product_id),
        )
    return so_id


# ---------------------------------------------------------------------------
# create_sales_order_draft
# ---------------------------------------------------------------------------

def test_create_draft_happy_path():
    """create_sales_order_draft inserts a SO header + lines; returns draft status."""
    owner_id = 9001
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    result = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Acme Corp",
        customer_contact="ops@acme.test",
        lines=[
            {"product_id": product_id, "quantity": Decimal("100.0000"), "sell_price": Decimal("10.0000")},
        ],
    )

    assert result["status"] == "draft"
    assert result["customer_name"] == "Acme Corp"
    assert result["customer_contact"] == "ops@acme.test"
    assert len(result["lines"]) == 1
    assert Decimal(str(result["lines"][0]["quantity"])) == Decimal("100.0000")
    assert result["allocations"] == []

    # Verify DB state
    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            "SELECT status, customer_name FROM sales_orders WHERE id = %s",
            (result["id"],),
        ).fetchone()
    assert row[0] == "draft"
    assert row[1] == "Acme Corp"


def test_create_draft_empty_lines_raises_validation_error():
    """create_sales_order_draft with empty lines raises ValidationError."""
    owner_id = 9002
    _seed_user(owner_id)

    with pytest.raises(SalesValidationError):
        create_sales_order_draft(
            owner_id=owner_id,
            customer_name="Test",
            customer_contact=None,
            lines=[],
        )


def test_create_draft_cross_owner_product_raises_product_not_found():
    """create_sales_order_draft with another owner's product_id raises ProductNotFound."""
    owner_a = 9003
    owner_b = 9004
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)

    with pytest.raises(ProductNotFound):
        create_sales_order_draft(
            owner_id=owner_b,
            customer_name="Acme",
            customer_contact=None,
            lines=[{"product_id": product_a, "quantity": Decimal("1.0000"), "sell_price": Decimal("5.0000")}],
        )


# ---------------------------------------------------------------------------
# update_sales_order_draft
# ---------------------------------------------------------------------------

def test_update_draft_replaces_lines():
    """update_sales_order_draft with new lines deletes old lines and inserts new set."""
    owner_id = 9005
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Original Name",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("10.0000"), "sell_price": Decimal("5.0000")}],
    )
    so_id = so["id"]

    product_id2 = _seed_product(owner_id)
    updated = update_sales_order_draft(
        owner_id=owner_id,
        so_id=so_id,
        customer_name="Updated Name",
        lines=[
            {"product_id": product_id2, "quantity": Decimal("50.0000"), "sell_price": Decimal("12.0000")},
        ],
    )

    assert updated["customer_name"] == "Updated Name"
    assert len(updated["lines"]) == 1
    assert str(updated["lines"][0]["product_id"]) == product_id2


def test_update_committed_so_raises_not_draft():
    """update_sales_order_draft on a committed SO raises SalesOrderNotDraft (409)."""
    owner_id = 9006
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    so_id = _seed_committed_so(owner_id, product_id)

    with pytest.raises(SalesOrderNotDraft):
        update_sales_order_draft(
            owner_id=owner_id,
            so_id=so_id,
            customer_name="New Name",
        )


def test_update_cross_owner_raises_not_found():
    """update_sales_order_draft cross-owner returns SalesOrderNotFound (D4 → 404)."""
    owner_a = 9007
    owner_b = 9008
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_a = _seed_product(owner_a)
    so_a = create_sales_order_draft(
        owner_id=owner_a,
        customer_name="A Corp",
        customer_contact=None,
        lines=[{"product_id": product_a, "quantity": Decimal("1.0000"), "sell_price": Decimal("1.0000")}],
    )

    with pytest.raises(SalesOrderNotFound):
        update_sales_order_draft(
            owner_id=owner_b,
            so_id=so_a["id"],
            customer_name="Hijacked",
        )


# ---------------------------------------------------------------------------
# delete_sales_order_draft
# ---------------------------------------------------------------------------

def test_delete_draft_removes_so_and_lines():
    """delete_sales_order_draft removes SO; lines cascade."""
    owner_id = 9009
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    so = create_sales_order_draft(
        owner_id=owner_id,
        customer_name="Delete Me",
        customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("1.0000"), "sell_price": Decimal("1.0000")}],
    )
    so_id = so["id"]

    delete_sales_order_draft(owner_id=owner_id, so_id=so_id)

    with psycopg.connect(_DB_URL) as conn:
        row = conn.execute(
            "SELECT 1 FROM sales_orders WHERE id = %s", (so_id,)
        ).fetchone()
    assert row is None


def test_delete_committed_so_raises_not_draft():
    """delete_sales_order_draft on a committed SO raises SalesOrderNotDraft (409)."""
    owner_id = 9010
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)
    so_id = _seed_committed_so(owner_id, product_id)

    with pytest.raises(SalesOrderNotDraft):
        delete_sales_order_draft(owner_id=owner_id, so_id=so_id)


# ---------------------------------------------------------------------------
# list_sales_orders_for_owner (cursor pagination)
# ---------------------------------------------------------------------------

def test_list_returns_multiple_sos_newest_first():
    """list_sales_orders_for_owner returns SOs in newest-first order."""
    owner_id = 9011
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    so1 = create_sales_order_draft(
        owner_id=owner_id, customer_name="Alpha", customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("1"), "sell_price": Decimal("1")}],
    )
    so2 = create_sales_order_draft(
        owner_id=owner_id, customer_name="Beta", customer_contact=None,
        lines=[{"product_id": product_id, "quantity": Decimal("1"), "sell_price": Decimal("1")}],
    )

    result = list_sales_orders_for_owner(owner_id=owner_id, limit=50)
    ids = [item["id"] for item in result["items"]]
    # Newest first
    assert ids.index(so2["id"]) < ids.index(so1["id"])


def test_list_cursor_pagination():
    """list_sales_orders_for_owner cursor pagination returns next_cursor and correct items."""
    owner_id = 9012
    _seed_user(owner_id)
    product_id = _seed_product(owner_id)

    created = []
    for i in range(3):
        so = create_sales_order_draft(
            owner_id=owner_id,
            customer_name=f"Page customer {i}",
            customer_contact=None,
            lines=[{"product_id": product_id, "quantity": Decimal("1"), "sell_price": Decimal("1")}],
        )
        created.append(so["id"])

    page1 = list_sales_orders_for_owner(owner_id=owner_id, limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = list_sales_orders_for_owner(owner_id=owner_id, limit=2, cursor=page1["next_cursor"])
    # Should have the remaining item(s)
    ids_page1 = {item["id"] for item in page1["items"]}
    ids_page2 = {item["id"] for item in page2["items"]}
    assert ids_page1.isdisjoint(ids_page2)
