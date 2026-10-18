-- Rollback of migration 519.
-- PART 1: puts the six declaration write policies back on the ROLE (`my_role_at_least`), exactly as migrations 296 and 297 defined
-- them. THIS RE-OPENS the hole it closed: a Manager whom the Team screen has blocked from payroll:write can write an employee's tax
-- declaration directly over the database again.
-- PART 2: gives `authenticated` back the grants production held on 18-10-2026: INSERT, UPDATE and DELETE on client_statutory_identity
-- and client_pt_registrations; DELETE on client_payroll_settings with the column-level INSERT and UPDATE migration 332 left (the three
-- enablement columns stay out of reach). It does NOT restore TRUNCATE, which no migration ever granted (it came from the hosting
-- platform's defaults) and which a signed-in role has no use for; the same goes for the TRUNCATE the migration took from the two
-- declaration tables. PART 1's delete policies go back from `finalize` to the role as well.
DO $$
BEGIN
    IF to_regclass('public.payroll_it_declarations') IS NOT NULL AND to_regclass('public.payroll_it_declaration_items') IS NOT NULL THEN
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
            OR (employee_id IN (SELECT public.my_employee_ids())
                AND proofs_verified IS FALSE)
          )
          WITH CHECK (
            public.my_role_at_least('Manager')
            OR (employee_id IN (SELECT public.my_employee_ids())
                AND proofs_verified IS FALSE)
          );

        DROP POLICY IF EXISTS "payroll_it_declarations_role_delete" ON public.payroll_it_declarations;
        CREATE POLICY "payroll_it_declarations_role_delete" ON public.payroll_it_declarations
          AS RESTRICTIVE FOR DELETE
          USING (public.my_role_at_least('Partner'));

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

        DROP POLICY IF EXISTS "payroll_it_declaration_items_role_delete" ON public.payroll_it_declaration_items;
        CREATE POLICY "payroll_it_declaration_items_role_delete" ON public.payroll_it_declaration_items
          AS RESTRICTIVE FOR DELETE
          USING (
            public.my_role_at_least('Partner')
            OR declaration_id IN (SELECT public.my_it_declaration_ids())
          );
    END IF;
END $$;

-- ===== PART 2 ROLLBACK: the grants (a test that measures the row policies as a signed-in role runs everything below this line) =====
DO $$
BEGIN
    IF to_regclass('public.client_statutory_identity') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.client_statutory_identity TO authenticated;
    END IF;
    IF to_regclass('public.client_pt_registrations') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.client_pt_registrations TO authenticated;
    END IF;
    IF to_regclass('public.client_payroll_settings') IS NOT NULL THEN
        GRANT DELETE ON public.client_payroll_settings TO authenticated;
        GRANT INSERT (id, firm_id, client_id, inputs_due_day, note, updated_by, created_at, updated_at)
            ON public.client_payroll_settings TO authenticated;
        GRANT UPDATE (inputs_due_day, note, updated_by, updated_at) ON public.client_payroll_settings TO authenticated;
    END IF;
END $$;
