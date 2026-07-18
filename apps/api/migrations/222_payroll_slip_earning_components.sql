-- 222 — payroll_slips: earning-component columns (fixes create_run 500).
--
-- Problem
-- -------
-- routers/payroll.py::_compute_slip returns a per-slip breakdown that includes
-- basic_paise / hra_paise / da_paise / lta_paise / medical_paise /
-- special_allowance_paise, and create_run inserts that whole dict verbatim into
-- payroll_slips. But the base payroll schema (014) plus migration 093 §4 only
-- ever added gross/PF/ESI/PT/TDS/net + employer PF/ESI + attendance columns —
-- the six earning-component columns were never created. Every draft payroll run
-- for a client with at least one active employee therefore fails the slip
-- INSERT (unknown column) and 500s, and — because the run header row is inserted
-- BEFORE the slips — a retry then hits the duplicate-run 409 guard, stranding an
-- empty broken run. Same class as the R2.10 payroll_slips.firm_id bug.
--
-- services/payslip_pdf_service.py already reads these columns to render the
-- earnings breakdown ("only render lines present on the slip"), and
-- models/payroll.py already carries the matching employee-master fields — so the
-- clearly-intended schema is that payroll_slips stores the breakdown. This adds
-- the missing columns.
--
-- other_allowances_paise is added alongside the six: it is a real employee-master
-- field (models/payroll.py) that _compute_slip previously dropped from gross
-- entirely (bug), so once it is folded into gross it must also be stored per-slip
-- for the earnings breakdown to reconcile to gross.
--
-- All BIGINT NOT NULL DEFAULT 0 (integer paise, CLAUDE.md) — purely additive, so
-- existing rows are unaffected and existing readers keep working.

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS basic_paise             BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS hra_paise               BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS da_paise                BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lta_paise               BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS medical_paise           BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS special_allowance_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS other_allowances_paise  BIGINT NOT NULL DEFAULT 0;
