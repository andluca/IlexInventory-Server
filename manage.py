#!/usr/bin/env python
"""Django management entry point.

Run `python manage.py help` for available commands.

DJANGO_SETTINGS_MODULE defaults to `settings.dev`; set it to
`settings.prod` in production.  The ``backend/`` directory is added to
``sys.path`` below so commands can be invoked from the project root
without ``PYTHONPATH=backend``.
"""

import os
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parent / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Could not import Django. Make sure it is installed and available "
            "on your PYTHONPATH environment variable. Did you forget to "
            "activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
