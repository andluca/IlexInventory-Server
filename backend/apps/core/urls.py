"""URL patterns for apps.core.

Routes added here are mounted under /api/v1/ in the root urls.py.
"""

from __future__ import annotations

from django.urls import path

from apps.core.apis import HealthView

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
]
