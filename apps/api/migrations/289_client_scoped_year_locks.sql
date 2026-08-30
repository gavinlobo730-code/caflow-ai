-- ============================================================================
-- 289 — a year-end completion must lock ONE client's year, not the firm's
--
-- WHAT WAS WRONG
--     Finalising a year-end engagement calls
--     year_end_workflow_service.lock_year_if_completing, which called
--     year_lock_service.set_lock(db, firm_id, financial_year, ...). There is
--     no client dimension anywhere in that path: the lock lives in
--     firms.locked_financial_years (a text[]), and is_fy_locked() reads it per
--     FIRM. So a Partner finalising one client's FY 2024-25 stopped posting to
--     FY 2024-25 for EVERY OTHER CLIENT in the practice, and clearing it
--     needed the firm lock PIN.
--
--     In March or September that is a practice-wide outage produced by a
--     routine click. It is also the wrong shape: the tenancy model is
--     firm = tenant, client = accounting entity, and a year-end engagement
--     belongs to one entity.
--
-- WHAT THIS ADDS, AND WHAT IT DELIBERATELY LEAVES ALONE
--     A client-scoped lock, BESIDE the firm-level one rather than replacing
--     it. Both are legitimate and they mean different things:
--       * a FIRM lock is a deliberate practice-wide decision, taken through a
--         Partner-gated endpoint with the lock PIN — it stays exactly as it
--         is, and every one of the 67 existing validate_posting_date(firm_id,
--         date) call sites keeps its current behaviour and signature;
--       * a CLIENT lock is what finalising that client's year-end now writes.
--
--     A posting is refused if EITHER applies.
--
--     EXISTING firm-level locks are NOT touched by this migration. Some were
--     deliberate Partner decisions and some were created by the bug above,
--     and nothing in the data distinguishes them — firms.locked_financial_years
--     records only the year, not who locked it or why. Auto-unlocking would
--     silently reopen a year a Partner meant to close, which is the worse
--     error of the two: a wrongly-locked year is visible, reversible with the
--     PIN, and blocks work loudly, while a wrongly-UNLOCKED year lets a
--     posting into a filed period silently. So they stay, and a CA unlocks
--     any that were the bug's doing through the existing endpoint.
--
-- The FY derivation below is copied from is_fy_locked (migration 020) rather
-- than reimplemented, so a date resolves to the same Indian financial year on
-- both paths — April onwards is YYYY-YY of this year, January to March
-- belongs to the FY that began the previous April.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.client_year_locks (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id        UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year   TEXT NOT NULL,          -- "2025-26"
  locked_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  locked_by        UUID REFERENCES public.users(id),
  -- Why it was locked, so a CA reading the row knows whether to expect it.
  reason           TEXT,
  UNIQUE (firm_id, client_id, financial_year)
);

CREATE INDEX IF NOT EXISTS idx_client_year_locks_lookup
  ON public.client_year_locks (firm_id, client_id, financial_year);

ALTER TABLE public.client_year_locks ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS client_year_locks_firm_isolation ON public.client_year_locks;
CREATE POLICY client_year_locks_firm_isolation ON public.client_year_locks
  FOR ALL
  USING (firm_id = (auth.jwt() ->> 'firm_id')::uuid)
  WITH CHECK (firm_id = (auth.jwt() ->> 'firm_id')::uuid);

-- Mirrors is_fy_locked (migration 020) with the client dimension added.
CREATE OR REPLACE FUNCTION public.is_client_fy_locked(
  p_firm_id uuid, p_client_id uuid, p_date date
)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT EXISTS (
    SELECT 1
      FROM public.client_year_locks l
     WHERE l.firm_id = p_firm_id
       AND l.client_id = p_client_id
       AND l.financial_year =
           CASE
             WHEN EXTRACT(MONTH FROM p_date) >= 4 THEN
               (EXTRACT(YEAR FROM p_date)::text || '-' ||
                RIGHT((EXTRACT(YEAR FROM p_date) + 1)::text, 2))
             ELSE
               ((EXTRACT(YEAR FROM p_date) - 1)::text || '-' ||
                RIGHT(EXTRACT(YEAR FROM p_date)::text, 2))
           END
  );
$$;

GRANT EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date)
  TO authenticated, service_role;

-- The API runs as `authenticated` under USE_USER_JWT, and the posting kernel
-- reads this table on every GL write. A table the backend reads that
-- `authenticated` cannot is a 403 from PostgREST and a 500 from the endpoint —
-- the exact outage migration 287 exists to prevent, and
-- test_itc_reversal_register_grants_pg.py enforces it. RLS above still scopes
-- every row to the caller's firm; the grant only makes the table reachable.
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_year_locks TO authenticated;
GRANT ALL                            ON public.client_year_locks TO service_role;
