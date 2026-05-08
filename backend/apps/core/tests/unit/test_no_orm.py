"""Meta-test: ORM allowlist gate (BE-D14).

Greps backend/apps/ for any import from django.db.models or django.contrib.auth.
The ONLY allowed file is backend/apps/core/auth.py.

This test enforces D14 on every pytest run (belt-and-suspenders alongside the
CI shell script scripts/check_no_orm.sh).
"""

from __future__ import annotations

import re
from pathlib import Path


_BACKEND_DIR = Path(__file__).resolve().parents[4]
_APPS_DIR = _BACKEND_DIR / "apps"
_ALLOWLIST_FILE = _BACKEND_DIR / "apps" / "core" / "auth.py"

# Matches import lines only (starts with optional whitespace + "from django...")
_ORM_IMPORT_RE = re.compile(
    r"^\s*from django\.db\.models\b|^\s*from django\.contrib\.auth\b",
    re.MULTILINE,
)


def test_no_orm_outside_allowlist():
    """Only apps/core/auth.py may import from django.db.models or django.contrib.auth."""
    violations: list[str] = []

    for py_file in sorted(_APPS_DIR.rglob("*.py")):
        # Skip the allowlist file itself.
        if py_file.resolve() == _ALLOWLIST_FILE.resolve():
            continue
        # Skip __pycache__ directories.
        if "__pycache__" in py_file.parts:
            continue

        text = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _ORM_IMPORT_RE.match(line):
                violations.append(f"{py_file.relative_to(_BACKEND_DIR)}:{lineno}: {line.strip()}")

    assert not violations, (
        "ORM import found outside the allowlist file (apps/core/auth.py).\n"
        "Move the import into apps/core/auth.py or remove it:\n"
        + "\n".join(violations)
    )


def test_allowlist_file_has_orm_import():
    """Sanity check: apps/core/auth.py must actually contain an ORM import."""
    text = _ALLOWLIST_FILE.read_text(encoding="utf-8")
    assert _ORM_IMPORT_RE.search(text), (
        "apps/core/auth.py has no django.contrib.auth import — allowlist is stale."
    )
