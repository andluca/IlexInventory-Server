"""Development settings.

DEBUG on, CORS open, cookies insecure — never use in production.
"""

from __future__ import annotations

from settings.base import *  # noqa: F401,F403

DEBUG = True

ALLOWED_HOSTS = ["*"]

CORS_ALLOW_ALL_ORIGINS = True

SESSION_COOKIE_SECURE = False
