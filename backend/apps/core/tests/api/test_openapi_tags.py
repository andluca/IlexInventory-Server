"""API tests: every path operation carries exactly one tag from the canonical set.
Four CSV endpoints declare the 'format' query parameter.
"""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_CANONICAL_TAGS = frozenset({"auth", "catalog", "procurement", "inventory", "sales", "financials", "meta"})
_ACCEPT = "application/vnd.oai.openapi+json"

# Endpoints that must advertise the ?format=csv query parameter.
_CSV_ENDPOINTS = [
    ("get", "/api/v1/movements"),
    ("get", "/api/v1/batches/{batch_id}/recall-report"),
    ("get", "/api/v1/financials/margin"),
    ("get", "/api/v1/financials/dashboard"),
]


@pytest.fixture
def client():
    return APIClient()


def _get_schema(client):
    resp = client.get("/api/v1/openapi.json", HTTP_ACCEPT=_ACCEPT)
    assert resp.status_code == 200
    return json.loads(resp.content)


def test_every_operation_has_exactly_one_tag(client):
    schema = _get_schema(client)
    errors = []
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            tags = operation.get("tags", [])
            if len(tags) != 1:
                errors.append(f"{method.upper()} {path}: tags={tags!r}")
    assert not errors, "Operations with != 1 tag:\n" + "\n".join(errors)


def test_all_tags_in_canonical_set(client):
    schema = _get_schema(client)
    unknown = []
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            for tag in operation.get("tags", []):
                if tag not in _CANONICAL_TAGS:
                    unknown.append(f"{method.upper()} {path}: unknown tag '{tag}'")
    assert not unknown, "Unknown tags found:\n" + "\n".join(unknown)


def test_csv_endpoints_declare_format_parameter(client):
    schema = _get_schema(client)
    paths = schema.get("paths", {})
    missing = []

    for method, path in _CSV_ENDPOINTS:
        path_item = paths.get(path, {})
        operation = path_item.get(method, {})
        params = operation.get("parameters", [])
        format_param = next((p for p in params if p.get("name") == "format"), None)
        if format_param is None:
            missing.append(f"{method.upper()} {path}: missing 'format' parameter")
            continue
        enums = format_param.get("schema", {}).get("enum", [])
        if "csv" not in enums:
            missing.append(
                f"{method.upper()} {path}: 'format' parameter missing enum=['csv'], got {enums!r}"
            )

    assert not missing, "CSV endpoints with missing/wrong format param:\n" + "\n".join(missing)
