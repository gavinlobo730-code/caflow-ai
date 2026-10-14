-- Rollback of migration 492: restores migration 297's body of payroll_declaration_guard_verified_columns(), which does
-- not guard `status`. THIS RE-OPENS THE HOLE: an employee can again mark their own declaration verified.

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
       OR NEW.verified_by IS NOT NULL THEN
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
     OR NEW.employee_id IS DISTINCT FROM OLD.employee_id
     OR NEW.firm_id IS DISTINCT FROM OLD.firm_id
     OR NEW.client_id IS DISTINCT FROM OLD.client_id THEN
    RAISE EXCEPTION
      'An employee may declare an amount but not verify it, and may not move '
      'a declaration to another employee, client or firm.';
  END IF;
  RETURN NEW;
END $$;
