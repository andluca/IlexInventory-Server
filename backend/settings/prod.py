"""Production settings.

All security headers enforced, CORS locked to allowed origins, cookies secure.
"""

from __future__ import annotations

from settings._env import env_csv
from settings.base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = env_csv("ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")

# Frontend on a different site (Netlify) sends cookies cross-origin to this
# backend (Railway). Allow the browser to attach the session cookie + accept
# Set-Cookie on cross-site fetches.
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# SameSite=None is required for cross-site cookie flow; pairs with Secure=True.
SESSION_COOKIE_SAMESITE = "None"
CSRF_COOKIE_SAMESITE = "None"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
