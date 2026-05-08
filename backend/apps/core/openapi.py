"""OpenAPI helpers: postprocessing hooks and shared parameter constants.

Used by SPECTACULAR_SETTINGS["POSTPROCESSING_HOOKS"] in settings/base.py.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter

# ---------------------------------------------------------------------------
# Shared query parameter: ?format=csv
# ---------------------------------------------------------------------------

# Reusable OpenAPI parameter for the four endpoints that support CSV streaming:
#   GET /movements, GET /batches/{id}/recall-report,
#   GET /financials/margin, GET /financials/dashboard
CSV_FORMAT_PARAMETER = OpenApiParameter(
    name="format",
    type=str,
    enum=["csv"],
    required=False,
    description=(
        "Set to 'csv' to receive a streaming CSV export instead of the "
        "default JSON response. The response Content-Type will be "
        "text/csv; charset=utf-8 with a Content-Disposition header."
    ),
)

# ---------------------------------------------------------------------------
# ErrorResponse component schema
# ---------------------------------------------------------------------------

_ERROR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["error"],
    "properties": {
        "error": {
            "type": "string",
            "description": "Machine-readable error code (e.g. 'ValidationError', 'NotFound').",
        },
        "detail": {
            "type": "string",
            "description": "Human-readable explanation (optional).",
        },
        "fields": {
            "type": "object",
            "description": "Per-field validation errors keyed by field name (optional).",
            "additionalProperties": True,
        },
    },
}

_ERROR_STATUSES = frozenset({"400", "401", "403", "404", "422"})

_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}


# ---------------------------------------------------------------------------
# Postprocessing hook
# ---------------------------------------------------------------------------


def inject_error_response_component(
    result: dict[str, Any],
    generator: Any,
    request: Any,
    public: Any,
) -> dict[str, Any]:
    """drf-spectacular postprocessing hook.

    Ensures ``components.schemas.ErrorResponse`` exists in the generated schema
    and replaces every 400/401/403/404/422 response body with a ``$ref`` to it.

    Idempotent: running it twice on the same schema produces identical output.
    """
    # Ensure the component exists.
    components = result.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas["ErrorResponse"] = _ERROR_RESPONSE_SCHEMA

    # Rewrite 4xx responses in every operation across all paths.
    for _path, path_item in result.get("paths", {}).items():
        for _method, operation in path_item.items():
            if not isinstance(operation, dict):
                continue
            for status_code, response in operation.get("responses", {}).items():
                if str(status_code) not in _ERROR_STATUSES:
                    continue
                if not isinstance(response, dict):
                    continue
                content = response.get("content", {})
                json_content = content.get("application/json", {})
                if not json_content:
                    continue
                # Replace whatever schema is there with the $ref.
                json_content["schema"] = _ERROR_REF

    return result
