-- Rollback of migration 515: gives `authenticated` back the write privileges the earlier migrations granted.
-- THIS RE-OPENS TWO THINGS: a Manager the Team screen has blocked from payroll:write can change an employee's leave allotment
-- directly over the database again, and a signed-in browser can again write an entry in a client's activity feed naming any actor
-- it likes. It restores INSERT, UPDATE and DELETE on leave_balances (migrations 027 and 041) and INSERT on client_timeline_events
-- (migration 187b), exactly as production held them on 18-10-2026. It does NOT restore TRUNCATE, which no migration ever granted
-- (it came from the hosting platform's defaults) and which a signed-in role has no use for.
DO $$
BEGIN
    IF to_regclass('public.leave_balances') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.leave_balances TO authenticated;
    END IF;
    IF to_regclass('public.client_timeline_events') IS NOT NULL THEN
        GRANT INSERT ON public.client_timeline_events TO authenticated;
    END IF;
END $$;
