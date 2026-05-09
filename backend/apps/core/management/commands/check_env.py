"""manage.py check_env — fail-fast validation of required production env vars.

Imports settings.prod at module load (which calls env_csv for ALLOWED_HOSTS and
CORS_ALLOWED_ORIGINS); catches ImproperlyConfigured and writes a clear message
to stderr with exit 1. Called by the entrypoint script before migrate_sql runs.

Required vars: DJANGO_SECRET_KEY, DATABASE_URL, ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS.
Optional vars with defaults: PORT, OPENAPI_PUBLIC_DOCS, SESSION_COOKIE_SECURE, CSRF_COOKIE_SECURE.
"""

from __future__ import annotations

import sys

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Validate required production environment variables; exit 1 on the first missing one."

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        try:
            # break cycle: settings.prod's module body raises ImproperlyConfigured
            # on missing required env vars at import time. Hoisting this to the
            # module top would crash the management subsystem before it can run
            # any *other* command (e.g. `migrate_sql`) on a misconfigured env.
            # The import is intentionally side-effectful and gated on `handle`.
            import settings.prod  # noqa: F401
        except ImproperlyConfigured as exc:
            self.stderr.write(f"check-env: FATAL — {exc}")
            sys.exit(1)

        self.stdout.write("check-env: OK")
