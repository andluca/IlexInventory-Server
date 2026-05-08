"""Unit tests for the inject_error_response_component postprocessing hook.

Behavioral: given a fake schema dict, the hook rewrites free-form 4xx responses
to reference the ErrorResponse component and ensures the component exists.
"""

from apps.core.openapi import inject_error_response_component


def _fake_schema(response_status: str, response_content: dict) -> dict:
    """Build a minimal OpenAPI schema dict with one operation."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "Test", "version": "0.0.1"},
        "paths": {
            "/test": {
                "get": {
                    "operationId": "test_get",
                    "responses": {
                        "200": {"description": "OK"},
                        response_status: {
                            "description": "Error",
                            "content": {"application/json": {"schema": response_content}},
                        },
                    },
                }
            }
        },
        "components": {"schemas": {}},
    }


_FREE_FORM = {"type": "object"}


def test_hook_injects_error_response_component_for_400():
    schema = _fake_schema("400", _FREE_FORM)
    result = inject_error_response_component(schema, None, None, None)

    assert "ErrorResponse" in result["components"]["schemas"]
    err_schema = result["components"]["schemas"]["ErrorResponse"]
    assert "error" in err_schema["properties"]


def test_hook_replaces_400_with_ref():
    schema = _fake_schema("400", _FREE_FORM)
    result = inject_error_response_component(schema, None, None, None)

    response_400 = result["paths"]["/test"]["get"]["responses"]["400"]
    schema_node = response_400["content"]["application/json"]["schema"]
    assert schema_node == {"$ref": "#/components/schemas/ErrorResponse"}


def test_hook_replaces_404_with_ref():
    schema = _fake_schema("404", _FREE_FORM)
    result = inject_error_response_component(schema, None, None, None)

    response_404 = result["paths"]["/test"]["get"]["responses"]["404"]
    schema_node = response_404["content"]["application/json"]["schema"]
    assert schema_node == {"$ref": "#/components/schemas/ErrorResponse"}


def test_hook_does_not_replace_200():
    schema = _fake_schema("400", _FREE_FORM)
    # Also has a 200 response with a real schema
    schema["paths"]["/test"]["get"]["responses"]["200"] = {
        "description": "OK",
        "content": {"application/json": {"schema": {"type": "object", "properties": {"id": {"type": "string"}}}}},
    }
    result = inject_error_response_component(schema, None, None, None)

    response_200 = result["paths"]["/test"]["get"]["responses"]["200"]
    schema_node = response_200["content"]["application/json"]["schema"]
    # 200 is untouched
    assert "$ref" not in schema_node


def test_hook_is_idempotent():
    schema = _fake_schema("400", _FREE_FORM)
    once = inject_error_response_component(schema, None, None, None)
    twice = inject_error_response_component(once, None, None, None)
    assert once == twice


def test_hook_covers_all_4xx_error_statuses():
    """Hook rewrites 400, 401, 403, 404, 422 responses."""
    for http_status in ("400", "401", "403", "404", "422"):
        schema = _fake_schema(http_status, _FREE_FORM)
        result = inject_error_response_component(schema, None, None, None)
        resp = result["paths"]["/test"]["get"]["responses"][http_status]
        schema_node = resp["content"]["application/json"]["schema"]
        assert schema_node == {"$ref": "#/components/schemas/ErrorResponse"}, (
            f"Status {http_status} not rewritten"
        )
