"""Tests for the check_env management command.

Runs the command in a subprocess with a complete env → exit 0 + "check-env: OK".
Missing ALLOWED_HOSTS → exit 1 with ALLOWED_HOSTS in stderr.
Missing CORS_ALLOWED_ORIGINS → exit 1 with CORS_ALLOWED_ORIGINS in stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[4]
_REPO_ROOT = _BACKEND_DIR.parent
_MANAGE = _REPO_ROOT / "manage.py"


def _base_env() -> dict[str, str]:
    """Return a complete prod env for check_env to succeed."""
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "settings.prod"
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    env["DJANGO_SECRET_KEY"] = "test-secret-key-for-ci"
    env["DATABASE_URL"] = env.get("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ilex_test")
    env["ALLOWED_HOSTS"] = "localhost"
    env["CORS_ALLOWED_ORIGINS"] = "http://localhost"
    return env


def test_check_env_success() -> None:
    env = _base_env()
    result = subprocess.run(
        [sys.executable, str(_MANAGE), "check_env"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "check-env: OK" in result.stdout


def test_check_env_missing_allowed_hosts() -> None:
    env = _base_env()
    env.pop("ALLOWED_HOSTS", None)
    result = subprocess.run(
        [sys.executable, str(_MANAGE), "check_env"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "ALLOWED_HOSTS" in result.stderr


def test_check_env_missing_cors_allowed_origins() -> None:
    env = _base_env()
    env.pop("CORS_ALLOWED_ORIGINS", None)
    result = subprocess.run(
        [sys.executable, str(_MANAGE), "check_env"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert "CORS_ALLOWED_ORIGINS" in result.stderr
