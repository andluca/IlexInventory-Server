-- 0001_init.sql — substrate every other migration sits on.
--
-- Ships: pgcrypto extension, SQL uuidv7() companion function,
--        and the idempotency_keys cross-cutting table.
--
-- NOTE: _sql_migrations is NOT created here — the migrate_sql runner
--       creates it programmatically before reading any migration file
--       (chicken-and-egg: the tracker must exist before 0001 can run).
--
-- NOTE: idempotency_keys.owner_id has no FK to auth_user yet.
--       auth_user is created by `manage.py migrate auth` in ILEX-003.
--       ILEX-003's migration adds:
--         ALTER TABLE idempotency_keys
--           ADD CONSTRAINT idempotency_keys_owner_id_fkey
--           FOREIGN KEY (owner_id) REFERENCES auth_user(id);

-- ---------------------------------------------------------------------------
-- Extension
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- UUIDv7 SQL function — companion to apps/core/ids.py
--
-- Generates a v7 UUID per RFC 9562 §5.7:
--   48-bit ms timestamp | 4-bit version (0x7) | 12 random bits
--   | 2-bit variant (0b10) | 62 random bits
--
-- Uses clock_timestamp() (not now()) so multiple calls within one
-- transaction produce strictly increasing timestamps.
-- Uses gen_random_bytes() from pgcrypto for the random bits.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION uuidv7() RETURNS uuid
LANGUAGE plpgsql
AS $$
DECLARE
    ms        BIGINT;
    rand_a    BIGINT;
    rand_b    BIGINT;
    rand_bytes BYTEA;
    hi        BIGINT;
    lo        BIGINT;
    hex_str   TEXT;
BEGIN
    -- 48-bit millisecond Unix timestamp
    ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;

    -- 10 random bytes = 80 random bits (we use 12 + 62 = 74)
    rand_bytes := gen_random_bytes(10);

    -- rand_a: top 12 random bits (bits 79-68 in the UUID layout are version+rand_a)
    rand_a := (get_byte(rand_bytes, 0)::BIGINT << 4)
            | (get_byte(rand_bytes, 1)::BIGINT >> 4);
    rand_a := rand_a & x'FFF'::BIGINT;

    -- rand_b: 62 random bits
    rand_b := (get_byte(rand_bytes, 2)::BIGINT << 54)
            | (get_byte(rand_bytes, 3)::BIGINT << 46)
            | (get_byte(rand_bytes, 4)::BIGINT << 38)
            | (get_byte(rand_bytes, 5)::BIGINT << 30)
            | (get_byte(rand_bytes, 6)::BIGINT << 22)
            | (get_byte(rand_bytes, 7)::BIGINT << 14)
            | (get_byte(rand_bytes, 8)::BIGINT << 6)
            | (get_byte(rand_bytes, 9)::BIGINT >> 2);
    rand_b := rand_b & x'3FFFFFFFFFFFFFFF'::BIGINT;

    -- Assemble: [48-bit ms][4-bit version=7][12-bit rand_a][2-bit variant=0b10][62-bit rand_b]
    hi := (ms << 16) | (x'7'::BIGINT << 12) | rand_a;
    lo := (x'8000000000000000'::BIGINT) | rand_b;

    hex_str := lpad(to_hex(hi), 16, '0') || lpad(to_hex(lo), 16, '0');

    RETURN (
        substring(hex_str, 1, 8)  || '-' ||
        substring(hex_str, 9, 4)  || '-' ||
        substring(hex_str, 13, 4) || '-' ||
        substring(hex_str, 17, 4) || '-' ||
        substring(hex_str, 21, 12)
    )::uuid;
END;
$$;

-- ---------------------------------------------------------------------------
-- idempotency_keys — cross-cutting cache for mutating terminal endpoints.
-- See SPEC §2.6 for the endpoint table.
--
-- owner_id: bare UUID (no FK yet — auth_user lands in ILEX-003).
-- TTL cleanup deferred to a later issue.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS idempotency_keys (
    owner_id        UUID        NOT NULL,
    key             TEXT        NOT NULL,
    endpoint        TEXT        NOT NULL,
    response_status INT         NOT NULL,
    response_body   JSONB       NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (owner_id, key, endpoint)
);
