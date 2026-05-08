"""URL configuration for apps.inventory.

Paths wired into backend/urls.py under the api/v1/ prefix.
"""

from __future__ import annotations

from django.urls import path

from apps.inventory.apis import (
    BatchDetailApi,
    BatchListApi,
    BatchMovementsApi,
    BatchRecallApi,
    BatchRecallReportApi,
    BatchUnRecallApi,
    MovementsAuditApi,
)

urlpatterns = [
    path("batches", BatchListApi.as_view(), name="batch-list"),
    path("batches/<str:batch_id>", BatchDetailApi.as_view(), name="batch-detail"),
    path("batches/<str:batch_id>/movements", BatchMovementsApi.as_view(), name="batch-movements"),
    path("batches/<str:batch_id>/recall", BatchRecallApi.as_view(), name="batch-recall"),
    path("batches/<str:batch_id>/un-recall", BatchUnRecallApi.as_view(), name="batch-un-recall"),
    path("batches/<str:batch_id>/recall-report", BatchRecallReportApi.as_view(), name="batch-recall-report"),
    path("movements", MovementsAuditApi.as_view(), name="movements-audit"),
]
