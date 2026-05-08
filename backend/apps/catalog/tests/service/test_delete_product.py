"""Service tests — delete_product."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.errors import ProductNotFound
from apps.catalog.services import create_product, delete_product
from apps.core.tests.db_test import post_db, pre_db

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"del_user_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"deluser{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


def test_delete_product_without_batches_removes_row(db):
    """delete_product with no batches: row is gone."""
    pre_db(db, {"auth_user": [_owner_row(40)], "products": []})
    db.commit()

    p = create_product(owner_id=40, sku="DEL-001", name="P", description="", base_unit="unit")
    product_id = p["id"]

    # Stub returns 0 by default (no batches table).
    delete_product(owner_id=40, product_id=uuid.UUID(str(product_id)))

    post_db(db, {"products": []})
    db.rollback()


def test_delete_product_cross_owner_raises_not_found(db):
    """delete_product by wrong owner raises ProductNotFound (D4)."""
    pre_db(db, {"auth_user": [_owner_row(42), _owner_row(43)], "products": []})
    db.commit()

    p = create_product(owner_id=42, sku="DEL-003", name="P", description="", base_unit="unit")
    product_id = p["id"]

    with pytest.raises(ProductNotFound):
        delete_product(owner_id=43, product_id=uuid.UUID(str(product_id)))

    post_db(db, {"products": [{"sku": "DEL-003"}]})
    db.rollback()
