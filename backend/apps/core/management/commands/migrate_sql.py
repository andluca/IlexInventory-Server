"""manage.py migrate_sql — apply plain SQL migration files in order.

Reads *.sql files from backend/migrations/, sorted lexicographically.
Tracks applied files in _sql_migrations (created here, not in a migration,
to avoid the chicken-and-egg problem of needing a tracker before the first
migration can be recorded).

This command is allowed to use cursor.execute() directly because it IS the
schema-application tool — there is no service layer below it.

See ILEX-002 plan and SPEC §2.2 for context.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from django.conf import settings
from django.core.management.base import BaseCommand


_TRACKER_DDL = """
CREATE TABLE IF NOT EXISTS _sql_migrations (
    filename   TEXT        PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

# migrations/ lives at backend/migrations/, four levels up from this file:
# commands/ → management/ → core/ → apps/ → backend/ → project root
_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations"


class Command(BaseCommand):
    help = "Apply plain SQL migration files from backend/migrations/ in order."

    def handle(self, *args, **options) -> None:  # type: ignore[override]
        db_url = settings.DATABASE_URL

        try:
            conn = psycopg.connect(db_url, autocommit=False)
        except psycopg.OperationalError as exc:
            self.stderr.write(f"error: cannot connect to database: {exc}")
            sys.exit(1)

        try:
            self._run(conn)
        finally:
            conn.close()

    def _run(self, conn: psycopg.Connection) -> None:
        # Ensure tracker table exists (idempotent; runs on every invocation).
        # cursor.execute() is intentional here — this command IS the migration tool.
        with conn.cursor() as cur:
            cur.execute(_TRACKER_DDL)
        conn.commit()

        # Fetch already-applied filenames.
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM _sql_migrations")
            applied: set[str] = {row[0] for row in cur.fetchall()}

        sql_files = sorted(_MIGRATIONS_DIR.glob("*.sql"))
        pending = [f for f in sql_files if f.name not in applied]

        if not pending:
            self.stdout.write("up to date")
            return

        for migration_file in pending:
            sql = migration_file.read_text(encoding="utf-8")
            try:
                with conn.cursor() as cur:
                    # cursor.execute() is intentional — this is the migration tool.
                    cur.execute(sql)
                    cur.execute(
                        "INSERT INTO _sql_migrations (filename) VALUES (%s)",
                        (migration_file.name,),
                    )
                conn.commit()
                self.stdout.write(f"applied: {migration_file.name}")
            except psycopg.Error as exc:
                conn.rollback()
                self.stderr.write(
                    f"error applying {migration_file.name}: {exc}"
                )
                sys.exit(1)
