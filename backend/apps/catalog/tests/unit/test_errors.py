"""Unit tests for apps.catalog.errors — error code inheritance and HTTP mapping."""

from __future__ import annotations

from apps.catalog.errors import (
    CsvParseError,
    DuplicateSKU,
    ProductHasBatches,
    ProductHasNoBatches,
    ProductNotFound,
)
from apps.core.errors import to_response


def test_duplicate_sku_code_and_status():
    exc = DuplicateSKU()
    body, status = to_response(exc)
    assert status == 409
    assert body["error"] == "DuplicateSKU"


def test_product_not_found_code_and_status():
    body, status = to_response(ProductNotFound())
    assert status == 404
    assert body["error"] == "ProductNotFound"


def test_product_has_batches_code_and_status():
    body, status = to_response(ProductHasBatches())
    assert status == 409
    assert body["error"] == "ProductHasBatches"


def test_product_has_no_batches_code_and_status():
    body, status = to_response(ProductHasNoBatches())
    assert status == 409
    assert body["error"] == "ProductHasNoBatches"


def test_csv_parse_error_code_and_status():
    body, status = to_response(CsvParseError(detail="bad csv"))
    assert status == 400
    assert body["error"] == "CsvParseError"
