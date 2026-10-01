-- Rollback for 454.
--
-- Dropping this column loses which suppliers were recorded as a bank deposit
-- and whether the depositor is a senior citizen — a fact about the instrument
-- and the payee that nothing else holds. Export
-- vendors(id, interest_threshold_class) WHERE interest_threshold_class IS NOT NULL
-- before running this.
--
-- Section 194A then takes its single ₹10,000 limit for every supplier, which is
-- the lowest and so over-withholds on a deposit with a bank rather than
-- under-withholding.

ALTER TABLE public.vendors
  DROP CONSTRAINT IF EXISTS vendors_interest_threshold_class_check;

ALTER TABLE public.vendors
  DROP COLUMN IF EXISTS interest_threshold_class;
