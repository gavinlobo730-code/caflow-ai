-- Migration 170: harden RLS on compliance_tasks (System B) -- R3.13
-- compliance data-model consolidation.
--
-- compliance_records is now the canonical obligation entity (Decision made
-- during the R3.13 consolidation: richest status machine, the only
-- cross-client aggregation engine, RLS-hardened, and every real frontend
-- consumer has been migrated onto it — see R3.13c/R3.13d/R3.13e in the
-- audit doc). compliance_tasks (System B) has zero remaining consumers with
-- any live frontend caller: routers/compliance.py (the only backend module
-- still reading/writing it) backs API paths that api.compliance.* wraps in
-- lib/api/index.ts, but that wrapper itself has zero callers anywhere in
-- apps/web — confirmed by exhaustive grep during the consolidation.
--
-- This does NOT touch compliance_calendar (System C) -- that table still
-- has active direct-Supabase writers that have not yet been migrated
-- (apps/web/app/income-tax/page.tsx inserts/updates it directly; apps/web/
-- app/gst/page.tsx, app/risks/page.tsx, and app/reports/cash-flow/page.tsx
-- also read it) -- hardening compliance_calendar before those are migrated
-- would break live functionality. Tracked as a follow-up in the audit doc.
--
-- Additive/non-destructive: revokes direct browser (authenticated-role)
-- write access only -- the backend's service-role connection (which
-- routers/compliance.py itself uses) is unaffected, and no existing row is
-- touched or deleted.

REVOKE INSERT, UPDATE, DELETE ON public.compliance_tasks FROM authenticated;

DROP POLICY IF EXISTS "compliance_tasks_own_firm" ON public.compliance_tasks;
CREATE POLICY "compliance_tasks_own_firm" ON public.compliance_tasks
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());
