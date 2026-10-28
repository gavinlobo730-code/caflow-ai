-- Migration 557: a person can dismiss the first-run checklist for good (ledger POST-A-002).
--
-- The dashboard's "Getting started" card (market_and_trust-16) ticks itself from the firm's own rows and stays until the firm has done its first
-- four things. A person who does not want it could only COLLAPSE it, per browser, which is a convenience and not a record. A dismissal is a
-- fact about a PERSON ("I have seen this and do not want it"), not about the firm, so it is a column on `users`: a second Partner who has
-- not dismissed it still sees it, and the same person sees nothing on any device.
--
-- WHAT THIS ADDS: `users.first_run_dismissed_at`, nullable, no default. NULL means "has not dismissed it". Written by the API only
-- (`POST /api/onboarding/first-run/dismiss`, which keeps the FIRST stamp if it is asked twice); read by `GET /api/onboarding/status`, which
-- answers `dismissed` and turns `visible` off. Nothing else reads it and it carries no meaning for the firm's data.
--
-- Idempotent and metadata only. Reversible: 555_..._rollback.sql drops the column, and every dismissed card comes back.

ALTER TABLE public.users ADD COLUMN IF NOT EXISTS first_run_dismissed_at TIMESTAMPTZ;

COMMENT ON COLUMN public.users.first_run_dismissed_at IS
  'When this person dismissed the dashboard''s first-run checklist for good (POST-A-002). NULL = has not. Written by the API only; a person-level preference, not firm data.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'users'
                      AND column_name = 'first_run_dismissed_at'
                      AND data_type = 'timestamp with time zone' AND is_nullable = 'YES' AND column_default IS NULL) THEN
        RAISE EXCEPTION 'migration 557: users.first_run_dismissed_at is not a nullable timestamptz with no default';
    END IF;
END $$;
