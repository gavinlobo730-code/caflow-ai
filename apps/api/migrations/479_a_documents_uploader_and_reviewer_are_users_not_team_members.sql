-- Migration 479 — a document's uploader and reviewer are people in `users`,
-- not rows of `team_members` (PRE-A-012).
--
-- THE BUG
--   Migration 001 declared
--
--       documents.uploaded_by UUID REFERENCES team_members(id)
--       documents.reviewed_by UUID REFERENCES team_members(id)
--
--   `team_members` is the early schema's staff table. Nothing in the product has
--   written to it since `users` replaced it (migration 014 onwards), and in
--   production it holds ZERO rows (read-only look, 2 October 2026). The only
--   writer of `documents`, POST /api/documents/upload, stamps `uploaded_by` with
--   the caller's identity, so every upload that reaches the database violates
--   the foreign key (SQLSTATE 23503) and fails. `documents` has held zero rows
--   in production for the same reason: no upload has ever succeeded. The one
--   screen that calls the route is the bank entry modal's "attach a receipt", so
--   attachments on bank lines have never worked in production.
--
--   `client_documents` (migration 023) was built after the problem was found
--   and references `public.users(id)` — the same shape as every other
--   created_by / posted_by / uploaded_by column in the schema (CLAUDE.md:
--   "`created_by` / `posted_by` FK to `public.users.id` (the internal user id),
--   not the Supabase auth id").
--
-- WHAT THIS DOES
--   Repoints both columns at `public.users(id)`. The route changes in the same
--   commit to write the internal user id (`current_user["id"]`) and no longer
--   writes the Supabase auth id, which matches no `users.id` and would be
--   refused by the new foreign key as well.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * `documents.deleted_by` has no foreign key (it never had one) and is not
--     given one: a soft delete must not fail over who did it, and the audit
--     log already names the actor.
--   * No row is rewritten and none is deleted. The constraints are added NOT
--     VALID and then validated in a block that tolerates a failure: a row
--     written before this migration cannot be pointing at a `users.id` (the old
--     constraint admitted only `team_members` ids), so on a database that holds
--     such a row the constraint keeps protecting every NEW write and the old row
--     is left exactly as it was, with a notice, rather than the migration — and
--     with it the deploy — failing. Production has no row at all.
--   * Whether to retire `documents` in favour of `client_documents` is an owner
--     question and is not decided here.
--
-- Idempotent: DROP CONSTRAINT IF EXISTS before each ADD. The closing check fails
-- the migration (and so the deploy) unless both foreign keys now reference
-- `users`. Reversible: 479_..._rollback.sql puts the `team_members` references
-- back (NOT VALID, so it cannot fail over rows written since).

ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_uploaded_by_fkey;
ALTER TABLE public.documents
  ADD CONSTRAINT documents_uploaded_by_fkey
  FOREIGN KEY (uploaded_by) REFERENCES public.users(id) NOT VALID;

ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_reviewed_by_fkey;
ALTER TABLE public.documents
  ADD CONSTRAINT documents_reviewed_by_fkey
  FOREIGN KEY (reviewed_by) REFERENCES public.users(id) NOT VALID;

DO $$
BEGIN
  BEGIN
    ALTER TABLE public.documents VALIDATE CONSTRAINT documents_uploaded_by_fkey;
  EXCEPTION WHEN foreign_key_violation THEN
    RAISE NOTICE 'documents_uploaded_by_fkey left NOT VALID: an older row names a uploader that is not in users';
  END;
  BEGIN
    ALTER TABLE public.documents VALIDATE CONSTRAINT documents_reviewed_by_fkey;
  EXCEPTION WHEN foreign_key_violation THEN
    RAISE NOTICE 'documents_reviewed_by_fkey left NOT VALID: an older row names a reviewer that is not in users';
  END;
END $$;

DO $$
DECLARE
  n_users int;
BEGIN
  SELECT count(*) INTO n_users
    FROM pg_constraint c
   WHERE c.conrelid = 'public.documents'::regclass
     AND c.contype = 'f'
     AND c.conname IN ('documents_uploaded_by_fkey', 'documents_reviewed_by_fkey')
     AND c.confrelid = 'public.users'::regclass;
  IF n_users <> 2 THEN
    RAISE EXCEPTION
      'migration 479: documents.uploaded_by and reviewed_by must both reference public.users (found % that do)',
      n_users;
  END IF;
END $$;
