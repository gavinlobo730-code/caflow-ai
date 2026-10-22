-- Migration 535 — the record that a return was filed is written by the API only, never by a signed-in session (security, ledger
-- POST-A-319, found by the independent review of migration 533 and reproduced on a throwaway database on 22-10-2026).
--
-- WHAT WAS WRONG
--   `filings` is what `period_lock_reason` and `journal_period_lock_reason` read to refuse a posting, an edit or a discard inside
--   a period whose GSTR-1 or GSTR-3B has gone to the portal (migrations 266, 267, 361). The sales invoice, purchase bill,
--   credit and debit note, advance-GST receipt, fixed asset and manual journal pre-checks all depend on it. The table was
--   granted INSERT, UPDATE and DELETE to `authenticated`, and its policies are the firm's and the assignment scope: no role
--   tier. The review reproduced it as an assigned Reviewer: they read "GSTR-3B covering this date was filed on 20 Jul 2025",
--   ran `DELETE FROM filings WHERE client_id = ...` (DELETE 1), and the same function then answered open. A lock that any
--   assigned member can remove is not a lock; and nothing records that it was removed.
--
--   Nothing in `apps/web` writes the table. The only Python writer is `services/gst_filing_record_service.record_filing`,
--   called by the GST workspace's mark-filed routes and by the compliance obligation path with the request's own client; since
--   the change before this one it writes with the privileged client (the shape of `year_lock_service._lock_table_db`,
--   migration 532) and asks first that the client is the firm's, the one fact the row policy used to ask on top.
--
-- WHAT THIS DOES
--   REVOKEs INSERT, UPDATE, DELETE and TRUNCATE on `filings` from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE
--   privilege (table, column, through PUBLIC), the shape of migrations 499, 513, 519 and 534. SELECT is untouched: the period
--   functions are SECURITY INVOKER and read the table as the caller, scoped to the caller's clients by the policies already
--   there. The service role keeps its writes. With no write verb granted a write policy would decide nothing, so none is added.
--
-- DEPLOY ORDER: the API change that moves the writer shipped in the change before this one, at least an hour earlier, and it
-- has to: the OLD API against these revoked grants writes a GSTR-1 or GSTR-3B's status and fails to write the `filings` row (the
-- workspace logs it and carries on, because the return IS filed), so the lock is missing until the return is marked again. The
-- new API works on either side of this migration.
--
-- A SOFT-DELETED ROW: `record_filing` finds a `filings` row whether or not `deleted_at` is set (before this migration any
-- assigned member could soft-delete one) and writes `deleted_at` back to null when it records the return again.
--
-- Idempotent. Reversible: 535_..._rollback.sql gives INSERT, UPDATE and DELETE back to `authenticated`, which RE-OPENS the hole.
-- It restores what the migrations granted (041 and 095), which is not necessarily what production's platform defaults gave
-- (`anon`, TRUNCATE, REFERENCES, TRIGGER among them): production's own ACL was not read, and the revoke does not depend on it.

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    IF to_regclass('public.filings') IS NULL THEN
        RAISE NOTICE 'migration 535: public.filings does not exist; nothing to revoke';
        RETURN;
    END IF;

    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.filings FROM PUBLIC, authenticated, anon;

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
            IF has_table_privilege(r, 'public.filings', verb) THEN
                RAISE EXCEPTION 'migration 535: % still holds % on filings', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.filings', 'INSERT') OR has_any_column_privilege(r, 'public.filings', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 535: % still holds a column-level write privilege on filings', r;
        END IF;
    END LOOP;

    IF NOT has_table_privilege('service_role', 'public.filings', 'INSERT')
       OR NOT has_table_privilege('service_role', 'public.filings', 'UPDATE')
       OR NOT has_table_privilege('service_role', 'public.filings', 'DELETE') THEN
        RAISE EXCEPTION 'migration 535: service_role lost a write privilege on filings';
    END IF;
END $$;
