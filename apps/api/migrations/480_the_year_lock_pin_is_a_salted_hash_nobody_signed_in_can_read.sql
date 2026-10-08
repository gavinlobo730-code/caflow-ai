-- ============================================================================
-- 480 — the year-lock PIN is a salted hash in a table nobody signed in can
--       read (POST-A-004)
--
-- WHAT WAS WRONG
--     services/year_lock_service.py kept the firm's lock PIN as typed, in
--     firms.lock_pin (migrations 021, 033), and compared it with `!=`.
--     public.firms is readable by EVERY member of the firm over PostgREST
--     (migration 033: GRANT SELECT, UPDATE ... TO authenticated; policy
--     firms_own is FOR ALL on id = get_my_firm_id(); the role-by-table matrix
--     shows a Manager, an Executive and a Reviewer all SELECT the row), so
--     `select lock_pin from firms` from a browser console returned the PIN that
--     authorises locking and unlocking a financial year, even though the API
--     never sent it. The same grant let a Partner's own session set the column
--     to NULL, which is "no PIN set", and switch the control off.
--
-- WHAT THIS DOES, AND WHY THAT SHAPE
--     1. public.firm_lock_pins(firm_id PRIMARY KEY, pin_hash, created_at,
--        updated_at). Row-level security is ON with NO policy and `anon` and
--        `authenticated` hold no privilege at all; only service_role does, which
--        is the API's own client (migration 471's scheduler_claims is the
--        precedent). The ACCESS is the fix. A salted hash of a four-character PIN
--        is brute-forced in seconds by anyone who can read it, so hashing a
--        column that stayed browser-readable would have fixed almost nothing, and
--        a column-level REVOKE would have done nothing at all: PostgreSQL ignores
--        REVOKE SELECT (col) while a table-level SELECT is granted.
--     2. Every PIN that exists is carried over as `sha256$<salt>$<hex>`: one
--        round of SHA-256 over salt || pin, made in SQL because core Postgres has
--        sha256() and gen_random_uuid() and no PBKDF2 (pgcrypto is an extension
--        that lives in another schema on Supabase and is not assumed). The API
--        verifies that form and REWRITES it as pbkdf2_sha256 the first time the
--        PIN is used (domain/firm/lock_pin.py), so the weak form lasts until the
--        PIN is next typed, and while it lasts it sits behind a wall the plaintext
--        never had. The Python and SQL forms are pinned to each other by
--        tests/test_480_the_year_lock_pin_pg.py, which verifies a hash MADE BY
--        THIS FILE with the Python verifier, a non-ASCII PIN included.
--     3. firms.lock_pin is set to NULL for every firm, and a CHECK
--        (firms_lock_pin_retired: lock_pin IS NULL) keeps it NULL, so an old
--        deploy, a PostgREST write or a hand-run UPDATE can never put a PIN back
--        in the readable place; it fails loudly instead. The COLUMN is not
--        dropped: a DROP moves both sides of the production-fixture comparison
--        at once and needs the refresh in docs/schema-drift.md (migrations 371
--        and 399 took the same decision).
--
-- WHAT IT DOES TO EXISTING ROWS
--     * public.firms: only a row whose lock_pin IS NOT NULL changes, and the
--       change is lock_pin -> NULL (the BEFORE UPDATE updated_at trigger moves
--       updated_at on those rows, nothing else). The year-lock trigger (136)
--       ignores it because locked_financial_years is untouched, and the audit
--       trigger (111) skips it because a migration has no auth.uid(). Run
--       `select count(*) from firms where lock_pin is not null` first to know
--       how many that is; before this change it is the number of firms that ever
--       set a PIN.
--     * public.firm_lock_pins: one row for each of those firms whose PIN was not
--       empty. A firm whose lock_pin was NULL or '' (no PIN) gets no row, and
--       reads as "no PIN set", exactly as before.
--     * No other table is touched. No locked_financial_years value changes, so
--       no year opens or closes.
--
-- WHAT IT CANNOT UNDO
--     audit_log (migration 111's audit_capture_firm) wrote to_jsonb(OLD) and
--     to_jsonb(NEW) of the WHOLE firms row for any firms write made under a
--     user's JWT, so a plaintext PIN may already sit in immutable audit_log rows
--     (readable only by a Partner of that firm). They cannot be scrubbed (the
--     table is append-only by trigger) and this migration does not try. A PIN
--     that has ever been readable should be treated as known, and changed.
--
-- ORDER OF DEPLOY
--     The migration and the API deploy race on a push to main. New API before
--     this migration: year-lock requests fail until firm_lock_pins exists
--     (closed, and Partner-only). This migration before the new API: the OLD
--     code reads firms.lock_pin, finds NULL and reads "no PIN set", so for a few
--     minutes a firm that HAD a PIN is treated as having none (an unlock with no
--     PIN would succeed), and a Partner who tries to set a new PIN gets an error
--     from the CHECK rather than a stored PIN. The window is Partner-only and
--     short. Production held 0 firms with a PIN when this was written (read-only
--     query, 8 October 2026), so nothing is exposed there; a database that holds
--     PINs should be migrated and deployed together.
--
-- Idempotent: CREATE ... IF NOT EXISTS, INSERT ... ON CONFLICT DO NOTHING, an
-- UPDATE that matches nothing the second time, and the constraint guarded by a
-- catalogue lookup. Rollback: 480_..._rollback.sql (it cannot restore the PINs).
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.firm_lock_pins (
    firm_id    uuid        PRIMARY KEY REFERENCES public.firms(id) ON DELETE CASCADE,
    pin_hash   text        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT firm_lock_pins_scheme CHECK (pin_hash ~ '^(pbkdf2_sha256|sha256)[$]')
);

COMMENT ON TABLE public.firm_lock_pins IS
    'The firm''s year-lock PIN, as a salted hash (pbkdf2_sha256$iterations$salt$hash, or sha256$salt$hash from '
    'migration 480''s backfill until the PIN is next used). Service-role only: RLS on, no policy, no privilege '
    'for anon or authenticated, because the PIN it stands for authorises locking and unlocking a financial year. '
    'Written and read only by services/year_lock_service.py. Migration 480.';
COMMENT ON COLUMN public.firm_lock_pins.pin_hash IS
    'Never the PIN. domain/firm/lock_pin.py writes and verifies it.';

ALTER TABLE public.firm_lock_pins ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.firm_lock_pins FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.firm_lock_pins TO service_role;

-- Carry every existing PIN over. A fresh salt per firm: the salt is a volatile
-- expression in a subquery's target list, which Postgres evaluates once per row
-- and never pulls up, so the two places the outer query reads it see ONE value
-- (a LATERAL subquery that mentions no outer column is evaluated once for the
-- whole query, and gave every firm the same salt; the pg test caught exactly
-- that). The digest is over the salt's bytes followed by the PIN's UTF-8 bytes,
-- which is what hashlib.sha256(salt + pin) computes in domain/firm/lock_pin.py.
INSERT INTO public.firm_lock_pins (firm_id, pin_hash)
SELECT s.firm_id,
       'sha256$' || s.salt || '$'
           || encode(sha256(convert_to(s.salt || s.lock_pin, 'UTF8')), 'hex')
  FROM (SELECT f.id AS firm_id,
               f.lock_pin,
               replace(gen_random_uuid()::text, '-', '') AS salt
          FROM public.firms f
         WHERE f.lock_pin IS NOT NULL
           AND f.lock_pin <> '') s
ON CONFLICT (firm_id) DO NOTHING;

-- Empty the readable place. NULL and '' both mean "no PIN set" to every reader
-- there ever was, so both go, and the CHECK below needs every row to be NULL.
UPDATE public.firms SET lock_pin = NULL WHERE lock_pin IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'firms_lock_pin_retired'
           AND conrelid = 'public.firms'::regclass
    ) THEN
        ALTER TABLE public.firms
            ADD CONSTRAINT firms_lock_pin_retired CHECK (lock_pin IS NULL);
    END IF;
END
$$;

COMMENT ON COLUMN public.firms.lock_pin IS
    'RETIRED by migration 480 and always NULL (firms_lock_pin_retired). The year-lock PIN is a salted hash in '
    'public.firm_lock_pins, which no signed-in session can read. The column is kept, not dropped, so the '
    'production-fixture comparison does not move.';

COMMIT;
