"""Production settings.

All security headers enforced, CORS locked to allowed origins, cookies secure.
"""

from __future__ import annotations

from settings._env import env_csv
from settings.base import *  # noqa: F401,F403

DEBUG = False

ALLOWED_HOSTS = env_csv("ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
