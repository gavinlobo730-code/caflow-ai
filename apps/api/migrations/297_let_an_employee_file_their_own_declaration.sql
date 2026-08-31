-- ============================================================================
-- 297 — an employee may file their own declaration, and only their own
--
-- WHY
--     Form 12BB is the EMPLOYEE's statement. Rule 26C requires "the assessee"
--     to furnish it to "the person responsible for paying" — the employee makes
--     the claim, the employer acts on it. Migration 296 created the tables with
--     staff-only write policies (payroll:write is Manager and above), which is
--     right for a CA keying in a paper form but leaves the self-service portal
--     unable to do the one thing it exists for.
--
--     The portal reads payroll_employees, payroll_slips and leave_balances
--     directly through PostgREST under policies keyed on auth.uid() (migration
--     262). Writes go the same way, through the same helper, rather than a new
--     employee-authenticated API surface — one identity model, not two.
--
-- WHAT AN EMPLOYEE MAY DO, AND WHAT THEY MAY NOT
--     They may insert and update THEIR OWN declaration for as long as it is
--     unverified, and read it always. They may not:
--
--       * touch anyone else's — my_employee_ids() returns their own row and no
--         other, and is SECURITY DEFINER so it cannot be widened by the caller;
--       * alter a declaration after the CA has verified the proofs. Once
--         proofs_verified is true the figures have been checked and payroll is
--         withholding on them; letting the employee move them afterwards would
--         let a verified proof carry an unverified amount;
--       * write any *_verified_paise column or set proofs_verified. Those are
--         the verifier's, and an employee who could set them would be verifying
--         their own proofs. Enforced by a trigger rather than a policy, because
--         a row-level policy can test the row but not WHICH COLUMNS changed;
--       * delete anything, ever.
--
-- WHY A TRIGGER AND NOT COLUMN GRANTS
--     Postgres column-level UPDATE privileges would express "not these columns"
--     precisely, but they are granted to a ROLE, and staff and employees are
--     the same `authenticated` role here — the distinction is made by
--     auth.uid(), not by role. So the check has to be per-row, which is what
--     the trigger does.
-- ============================================================================

-- ─── The declaration header ──────────────────────────────────────────────────
-- Replaces 296's three FOR-command restrictive policies with ones that also
-- admit the employee's own row. Staff scoping is unchanged in every arm; the
-- only widening is the employee branch, and only where it is their own.

DROP POLICY IF EXISTS "payroll_it_declarations_role_insert" ON public.payroll_it_declarations;
CREATE POLICY "payroll_it_declarations_role_insert" ON public.payroll_it_declarations
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (
    public.my_role_at_least('Manager')
    OR (employee_id IN (SELECT public.my_employee_ids())
        AND proofs_verified IS FALSE)
  );

DROP POLICY IF EXISTS "payroll_it_declarations_role_update" ON public.payroll_it_declarations;
CREATE POLICY "payroll_it_declarations_role_update" ON public.payroll_it_declarations
  AS RESTRICTIVE FOR UPDATE
  USING (
    public.my_role_at_least('Manager')
    -- USING sees the row as it stands. An employee may only reach a
    -- declaration that has not yet been verified.
    OR (employee_id IN (SELECT public.my_employee_ids())
        AND proofs_verified IS FALSE)
  )
  WITH CHECK (
    public.my_role_at_least('Manager')
    OR (employee_id IN (SELECT public.my_employee_ids())
        AND proofs_verified IS FALSE)
  );

-- DELETE stays Manager-and-above from 296. An employee withdrawing a claim
-- edits it to nil, which leaves a record; deleting it would leave none.

