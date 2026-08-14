-- Migration 263: give tds_deductions the financial year it has always been
-- queried by.
--
-- WHY
--     Two independent pieces of code already assume this column exists:
--
--       * repositories/tds_repository.py filters
--         `.eq("financial_year", financial_year)` on tds_deductions. That query
--         has always 400'd whenever a financial year was passed — which is
--         every call from /api/tds that supplies one.
--       * apps/web/app/tds records a deduction with an `fy` field ("2025-26")
--         that had nowhere to go.
--
--     So this is not a new idea being bolted on. The column was designed in and
--     never created; the reader and the writer were both written against it.
--
-- SHAPE
--     TEXT, nullable, no CHECK — matching the twelve other financial_year
--     columns in this schema (advance_tax_payments, documents,
--     engagement_letters, form_26as_*, gst_portal_snapshots, tds_returns …),
--     none of which constrain the value. Consistency matters more here than a
--     constraint on one table out of thirteen: a CHECK only on this one would
--     be a trap for anyone copying the established pattern.
--
--     Nullable rather than NOT NULL because form26as_service reads
--     tds_deductions rows it did not necessarily write, and a NOT NULL would
--     turn any future insert that omits the FY into a hard failure rather than
--     a fixable gap. Production currently holds 0 rows, so nothing is
--     backfilled — but the backfill below is written anyway, because this
--     migration must also do the right thing on a developer database that has
--     data.
--
-- The Indian financial year runs 1 April to 31 March, so a transaction dated
-- Jan-Mar belongs to the year that STARTED in the previous calendar year.
-- Format "2025-26", the same string the rest of the codebase uses (see
-- routers/accounting.py::_current_fy_long).
--
-- Re-runnable and atomic, per migration 262's header: ADD COLUMN IF NOT EXISTS,
-- and the whole file in one transaction so a failure cannot leave the column
-- added but unbackfilled.

BEGIN;

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS financial_year TEXT;

COMMENT ON COLUMN public.tds_deductions.financial_year IS
  'Indian financial year the deduction falls in, e.g. "2025-26" (1 Apr - 31 Mar).';

-- Backfill from transaction_date (NOT NULL on this table, so every existing row
-- gets a value). Idempotent: only rows still missing one are touched, so a
-- re-run neither overwrites a corrected value nor does redundant work.
--
-- Verified on real Postgres:  2025-04-01 -> 2025-26 (first day of the FY),
-- 2026-01-15 -> 2025-26 (Jan belongs to the FY that began the previous April),
-- 2026-03-31 -> 2025-26 (last day), 2026-04-01 -> 2026-27.
--
-- Century edge, deliberately NOT "fixed": 2099-12-31 yields '2099-00', because
-- RIGHT(2100, 2) is '00'. That is precisely what
-- routers/accounting.py::_current_fy_long already produces for the same year
-- (f"{start}-{str(start + 1)[2:]}"). Matching the application's convention
-- matters more than being right in 2099 — a migration that disagreed with the
-- code would put two different strings for one financial year into the same
-- column, and the mismatch would be found by a failed lookup, not a comment.
UPDATE public.tds_deductions
SET financial_year =
      CASE
        WHEN EXTRACT(MONTH FROM transaction_date) >= 4
          THEN EXTRACT(YEAR FROM transaction_date)::int || '-' ||
               RIGHT(((EXTRACT(YEAR FROM transaction_date)::int) + 1)::text, 2)
        ELSE (EXTRACT(YEAR FROM transaction_date)::int - 1) || '-' ||
             RIGHT((EXTRACT(YEAR FROM transaction_date)::int)::text, 2)
      END
WHERE financial_year IS NULL;

-- The page and the repository both filter firm + client + FY together.
CREATE INDEX IF NOT EXISTS idx_tds_deductions_firm_client_fy
  ON public.tds_deductions (firm_id, client_id, financial_year);

COMMIT;
