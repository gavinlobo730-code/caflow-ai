-- Rollback for 450. DISCARDS every recorded send and every person's email
-- preference, and restores migration 157's notifications_type_check.
--
-- A notification of type 'portal_message' already written would FAIL the
-- restored CHECK, so those rows are removed first. They are in-app notices
-- about a message that is itself still on portal_messages; nothing else
-- references them.
--
-- document_requests.due_date is dropped, which loses any "needed by" date a CA
-- typed since 450 landed. The POST door that declared the field then fails
-- again on every call, exactly as it did before 450 — roll the code back with
-- this file.

BEGIN;

DELETE FROM public.notifications WHERE type = 'portal_message';

ALTER TABLE public.notifications
    DROP CONSTRAINT IF EXISTS notifications_type_check;

ALTER TABLE public.notifications
    ADD CONSTRAINT notifications_type_check CHECK (type IN (
        'task_assigned', 'risk_detected', 'document_processed',
        'compliance_due', 'ai_recommendation', 'status_changed',
        'task_reassigned', 'due_soon', 'overdue', 'task_overdue',
        'recurring_generated',
        'workflow'
    ));

DROP INDEX IF EXISTS public.idx_portal_messages_unread_from_client;

ALTER TABLE public.document_requests DROP COLUMN IF EXISTS due_date;

DROP TABLE IF EXISTS public.practice_email_log;
DROP TABLE IF EXISTS public.user_notification_preferences;

COMMIT;
