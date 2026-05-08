"""Static regression guard for scripts/entrypoint.sh.

Asserts that the entrypoint file exists, is executable, and contains the
three boot steps in the correct order:
  1. python manage.py check_env
  2. python manage.py migrate_sql
  3. exec gunicorn

No subprocess execution — the CI smoke job exercises the full boot sequence.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_ENTRYPOINT = _REPO_ROOT / "scripts" / "entrypoint.sh"


def test_entrypoint_exists() -> None:
    assert _ENTRYPOINT.is_file(), f"entrypoint.sh not found at {_ENTRYPOINT}"


def test_entrypoint_is_executable() -> None:
    mode = _ENTRYPOINT.stat().st_mode
    assert mode & stat.S_IXUSR, "entrypoint.sh is not user-executable"


def test_entrypoint_boot_sequence_order() -> None:
    content = _ENTRYPOINT.read_text()

    check_env_pos = content.find("python manage.py check_env")
    migrate_pos = content.find("python manage.py migrate_sql")
    # Match the actual exec command (not comments that may mention it)
    gunicorn_match = re.search(r"^exec gunicorn", content, re.MULTILINE)

    assert check_env_pos != -1, "entrypoint.sh missing: python manage.py check_env"
    assert migrate_pos != -1, "entrypoint.sh missing: python manage.py migrate_sql"
    assert gunicorn_match is not None, "entrypoint.sh missing: exec gunicorn (at line start)"
    gunicorn_pos = gunicorn_match.start()

    assert check_env_pos < migrate_pos, "check_env must come before migrate_sql"
    assert migrate_pos < gunicorn_pos, "migrate_sql must come before exec gunicorn"


def test_entrypoint_uses_set_pipefail() -> None:
    content = _ENTRYPOINT.read_text()
    assert re.search(r"set\s+-[a-zA-Z]*e[a-zA-Z]*u[a-zA-Z]*o pipefail|set\s+-euo pipefail", content), \
        "entrypoint.sh must use 'set -euo pipefail'"
