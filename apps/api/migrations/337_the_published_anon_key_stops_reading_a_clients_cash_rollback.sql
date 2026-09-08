-- Rollback for migration 337: put EXECUTE back to PUBLIC on the seven
-- functions, and unpin role_rank's search_path.
--
-- WHAT THIS RESTORES IS THE HOLE. `anon` is a member of PUBLIC and the anon key
-- ships in the browser bundle, so re-granting PUBLIC on
-- get_cash_payments_above_threshold hands every visitor the ability to read any
-- client's cash payments given a firm id and a client id. Run this only to
-- unblock a caller that 337 broke, and only long enough to find out which
-- caller it is — the fix is then a targeted GRANT to that role, not this file.
--
-- NOTHING TO UNDO FOR SECTION 5. Migration 337's section 5 is prose: it
-- RECOMMENDS dropping three leftover working tables (_backup_247_invoices,
-- _backup_247_journal_lines, _mig247_targets) and drops nothing. If the owner
-- has since run those three statements by hand, this file cannot put them
-- back — they were created outside this repository and no migration defines
-- their shape — which is exactly why 337 leaves the decision to a person.
--
-- Idempotent, and safe to re-run.

BEGIN;

GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(uuid, uuid, bigint)
  TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_public_columns()                              TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_public_schema_columns()                       TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.increment_message_count(uuid)                     TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.is_client_fy_locked(uuid, uuid, date)             TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.payroll_declaration_guard_verified_columns()      TO PUBLIC;
GRANT EXECUTE ON FUNCTION public.payroll_declaration_item_guard_verified_columns() TO PUBLIC;

-- The explicit grants 337 added to authenticated and service_role are LEFT IN
-- PLACE. They restate access those two roles already had through PUBLIC, so
-- removing them would narrow, not restore — and every one of them matches a
-- caller named in 337's header.

ALTER FUNCTION public.role_rank(text) RESET search_path;

COMMIT;
