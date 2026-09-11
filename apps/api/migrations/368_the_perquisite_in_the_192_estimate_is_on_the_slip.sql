-- 368: what §17(2) perquisite went into this slip's §192 estimate (PAY-07)
--
-- WHAT WAS WRONG
--
-- `payroll_perquisites` (the year's §17(2) valuations, recorded from the
-- client workspace's Perquisites section) was read by exactly ONE caller: the
-- 24Q Annexure II builder that produces Form 16 Part B. It never reached the
-- monthly §192 withholding.
--
-- §17(1)(iv) makes "the value of any perquisite" part of salary and §192(1)
-- charges the employer to deduct on "the estimated income of the assessee
-- under the head 'Salaries' for that financial year". So the value belongs in
-- the estimate. Leaving it out under-withholds every month of the year and
-- hands the employee the whole liability on assessment — and the employer the
-- §201(1A) interest for having deducted short.
--
-- The part that made it hard to notice: the CA who valued the perquisite got a
-- confirmation that read as reassurance ("§17(2) perquisites recorded for
-- 2026-27"), and the figure DID appear on Form 16 in May. Everything looked
-- like it worked except the twelve deductions in between.
--
-- WHY A COLUMN RATHER THAN LEAVING IT IMPLICIT
--
-- The slip already records every other figure that moved its TDS, and this one
-- is the only input to the estimate that is not visible anywhere on the
-- payslip: it is not in gross pay (the employee is not paid it in cash — see
-- below), so a CA reading a slip whose TDS jumped in December has no way to
-- see why. Recording it makes the deduction explicable, which is what a
-- payslip is for.
--
-- It is deliberately NOT added to gross_paise. A perquisite is a benefit, not
-- cash: adding it to gross would inflate net pay, the PF wage base and the ESI
-- gross alike, none of which the value belongs in. It enters the TDS estimate
-- and nothing else.
--
-- NOT BACKFILLED. A slip computed before this migration was computed without
-- the perquisite, and writing today's valuation onto it would claim the
-- deduction had considered a figure it never saw. Zero on an old slip is the
-- truth: nothing was considered.

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS perquisites_in_tds_estimate_paise BIGINT NOT NULL DEFAULT 0;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_slips_perquisites_nonneg') THEN
    ALTER TABLE public.payroll_slips
      ADD CONSTRAINT payroll_slips_perquisites_nonneg
      CHECK (perquisites_in_tds_estimate_paise >= 0);
  END IF;
END $$;

COMMENT ON COLUMN public.payroll_slips.perquisites_in_tds_estimate_paise IS
  'The year''s §17(2) perquisite value that this slip''s §192 estimate was '
  'computed on. NOT part of gross pay — a perquisite is a benefit, not cash, '
  'so it enters the annual salary estimate and nothing else: not net pay, not '
  'the PF wage base, not the ESI gross. Zero on a slip computed before '
  'migration 368, where nothing was considered.';
