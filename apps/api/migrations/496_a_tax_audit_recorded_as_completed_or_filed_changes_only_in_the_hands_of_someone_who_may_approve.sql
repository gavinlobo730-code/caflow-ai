-- Migration 496 — a tax audit recorded as completed or filed changes only in the hands of someone who may approve income
-- tax work (found by the 14-10-2026 audit of the browser's direct writes; ledger POST-A-226).
--
-- THE HOLE
--   `tax_audits` takes its writes from anyone with `income_tax:compute` (Executive and above: migration 261), and its
--   deletes from `income_tax:approve` (Manager and above). The Tax Audit tracker writes the table straight from the
--   browser, including `status = 'completed'` or `'filed'` with a UDIN, an acknowledgement number and a filing date.
--   Recording an audit as completed or filed is a statement that the auditor has signed and the report is on the portal;
--   the ITR filing record for the same client is Manager-tier (`itr_filings` update) and goes through the API's
--   mark-filed door, so an Executive could say the audit was done when the same Executive could not say the return was.
--   A row policy cannot see a transition, so there is no way to let an Executive move an audit from "not started" to
--   "in progress" and refuse the step after it by transition; what it CAN see is the status a row has and the status it
--   is given, which is what this asks.
--
-- WHAT THIS DOES (RESTRICTIVE, so it ANDs with the firm, assignment and `income_tax:compute` rules and can only narrow)
--   With `my_permission('income_tax', 'approve', 'Manager')` (so the per-person grid counts here as it does in `can_user`
--   at the routes):
--     INSERT   a row may be created `completed` or `filed` only by someone who may approve
--     UPDATE   a row that is CURRENTLY `completed` or `filed` may be changed only by someone who may approve, and any row
--              may be given either status only by them. An Executive still creates, edits and progresses an audit that
--              is not started or in progress.
--     DELETE   a completed or filed audit is deleted only by someone who may approve (delete already takes `approve`
--              from migration 261; this keeps the rule true if a grant ever lowers that tier)
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * The service role and a connection with no JWT are not `authenticated` and are untouched.
--   * It does not decide which transitions are valid (a Manager can still reopen a completed audit).
--   * It does not look at `udin`, `ack_number` or `filing_date` on a row whose status is not terminal: those are details of
--     the record, and the status is what says it is done.
--   * No function, grant, table or row changes. No backfill.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the deploy) if
-- any policy is missing or not RESTRICTIVE. Reversible: 496_..._rollback.sql drops them again, which RE-OPENS the hole.

DROP POLICY IF EXISTS "tax_audits_state_tier_insert" ON public.tax_audits;
CREATE POLICY "tax_audits_state_tier_insert" ON public.tax_audits
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (COALESCE(status, 'not_started') NOT IN ('completed', 'filed')
              OR public.my_permission('income_tax', 'approve', 'Manager'));

DROP POLICY IF EXISTS "tax_audits_state_tier_update" ON public.tax_audits;
CREATE POLICY "tax_audits_state_tier_update" ON public.tax_audits
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (COALESCE(status, 'not_started') NOT IN ('completed', 'filed')
         OR public.my_permission('income_tax', 'approve', 'Manager'))
  WITH CHECK (COALESCE(status, 'not_started') NOT IN ('completed', 'filed')
              OR public.my_permission('income_tax', 'approve', 'Manager'));

DROP POLICY IF EXISTS "tax_audits_state_tier_delete" ON public.tax_audits;
CREATE POLICY "tax_audits_state_tier_delete" ON public.tax_audits
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (COALESCE(status, 'not_started') NOT IN ('completed', 'filed')
         OR public.my_permission('income_tax', 'approve', 'Manager'));

-- ── the closing check: all three policies exist and every one is RESTRICTIVE ─────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN ('tax_audits_state_tier_insert', 'tax_audits_state_tier_update', 'tax_audits_state_tier_delete');
  IF n <> 3 THEN
    RAISE EXCEPTION 'migration 496: expected 3 restrictive policies, found %', n;
  END IF;
END $$;
