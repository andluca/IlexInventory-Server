#!/usr/bin/env python
"""Django management entry point.

Run `python manage.py help` for available commands.

DJANGO_SETTINGS_MODULE defaults to `settings.dev`; set it to
`settings.prod` in production.  The `backend/` directory must be on
PYTHONPATH (pyproject.toml sets this for pytest; export PYTHONPATH=backend
when running manage.py directly).
"""

import os
import sys


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
