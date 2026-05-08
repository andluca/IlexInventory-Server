-- 0002_auth_fk.sql — retype idempotency_keys.owner_id to INT and add FK.
--
-- Rationale (ILEX-003, Notes):
--   auth_user.id is Django's default AutoField (INT).  Every owner-scoped
--   column must be the same type to keep FK constraints enforceable (D4).
--   UUIDv7 stays the PK type for *business* entities; owner references are INT.
--
-- This migration is safe pre-deploy: idempotency_keys holds no production data.
-- TRUNCATE + USING NULL is acceptable because the table is logically empty
-- during development (migrate_sql test runner truncates before each suite run).

-- Step 1: truncate so USING NULL doesn't violate the NOT NULL constraint on
-- existing rows (there are none in practice, but be explicit).
TRUNCATE idempotency_keys;

-- Step 2: change the column type from UUID to INT.
ALTER TABLE idempotency_keys
    ALTER COLUMN owner_id TYPE INT USING NULL;

-- Step 3: add FK to auth_user(id) created by `manage.py migrate auth`.
ALTER TABLE idempotency_keys
    ADD CONSTRAINT idempotency_keys_owner_id_fkey
    FOREIGN KEY (owner_id)
    REFERENCES auth_user(id)
    ON DELETE CASCADE;
