-- Migration 171: harden RLS on journal_entries/journal_lines -- R3.9
-- unmediated-write audit.
--
-- Two live frontend pages wrote directly to these tables, both bypassing
-- the backend's single posting kernel (manual_journal_service ->
-- phase2_journal_service._create_journal, atomic via post_journal_atomic --
-- see migration 152/R1.6) and its authoritative FY-lock validation:
--
--   * apps/web/app/clients/[id]/accounting/page.tsx (the main, actively-
--     linked per-client "New Journal Entry" form) did two separate,
--     non-atomic inserts -- journal_entries, then journal_lines. If the
--     second insert ever failed (network blip, validation error), the
--     result was exactly the F2 "orphan posted entry" bug R1.6 was meant to
--     have closed everywhere -- except this page was never migrated onto
--     that fix, so the failure mode was still live. Its own FY-lock guard
--     was also a client-side-only re-implementation (TOCTOU-vulnerable,
--     bypassable by any direct REST call), not authoritative.
--
--   * apps/web/app/accounting/recurring/page.tsx's "Post Now" action
--     inserted a nonexistent-column payload (total_debit_paise/
--     total_credit_paise are response-only fields computed by
--     manual_journal_service, never real journal_entries columns) and then
--     into journal_entry_lines, a read-only 3-way JOIN view (migration 016)
--     -- so in practice every click failed outright with a schema error.
--     Confirmed against a real Postgres 16 instance with every migration
--     applied: this insert never actually succeeded in production, so no
--     phantom posted journal exists from this path today.
--
-- Both call sites are fixed in the accompanying frontend change to POST
-- through /api/accounting/journal instead. This migration closes the
-- underlying tables so no future direct REST/Supabase call can reintroduce
-- either bug -- additive/non-destructive, no existing row touched.

REVOKE INSERT, UPDATE, DELETE ON public.journal_entries FROM authenticated;
REVOKE INSERT, UPDATE, DELETE ON public.journal_lines FROM authenticated;

DROP POLICY IF EXISTS "journal_entries_own_firm" ON public.journal_entries;
DROP POLICY IF EXISTS "firm_isolation" ON public.journal_entries;
DROP POLICY IF EXISTS "firm_journal_entries" ON public.journal_entries;
DROP POLICY IF EXISTS "firm_client_isolation" ON public.journal_entries;
CREATE POLICY "firm_client_isolation" ON public.journal_entries
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "journal_lines_own_firm" ON public.journal_lines;
DROP POLICY IF EXISTS "firm_isolation" ON public.journal_lines;
DROP POLICY IF EXISTS "firm_journal_lines" ON public.journal_lines;
DROP POLICY IF EXISTS "firm_client_isolation" ON public.journal_lines;
CREATE POLICY "firm_client_isolation" ON public.journal_lines
  FOR SELECT TO authenticated
  USING (
    journal_entry_id IN (
      SELECT je.id FROM public.journal_entries je
      WHERE je.firm_id = public.get_my_firm_id()
    )
  );
