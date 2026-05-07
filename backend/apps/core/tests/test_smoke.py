"""Smoke test — verifies pytest discovers backend/conftest.py and Postgres connects."""


def test_db_connects(db):
    with db.cursor() as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone() == (1,)
