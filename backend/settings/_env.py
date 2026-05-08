"""Env-var helpers used across the settings modules.

Fail fast on required vars; provide typed access for optional ones. The
``.env`` file at the project root is auto-loaded into ``os.environ`` on
import so a fresh ``cp .env.example .env`` is enough — no shell sourcing
needed.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured


def _load_dotenv() -> None:
    """Load ``<project_root>/.env`` into ``os.environ`` (idempotent).

    Existing environment variables win — ``.env`` only fills in the gaps,
    matching standard dotenv-loader behaviour.
    """
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def env(name: str) -> str:
    """Return a required env var; raise ImproperlyConfigured when missing."""
    value = os.environ.get(name)
    if value is None:
        raise ImproperlyConfigured(f"Required environment variable '{name}' is not set.")
    return value


def env_optional(name: str, default: str) -> str:
    """Return env var or *default* when the var is absent."""
    return os.environ.get(name, default)


_UNSET: list[str] = []  # sentinel — distinct from an explicitly passed default


def env_csv(name: str, default: list[str] | None = None) -> list[str]:
    """Return a comma-split env var.

    - When the var is absent and *default* is a list, return that list.
    - When the var is absent and *default* is ``None`` (the sentinel),
      raise ``ImproperlyConfigured`` — the var is required.
    """
    raw = os.environ.get(name)
    if raw is None:
        if default is None:
            raise ImproperlyConfigured(f"Required environment variable '{name}' is not set.")
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_bool(name: str, default: bool) -> bool:
    """Parse a boolean env var.

    Truthy: ``"true"``, ``"True"``, ``"TRUE"``, ``"1"``
    Falsy:  ``"false"``, ``"False"``, ``"FALSE"``, ``"0"``
    Missing: returns *default*.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    if raw.lower() in ("true", "1"):
        return True
    if raw.lower() in ("false", "0"):
        return False
    raise ImproperlyConfigured(
        f"Environment variable '{name}' must be 'true', 'false', '1', or '0'; got {raw!r}."
    )
