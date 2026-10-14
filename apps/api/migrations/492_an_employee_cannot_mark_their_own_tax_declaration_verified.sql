-- Migration 492 — an employee cannot mark their own tax declaration `verified`
-- (found by the 14-10-2026 audit of the browser's direct writes; ledger POST-A-229).
--
-- THE HOLE
--   Migration 297 lets an employee file their own income-tax declaration and guards, by trigger, the COLUMNS a row
--   policy cannot: the verified amounts, `proofs_verified`, `verified_at`, `verified_by` and the keys. It did not
--   guard `status`, whose CHECK allows `verified` (296). So an employee could write their own header as `verified`
--   (components/portal/TaxDeclarationTab.tsx already writes this header under the employee's own sign-in, with
--   `status: "submitted"`). The money does not move: withholding follows `proofs_verified`, which stays guarded. What
--   moves is what people READ: the employee's screen and the staff view show a declaration as verified, and
--   domain/payroll/declarations.py suppresses its "proofs are not verified" notice for it. A statement that someone
--   checked the proofs, made by the person whose proofs they are.
--
-- WHAT THIS DOES
--   Replaces `payroll_declaration_guard_verified_columns()` (297 is its only definer; 337 changed its grants and not
--   its body) with the same body plus one condition in each branch: an employee acting on their own row may not write
--   `status = 'verified'` (on INSERT, or on an UPDATE that moves it there). Staff (Manager and above), the service
--   role and any row that is not the writer's own are unaffected, exactly as before. The item guard has refused
--   `verified` on a line since 297; this is the same rule for the header.
--
-- WHAT IT LEAVES ALONE
--   The function's owner, SECURITY DEFINER, search_path and grants (CREATE OR REPLACE keeps them), the trigger itself,
--   and every policy. No row changes. Reversible: 492_..._rollback.sql restores 297's body.

CREATE OR REPLACE FUNCTION public.payroll_declaration_guard_verified_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
  -- Staff are unaffected. So is anything running as the service role, which
  -- has no auth.uid() and is how the API and the migrations write.
  IF public.my_role_at_least('Manager') THEN
    RETURN NEW;
  END IF;
  IF NEW.employee_id NOT IN (SELECT public.my_employee_ids()) THEN
    RETURN NEW;   -- not an employee acting on their own row; policies decide
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF COALESCE(NEW.rent_paid_verified_paise, 0) <> 0
       OR COALESCE(NEW.lta_verified_paise, 0) <> 0
       OR COALESCE(NEW.home_loan_interest_verified_paise, 0) <> 0
       OR COALESCE(NEW.proofs_verified, FALSE) IS TRUE
       OR NEW.verified_at IS NOT NULL
       OR NEW.verified_by IS NOT NULL
       OR NEW.status = 'verified' THEN
      RAISE EXCEPTION
        'An employee may declare an amount but not verify it. Rule 26C makes '
        'Form 12BB the employee''s statement and the proofs the employer''s to '
        'check; the verified columns belong to whoever checks them.';
    END IF;
    RETURN NEW;
  END IF;

  IF NEW.rent_paid_verified_paise IS DISTINCT FROM OLD.rent_paid_verified_paise
     OR NEW.lta_verified_paise IS DISTINCT FROM OLD.lta_verified_paise
     OR NEW.home_loan_interest_verified_paise IS DISTINCT FROM OLD.home_loan_interest_verified_paise
     OR NEW.proofs_verified IS DISTINCT FROM OLD.proofs_verified
     OR NEW.verified_at IS DISTINCT FROM OLD.verified_at
     OR NEW.verified_by IS DISTINCT FROM OLD.verified_by
     OR (NEW.status = 'verified' AND NEW.status IS DISTINCT FROM OLD.status)
     OR NEW.employee_id IS DISTINCT FROM OLD.employee_id
     OR NEW.firm_id IS DISTINCT FROM OLD.firm_id
     OR NEW.client_id IS DISTINCT FROM OLD.client_id THEN
    RAISE EXCEPTION
      'An employee may declare an amount but not verify it, and may not move '
      'a declaration to another employee, client or firm.';
  END IF;
  RETURN NEW;
END $$;
