"""Unit tests for apps.inventory.errors — code attributes + HTTP mapping smoke."""

from __future__ import annotations

import pytest

from apps.core.errors import to_response
from apps.inventory.errors import (
    BatchExists,
    BatchHasMovements,
    BatchNotFound,
    InvalidMetadataField,
    InvalidMovementKind,
    ProductNotFound,
    RecallReasonRequired,
    WriteOffExceedsOnHand,
)


@pytest.mark.parametrize("exc_class, code, expected_status", [
    (BatchNotFound, "BatchNotFound", 404),
    (ProductNotFound, "ProductNotFound", 404),
    (BatchExists, "BatchExists", 409),
    (BatchHasMovements, "BatchHasMovements", 409),
    (WriteOffExceedsOnHand, "WriteOffExceedsOnHand", 422),
    (InvalidMovementKind, "InvalidMovementKind", 400),
    (InvalidMetadataField, "InvalidMetadataField", 400),
    (RecallReasonRequired, "RecallReasonRequired", 400),
])
def test_error_code_and_http_status(exc_class, code, expected_status):
    """Each error class has correct code and maps to the expected HTTP status."""
    exc = exc_class(detail="test")
    assert exc.code == code
    body, http_status = to_response(exc)
    assert http_status == expected_status
    assert body["error"] == code
