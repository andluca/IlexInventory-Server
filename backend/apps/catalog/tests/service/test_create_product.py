"""Service tests — create_product."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.errors import DuplicateSKU
from apps.catalog.services import create_product
from apps.core.tests.db_test import post_db, pre_db

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"svc_user_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"svcuser{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


def test_create_product_inserts_row(db):
    """Happy path: product row is inserted, UUIDv7 PK, all fields echoed."""
    pre_db(db, {"auth_user": [_owner_row(10)], "products": []})
    db.commit()

    p = create_product(
        owner_id=10,
        sku="SKU-001",
        name="Cold Brew",
        description="Cold brew coffee",
        base_unit="ml",
    )

    assert p["sku"] == "SKU-001"
    assert p["name"] == "Cold Brew"
    assert p["owner_id"] == 10
    assert p["base_unit"] == "ml"
    assert p["archived_at"] is None
    assert "id" in p

    # Verify version nibble = 7 (UUIDv7)
    uid = uuid.UUID(str(p["id"]))
    assert uid.version == 7

    post_db(db, {"products": [{"sku": "SKU-001", "owner_id": 10}]})
    db.rollback()


def test_create_product_duplicate_sku_same_owner_raises(db):
    """Duplicate SKU for same owner raises DuplicateSKU; no extra row persisted."""
    pre_db(db, {"auth_user": [_owner_row(11)], "products": []})
    db.commit()

    create_product(owner_id=11, sku="DUPE", name="First", description="", base_unit="g")

    with pytest.raises(DuplicateSKU):
        create_product(owner_id=11, sku="DUPE", name="Second", description="", base_unit="g")

    post_db(db, {"products": [{"sku": "DUPE", "owner_id": 11}]})
    db.rollback()


def test_create_product_same_sku_different_owner_succeeds(db):
    """Same SKU for different owners: both rows persist (D4 isolation)."""
    pre_db(db, {"auth_user": [_owner_row(12), _owner_row(13)], "products": []})
    db.commit()

    p1 = create_product(owner_id=12, sku="SHARED", name="Product A", description="", base_unit="unit")
    p2 = create_product(owner_id=13, sku="SHARED", name="Product B", description="", base_unit="unit")

    assert p1["owner_id"] == 12
    assert p2["owner_id"] == 13
    assert p1["id"] != p2["id"]

    post_db(db, {"products": [
        {"sku": "SHARED", "owner_id": 12},
        {"sku": "SHARED", "owner_id": 13},
    ]})
    db.rollback()
