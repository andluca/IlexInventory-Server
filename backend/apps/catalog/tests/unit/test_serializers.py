"""Unit tests for apps.catalog serializers (no DB required)."""

from __future__ import annotations

from apps.catalog.errors import DuplicateSKU, ProductHasNoBatches, ProductNotFound
from apps.catalog.serializers import ProductCreateRequest, ProductUpdateRequest
from apps.core.errors import to_response

# ---------------------------------------------------------------------------
# ProductCreateRequest
# ---------------------------------------------------------------------------


def test_create_request_valid():
    s = ProductCreateRequest(data={"sku": "SKU-1", "name": "Product", "base_unit": "ml"})
    assert s.is_valid(), s.errors
    assert s.validated_data["description"] == ""  # default


def test_create_request_rejects_bad_base_unit():
    s = ProductCreateRequest(data={"sku": "SKU-1", "name": "Product", "base_unit": "GALLON"})
    assert not s.is_valid()
    assert "base_unit" in s.errors


def test_create_request_accepts_all_valid_base_units():
    for unit in ("g", "ml", "unit"):
        s = ProductCreateRequest(data={"sku": "S", "name": "N", "base_unit": unit})
        assert s.is_valid(), f"Expected valid for base_unit={unit!r}: {s.errors}"


# ---------------------------------------------------------------------------
# ProductUpdateRequest
# ---------------------------------------------------------------------------


def test_update_request_accepts_name_only():
    s = ProductUpdateRequest(data={"name": "New Name"})
    assert s.is_valid(), s.errors


def test_update_request_accepts_description_only():
    s = ProductUpdateRequest(data={"description": "New desc"})
    assert s.is_valid(), s.errors


def test_update_request_rejects_sku_key():
    s = ProductUpdateRequest(data={"name": "N", "sku": "NEW-SKU"})
    assert not s.is_valid()
    assert "sku" in s.errors


def test_update_request_rejects_unknown_keys():
    s = ProductUpdateRequest(data={"base_unit": "g"})
    assert not s.is_valid()
    assert "base_unit" in s.errors


# ---------------------------------------------------------------------------
# Errors envelope
# ---------------------------------------------------------------------------


def test_errors_to_response_duplicate_sku_returns_409():
    exc = DuplicateSKU(detail="already exists")
    body, status = to_response(exc)
    assert status == 409
    assert body["error"] == "DuplicateSKU"
    assert body["detail"] == "already exists"


def test_errors_to_response_product_not_found_returns_404():
    body, status = to_response(ProductNotFound())
    assert status == 404
    assert body["error"] == "ProductNotFound"


def test_errors_to_response_product_has_no_batches_returns_409():
    body, status = to_response(ProductHasNoBatches())
    assert status == 409
    assert body["error"] == "ProductHasNoBatches"
