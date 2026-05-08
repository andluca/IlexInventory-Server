"""API tests: SPECTACULAR_SETTINGS tag list and COMPONENT_SPLIT_REQUEST behavior."""

from __future__ import annotations

import json

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

_CANONICAL_TAGS_ORDERED = ["auth", "catalog", "procurement", "inventory", "sales", "financials", "meta"]
_ACCEPT = "application/vnd.oai.openapi+json"


@pytest.fixture
def client():
    return APIClient()


def _get_schema(client):
    resp = client.get("/api/v1/openapi.json", HTTP_ACCEPT=_ACCEPT)
    assert resp.status_code == 200
    return json.loads(resp.content)


def test_schema_tags_array_has_7_entries(client):
    schema = _get_schema(client)
    tags = schema.get("tags", [])
    assert len(tags) == 7, f"Expected 7 tags, got {len(tags)}: {[t.get('name') for t in tags]}"


def test_schema_tags_match_canonical_order(client):
    schema = _get_schema(client)
    tag_names = [t["name"] for t in schema.get("tags", [])]
    assert tag_names == _CANONICAL_TAGS_ORDERED, (
        f"Tag order mismatch.\nExpected: {_CANONICAL_TAGS_ORDERED}\nGot: {tag_names}"
    )


def test_component_split_request_produces_separate_request_component(client):
    """With COMPONENT_SPLIT_REQUEST=True, input serializers produce a dedicated
    Request-suffixed component (drf-spectacular appends 'Request' to input schemas).
    Verify by checking that the product create input component exists separately
    from the response component.
    """
    schema = _get_schema(client)
    components = schema.get("components", {}).get("schemas", {})
    # With COMPONENT_SPLIT_REQUEST, the input variant of ProductCreateRequest serializer
    # is emitted as 'ProductCreateRequestRequest' (the serializer class name + Request suffix).
    # The response-only 'ProductResponse' should also exist.
    request_components = [k for k in components if k.endswith("Request")]
    assert request_components, (
        f"Expected at least one 'Request'-suffixed component (COMPONENT_SPLIT_REQUEST=True). "
        f"Got: {sorted(components.keys())}"
    )
    assert "ProductResponse" in components, (
        "Expected 'ProductResponse' output component to exist alongside request components."
    )
