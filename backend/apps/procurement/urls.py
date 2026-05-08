"""URL routing for apps.procurement."""

from __future__ import annotations

from django.urls import path

from apps.procurement.apis import (
    PurchaseOrderDetailApi,
    PurchaseOrderListApi,
    PurchaseOrderReceiveApi,
)

urlpatterns = [
    path("purchase-orders", PurchaseOrderListApi.as_view(), name="po-list"),
    path("purchase-orders/<uuid:po_id>", PurchaseOrderDetailApi.as_view(), name="po-detail"),
    path(
        "purchase-orders/<uuid:po_id>/receive",
        PurchaseOrderReceiveApi.as_view(),
        name="po-receive",
    ),
]
