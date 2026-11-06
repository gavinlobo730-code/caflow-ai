-- Migration 584 — a tax audit recorded as completed or filed does not carry a day that has not come (ledger POST-A-393, item 1).
--
-- THE GAP
--   `tax_audits.audit_date` and `tax_audits.filing_date` are written from the browser, straight to the table (the Tax Audit tracker; the only writer, and a source guard says so). The
--   table checks the form, the status, the firm, the client scope and (migration 496) who may record an audit as completed or filed, and NOTHING checks the two dates: a tracker row
--   recorded as FILED could carry a filing date next month. The ITR acknowledgement's door refuses such a day (`filed_date cannot be in the future`); a row that says
--   the audit report is signed and is on the portal is the same statement, and it was the one place that statement had no check at any layer.
--
-- THE RULE (the plain order of events, no period, rate or other statutory reading)
--   * An audit recorded as COMPLETED or FILED: its audit date is not a day that has not come.
--   * An audit recorded as FILED: its filing date is not a day that has not come.
--   "Not come" is judged on India's day (`now() AT TIME ZONE 'Asia/Kolkata'`), never the server's or UTC's: between 00:00 and 05:30 IST the UTC date is still yesterday's.
--   An audit that is not started or in progress may carry a PLANNED date: the boxes are labelled "Audit Date" and "Filing Date", and a person scheduling the work writes the day it is
--   meant to happen. Only a status that says the act is done makes the day a statement of fact.
--
-- THE SENTENCE'S DAYS are written as every screen writes a day (`08 Oct 2026`), and the function pins its search_path as the recent trigger functions do (566): it runs with the caller's own privileges,
-- so this is hardening and not a privilege matter. (`to_char`'s month name is English whatever the server's locale, because the `TM` prefix that translates it is not used.)
--
-- WHERE IT IS ENFORCED, AND WHY HERE
--   The browser writes the table directly, so there is no API door to ask, and moving the writer behind one (with the approver rule of 496, the duplicate message and the revoke of the
--   write grant) is a change of its own. A trigger is the one layer every writer meets (the screen, a hand-made PostgREST call, the service role), and it can word its refusal, which a
--   row policy cannot (a refused policy says "violates row-level security" and the screen would quote the wrong cause). The screen asks the same question first, in the box, with the
--   same bound, so the person is told before the request; this is the backstop for a writer that is not the screen.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * It is asked only when the row is INSERTED, when the status changes, or when the date in question changes. A row that already carries a day ahead (nothing has ever checked) is
--     therefore not locked: an unrelated edit (the UDIN, the acknowledgement number) goes through, and the next time somebody records it as done or touches the date they are asked.
--   * No row is changed. No backfill. No column, grant or policy is touched, and no other function. How many rows already carry such a day is REPORTED when the migration runs
--     (`RAISE WARNING`, which the runner keeps), as the count of audits recorded as completed or filed with an audit date ahead and of those recorded as filed with a filing date ahead.
--   * The SCREEN is stricter than this on such a row, on purpose: the Tax Audit tracker's box reports a day after today as a problem as soon as the form is opened over one, so a person
--     who opens a legacy row only to correct the UDIN is asked to put the day right first. The database asks only when the status or the day is touched, so a hand-made request that
--     edits the UDIN alone goes through.
--   * The two dates are not compared with each other here (a filing before the audit date): the screen hints it, and no refusal was asked for.
--
-- Idempotent: CREATE OR REPLACE FUNCTION and DROP TRIGGER IF EXISTS before CREATE. The closing check fails the migration (and so the deploy) if the trigger is missing.
-- Reversible: 584_..._rollback.sql drops both, which RE-OPENS the gap.

BEGIN;

-- CREATE TRIGGER takes a lock on tax_audits that waits behind any open transaction on it: under a timeout a busy table makes the deploy fail in words (the pipeline stays red until the migration is retried), not wait unseen.
SELECT set_config('lock_timeout', '15s', true);

