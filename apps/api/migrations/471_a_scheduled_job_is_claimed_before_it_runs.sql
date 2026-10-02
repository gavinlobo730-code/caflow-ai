-- ============================================================================
-- 471 — a scheduled job is CLAIMED before it runs, so two instances cannot both
--       run it (ops-14)
--
-- WHY
--     The daily sweep's only guard against running a job twice was a SELECT:
--     `_already_ran_today` read `scheduler_runs` for a success and, finding none,
--     ran the job and wrote its row afterwards. Between the read and the write
--     there is a window as wide as the job, and `scheduler_runs` has no unique
--     key to refuse the second writer (migration 066 gave it one non-unique
--     index). The per-minute workflow tick was worse: it listed every due
--     schedule, fired each, and only then advanced `next_run_at`, and its own
--     docstring said "NOT safe for multi-worker deployments". With one instance
--     that is a latent fact. The moment a second instance exists — a rolling
--     deploy overlapping the old one, or a standby — both run every job and
--     both fire every schedule, which for this product means every reminder and
--     every recurring invoice twice.
--
-- WHAT THIS IS
--     A claim row per (job, IST day, firm, claim key), taken by ONE statement:
--     `INSERT ... ON CONFLICT DO UPDATE ... WHERE <the row may be taken over>`.
--     Postgres locks the conflicting row, so a second claimant waits for the
--     first to commit and then evaluates the WHERE against the row as the first
--     left it. Exactly one of them gets a row back from RETURNING. It is a
--     function and not a client-side compare-and-set so the atomicity lives in
--     the database where a real-Postgres test can race two sessions at it
--     (tests/test_471_a_scheduled_job_is_claimed_before_it_runs_pg.py), and so
--     the lease uses the DATABASE's clock — two instances' clocks disagree, the
--     database's does not.
--
--     An advisory lock was considered and rejected: the API reaches Postgres
--     through PostgREST, where every call is its own transaction on whichever
--     pooled connection answers, so a session lock cannot be held across the
--     minutes a job runs, and a transaction lock is released when the call
--     returns. A row with an expiry is the only lock this transport can hold.
--
-- WHEN A CLAIM CAN BE TAKEN
--     * nobody has one                                       -> inserted;
--     * it is `failed`                                       -> retaken. A failure
--       today is retried by the next trigger, exactly as before this change; the
--       optional cooldown (p_retry_failed_after_seconds) is for a caller that
--       does not want a tight loop of retries;
--     * it is `running` and its lease has EXPIRED            -> taken over. This is
--       the crash path: a dead instance cannot block the day for longer than its
--       lease. The API's lease is 10 minutes and a live holder renews it every
--       3 (jobs/claims.py), so a slow job is not stolen from and a dead one is
--       released within ten minutes;
--     * it is `success` and the caller passed p_force       -> retaken (a Partner
--       pressing "run again"). Without force a success is final for the day.
--     A `running` claim with a live lease is never taken, force or not.
--
-- WHAT IT DOES NOT REPLACE
--     `scheduler_runs` stays the human-readable history (status page, last run
--     per job, the catch-up's "what is still pending"). A claim is the LOCK; the
--     run row is the RECORD. The scheduler asks the record first, so a day's
--     success written before this migration still counts.
--
-- THE TABLE IS SERVICE-ROLE ONLY: RLS is on with NO policy and `anon` and
-- `authenticated` hold no privilege at all. Nothing in the browser has a reason
-- to read it, and a write from a signed-in session could forge a claim and stop
-- a firm's daily jobs for a day — a denial of service on that firm's reminders
-- needing nothing but a JWT. The user-visible record is `scheduler_runs`.
--
-- Additive and idempotent: CREATE ... IF NOT EXISTS, CREATE OR REPLACE for the
-- four new functions, no data rewritten, no policy removed.
-- ============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.scheduler_claims (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name     text        NOT NULL,
    -- The IST day the claim is FOR. A per-minute workflow tick uses the IST day
    -- of the occurrence's own due time, so the key is stable across midnight.
    run_date     date        NOT NULL,
    firm_id      uuid        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    -- '' for a daily job. A workflow schedule fires many times a day, so its
    -- claim carries `<schedule id>@<the due time>`: one row per occurrence.
    claim_key    text        NOT NULL DEFAULT '',
    -- Which process holds it: host, pid and a per-process random suffix.
    owner        text        NOT NULL,
    status       text        NOT NULL DEFAULT 'running'
                     CHECK (status IN ('running', 'success', 'failed')),
    attempt      integer     NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    claimed_at   timestamptz NOT NULL DEFAULT now(),
    expires_at   timestamptz NOT NULL,
    finished_at  timestamptz NULL
);

COMMENT ON TABLE public.scheduler_claims IS
    'The lock a scheduled job takes before it runs: one row per (job, IST day, '
    'firm, claim key), taken atomically by claim_scheduler_job. A running claim '
    'carries a lease that expires, so a crashed instance cannot block the day. '
    'Service-role only. scheduler_runs is the record; this is the lock. Migration 471.';
COMMENT ON COLUMN public.scheduler_claims.claim_key IS
    'Empty for a daily job. For a workflow schedule: <schedule id>@<due time>, so '
    'each occurrence is claimed once.';
COMMENT ON COLUMN public.scheduler_claims.expires_at IS
    'Database time. A running claim past this is a dead holder and may be taken '
    'over; a live holder renews it (renew_scheduler_claim).';

CREATE UNIQUE INDEX IF NOT EXISTS uq_scheduler_claims_key
    ON public.scheduler_claims (job_name, run_date, firm_id, claim_key);
CREATE INDEX IF NOT EXISTS idx_scheduler_claims_run_date
    ON public.scheduler_claims (run_date);

ALTER TABLE public.scheduler_claims ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.scheduler_claims FROM anon, authenticated;
GRANT ALL ON public.scheduler_claims TO service_role;

-- ── take it ─────────────────────────────────────────────────────────────────
-- Returns {"claimed": true, "id", "attempt"} or {"claimed": false, "status",
-- "owner", "expires_at"} naming what is in the way, so a caller can say "already
-- done" and "another instance is on it" in different words.
CREATE OR REPLACE FUNCTION public.claim_scheduler_job(
    p_job_name                   text,
    p_run_date                   date,
    p_firm_id                    uuid,
    p_owner                      text,
    p_claim_key                  text    DEFAULT '',
    p_lease_seconds              integer DEFAULT 600,
    p_force                      boolean DEFAULT false,
    p_retry_failed_after_seconds integer DEFAULT 0
) RETURNS jsonb
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_key      text := coalesce(p_claim_key, '');
    v_id       uuid;
    v_attempt  integer;
    v_status   text;
    v_owner    text;
    v_expires  timestamptz;
BEGIN
    IF p_lease_seconds IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 86400 THEN
        RAISE EXCEPTION 'claim_scheduler_job: a lease is between 30 seconds and a day, got %',
            p_lease_seconds;
    END IF;

    INSERT INTO public.scheduler_claims AS c
        (job_name, run_date, firm_id, claim_key, owner, status, attempt, claimed_at, expires_at)
    VALUES
        (p_job_name, p_run_date, p_firm_id, v_key, p_owner, 'running', 1, now(),
         now() + make_interval(secs => p_lease_seconds))
    ON CONFLICT (job_name, run_date, firm_id, claim_key) DO UPDATE
       SET owner       = EXCLUDED.owner,
           status      = 'running',
           attempt     = c.attempt + 1,
           claimed_at  = EXCLUDED.claimed_at,
           expires_at  = EXCLUDED.expires_at,
           finished_at = NULL
     WHERE (c.status = 'running' AND c.expires_at <= now())
        OR (c.status = 'failed'
            AND (coalesce(p_retry_failed_after_seconds, 0) <= 0
                 OR c.finished_at IS NULL
                 OR c.finished_at <= now() - make_interval(secs => p_retry_failed_after_seconds)))
        OR (c.status = 'success' AND coalesce(p_force, false))
    RETURNING c.id, c.attempt INTO v_id, v_attempt;

    IF v_id IS NOT NULL THEN
        RETURN jsonb_build_object('claimed', true, 'id', v_id, 'attempt', v_attempt);
    END IF;

    SELECT s.status, s.owner, s.expires_at
      INTO v_status, v_owner, v_expires
      FROM public.scheduler_claims s
     WHERE s.job_name = p_job_name AND s.run_date = p_run_date
       AND s.firm_id = p_firm_id AND s.claim_key = v_key;

    RETURN jsonb_build_object('claimed', false, 'status', v_status,
                              'owner', v_owner, 'expires_at', v_expires);
END
$fn$;

-- ── keep it while the job is still running ──────────────────────────────────
-- False when the claim is no longer this owner's (its lease ran out and somebody
-- took it over), which the caller records: the job it is running is now running
-- twice, and the second holder is the one the database will believe.
CREATE OR REPLACE FUNCTION public.renew_scheduler_claim(
    p_id            uuid,
    p_owner         text,
    p_lease_seconds integer DEFAULT 600
) RETURNS boolean
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF p_lease_seconds IS NULL OR p_lease_seconds < 30 OR p_lease_seconds > 86400 THEN
        RAISE EXCEPTION 'renew_scheduler_claim: a lease is between 30 seconds and a day, got %',
            p_lease_seconds;
    END IF;
    UPDATE public.scheduler_claims
       SET expires_at = now() + make_interval(secs => p_lease_seconds)
     WHERE id = p_id AND owner = p_owner AND status = 'running';
    RETURN FOUND;
