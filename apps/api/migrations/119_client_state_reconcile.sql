-- Migration 119: reconcile client lifecycle mirror columns
-- The canonical lifecycle fields are status ('archived') and deleted_at (NULL = live).
-- is_archived/is_deleted are derived mirrors used by partial indexes. This migration
-- repairs any historical drift so the mirrors exactly match the canonical fields.
-- Idempotent and safe to re-run.

UPDATE public.clients
   SET is_archived = (status = 'archived')
 WHERE is_archived IS DISTINCT FROM (status = 'archived');

UPDATE public.clients
   SET is_deleted = (deleted_at IS NOT NULL)
 WHERE is_deleted IS DISTINCT FROM (deleted_at IS NOT NULL);
