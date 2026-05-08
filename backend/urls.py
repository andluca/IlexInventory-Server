"""Root URL configuration.

App-level URL confs are included here; each app owns its own urls.py.
"""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/openapi.json", SpectacularAPIView.as_view(), name="schema"),
]
