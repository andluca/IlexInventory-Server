"""Shared settings for all environments.

Environment-specific overrides live in dev.py and prod.py.
"""

from __future__ import annotations

import urllib.parse

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
}
