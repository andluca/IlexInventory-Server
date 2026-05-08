"""Tests for the OPENAPI_PUBLIC_DOCS Swagger UI toggle.

When OPENAPI_PUBLIC_DOCS is false (the prod default), GET /api/v1/docs
returns 404. When it is true, GET /api/v1/docs returns 200 and the response
body contains the Swagger UI bundle marker.
"""

from __future__ import annotations

import importlib
import sys

import django.urls
import pytest
from django.test import Client


def _reload_urls(monkeypatch: pytest.MonkeyPatch, public_docs: bool) -> None:
    """Reload urls.py with OPENAPI_PUBLIC_DOCS toggled, then reset Django's URL resolver."""
    monkeypatch.setenv("OPENAPI_PUBLIC_DOCS", "true" if public_docs else "false")
    # Force reimport of the urls module so the module-level env_bool() re-reads the var.
    if "urls" in sys.modules:
        del sys.modules["urls"]
    importlib.import_module("urls")
    django.urls.clear_url_caches()
    django.urls.set_urlconf(None)


@pytest.fixture(autouse=True)
def _restore_urls():
    """Always restore original urlconf after each test in this module."""
    yield
    django.urls.clear_url_caches()
    django.urls.set_urlconf(None)
    if "urls" in sys.modules:
        del sys.modules["urls"]
    importlib.import_module("urls")


def test_docs_404_when_toggle_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_urls(monkeypatch, public_docs=False)
    client = Client()
    response = client.get("/api/v1/docs")
    assert response.status_code == 404


def test_docs_200_when_toggle_on(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_urls(monkeypatch, public_docs=True)
    client = Client()
    response = client.get("/api/v1/docs")
    assert response.status_code == 200
    content = response.content.decode()
    assert "swagger-ui" in content.lower()
