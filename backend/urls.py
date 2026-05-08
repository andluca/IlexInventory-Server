"""Root URL configuration.

App-level URL confs are included here; each app owns its own urls.py.
"""

from __future__ import annotations

from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from settings._env import env_bool

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.catalog.urls")),
    path("api/v1/", include("apps.procurement.urls")),
    path("api/v1/", include("apps.inventory.urls")),
    path("api/v1/", include("apps.sales.urls")),
    path("api/v1/", include("apps.financials.urls")),
    path("api/v1/openapi.json", SpectacularAPIView.as_view(), name="schema"),
]

if env_bool("OPENAPI_PUBLIC_DOCS", False):
    urlpatterns += [
        path("api/v1/docs", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    ]
