#!/bin/sh
# Production entrypoint.
# Sequence: validate env vars → apply Django migrations → apply SQL migrations → exec gunicorn.
# Uses exec so gunicorn becomes PID 1 and receives SIGTERM cleanly.
set -euo pipefail

cd /app

# Step 1: fail fast if any required env var is missing.
python manage.py check_env

# Step 2: apply Django ORM migrations (auth_user, django_session, contenttypes).
# Required before migrate_sql since 0002_auth_fk.sql references auth_user.
# Idempotent — Django skips already-applied migrations.
python manage.py migrate --noinput

# Step 3: apply pending SQL migrations (idempotent on re-deploy).
python manage.py migrate_sql

# Step 4: hand off to gunicorn — becomes PID 1.
# wsgi.py lives in backend/, but manage.py is at /app — gunicorn doesn't go
# through manage.py, so add backend/ to PYTHONPATH explicitly.
exec gunicorn wsgi:application \
    --pythonpath /app/backend \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers "${GUNICORN_WORKERS:-3}" \
    --access-logfile - \
    --error-logfile -
