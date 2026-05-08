"""Service tests for create_purchase_order_draft.

Behavioral: assert return values and post_db state. No mocking.
Cross-owner product → ProductNotFound (404, D4).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import psycopg
import pytest

from apps.core.tests.db_test import post_db, pre_db
from apps.procurement.errors import ProductNotFound, ValidationError
from apps.procurement.services import create_purchase_order_draft

pytestmark = pytest.mark.django_db

_DB_URL = "postgresql://postgres:postgres@localhost:5432/ilex_test"

import os
_DB_URL = os.environ.get("DATABASE_URL", _DB_URL)


def _seed_user(uid: int) -> None:
    email = f"svc_create_{uid}@test.invalid"
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
            (product_id, owner_id, f"SKU-{product_id[:8]}", f"Prod {product_id[:8]}"),
        )
    return product_id


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_create_draft_happy_path():
    """Create PO with 2 lines; assert header + lines in DB."""
    owner_id = 6001
    _seed_user(owner_id)
    p1 = _seed_product(owner_id)
    p2 = _seed_product(owner_id)

    result = create_purchase_order_draft(
        owner_id=owner_id,
        supplier_name="Acme Corp",
        supplier_contact="acme@example.com",
        lines=[
            {"product_id": p1, "quantity": Decimal("10.0000"), "unit_cost": Decimal("2.5000")},
            {"product_id": p2, "quantity": Decimal("5.0000"), "unit_cost": Decimal("0.0000")},
        ],
    )

    assert result["status"] == "draft"
    assert result["received_at"] is None
    assert result["supplier_name"] == "Acme Corp"
    assert result["supplier_contact"] == "acme@example.com"
    assert len(result["lines"]) == 2

    # Verify line order matches input order
    line_product_ids = [str(ln["product_id"]) for ln in result["lines"]]
    assert p1 in line_product_ids
    assert p2 in line_product_ids


# ---------------------------------------------------------------------------
# Empty lines → ValidationError
# ---------------------------------------------------------------------------

def test_create_draft_empty_lines_raises_validation_error():
    """Empty lines list → ValidationError; no rows inserted."""
    owner_id = 6002
    _seed_user(owner_id)

    with psycopg.connect(_DB_URL, autocommit=True) as pre:
        pre_count = pre.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE owner_id = %s", (owner_id,)
        ).fetchone()[0]

    with pytest.raises(ValidationError):
        create_purchase_order_draft(
            owner_id=owner_id,
            supplier_name="Acme",
            supplier_contact=None,
            lines=[],
        )

    with psycopg.connect(_DB_URL, autocommit=True) as post:
        post_count = post.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE owner_id = %s", (owner_id,)
        ).fetchone()[0]

    assert pre_count == post_count  # No rows inserted


# ---------------------------------------------------------------------------
# Cross-owner product → ProductNotFound
# ---------------------------------------------------------------------------

def test_create_draft_cross_owner_product_raises_product_not_found():
    """Line references another owner's product → ProductNotFound (D4, not 403)."""
    owner_a = 6003
    owner_b = 6004
    _seed_user(owner_a)
    _seed_user(owner_b)
    product_b = _seed_product(owner_b)  # belongs to owner B

    with psycopg.connect(_DB_URL, autocommit=True) as pre:
        pre_po_count = pre.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE owner_id = %s", (owner_a,)
        ).fetchone()[0]

    with pytest.raises(ProductNotFound):
        create_purchase_order_draft(
            owner_id=owner_a,
            supplier_name="Acme",
            supplier_contact=None,
            lines=[
                {"product_id": product_b, "quantity": Decimal("1.0000"), "unit_cost": Decimal("1.0000")}
            ],
        )

    with psycopg.connect(_DB_URL, autocommit=True) as post:
        post_po_count = post.execute(
            "SELECT COUNT(*) FROM purchase_orders WHERE owner_id = %s", (owner_a,)
        ).fetchone()[0]

    # State unchanged
    assert pre_po_count == post_po_count
