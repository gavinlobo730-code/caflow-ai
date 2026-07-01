-- Migration 144: Security hardening (Production Readiness Phase 4).
--
-- M23 — pin search_path on every remaining function flagged function_search_path_mutable.
--   A mutable search_path on a SECURITY DEFINER function (get_my_role / get_my_user_id /
--   my_internal_client_id are the RLS helpers, run as owner and are called inside RLS
--   policies) is a search-path-hijack risk. ALTER FUNCTION ... SET search_path pins it
--   WITHOUT rewriting the body (zero behaviour change). Applied to the SECURITY INVOKER
--   integrity triggers too, to fully clear the advisor.
ALTER FUNCTION public.get_my_role()                          SET search_path = public, pg_catalog;
ALTER FUNCTION public.get_my_user_id()                       SET search_path = public, pg_catalog;
ALTER FUNCTION public.my_internal_client_id()                SET search_path = public, pg_catalog;
ALTER FUNCTION public.provision_internal_client(uuid, text, text, text, text)
                                                             SET search_path = public, pg_catalog;
ALTER FUNCTION public.prevent_posted_journal_update()        SET search_path = public, pg_catalog;
ALTER FUNCTION public.prevent_posted_journal_delete()        SET search_path = public, pg_catalog;
ALTER FUNCTION public.guard_locked_financial_years()         SET search_path = public, pg_catalog;
ALTER FUNCTION public.prevent_archived_account_journal_line() SET search_path = public, pg_catalog;
ALTER FUNCTION public.prevent_snapshot_mutation()            SET search_path = public, pg_catalog;
ALTER FUNCTION public.prevent_itr_version_mutation()         SET search_path = public, pg_catalog;
ALTER FUNCTION public.audit_log_block_mutation()             SET search_path = public, pg_catalog;
ALTER FUNCTION public.update_updated_at_column()             SET search_path = public, pg_catalog;
ALTER FUNCTION public.health_grade_from_score(integer)       SET search_path = public, pg_catalog;

-- N1 — credit_note_allocations (added in migration 140) had RLS enabled but NO policy.
-- Under service-role that is deny-all-by-default (safe), but the table should carry the
-- same firm-scoped policy as its siblings (receipt_allocations, credit_note_lines) so a
-- future authenticated/USE_USER_JWT path stays tenant-isolated. Defense in depth.
DROP POLICY IF EXISTS firm_credit_note_allocations ON public.credit_note_allocations;
CREATE POLICY firm_credit_note_allocations ON public.credit_note_allocations
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
