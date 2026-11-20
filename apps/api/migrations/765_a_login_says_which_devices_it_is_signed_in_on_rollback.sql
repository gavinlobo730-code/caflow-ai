-- Rollback of migration 765. Drops the record of which devices a login was signed in on and the "sign out other sessions" marks, takes
-- the second_device notice type out (any such notification already written is removed first, or the narrower constraint could not be
-- added), and drops login_events.session_id. Sign-ins are still recorded, without a session id; nothing else in the API depends on these.
-- ORDER: if migration 773 (POST-A-509) is applied, roll IT back first. The database's row-security helpers read the two "sign out other
-- sessions" columns this file drops, and without them every helper call, and so every request row security checks, fails.
BEGIN;
DELETE FROM public.notifications WHERE type = 'second_device';
ALTER TABLE public.notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE public.notifications
    ADD CONSTRAINT notifications_type_check CHECK (type IN (
        'task_assigned', 'risk_detected', 'document_processed',
        'compliance_due', 'ai_recommendation', 'status_changed',
        'task_reassigned', 'due_soon', 'overdue', 'task_overdue',
        'recurring_generated',
        'workflow',
        'portal_message'
    ));
ALTER TABLE public.users DROP COLUMN IF EXISTS other_sessions_kept_session_id;
ALTER TABLE public.users DROP COLUMN IF EXISTS other_sessions_revoked_at;
DROP TABLE IF EXISTS public.login_sessions;
ALTER TABLE public.login_events DROP COLUMN IF EXISTS session_id;
COMMIT;
