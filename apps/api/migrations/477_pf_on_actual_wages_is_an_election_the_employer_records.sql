-- 477 — PF ON ACTUAL WAGES ABOVE THE CEILING IS AN ELECTION THE EMPLOYER RECORDS (payroll-22)
--
-- WHAT WAS WRONG
--   `_compute_pf` capped the employee's 12% and the employer's 12% at the Rs 15,000
--   ceiling for every employee, and `domain/payroll/ecr.py` capped the EPF wage on
--   the ECR the same way. Many employers contribute on the whole of the wage:
--   EPF Scheme 1952 para 26(6) lets an employee and the employer jointly do so.
--   Nothing on the employee master could say it, so such an employer's payroll
--   under-deducted, its ledger under-accrued and its return declared the wrong EPF
--   wage, with no way to put it right short of editing a file by hand.
--
-- [S] — THE LAW IS SECONDARY-SOURCED AND SAYS SO
--   This environment's egress is refused, so para 26(6), the EPS and EDLI ceilings
--   and the base of the administrative charge are written from knowledge. What
--   nobody has read is whether the joint request is REQUIRED in law in every case,
--   what form it takes, and whether EPFO accepts it for a given member. So the
--   product records the EMPLOYER'S ASSERTION and nothing cleverer: it never checks
--   the request exists and never infers an election from wages
--   (domain/payroll/pf_wage_election.py, VERIFIED = False).
--
-- THE FOUR COLUMNS
--   payroll_employees.pf_on_actual_wages            boolean, NULL
--       NULL  : never recorded — the statutory default, the ceiling.
--       true  : the employer has elected.
--       false : an election was recorded and has been withdrawn.
--     NO DEFAULT AND NO BACKFILL. NULL and false compute identically; they differ
--     because "nobody said" and "somebody withdrew it" are different facts to read
--     back (`vendors.msme_status`, `fixed_assets.rule_43_use`). Every employee that
--     exists today is NULL and computes exactly what it computed yesterday.
--   payroll_employees.pf_on_actual_wages_from       date, NULL
--     The date the election takes effect. A payroll month ENDING before it stays
--     capped (a month is paid as one thing — the test `wage_base.rule_in_force`
--     applies to 21-11-2025), so a draft recomputed after the election was
--     recorded does not reach back before the request. NULL means every month.
--   payroll_employees.pf_on_actual_wages_reference  text, NULL
--     The employer's own words about where the joint request is kept. Not a URL,
--     not an upload: no document workflow is built here.
--   payroll_slips.pf_on_actual_wages                boolean NOT NULL DEFAULT false
--     Whether THIS slip's contribution was computed on actual wages. The ECR is a
--     return of what was remitted, so it reads this and never the employee row,
--     which can change after a month is finalised. DEFAULTED AND NOT NULL, unlike
--     the master's column, because the value is KNOWN for every existing slip:
--     nothing could elect before this migration, so false is true of all of them.
--
-- PER EMPLOYEE, NOT PER CLIENT OR FIRM
--   The request is joint and EPFO treats contribution above the ceiling as a fact
--   about the member. A client-wide switch would decide for every employee,
--   including the ones who never asked and the ones hired next year.
--
-- WHAT THE CHECKS ARE, AND WHY THEY ARE THE SAME ONES THE API ASKS
--   * An election needs PF to apply: `pf_on_actual_wages IS NOT TRUE OR pf_applicable`.
--   * A date or a reference belongs only to an election that is true.
--   * A reference is non-blank and at most 200 characters.
--   * The date is not before 1952 (the Scheme itself): the typo "1926" for "2026"
--     would otherwise read as "applies to every month".
--   All four are vacuous for every row that exists (the columns are new and NULL),
--   so none of them can fail the production apply. The API asks the same rules in
--   sentences first (`pf_wage_election.problems` at create, `plan_update` at PATCH);
--   these are the last line for a write that skipped it.
--
-- NOT DONE, AND NAMED
--   The higher-pension option under EPS para 11(3) (a different joint option with
--   EPFO), contribution on an amount between the ceiling and actual wages, a
--   document store for the joint request, and an importer column — the election is
--   recorded one employee at a time because it is an assertion somebody makes.
--
-- ADDITIVE AND IDEMPOTENT
--   Four ADD COLUMN IF NOT EXISTS and four guarded constraints. Rollback is
--   477_..._rollback.sql and DISCARDS every recorded election.

BEGIN;

ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS pf_on_actual_wages            boolean,
  ADD COLUMN IF NOT EXISTS pf_on_actual_wages_from       date,
  ADD COLUMN IF NOT EXISTS pf_on_actual_wages_reference  text;

ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_on_actual_wages boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.payroll_employees.pf_on_actual_wages IS
  'payroll-22. The EMPLOYER''S recorded election to contribute PF on the whole PF '
  'wage rather than the statutory ceiling (EPF Scheme 1952 para 26(6), a joint '
  'request of employee and employer; the reading is unverified, [S]). NULL = never '
  'recorded (the ceiling), true = elected, false = recorded and withdrawn; NULL and '
  'false compute alike. Never inferred from wages and never checked against a '
  'document. EPS wages, EDLI wages and the EDLI limit stay at the ceiling either way.';
COMMENT ON COLUMN public.payroll_employees.pf_on_actual_wages_from IS
  'payroll-22. The date the PF election takes effect. A payroll month ending before '
  'it is computed on the ceiling. NULL with an election = every month. Held only '
  'while pf_on_actual_wages is true.';
COMMENT ON COLUMN public.payroll_employees.pf_on_actual_wages_reference IS
  'payroll-22. The employer''s own reference for the joint request (where it is '
  'kept). Free text, at most 200 characters; not a link and not an upload. Held '
  'only while pf_on_actual_wages is true.';
COMMENT ON COLUMN public.payroll_slips.pf_on_actual_wages IS
  'payroll-22. TRUE when this slip''s PF contributions were computed on actual '
  'wages above the ceiling by the employer''s election. Stored with the figures it '
  'produced so the ECR declares what was remitted and not what the employee row '
  'says today. False on every slip written before migration 477.';

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_employees_pf_election_needs_pf') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_pf_election_needs_pf
      CHECK (pf_on_actual_wages IS NOT TRUE OR pf_applicable IS TRUE);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_employees_pf_election_detail_needs_election') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_pf_election_detail_needs_election
      CHECK ((pf_on_actual_wages_from IS NULL AND pf_on_actual_wages_reference IS NULL)
             OR pf_on_actual_wages IS TRUE);
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_employees_pf_election_reference_shape') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_pf_election_reference_shape
      CHECK (pf_on_actual_wages_reference IS NULL
             OR (length(btrim(pf_on_actual_wages_reference)) BETWEEN 1 AND 200));
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_employees_pf_election_date_plausible') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_pf_election_date_plausible
      CHECK (pf_on_actual_wages_from IS NULL
             OR pf_on_actual_wages_from >= DATE '1952-01-01');
  END IF;
END $$;

COMMIT;
