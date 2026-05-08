"""Service tests — update_product."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.errors import ProductNotFound
from apps.catalog.services import create_product, update_product
from apps.core.tests.db_test import post_db, pre_db

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"upd_user_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"upduser{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


def test_update_name_only_leaves_description_unchanged(db):
    """update_product with name only: description stays untouched."""
    pre_db(db, {"auth_user": [_owner_row(20)], "products": []})
    db.commit()

    p = create_product(
        owner_id=20, sku="UPD-001", name="Original", description="Keep me", base_unit="g"
    )
    product_id = p["id"]

    updated = update_product(owner_id=20, product_id=product_id, name="Updated Name")

    assert updated["name"] == "Updated Name"
    assert updated["description"] == "Keep me"

    post_db(db, {"products": [{"sku": "UPD-001", "name": "Updated Name", "description": "Keep me"}]})
    db.rollback()


def test_update_cross_owner_raises_product_not_found(db):
    """update_product by wrong owner returns ProductNotFound (D4: 404, not 403)."""
    pre_db(db, {"auth_user": [_owner_row(21), _owner_row(22)], "products": []})
    db.commit()

    p = create_product(owner_id=21, sku="UPD-002", name="Mine", description="", base_unit="unit")
    product_id = p["id"]

    with pytest.raises(ProductNotFound):
        update_product(owner_id=22, product_id=uuid.UUID(str(product_id)), name="Hijacked")

    post_db(db, {"products": [{"sku": "UPD-002", "name": "Mine"}]})
    db.rollback()
