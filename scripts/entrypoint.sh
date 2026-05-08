#!/bin/sh
# Production entrypoint.
# Sequence: validate env vars → apply SQL migrations → exec gunicorn.
# Uses exec so gunicorn becomes PID 1 and receives SIGTERM cleanly.
set -euo pipefail

cd /app

# Step 1: fail fast if any required env var is missing.
python manage.py check_env

# Step 2: apply pending SQL migrations (idempotent on re-deploy).
python manage.py migrate_sql

# Step 3: hand off to gunicorn — becomes PID 1.
exec gunicorn wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --access-logfile - \
    --error-logfile -
