-- Migration 122: Widen notifications.type CHECK constraint
--
-- Problem: notifications.type CHECK was frozen at 6 values from migration 004
-- ('task_assigned','risk_detected','document_processed','compliance_due',
--  'ai_recommendation','status_changed'). Every other notification type in
-- notification_service.py, escalation_service.py, and compliance_obligation_service.py
-- would cause a CHECK constraint violation → silent write failure in production,
-- meaning CAs receive ZERO notifications for overdue tasks, reassignments, and
-- compliance deadlines.
--
-- Fix: drop the old constraint and replace with one covering all types in use.
-- Idempotent (constraint name is deterministic; DROP IF EXISTS guards the old name).

ALTER TABLE public.notifications
  DROP CONSTRAINT IF EXISTS notifications_type_check;

ALTER TABLE public.notifications
  ADD CONSTRAINT notifications_type_check CHECK (type IN (
    -- original 6 types
    'task_assigned',
    'risk_detected',
    'document_processed',
    'compliance_due',
    'ai_recommendation',
    'status_changed',
    -- task lifecycle (notification_service.py + escalation_service.py)
    'task_reassigned',
    'due_soon',
    'overdue',
    'task_overdue',
    'recurring_generated'
  ));

COMMENT ON CONSTRAINT notifications_type_check ON public.notifications IS
  'All notification types emitted by notification_service, escalation_service, '
  'and compliance_obligation_service. Widened in migration 122.';
