-- Rollback for 373.
--
-- Dropping this column loses which suppliers have a WRITTEN payment agreement
-- and for how long — a fact about a contract that no ledger holds and that
-- cannot be rebuilt from anything else. Export
-- vendors(id, msmed_agreement_days) WHERE msmed_agreement_days IS NOT NULL
-- before running this.
--
-- The s.43B(h) engine then reads every supplier as having no written
-- agreement, which applies MSMED s.2(b)'s fifteen days — the statutory
-- default, and the direction that over-states the disallowance rather than
-- under-stating it.

ALTER TABLE public.vendors
  DROP CONSTRAINT IF EXISTS vendors_msmed_agreement_days_check;

ALTER TABLE public.vendors
  DROP COLUMN IF EXISTS msmed_agreement_days;
