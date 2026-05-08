"""Unit tests for apps.core.errors — DomainError hierarchy + to_response mapping."""

from __future__ import annotations

import pytest


def test_not_found_to_response():
    from apps.core.errors import NotFound, to_response

    exc = NotFound("missing", detail="Item not found")
    body, status = to_response(exc)
    assert status == 404
    assert body["error"] == "NotFound"
    assert body["detail"] == "Item not found"
    assert "fields" not in body


def test_validation_error_with_fields():
    from apps.core.errors import ValidationError, to_response

    exc = ValidationError("bad_input", fields={"sku": "required"})
    body, status = to_response(exc)
    assert status == 400
    assert body["error"] == "ValidationError"
    assert body["fields"] == {"sku": "required"}
    assert "detail" not in body


def test_conflict_to_response():
    from apps.core.errors import Conflict, to_response

    exc = Conflict("sku_locked")
    body, status = to_response(exc)
    assert status == 409
    assert body["error"] == "Conflict"


def test_unprocessable_to_response():
    from apps.core.errors import Unprocessable, to_response

    exc = Unprocessable("fefo_shortfall", detail="Not enough stock")
    body, status = to_response(exc)
    assert status == 422
    assert body["error"] == "Unprocessable"
    assert body["detail"] == "Not enough stock"


def test_non_domain_error_raises():
    """to_response must only accept DomainError; caller maps framework errors."""
    from apps.core.errors import to_response

    with pytest.raises(TypeError):
        to_response(ValueError("oops"))  # type: ignore[arg-type]


def test_domain_error_attributes():
    from apps.core.errors import DomainError

    exc = DomainError("test_code", detail="some detail", fields={"x": "y"})
    assert exc.code == "test_code"
    assert exc.detail == "some detail"
    assert exc.fields == {"x": "y"}


def test_not_found_default_code():
    from apps.core.errors import NotFound

    exc = NotFound()
    assert exc.code == "NotFound"


def test_to_response_omits_none_detail():
    from apps.core.errors import NotFound, to_response

    exc = NotFound()
    body, _ = to_response(exc)
    assert "detail" not in body


def test_to_response_omits_none_fields():
    from apps.core.errors import NotFound, to_response

    exc = NotFound(detail="gone")
    body, _ = to_response(exc)
    assert "fields" not in body
