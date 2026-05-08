"""Request/response serializers for apps.catalog.

Naming convention: *Request for input validation, *Response for output shaping.
All serializers are read via drf-spectacular for OpenAPI schema generation.
"""

from __future__ import annotations

from rest_framework import serializers

_BASE_UNIT_CHOICES = ["g", "ml", "unit"]


class ProductCreateRequest(serializers.Serializer):
    sku = serializers.CharField(max_length=255)
    name = serializers.CharField(max_length=255)
    description = serializers.CharField(default="", allow_blank=True, required=False)
    base_unit = serializers.ChoiceField(choices=_BASE_UNIT_CHOICES)


class ProductUpdateRequest(serializers.Serializer):
    """PATCH /products/{id} — only name and description are patchable.

    Any other key (including `sku`) is rejected: DRF strict-mode via
    validate() to keep the serializer layer clean of SKU-lock business logic.
    """

    name = serializers.CharField(max_length=255, required=False)
    description = serializers.CharField(allow_blank=True, required=False)

    def validate(self, attrs: dict) -> dict:
        allowed = {"name", "description"}
        unknown = set(self.initial_data.keys()) - allowed
        if unknown:
            raise serializers.ValidationError(
                {k: ["This field is not allowed in PATCH."] for k in unknown}
            )
        return attrs


class ProductResponse(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    sku = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    base_unit = serializers.CharField(read_only=True)
    archived_at = serializers.DateTimeField(allow_null=True, read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class ProductListResponse(serializers.Serializer):
    items = ProductResponse(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    limit = serializers.IntegerField(read_only=True)
    offset = serializers.IntegerField(read_only=True)


class FailedRowResponse(serializers.Serializer):
    row_index = serializers.IntegerField(read_only=True)
    error = serializers.CharField(read_only=True)
    detail = serializers.CharField(allow_null=True, required=False, read_only=True)
    fields = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()),
        allow_null=True,
        required=False,
        read_only=True,
    )


class ProductImportResponse(serializers.Serializer):
    imported = serializers.IntegerField(read_only=True)
    failed = FailedRowResponse(many=True, read_only=True)
