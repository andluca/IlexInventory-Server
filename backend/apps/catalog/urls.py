"""URL patterns for apps.catalog.

Mounted under /api/v1/ in the root urls.py.

Route ordering matters:
  - "products/import" must appear BEFORE "products/<uuid:product_id>" so that
    the literal "import" path is not captured as a UUID.
"""

from __future__ import annotations

from django.urls import path

from apps.catalog.apis import (
    ProductArchiveApi,
    ProductDetailApi,
    ProductImportApi,
    ProductListApi,
)

urlpatterns = [
    # Collection scope
    path("products", ProductListApi.as_view(), name="products-list"),

    # Import (literal path — must precede the UUID pattern)
    path("products/import", ProductImportApi.as_view(), name="products-import"),

    # Item scope
    path("products/<uuid:product_id>", ProductDetailApi.as_view(), name="products-detail"),
    path("products/<uuid:product_id>/archive", ProductArchiveApi.as_view(), name="products-archive"),
]
