-- Migration 114: Client archive and deletion lifecycle fields
--
-- The existing status = 'archived' and deleted_at patterns are preserved for
-- backward-compatible queries. These new fields add:
--   • is_archived / is_deleted  — boolean flags for index-friendly filtering
--   • archived_at / archived_by — when/who archived (audit trail)
--   • deleted_by                — who performed the soft-delete (deleted_at already existed)
--
-- Backfills sync the boolean flags with pre-existing status/deleted_at values.

ALTER TABLE public.clients
    ADD COLUMN IF NOT EXISTS is_archived  BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS archived_at  TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS archived_by  UUID        NULL,
    ADD COLUMN IF NOT EXISTS is_deleted   BOOLEAN     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_by   UUID        NULL;

-- Backfill: mark rows that were archived before this migration
UPDATE public.clients
SET    is_archived = true
WHERE  status = 'archived'
AND    is_archived = false;

-- Backfill: mark rows that were soft-deleted before this migration
UPDATE public.clients
SET    is_deleted = true
WHERE  deleted_at IS NOT NULL
AND    is_deleted = false;

-- Index: active clients by firm — the most common list query
CREATE INDEX IF NOT EXISTS idx_clients_firm_active
    ON public.clients (firm_id, client_name)
    WHERE is_archived = false AND is_deleted = false AND deleted_at IS NULL;

-- Index: archived clients by firm (for the "Archived" filter view)
CREATE INDEX IF NOT EXISTS idx_clients_firm_archived_flag
    ON public.clients (firm_id, archived_at DESC)
    WHERE is_archived = true AND deleted_at IS NULL;
