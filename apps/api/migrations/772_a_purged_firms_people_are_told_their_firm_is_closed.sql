-- Migration 772 (POST-A-499): the people of a permanently deleted firm are told their firm is closed.
--
-- A platform administrator's purge (`platform_purge_firm`, migration 141) deletes the firm's `users` rows and leaves the sign-in accounts
-- alone, on purpose: no sign-in is ever deleted, and the administrator's own access survives purging their own firm. So a person who was
-- signed in to the purged firm held a session whose account had no member row: the API answered 403 "User not found in firm", the browser
-- found no practice and opened the new-practice wizard, and nobody was signed out or told why. Suspend and soft delete end the sessions by
-- a stamp on the member's row (`sessions_revoked_at`); a stamp on a row that is about to be deleted ends nothing.
--
-- This table is the stamp that survives the row. The API writes one row per member of the firm BEFORE it purges (and refuses the purge
-- if the rows could not be written), and `get_current_user` reads it only on the path where a signed-in account has no member row: a
-- token whose session began before `closed_at` is answered 403 "Firm unavailable", which the browser already treats as "the firm is
-- closed" (it signs the person out and says so in words that blame nobody). A sign-in that began AFTER `closed_at` is not refused: that
-- person may start a new practice with the same login, as they could before.
--
-- Holds an internal sign-in id and an instant, and no name or address. Written by the API only; the signed-in database roles hold
-- nothing on it. Retention follows the sign-in account, which this product never deletes.
--
-- Additive and idempotent; the rollback drops the table.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.closed_account_markers (
  -- The sign-in service's account id of a person whose firm was purged. No foreign key: the member row it described is gone, and the
  -- sign-in account lives in another schema.
  auth_user_id UUID        PRIMARY KEY,
  -- A session that began before this instant belonged to the closed firm.
  closed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  closed_how   TEXT        NOT NULL,
  CONSTRAINT closed_account_markers_how_is_known CHECK (closed_how IN ('firm_purged'))
);

COMMENT ON TABLE public.closed_account_markers IS
  'POST-A-499, migration 772. One row per person whose firm was permanently deleted: the instant it was, so a session that began before it is told the '
  'firm is closed instead of being sent to the new-practice wizard. Read by core/auth.get_current_user only when a signed-in account has no member '
  'row; written by routers/platform.purge_firm before the purge. The signed-in database roles hold nothing on it.';

ALTER TABLE public.closed_account_markers ENABLE ROW LEVEL SECURITY;

-- No policy: nobody but the privileged API client reads or writes it.
REVOKE ALL ON public.closed_account_markers FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.closed_account_markers TO service_role;

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.closed_account_markers', verb) THEN
                RAISE EXCEPTION 'migration 772: % still holds % on public.closed_account_markers', r, verb;
            END IF;
        END LOOP;
    END LOOP;
    IF NOT has_table_privilege('service_role', 'public.closed_account_markers', 'INSERT') THEN
        RAISE EXCEPTION 'migration 772: service_role cannot write public.closed_account_markers';
    END IF;
    IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.closed_account_markers'::regclass) THEN
        RAISE EXCEPTION 'migration 772: row security is not on for public.closed_account_markers';
    END IF;
END $$;

COMMIT;