CREATE OR REPLACE FUNCTION public.tax_audit_dates_follow_the_status()
RETURNS trigger
LANGUAGE plpgsql
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
BEGIN
    IF NEW.status IN ('completed', 'filed')
       AND NEW.audit_date IS NOT NULL
       AND NEW.audit_date > v_today
       AND (TG_OP = 'INSERT'
            OR NEW.status IS DISTINCT FROM OLD.status
            OR NEW.audit_date IS DISTINCT FROM OLD.audit_date) THEN
        RAISE EXCEPTION 'The audit date of a tax audit recorded as % cannot be %: that day has not come (today in India is %). Record the day the audit report was dated.',
            replace(NEW.status, '_', ' '), to_char(NEW.audit_date, 'DD Mon YYYY'), to_char(v_today, 'DD Mon YYYY')
            USING ERRCODE = '23514', HINT = 'tax_audits_dates_follow_the_status';
    END IF;

    IF NEW.status = 'filed'
       AND NEW.filing_date IS NOT NULL
       AND NEW.filing_date > v_today
       AND (TG_OP = 'INSERT'
            OR NEW.status IS DISTINCT FROM OLD.status
            OR NEW.filing_date IS DISTINCT FROM OLD.filing_date) THEN
        RAISE EXCEPTION 'The filing date of a tax audit recorded as filed cannot be %: that day has not come (today in India is %). Record the day the report was filed on the portal.',
            to_char(NEW.filing_date, 'DD Mon YYYY'), to_char(v_today, 'DD Mon YYYY')
            USING ERRCODE = '23514', HINT = 'tax_audits_dates_follow_the_status';
    END IF;

    RETURN NEW;
END
$$;

COMMENT ON FUNCTION public.tax_audit_dates_follow_the_status() IS
    'POST-A-393: an audit recorded as completed or filed does not carry an audit date that has not come; one recorded as filed does not carry a filing date that has not come. India''s day. Asked on insert, on a status change and when the date itself changes.';

-- A trigger function is never called by a person: a trigger does not ask its caller for EXECUTE, so nothing here needs a signed-in role to hold it.
REVOKE ALL ON FUNCTION public.tax_audit_dates_follow_the_status() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.tax_audit_dates_follow_the_status() FROM anon;
REVOKE ALL ON FUNCTION public.tax_audit_dates_follow_the_status() FROM authenticated;

-- Report what already breaks the rule (and change none of it), then install.
DO $$
DECLARE
    v_today date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
    v_audit int;
    v_filing int;
BEGIN
    SELECT count(*) INTO v_audit FROM public.tax_audits WHERE status IN ('completed', 'filed') AND audit_date > v_today;
    SELECT count(*) INTO v_filing FROM public.tax_audits WHERE status = 'filed' AND filing_date > v_today;
    RAISE WARNING 'migration 584: % tax audit(s) recorded as completed or filed already carry an audit date that has not come, and % recorded as filed a filing date that has not come (left as they are)',
        v_audit, v_filing;
END $$;

DROP TRIGGER IF EXISTS tax_audit_dates_follow_the_status ON public.tax_audits;
CREATE TRIGGER tax_audit_dates_follow_the_status
    BEFORE INSERT OR UPDATE ON public.tax_audits
    FOR EACH ROW EXECUTE FUNCTION public.tax_audit_dates_follow_the_status();

-- ── the closing check: the trigger exists, is enabled and is a row trigger before insert and update ───────────────────────────────
DO $$
DECLARE
    n int;
BEGIN
    SELECT count(*) INTO n
      FROM pg_trigger g
     WHERE g.tgrelid = 'public.tax_audits'::regclass
       AND g.tgname = 'tax_audit_dates_follow_the_status'
       AND NOT g.tgisinternal
       AND g.tgenabled = 'O'
       AND (g.tgtype & 1) = 1      -- FOR EACH ROW
       AND (g.tgtype & 2) = 2      -- BEFORE
       AND (g.tgtype & 4) = 4      -- INSERT
       AND (g.tgtype & 16) = 16;   -- UPDATE
    IF n <> 1 THEN
        RAISE EXCEPTION 'migration 584: the tax_audit_dates_follow_the_status trigger is missing or is not a BEFORE INSERT OR UPDATE row trigger';
    END IF;
END
$$;

COMMIT;