END
$fn$;

-- ── say how it ended ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.finish_scheduler_claim(
    p_id     uuid,
    p_owner  text,
    p_status text
) RETURNS boolean
LANGUAGE plpgsql
AS $fn$
BEGIN
    IF p_status NOT IN ('success', 'failed') THEN
        RAISE EXCEPTION 'finish_scheduler_claim: status must be success or failed, got %', p_status;
    END IF;
    UPDATE public.scheduler_claims
       SET status = p_status, finished_at = now()
     WHERE id = p_id AND owner = p_owner AND status = 'running';
    RETURN FOUND;
END
$fn$;

-- ── forget old days ─────────────────────────────────────────────────────────
-- A per-minute schedule leaves a row per occurrence, so the table is pruned: the
-- daily sweep calls this with the API's retention (30 days). Returns how many
-- rows it deleted.
CREATE OR REPLACE FUNCTION public.prune_scheduler_claims(
    p_older_than_days integer DEFAULT 30
) RETURNS integer
LANGUAGE plpgsql
AS $fn$
DECLARE
    v_deleted integer;
BEGIN
    IF p_older_than_days IS NULL OR p_older_than_days < 2 THEN
        RAISE EXCEPTION 'prune_scheduler_claims: keep at least two days, got %', p_older_than_days;
    END IF;
    DELETE FROM public.scheduler_claims
     WHERE run_date < (now() AT TIME ZONE 'Asia/Kolkata')::date - p_older_than_days;
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END
$fn$;

-- Only the API's service role may call any of them. Functions are executable by
-- PUBLIC unless that is taken away, and Supabase also grants EXECUTE to the two
-- browser roles by default.
REVOKE ALL ON FUNCTION public.claim_scheduler_job(text, date, uuid, text, text, integer, boolean, integer)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.renew_scheduler_claim(uuid, text, integer)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.finish_scheduler_claim(uuid, text, text)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.prune_scheduler_claims(integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_scheduler_job(text, date, uuid, text, text, integer, boolean, integer)
    TO service_role;
GRANT EXECUTE ON FUNCTION public.renew_scheduler_claim(uuid, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.finish_scheduler_claim(uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.prune_scheduler_claims(integer) TO service_role;

COMMIT;