-- The firm scope from 296 is FOR ALL and permissive, and an employee has no
-- firm — get_my_firm_id() is null for them, so `firm_id = null` is null and the
-- row is not granted. Their own permissive grant is added here rather than by
-- loosening the firm rule, which staff still need exactly as it is.
DROP POLICY IF EXISTS "payroll_it_declarations_own_employee" ON public.payroll_it_declarations;
CREATE POLICY "payroll_it_declarations_own_employee" ON public.payroll_it_declarations
  FOR ALL
  USING (employee_id IN (SELECT public.my_employee_ids()))
  WITH CHECK (employee_id IN (SELECT public.my_employee_ids()));


-- ─── The Chapter VI-A lines ──────────────────────────────────────────────────
-- Scoped through the parent declaration: a line is the employee's if the
-- declaration it belongs to is.
CREATE OR REPLACE FUNCTION public.my_it_declaration_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT d.id
  FROM public.payroll_it_declarations d
  WHERE d.employee_id IN (SELECT public.my_employee_ids())
$$;

REVOKE EXECUTE ON FUNCTION public.my_it_declaration_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_it_declaration_ids() TO authenticated;

DROP POLICY IF EXISTS "payroll_it_declaration_items_role_insert" ON public.payroll_it_declaration_items;
CREATE POLICY "payroll_it_declaration_items_role_insert" ON public.payroll_it_declaration_items
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (
    public.my_role_at_least('Manager')
    OR declaration_id IN (SELECT public.my_it_declaration_ids())
  );

DROP POLICY IF EXISTS "payroll_it_declaration_items_role_update" ON public.payroll_it_declaration_items;
CREATE POLICY "payroll_it_declaration_items_role_update" ON public.payroll_it_declaration_items
  AS RESTRICTIVE FOR UPDATE
  USING (
    public.my_role_at_least('Manager')
    OR declaration_id IN (SELECT public.my_it_declaration_ids())
  )
  WITH CHECK (
    public.my_role_at_least('Manager')
    OR declaration_id IN (SELECT public.my_it_declaration_ids())
  );

-- A line, unlike the header, IS deletable by its owner: re-declaring replaces
-- the whole set, and an employee who removed an investment has to be able to
-- remove its line. 296 set DELETE at Partner; widen it to the owner as well.
DROP POLICY IF EXISTS "payroll_it_declaration_items_role_delete" ON public.payroll_it_declaration_items;
CREATE POLICY "payroll_it_declaration_items_role_delete" ON public.payroll_it_declaration_items
  AS RESTRICTIVE FOR DELETE
  USING (
    public.my_role_at_least('Partner')
    OR declaration_id IN (SELECT public.my_it_declaration_ids())
  );

DROP POLICY IF EXISTS "payroll_it_declaration_items_own_employee" ON public.payroll_it_declaration_items;
CREATE POLICY "payroll_it_declaration_items_own_employee" ON public.payroll_it_declaration_items
  FOR ALL
  USING (declaration_id IN (SELECT public.my_it_declaration_ids()))
  WITH CHECK (declaration_id IN (SELECT public.my_it_declaration_ids()));


-- ─── Nobody verifies their own proofs ────────────────────────────────────────
-- The policies above decide WHICH ROWS an employee may write. This decides
-- which COLUMNS, which a row policy cannot express.
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

DROP TRIGGER IF EXISTS payroll_it_declarations_verified_guard
  ON public.payroll_it_declarations;
CREATE TRIGGER payroll_it_declarations_verified_guard
  BEFORE INSERT OR UPDATE ON public.payroll_it_declarations
  FOR EACH ROW EXECUTE FUNCTION public.payroll_declaration_guard_verified_columns();


CREATE OR REPLACE FUNCTION public.payroll_declaration_item_guard_verified_columns()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
BEGIN
  IF public.my_role_at_least('Manager') THEN
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

DROP TRIGGER IF EXISTS payroll_it_declaration_items_verified_guard
  ON public.payroll_it_declaration_items;
CREATE TRIGGER payroll_it_declaration_items_verified_guard
  BEFORE INSERT OR UPDATE ON public.payroll_it_declaration_items
  FOR EACH ROW EXECUTE FUNCTION public.payroll_declaration_item_guard_verified_columns();
