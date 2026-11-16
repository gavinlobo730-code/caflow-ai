-- Migration 660: the nightly books check stores what three exception engines found for each client (POST-A-050).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- The morning digest named, on every answer, that GSTR-2B (bills the suppliers have not furnished), near-duplicate bills and recurring-journal
-- suggestions were not covered, because none of the three had a stored result and computing them for every client on every page load is a read
-- proportional to transaction volume. The nightly books check already loads each client's posted ledger and runs for every client.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- One table, one row per (client, engine), replaced each night by the API: `nightly_exception_results`. A row is `computed` (the engine looked;
-- `count` may be a true zero) or `not_computed` (it could not look; `count` is NULL and `reason` says why), and the CHECK keeps the two apart so a
-- row can never read as "nothing found" when nothing was looked at. The fourth engine the digest names, Rule 37A, has no data source and no row.
--
-- SECURITY, the shape of migration 590: row security on, the firm isolation, the RESTRICTIVE assignment scope (a member reads the clients they
-- are assigned to, a Partner all), the internal practice Partner-only, every privilege revoked from PUBLIC, anon and the signed-in role and SELECT
-- given back to the signed-in role alone. The API's privileged client writes it, naming the firm. The table is on the lists that say a signed-in
-- session writes nothing to it.
--
-- DEPLOY ORDER: the API ahead of this migration finds no table and the nightly stage logs the failure and carries on (the books check itself is
-- unaffected); the digest reads the table through a guarded read and says the three engines are not covered until rows exist.
--
-- Idempotent. Reversible: 660_..._rollback.sql drops the table (the rows are recomputed every night).

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.nightly_exception_results (
  id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id     UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- `domain/practice/nightly_results.ENGINES`; a test holds the two lists identical.
  engine        TEXT        NOT NULL,
  status        TEXT        NOT NULL,
  -- The Indian day the nightly run was for.
  as_of_date    DATE        NOT NULL,
  count         INTEGER,
  amount_paise  BIGINT,
  reason        TEXT,
  details       JSONB       NOT NULL DEFAULT '{}'::jsonb,
  computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT nightly_exception_results_engine_is_known
    CHECK (engine IN ('gstr_2b', 'duplicate_bills', 'recurring_journals')),
  CONSTRAINT nightly_exception_results_status_is_known
    CHECK (status IN ('computed', 'not_computed')),
  -- A result that was not computed has no count and says why; one that was has a count and no reason. A zero is a reading only when it was read.
  CONSTRAINT nightly_exception_results_a_nil_is_not_a_zero
    CHECK ((status = 'computed' AND count IS NOT NULL AND count >= 0 AND reason IS NULL)
        OR (status = 'not_computed' AND count IS NULL AND amount_paise IS NULL AND reason IS NOT NULL AND btrim(reason) <> '')),
  CONSTRAINT nightly_exception_results_one_per_client_and_engine UNIQUE (client_id, engine)
);

COMMENT ON TABLE public.nightly_exception_results IS
  'POST-A-050, migration 660. What the nightly books check found, per client, for GSTR-2B/ITC, near-duplicate bills and recurring-journal '
  'suggestions, so the morning digest can cover them without computing them per page load. One row per (client, engine), replaced each night. '
  'A not_computed row is unknown and is never read as zero. Written by the API only.';

CREATE INDEX IF NOT EXISTS idx_nightly_exception_results_firm
  ON public.nightly_exception_results (firm_id, engine);

ALTER TABLE public.nightly_exception_results ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "nightly_exception_results_firm_isolation" ON public.nightly_exception_results;
CREATE POLICY "nightly_exception_results_firm_isolation" ON public.nightly_exception_results
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "nightly_exception_results_assignment_scope" ON public.nightly_exception_results;
CREATE POLICY "nightly_exception_results_assignment_scope" ON public.nightly_exception_results
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "nightly_exception_results_internal_partner_only" ON public.nightly_exception_results;
CREATE POLICY "nightly_exception_results_internal_partner_only" ON public.nightly_exception_results
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.nightly_exception_results FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.nightly_exception_results TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.nightly_exception_results TO service_role;

DO $$
BEGIN
    PERFORM public.guard_client_firm('public.nightly_exception_results');
END $$;

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.nightly_exception_results', verb) THEN
                RAISE EXCEPTION 'migration 660: % still holds % on nightly_exception_results', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.nightly_exception_results', 'INSERT')
           OR has_any_column_privilege(r, 'public.nightly_exception_results', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 660: % still holds a column-level write privilege on nightly_exception_results', r;
        END IF;
    END LOOP;
    IF has_table_privilege('anon', 'public.nightly_exception_results', 'SELECT') THEN
        RAISE EXCEPTION 'migration 660: anon reads nightly_exception_results';
    END IF;
    IF NOT has_table_privilege('service_role', 'public.nightly_exception_results', 'INSERT') THEN
        RAISE EXCEPTION 'migration 660: the API (service_role) cannot write nightly_exception_results';
    END IF;
END $$;

COMMIT;
