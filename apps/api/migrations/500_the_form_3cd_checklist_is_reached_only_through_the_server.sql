-- Migration 500: the Form 3CD checklist table is reached only through the PracticeSync server
-- (ledger POST-A-233, found by the independent review of the migration 496 diff).
--
-- WHAT WAS WRONG
--   `PUT /api/income-tax/form-3cd` records a checklist's status as `draft`, `review` or `finalised`. The route asked
--   `income_tax:write` (Executive and above) and accepted `finalised`, although recording an audit document as final is
--   an approver's act, the same as recording a tax audit as completed (migration 496) or a return as filed. The table
--   behind it, `tax_audit_checklists` (migration 014), had the firm rule and the assignment rule of migration 084 (a
--   RESTRICTIVE policy that confines everyone but a Partner to the clients they are assigned to) and every privilege
--   granted to signed-in users (migration 041). So a signed-in Executive assigned to a client, or a Partner, could also
--   write the status or any clause of that client's checklist straight over the database, past whatever the route said.
--   (A member not assigned to the client could neither read nor write it; the policy list was read from production on
--   17-10-2026: `tax_audit_own_firm` and `tax_audit_checklists_assignment_scope`.)
--
--   Nothing in the browser reads or writes the table: a search of `apps/web` for the table name finds nothing, and the
--   API reads and writes it with the privileged client (`routers/income_tax._db` is `service_db_or_none`). No figure
--   reads the status either, so nothing a screen shows moves. What the status says is that someone who may approve has
--   signed the checklist off.
--
-- WHAT THIS DOES
--   REVOKE every privilege on the table from `authenticated`, `anon` and PUBLIC (reads too: nothing reads it that way, so
--   they were privilege nobody used). The API (`service_role`) is untouched. The row-security policies (014, 084) stay as
--   a second lock: a later migration that grants a list of tables again (041 did) would undo a revoke and would not undo
--   a policy. The route now asks the per-person `income_tax:approve` for `finalised` and for any change to a checklist
--   that already is (the same commit; `services/form_3cd_service.save_manual_clauses`).
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * No row, column, function or policy changes. No backfill.
--   * It does not decide which status moves are valid: a Manager can still reopen a finalised checklist.
--   * Other tables that are nothing but API tables are not covered by this migration (ledger POST-A-018 holds eight of
--     them, which the API reads under a caller's own sign-in and so cannot lose their grants).
--
-- A signed-in read or write of the table is now "permission denied for table tax_audit_checklists" (SQLSTATE 42501).
-- Idempotent. Reversible: 500_..._rollback.sql grants back what migration 014 gave, which RE-OPENS the hole.

REVOKE ALL ON public.tax_audit_checklists FROM PUBLIC, authenticated, anon;

DO $$
DECLARE
  r text;
  verb text;
BEGIN
  -- The EFFECTIVE privilege (has_table_privilege and has_any_column_privilege see PUBLIC, membership and column grants).
  FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
    FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
      IF has_table_privilege(r, 'public.tax_audit_checklists', verb) THEN
        RAISE EXCEPTION 'migration 500: % still holds % on tax_audit_checklists', r, verb;
      END IF;
    END LOOP;
    IF has_any_column_privilege(r, 'public.tax_audit_checklists', 'SELECT')
       OR has_any_column_privilege(r, 'public.tax_audit_checklists', 'INSERT')
       OR has_any_column_privilege(r, 'public.tax_audit_checklists', 'UPDATE') THEN
      RAISE EXCEPTION 'migration 500: % still holds a column-level privilege on tax_audit_checklists', r;
    END IF;
  END LOOP;
  IF NOT has_table_privilege('service_role', 'public.tax_audit_checklists', 'INSERT')
     OR NOT has_table_privilege('service_role', 'public.tax_audit_checklists', 'UPDATE') THEN
    RAISE EXCEPTION 'migration 500: the API (service_role) lost its write privilege on tax_audit_checklists';
  END IF;
END $$;
