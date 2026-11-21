-- Migration 776: an employee of the firm's own payroll names the team member they are (POST-A-540).
--
-- WHAT WAS MISSING
--   A member of the firm's staff is two records: a sign-in on the Team screen (`users`) and, since the firm runs its own
--   staff's payroll on the practice client (POST-A-532), an employee row there (`payroll_employees`). Nothing said the two
--   were one person, so a Partner who invited somebody had not added a paid employee, and the reverse, and a name could be
--   spelt two ways with nothing to show it.
--
-- WHAT THIS ADDS
--   `payroll_employees.staff_user_id`: the INTERNAL id (`users.id`, never the auth id) of the team member this employee is.
--   NULL = not linked, which is every row today and every employee of a client for good.
--
--   A LINK, NEVER A MERGE. Neither record is written from the other: a sign-in is the firm's and an employee row is
--   payroll's, with different readers (the Team list is a Manager's and above, the firm's own payroll is a Partner's alone,
--   guardrail G4). The column is on the payroll side on purpose: only whoever may read the firm's payroll can read that a
--   member is on it.
--
--   THREE RULES THE DATABASE HOLDS, each also asked by the API in a sentence before it writes:
--     1. the member is of the row's own firm (`guard_member_firm`, migration 566);
--     2. one member is at most one employee (the partial unique index);
--     3. the employee is in the firm's OWN payroll: a client's employee is not a member of the firm's staff (the trigger).
--
--   `payroll_employees.auth_user_id` (migration 031) is NOT this: it is the employee portal's sign-in, a different principal
--   that has no `users` row.
--
-- No row changes. The table is the API's alone since migration 549, so nothing a signed-in session can do changes with this.
-- ON DELETE SET NULL: a member hard-deleted from the firm leaves the employee row, unlinked.
-- Reversible: 776_an_employee_of_the_firms_own_payroll_names_the_team_member_they_are_rollback.sql.

ALTER TABLE public.payroll_employees
    ADD COLUMN IF NOT EXISTS staff_user_id UUID REFERENCES public.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.payroll_employees.staff_user_id IS
    'POST-A-540. The team member (users.id, the internal id) this employee of the firm''s own payroll is. NULL = not linked. '
    'A link, never a merge; set only on an employee of the firm''s practice client. Migration 776.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_employees_staff_user
    ON public.payroll_employees (staff_user_id)
    WHERE staff_user_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.a_staff_link_is_on_the_firms_own_payroll()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.staff_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.firms f
         WHERE f.id = NEW.firm_id AND f.internal_client_id IS NOT NULL AND f.internal_client_id = NEW.client_id
    ) THEN
        RAISE EXCEPTION 'a team member is linked only to an employee of the firm''s own payroll'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.a_staff_link_is_on_the_firms_own_payroll() IS
    'POST-A-540. Refuses payroll_employees.staff_user_id on a row whose client is not the firm''s own practice. Migration 776.';

REVOKE ALL ON FUNCTION public.a_staff_link_is_on_the_firms_own_payroll() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS a_staff_link_is_on_the_firms_own_payroll ON public.payroll_employees;
CREATE TRIGGER a_staff_link_is_on_the_firms_own_payroll
    BEFORE INSERT OR UPDATE OF staff_user_id, client_id, firm_id ON public.payroll_employees
    FOR EACH ROW EXECUTE FUNCTION public.a_staff_link_is_on_the_firms_own_payroll();

DO $$
BEGIN
    -- Re-run so the member-of-the-firm triggers cover the new column (the function reads the table's foreign keys to users).
    PERFORM public.guard_member_firm('public.payroll_employees');
END $$;
