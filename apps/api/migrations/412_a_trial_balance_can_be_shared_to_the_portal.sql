-- Migration 412: a Trial Balance is a report the portal can be sent.
--
-- ── THE DEFECT ──────────────────────────────────────────────────────────────
-- The client accounting screen offers three reports to share with the client's
-- own portal — Profit & Loss, Balance Sheet and Trial Balance — and
-- `shareToPortal` maps only one of them:
--
--     report_type: reportType === "bs" ? "balance_sheet" : reportType
--
-- so "pl" goes in as 'pl', "bs" as 'balance_sheet', and "trial" as **'trial'**.
-- Migration 032 declared
--
--     CHECK (report_type IN ('pl', 'balance_sheet', 'gst_summary', 'tds_summary'))
--
-- and nothing has widened it since. So sharing a Trial Balance has never once
-- worked: the INSERT is refused by the constraint every time.
--
-- It fails in the worst order, too. The workbook is uploaded to Supabase
-- Storage FIRST and the row is inserted after, so a CA who presses the button
-- gets a raw Postgres constraint message in an `alert()`, the report never
-- reaches the portal, and the file stays in storage for ever with no row
-- pointing at it. Every press leaves another one.
--
-- ── THE FIX, AND WHY IT IS THE CONSTRAINT THAT MOVES ────────────────────────
-- The other reading — map "trial" onto one of the four values that already
-- exist — would file a trial balance as something it is not. A trial balance is
-- its own statement: it is not the P&L, and the portal renders these by type.
-- So the vocabulary was simply missing a member and gains one.
--
-- WIDENING a CHECK is additive and cannot fail on existing data: every row that
-- satisfied the old predicate satisfies the new one by construction. That
-- matters here because merging a migration applies it straight to the
-- production database with no review step in front of it.
--
-- 'payroll_summary' is deliberately NOT added, although migration 031 declared
-- it on the employee-portal table. Nothing shares a payroll summary through
-- this table, and a value no writer emits is a member of the vocabulary that
-- the next reader has to check before trusting — the shape this codebase keeps
-- finding and naming.

ALTER TABLE public.shared_reports
  DROP CONSTRAINT IF EXISTS shared_reports_report_type_check;

ALTER TABLE public.shared_reports
  ADD CONSTRAINT shared_reports_report_type_check
  CHECK (report_type IN ('pl', 'balance_sheet', 'trial_balance', 'gst_summary', 'tds_summary'));

COMMENT ON COLUMN public.shared_reports.report_type IS
  'Which statement was shared. The browser''s shareToPortal must emit exactly '
  'one of these; ''trial_balance'' was added by migration 412 because the screen '
  'offered a Trial Balance the constraint refused. Changing this list means '
  'changing apps/web''s map in the same commit — '
  'tests/test_a_shared_report_names_a_type_the_table_allows.py holds the two together.';
