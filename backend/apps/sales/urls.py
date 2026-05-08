"""URL configuration for apps.sales.

Paths wired into backend/urls.py under the api/v1/ prefix.
"""

from __future__ import annotations

from django.urls import path

from apps.sales.apis import (
    SalesOrderCommitApi,
    SalesOrderDetailApi,
    SalesOrderListApi,
    SalesOrderPreviewApi,
    SalesOrderVoidApi,
)

urlpatterns = [
    path("sales-orders", SalesOrderListApi.as_view(), name="sales-order-list"),
    path("sales-orders/<str:so_id>", SalesOrderDetailApi.as_view(), name="sales-order-detail"),
    path("sales-orders/<str:so_id>/preview", SalesOrderPreviewApi.as_view(), name="sales-order-preview"),
    path("sales-orders/<str:so_id>/commit", SalesOrderCommitApi.as_view(), name="sales-order-commit"),
    path("sales-orders/<str:so_id>/void", SalesOrderVoidApi.as_view(), name="sales-order-void"),
]
