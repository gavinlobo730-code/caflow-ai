-- ============================================================================
-- 295 — store the EPS/EPF split on the payslip, and whose EPS it is
--
-- WHY
--     Migration-free until now: _compute_pf splits the employer's 12% into EPS
--     and EPF, but payroll_slips keeps only pf_employer_paise, the total. The
--     EPFO's ECR return needs them apart — its eleven fields carry EPF WAGES,
--     EPS WAGES, EPF CONTRI REMITTED, EPS CONTRI REMITTED and the difference
--     between the two contributions as separate columns per member. Recomputing
--     the split at file-generation time from a stored total would be a second
--     implementation of the same rule, and the two would drift the first time a
--     ceiling moved. The slip stores what was actually contributed.
--
--     EDLI and the administrative charge are stored for the same reason. They
--     are employer costs outside the 12%, deducted from nobody, and the ECR
--     challan carries them.
--
-- EPS_ELIGIBLE IS A FIELD, NOT A DERIVATION, AND THAT IS DELIBERATE
--     EPS 1995 ¶6 as amended by GSR 609(E) closed the pension scheme, from
--     01-09-2014, to anyone joining EPF on or after that date whose pay AT
--     JOINING exceeded ₹15,000. Such a member gets no EPS at all: the whole
--     employer 12% goes to EPF. Existing members carried on regardless of later
--     pay rises.
--
--     It is tempting to derive that from joining_date and basic_paise, and it
--     would be wrong. The test is pay at the time of JOINING, and the employee
--     master holds only pay TODAY — so someone who joined below the ceiling in
--     2016 and earns ₹40,000 now would be silently thrown out of a pension
--     scheme they are entitled to, and their ₹1,250 a month misdirected to EPF
--     on a filed return. A default of TRUE with the CA able to say otherwise
--     states the common case and leaves the exception visible, rather than
--     inferring a statutory status from data that cannot support it.
--
--     TRUE is the right default: it is the position for every member who
--     joined before 01-09-2014 and for everyone who joined below the ceiling
--     since, which is the large majority.
--
-- Additive and idempotent. No backfill: every existing slip already has its
-- pf_employer_paise, and splitting it retrospectively would be inventing a
-- figure for a period nobody filed from this system.
-- ============================================================================

ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS eps_eligible boolean NOT NULL DEFAULT true;

COMMENT ON COLUMN public.payroll_employees.eps_eligible IS
  'Member of the Employees Pension Scheme 1995. FALSE only where EPS 1995 para 6 '
  '(as amended by GSR 609(E), w.e.f. 01-09-2014) excludes them: joined EPF on or '
  'after that date with pay at joining above the wage ceiling. Not derived — the '
  'test is pay AT JOINING and the master holds pay today.';

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_employer_eps_paise bigint NOT NULL DEFAULT 0;
ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_employer_epf_paise bigint NOT NULL DEFAULT 0;
ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS edli_paise            bigint NOT NULL DEFAULT 0;
ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_admin_paise        bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.payroll_slips.pf_employer_eps_paise IS
  'EPS 1995 para 3: 8.33% of EPS wages, capped at 8.33% of the ceiling. Part of '
  'the employer 12% in pf_employer_paise, not additional to it.';
COMMENT ON COLUMN public.payroll_slips.pf_employer_epf_paise IS
  'The employer 12% minus the EPS diversion. Together with pf_employer_eps_paise '
  'this sums exactly to pf_employer_paise.';
COMMENT ON COLUMN public.payroll_slips.edli_paise IS
  'EDLI 1976: 0.5% of PF wages, ceiling 15,000. Employer cost OUTSIDE the 12%.';
COMMENT ON COLUMN public.payroll_slips.pf_admin_paise IS
  'EPF administrative charges, 0.5% of PF wages. Employer cost OUTSIDE the 12%. '
  'The statutory minimum of 500 a month is per ESTABLISHMENT, so it is applied '
  'to the run total and never to one slip.';
