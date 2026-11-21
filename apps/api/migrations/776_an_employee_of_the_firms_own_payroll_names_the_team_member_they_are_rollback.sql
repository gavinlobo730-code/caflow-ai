-- Rollback of migration 776: drops the link between an employee of the firm's own payroll and a team member. Every link recorded in the
-- meantime is lost; neither record is otherwise changed (the link never wrote one from the other).

DROP TRIGGER IF EXISTS a_staff_link_is_on_the_firms_own_payroll ON public.payroll_employees;
DROP FUNCTION IF EXISTS public.a_staff_link_is_on_the_firms_own_payroll();
DROP INDEX IF EXISTS public.uq_payroll_employees_staff_user;

-- The member-of-the-firm triggers name the column (migration 566 builds them from the table's foreign keys to users), so they go
-- first and are rebuilt below from the keys that are left.
DROP TRIGGER IF EXISTS row_member_in_firm_ins ON public.payroll_employees;
DROP TRIGGER IF EXISTS row_member_in_firm_upd ON public.payroll_employees;

ALTER TABLE public.payroll_employees
    DROP COLUMN IF EXISTS staff_user_id;

DO $$
BEGIN
    -- The member-of-the-firm triggers are rebuilt from the foreign keys that are left.
    PERFORM public.guard_member_firm('public.payroll_employees');
END $$;
