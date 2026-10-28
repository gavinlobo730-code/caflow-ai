-- Migration 554 — the two declaration guard triggers ask the per-person grid who is staff
-- (ledger POST-A-219, the part migrations 519 left open; found by an independent read of 519 on 18-10-2026).
--
-- THE HOLE (narrow, and not a regression)
--   Migration 519 changed the staff arm of the six restrictive write policies on `payroll_it_declarations` and
--   `payroll_it_declaration_items` from `my_role_at_least('Manager')` to `my_permission('payroll','write','Manager')`, so that a
--   Partner's per-person block on the Team screen is honoured by the database. The two TRIGGERS that guard the verified columns
--   (297; 492 for the header) still opened with `IF public.my_role_at_least('Manager') THEN RETURN NEW`. So a Manager whom a Partner
--   had blocked from payroll:write, and who is ALSO the linked principal of an employee row (the employee portal's sign-in),
--   skipped the guard on their own row: the policies let them write their own declaration through the employee arm, and the
--   guard that exists to stop an employee verifying their own amounts did not run for them. They could write
--   `rent_paid_verified_paise`, `lta_verified_paise`, `home_loan_interest_verified_paise`, `proofs_verified`, `verified_at`,
--   `verified_by` and `status = 'verified'`, and an item's `amount_verified_paise` and `status = 'verified'`. Withholding follows
--   `proofs_verified`, so a falsely verified declaration reduces the tax deducted from that one person's pay.
--
-- WHAT THIS DOES
--   Replaces `payroll_declaration_guard_verified_columns()` (492 is its last definer) and
--   `payroll_declaration_item_guard_verified_columns()` (297 is its only definer; 337 changed its grants and not its body) with the
--   same bodies and ONE change each: the staff exemption asks `my_permission('payroll', 'write', 'Manager')`, the question the
--   policies ask. THE FLOOR IS UNCHANGED (a Manager with no grid row is staff, exactly as before; production holds no grid rows), so
--   nothing changes for anybody the grid has not been used on. With the grid refusing payroll:write for a person, that person is
--   no longer staff to the guard and, when they are also the employee on the row, may declare an amount but not verify it. With the
--   grid granting payroll:write to someone below Manager, they ARE staff to the guard, as they are to the policies.
--   The service role has no auth.uid(), is not staff by either question, and passes at the next test (it is not an employee acting
--   on their own row), which is how the API and the migrations write; that is why this cannot cut off the API.
--
-- WHAT IT LEAVES ALONE
--   Owner, SECURITY DEFINER, search_path and grants (CREATE OR REPLACE keeps them), both triggers, every policy, and every row.
--   Reversible: 554_..._rollback.sql restores 492's body and 297's body.

CREATE OR REPLACE FUNCTION public.payroll_declaration_guard_verified_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
  -- Staff are unaffected, STAFF BEING WHAT THE POLICIES ON THESE TABLES MEAN BY IT: someone whom the per-person grid lets write
  -- payroll (migration 519 changed the policies' staff arm to this very question). Asking the role here let a Manager a Partner had
  -- blocked from payroll:write, who is also the linked principal of an employee row, skip the guard and write their own verified
  -- columns. Anything running as the service role has no auth.uid(), so it is not staff by this question either; it falls to the
  -- next test, which is not an employee acting on their own row, and passes there, which is how the API and the migrations write.
  IF public.my_permission('payroll', 'write', 'Manager') THEN
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

CREATE OR REPLACE FUNCTION public.payroll_declaration_item_guard_verified_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
  -- Staff as the policies mean it (see the declaration guard above): the grid's answer for payroll:write, floor Manager.
  IF public.my_permission('payroll', 'write', 'Manager') THEN
    RETURN NEW;
  END IF;
  IF NEW.declaration_id NOT IN (SELECT public.my_it_declaration_ids()) THEN
    RETURN NEW;
  END IF;

  IF COALESCE(NEW.amount_verified_paise, 0) <> 0 THEN
    RAISE EXCEPTION
      'An employee may declare an amount but not verify it.';
  END IF;
  -- 'verified' is the verifier's word. An employee may leave a line declared
  -- or, on a re-declaration, mark it rejected — neither grants relief.
  IF NEW.status = 'verified' THEN
    RAISE EXCEPTION
      'Only whoever checked the proof may mark a line verified.';
  END IF;
  RETURN NEW;
END $$;

-- The closing check: both bodies ask the grid and neither asks the role any more.
DO $$
DECLARE
  fn text;
BEGIN
  FOREACH fn IN ARRAY ARRAY[
    'public.payroll_declaration_guard_verified_columns()',
    'public.payroll_declaration_item_guard_verified_columns()'
  ] LOOP
    IF position('my_permission' IN pg_get_functiondef(fn::regprocedure)) = 0
       OR position('my_role_at_least' IN pg_get_functiondef(fn::regprocedure)) > 0 THEN
      RAISE EXCEPTION 'migration 554: % does not ask the grid for staff', fn;
    END IF;
  END LOOP;
END $$;
