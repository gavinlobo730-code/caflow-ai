-- Migration 333: an employee has a CODE the CA already uses for them, and a
-- DATE OF BIRTH the Income-tax Act reads.
--
-- Payroll v1 item 1.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. employee_code — the identity the import is idempotent on
-- ═══════════════════════════════════════════════════════════════════════════
-- Every client already identifies its staff by something: EMP001, a payroll
-- number off the previous software, a branch prefix. Nothing here held it, so
-- the only handle on an employee was the row's UUID — which the CA has never
-- seen and cannot type.
--
-- That is why the bulk import could not be idempotent. Re-importing a corrected
-- file created a second Asha Rao beside the first, and neither the file nor this
-- table had a key that said they were the same person. A payroll with a
-- duplicated employee pays them twice, files them twice on the ECR under one
-- UAN, and issues two Form 16s.
--
-- UNIQUE PER CLIENT, NOT PER FIRM. The code is the CLIENT's, not the practice's,
-- and two clients of the same firm will both have an EMP001. Partial, because
-- the column is nullable: an employee added by hand before this migration has
-- no code, and NULLs do not collide.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 2. date_of_birth — this is not demographics, it changes the withholding
-- ═══════════════════════════════════════════════════════════════════════════
-- Part III of the First Schedule gives a resident individual "of the age of
-- sixty years or more at any time during the previous year" a basic exemption
-- of Rs 3,00,000 under the OLD regime, and Rs 5,00,000 at eighty. The engine
-- already implements all three ladders — domain/income_tax/itr_engine.py
-- _slabs_for reads ITRComputeRequest.is_senior_citizen and
-- is_very_senior_citizen — and domain/payroll/declarations._build_request never
-- set either of them, because payroll had no way to know.
--
-- So an employee of 62 who intimated the old regime was withheld on the general
-- ladder: a nil band of Rs 2,50,000 instead of Rs 3,00,000, over-deducted every
-- month, and refunded a year later on assessment. s.192(1) makes the employer
-- answerable for a correct deduction and this was not one.
--
-- "At any time during the previous year" is the statutory test and it is not
-- "on 1 April": someone who turns 60 in March is a senior citizen for the WHOLE
-- of that year. domain/payroll/age.py is the authority and the tests pin the
-- March birthday specifically.
--
-- Nullable, and the code REFUSES to guess: an employee with no date of birth is
-- withheld on the general ladder, which is what happens today, and the gap is
-- reported rather than assumed away.

BEGIN;

ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS employee_code  text,
  ADD COLUMN IF NOT EXISTS date_of_birth  date;

COMMENT ON COLUMN public.payroll_employees.employee_code IS
    'The identifier this CLIENT uses for the employee — EMP001, a number off '
    'their previous payroll software. Unique per client where present, which '
    'is what makes the bulk import idempotent: a re-imported row with a code '
    'already on file UPDATES that employee rather than creating a second one. '
    'Nullable, because employees added by hand before migration 333 have none. '
    'Migration 333, payroll v1 item 1.';

COMMENT ON COLUMN public.payroll_employees.date_of_birth IS
    'Date of birth. NOT demographics — it decides the s.192 withholding ladder: '
    'Part III of the First Schedule gives a resident of sixty or more AT ANY '
    'TIME during the previous year a wider nil band under the old regime, and '
    'wider still at eighty. NULL means unknown and the general ladder is used, '
    'which is what happened for every employee before this column existed. '
    'Migration 333, payroll v1 item 1.';

-- Partial unique: NULL codes do not collide with each other, and two clients of
-- the same firm may both have an EMP001.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_employees_client_code_uniq
    ON public.payroll_employees (client_id, employee_code)
    WHERE employee_code IS NOT NULL;

-- A code of '' is not a code. Without this the import's idempotency key becomes
-- the empty string for every row a spreadsheet left blank, and the partial index
-- above would then reject the SECOND such employee as a duplicate of the first.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_employees_employee_code_not_blank') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_employee_code_not_blank
      CHECK (employee_code IS NULL OR length(btrim(employee_code)) > 0);
  END IF;
END $$;

-- A date of birth in the future, or before 1900, is a mis-keyed year rather than
-- a person. Both directions are checked because '2062-05-01' for '1962-05-01' is
-- the typo this catches, and it would otherwise make a 62-year-old a minor.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'payroll_employees_date_of_birth_plausible') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_date_of_birth_plausible
      CHECK (date_of_birth IS NULL
             OR (date_of_birth > DATE '1900-01-01' AND date_of_birth < CURRENT_DATE));
  END IF;
END $$;

COMMIT;
