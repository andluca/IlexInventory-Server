"""API views for apps.catalog.

Architecture: one APIView class per resource scope (collection vs item).
Each HTTP method is declared explicitly — no ViewSets.

Layer flow: API → Service | Selector → Queries → Schema.
Views never import from queries/ directly; they call services or selectors.

Owner injection: all views read owner_id from request.user.id (set by
DRF SessionAuthentication). It is never accepted from the request body.
"""

from __future__ import annotations

import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog.errors import ProductNotFound
from apps.catalog.selectors import list_products, product_by_id
from apps.catalog.serializers import (
    ProductCreateRequest,
    ProductImportResponse,
    ProductListResponse,
    ProductResponse,
    ProductUpdateRequest,
)
from apps.catalog.services import (
    archive_product,
    create_product,
    delete_product,
    import_products_csv,
    update_product,
)
from apps.core.errors import DomainError, to_response
from apps.core.idempotency import idempotent


class ProductListApi(APIView):
    """GET /products — list + search + filter.
     POST /products — create a new product.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["catalog"],
        parameters=[
            OpenApiParameter("search", str, required=False, description="ILIKE on name/sku"),
            OpenApiParameter("archived", bool, required=False, description="true=archived only, false=active only"),
            OpenApiParameter("limit", int, required=False, description="Page size (default 50)"),
            OpenApiParameter("offset", int, required=False, description="Page offset (default 0)"),
        ],
        responses={200: ProductListResponse},
        summary="List products",
    )
    def get(self, request: Request) -> Response:
        search = request.query_params.get("search") or None
        archived_raw = request.query_params.get("archived")
        archived: bool | None = None
        if archived_raw is not None:
            archived = archived_raw.lower() == "true"

        try:
            limit = int(request.query_params.get("limit", 50))
            offset = int(request.query_params.get("offset", 0))
        except ValueError:
            return Response(
                {"error": "ValidationError", "detail": "limit and offset must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = list_products(
            owner_id=request.user.id,
            search=search,
            archived=archived,
            limit=limit,
            offset=offset,
        )

        serializer = ProductListResponse(result)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["catalog"],
        request=ProductCreateRequest,
        responses={200: ProductResponse},
        summary="Create a product",
    )
    def post(self, request: Request) -> Response:
        serializer = ProductCreateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product = create_product(
                owner_id=request.user.id,
                sku=serializer.validated_data["sku"],
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description", ""),
                base_unit=serializer.validated_data["base_unit"],
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(ProductResponse(product).data, status=status.HTTP_200_OK)


class ProductDetailApi(APIView):
    """GET/PATCH/DELETE /products/{product_id}."""

    permission_classes = [IsAuthenticated]

    @extend_schema(tags=["catalog"], responses={200: ProductResponse, 404: None}, summary="Get product by ID")
    def get(self, request: Request, product_id: str) -> Response:
        product = product_by_id(owner_id=request.user.id, product_id=str(product_id))
        if product is None:
            body, http_status = to_response(ProductNotFound())
            return Response(body, status=http_status)

        return Response(ProductResponse(product).data, status=status.HTTP_200_OK)

    @extend_schema(
        tags=["catalog"],
        request=ProductUpdateRequest,
        responses={200: ProductResponse, 400: None, 404: None},
        summary="Update product",
    )
    def patch(self, request: Request, product_id: str) -> Response:
        serializer = ProductUpdateRequest(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "ValidationError", "fields": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            product = update_product(
                owner_id=request.user.id,
                product_id=uuid.UUID(str(product_id)),
                name=serializer.validated_data.get("name"),
                description=serializer.validated_data.get("description"),
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(ProductResponse(product).data, status=status.HTTP_200_OK)

    @extend_schema(tags=["catalog"], responses={204: None, 404: None, 409: None}, summary="Delete product")
    def delete(self, request: Request, product_id: str) -> Response:
        try:
            delete_product(
                owner_id=request.user.id,
                product_id=uuid.UUID(str(product_id)),
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductArchiveApi(APIView):
    """POST /products/{product_id}/archive — soft-delete."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["catalog"],
        responses={200: ProductResponse, 404: None, 409: None},
        summary="Archive product",
    )
    def post(self, request: Request, product_id: str) -> Response:
        try:
            product = archive_product(
                owner_id=request.user.id,
                product_id=uuid.UUID(str(product_id)),
            )
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(ProductResponse(product).data, status=status.HTTP_200_OK)


class ProductImportApi(APIView):
    """POST /products/import — multipart CSV upload with idempotency."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    @extend_schema(
        tags=["catalog"],
        request=None,
        responses={200: ProductImportResponse, 400: None},
        summary="Bulk-import products from CSV (multipart/form-data)",
    )
    @idempotent("catalog.products_import")
    def post(self, request: Request) -> Response:
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return Response(
                {"error": "ValidationError", "detail": "Missing 'file' in multipart body"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        csv_bytes = uploaded.read()

        try:
            report = import_products_csv(owner_id=request.user.id, csv_bytes=csv_bytes)
        except DomainError as exc:
            body, http_status = to_response(exc)
            return Response(body, status=http_status)

        return Response(ProductImportResponse(report).data, status=status.HTTP_200_OK)
