"""Shared settings for all environments.

Environment-specific overrides live in dev.py and prod.py.
"""

from __future__ import annotations

import urllib.parse

from corsheaders.defaults import default_headers

from settings._env import env

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

SECRET_KEY = env("DJANGO_SECRET_KEY")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

# Direct psycopg URL available to service functions and the health view.
DATABASE_URL = env("DATABASE_URL")

# Parse DATABASE_URL for Django's ORM connection (used only for auth.User,
# django_session, and contenttypes — all other SQL goes through raw psycopg).
_db = urllib.parse.urlsplit(DATABASE_URL)
_db_name = _db.path.lstrip("/")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db_name,
        "USER": _db.username or "",
        "PASSWORD": _db.password or "",
        "HOST": _db.hostname or "localhost",
        "PORT": str(_db.port or 5432),
        # Tell pytest-django to use the same DB (no test_ prefix).
        # Our custom conftest already drops/recreates ilex_test for isolation.
        "TEST": {
            "NAME": _db_name,
        },
    }
}

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "corsheaders",
    "apps.core",
    "apps.catalog",
    "apps.procurement",
    "apps.inventory",
    "apps.sales",
    "apps.financials",
]

MIDDLEWARE = [
    # corsheaders must come before CommonMiddleware
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "urls"

# ---------------------------------------------------------------------------
# Templates (minimal — API-only server, no HTML views)
# ---------------------------------------------------------------------------

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "wsgi.application"
ASGI_APPLICATION = "asgi.application"

# ---------------------------------------------------------------------------
# Internationalisation
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CSRF + Session cookie policy
# ---------------------------------------------------------------------------

CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"

# ---------------------------------------------------------------------------
# CORS allow-list — extra request headers
# ---------------------------------------------------------------------------
#
# django-cors-headers' default_headers permits accept / authorization /
# content-type / user-agent / x-csrftoken / x-requested-with. The FE attaches
# `Idempotency-Key` on every SPEC §2.5 terminal mutation (commit SO, void SO,
# receive PO, recall, un-recall, manual batch, write-off, products import),
# so the browser preflight must see it in Access-Control-Allow-Headers when
# the FE and BE live on different origins (Netlify ↔ Railway). Without this
# allowlist entry the browser blocks the actual request before it reaches
# Django.

CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key")

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

LOGIN_URL = "/api/v1/auth/login"

# ---------------------------------------------------------------------------
# DRF
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.exception_handler",
    # Disable DRF's ?format= URL override so that views can use ?format=csv
    # as a plain query param for their own streaming CSV dispatch.
    # Without this, DRF intercepts ?format=csv and returns 404 (no CSV renderer).
    "URL_FORMAT_OVERRIDE": None,
}

# ---------------------------------------------------------------------------
# drf-spectacular (OpenAPI 3.1)
# ---------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    "TITLE": "Ilex Inventory API",
    "VERSION": "0.1.0",
    "DESCRIPTION": "Ilex Inventory Server — F&B CPG inventory management.",
    "SERVE_INCLUDE_SCHEMA": False,
    "OAS_VERSION": "3.1.0",
    "SECURITY": [{"cookieAuth": []}],
    "COMPONENTS": {
        "securitySchemes": {
            "cookieAuth": {
                "type": "apiKey",
                "in": "cookie",
                "name": "sessionid",
            }
        }
    },
    "POSTPROCESSING_HOOKS": [
        "drf_spectacular.hooks.postprocess_schema_enums",
        "apps.core.openapi.inject_error_response_component",
    ],
    "SORT_OPERATION_PARAMETERS": True,
    "COMPONENT_SPLIT_REQUEST": True,
    # Explicit tag list — controls sidebar ordering in docs UIs and pins the
    # tag-group set so a rename in a URL prefix doesn't churn the snapshot.
    "TAGS": [
        {"name": "auth", "description": "Authentication: signup, login, logout, and current-user."},
        {"name": "catalog", "description": "Product catalog: create, update, archive, and bulk CSV import."},
        {"name": "procurement", "description": "Purchase orders: draft, update, receive, and list."},
        {"name": "inventory", "description": "Batches and stock movements: FEFO tracking, recall, and audit log."},
        {"name": "sales", "description": "Sales orders: draft, preview FEFO allocations, commit, and void."},
        {"name": "financials", "description": "Financial reporting: margin by product and dashboard totals."},
        {"name": "meta", "description": "Operational endpoints: health probe and OpenAPI schema."},
    ],
    # Pin enum component names so that field-path renames don't churn
    # generated FE type names.  Values are the raw choice lists that
    # drf-spectacular hashes to identify the enum component.
    "ENUM_NAME_OVERRIDES": {
        "MovementKind": ["adjustment", "write_off"],
        "ProductBaseUnit": ["g", "ml", "unit"],
    },
}
