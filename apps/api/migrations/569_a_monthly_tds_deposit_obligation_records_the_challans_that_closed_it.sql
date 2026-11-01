-- 569 — a monthly TDS deposit obligation records the challans that closed it (POST-A-362).
--
-- THE GAP
--
-- `services/tds_deposit_closes_obligation` closes a month's TDS deposit obligation (`compliance_records`, obligation type
-- TDS_NON_SALARY_DEPOSIT) when the challans recorded in the register cover the tax deducted in that month, in full and on time. The
-- register pairs a challan to a deduction by ORDER within the quarter (a challan carries a quarter and no month), and nothing kept
-- WHICH challans a month was closed on. So retracting a challan recorded in error could not reopen the month it had helped to close
-- (the answer could only name every month of the quarter that still read filed), and a month a person reopened because the pairing
-- was wrong was closed again by the next challan saved for its quarter, on the very challans the person had just rejected.
--
-- WHAT THIS ADDS
--
-- One nullable column on `compliance_records`, `closing_tds_challan_ids`: a JSON array of the ids of the challans that covered the
-- month when the closer closed it. It is written by the closer after the close and by nothing else; the closer reads it on a month
-- that has been reopened (the same challans still cover it: leave it for the person), and the challan retraction reads it to find the
-- months a retracted challan closed. NULL means "no record of which challans closed it": every obligation closed before this, every
-- obligation of any other type, and a month whose write of this column failed. No backfill: which challans closed a past month is
-- what the register's order says today, not what was true when it was closed, and a guess stored as a fact is what this column
-- exists to stop. The array holds ids that may no longer exist (a retracted challan's id stays on the month it closed, which is how
-- the retraction finds it), so there is deliberately no foreign key.
--
-- Nothing here transmits anything to a portal.

BEGIN;

ALTER TABLE public.compliance_records
    ADD COLUMN IF NOT EXISTS closing_tds_challan_ids jsonb;

-- An array or nothing: a string or an object here would read as "no challans" to a reader that only looks inside a list.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'compliance_records_closing_tds_challan_ids_is_array') THEN
        ALTER TABLE public.compliance_records
            ADD CONSTRAINT compliance_records_closing_tds_challan_ids_is_array
            CHECK (closing_tds_challan_ids IS NULL OR jsonb_typeof(closing_tds_challan_ids) = 'array');
    END IF;
END $$;

COMMENT ON COLUMN public.compliance_records.closing_tds_challan_ids IS
    'The ids of the TDS challans that covered this monthly deposit obligation when it was closed from the challan register (a JSON array; the ids may name challans since retracted). NULL = no record of which challans closed it. POST-A-362.';

COMMIT;
