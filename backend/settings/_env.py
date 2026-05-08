"""Env-var helpers used across the settings modules.

Fail fast on required vars; provide typed access for optional ones.
"""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured


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
