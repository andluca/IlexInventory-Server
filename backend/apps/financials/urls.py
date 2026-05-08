"""URL configuration for apps.financials."""

from __future__ import annotations

from django.urls import path

from apps.financials.apis import FinancialsDashboardApi, FinancialsMarginListApi

urlpatterns = [
    path("financials/dashboard", FinancialsDashboardApi.as_view(), name="financials-dashboard"),
    path("financials/margin", FinancialsMarginListApi.as_view(), name="financials-margin"),
]
