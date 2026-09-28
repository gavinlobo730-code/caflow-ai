-- 430: client_instructions has no is_archived, and archiving one writes it.
--
-- WHY
--   routers/knowledge.py's POST .../instructions/{id}/archive, and the
--   PATCH beside it, hand {"is_archived": true} to
--   services/knowledge_service.update_instruction, which has allowed that key
--   since it was written -- and public.client_instructions (migration 073)
--   never had the column. Its columns are id, firm_id, client_id, title, body,
--   is_pinned, created_by, created_at, updated_at, confirmed against
--   production on 27-09-2026. So every archive answers PostgREST's PGRST204
--   ("could not find the 'is_archived' column"), which reached the browser as
--   a 400 in every client workspace AND on the practice's own standing
--   instructions, and the screen swallowed it (ClientInstructions.tsx's
--   `catch {}`), so the item simply stayed.
--
--   knowledge_articles, the sibling table built in the same migration, has
--   carried is_archived from the start; this is the half 073 left out.
--
-- WHAT THIS DOES
--   Adds is_archived boolean NOT NULL DEFAULT false. Safe on existing data by
--   construction: production held 2 rows (1 firm) on 27-09-2026, and adding a
--   column with a constant default fills every existing row with it without a
--   rewrite on Postgres 11+, so every instruction written so far reads as NOT
--   archived -- which is what each of them is, since no archive has ever
--   succeeded. ADD COLUMN IF NOT EXISTS so a re-run is a no-op.
--
--   The readers filter it: knowledge_service.list_client_instructions answers
--   live instructions only; the browser's own PostgREST read belongs to the
--   frontend change. No new grant is needed -- `authenticated` holds
--   table-level SELECT/INSERT/UPDATE on client_instructions, which covers a
--   new column, and every RLS policy on the table is row-level.
--
--   No index: the table is read per (firm_id, client_id), which
--   idx_client_instructions_firm_client already serves, and a client carries a
--   handful of instructions, so filtering the archived few is free.

BEGIN;

ALTER TABLE public.client_instructions
    ADD COLUMN IF NOT EXISTS is_archived boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.client_instructions.is_archived IS
    'An archived standing instruction is kept (it is part of the client''s '
    'history) and hidden from the live list. Migration 430 added it: the '
    'archive endpoint had been writing a column that did not exist.';

COMMIT;
