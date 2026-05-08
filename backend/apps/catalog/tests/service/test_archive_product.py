"""Service tests — archive_product."""

from __future__ import annotations

import uuid

import pytest

from apps.catalog.errors import ProductHasNoBatches, ProductNotFound
from apps.catalog.services import archive_product, create_product
from apps.core.tests.db_test import post_db, pre_db

pytestmark = pytest.mark.django_db


def _owner_row(user_id: int) -> dict:
    return {
        "id": user_id,
        "password": "hashed",
        "last_login": None,
        "is_superuser": False,
        "username": f"arch_user_{user_id}",
        "first_name": "",
        "last_name": "",
        "email": f"archuser{user_id}@test.invalid",
        "is_staff": False,
        "is_active": True,
        "date_joined": "2026-01-01T00:00:00+00:00",
    }


def test_archive_product_without_batches_raises_product_has_no_batches(db):
    """archive_product when count_batches_for_product == 0 raises ProductHasNoBatches."""
    pre_db(db, {"auth_user": [_owner_row(30)], "products": []})
    db.commit()

    p = create_product(owner_id=30, sku="ARCH-001", name="P", description="", base_unit="unit")
    product_id = p["id"]

    # count_batches_for_product returns 0 (stub returns 0 naturally since batches table
    # does not exist). This should raise ProductHasNoBatches.
    with pytest.raises(ProductHasNoBatches):
        archive_product(owner_id=30, product_id=uuid.UUID(str(product_id)))

    # State must be unchanged.
    post_db(db, {"products": [{"sku": "ARCH-001", "archived_at": None}]})
    db.rollback()


def test_archive_product_cross_owner_raises_not_found(db):
    """archive_product by wrong owner raises ProductNotFound (D4)."""
    pre_db(db, {"auth_user": [_owner_row(32), _owner_row(33)], "products": []})
    db.commit()

    p = create_product(owner_id=32, sku="ARCH-003", name="P", description="", base_unit="unit")
    product_id = p["id"]

    with pytest.raises(ProductNotFound):
        archive_product(owner_id=33, product_id=uuid.UUID(str(product_id)))

    post_db(db, {"products": [{"sku": "ARCH-003", "archived_at": None}]})
    db.rollback()
