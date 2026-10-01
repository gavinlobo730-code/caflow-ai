-- Migration 469 — a stored file opens only for the staff assigned to its client
-- (security_privacy-03).
--
-- THE HOLE
--   Migration 005's three policies on the 'Documents' bucket — and 426's copy of
--   them on 'year-end-exports' — test two things: the bucket, and that the first
--   folder of the path is the caller's own firm. Every upload path in this
--   product is
--
--       {firm_id}/{client_id}/…
--
--   and the second folder was never read. So any member of a firm, an Executive
--   assigned to two clients out of two hundred, or a Reviewer, could list, read,
--   overwrite and hard-delete EVERY client's files through the Storage API — the
--   bank statements, the ID documents, the audited accounts — while the tables
--   that describe those files (`client_documents`, `documents`) had been
--   assignment-scoped since 084 and role-scoped since 260 and 415. The row said
--   "you may not see this client" and the blob behind it did not.
--
-- WHAT THIS DOES
--   The second folder is the client. It is asked of `can_access_client` — the
--   function every `<table>_assignment_scope` policy asks — so a file is exactly
--   as visible as the row that describes it: a Partner sees every client, anyone
--   else sees the clients they are assigned to, and (since 468) a member who is
--   suspended or signed out sees none. A path with no second folder is a
--   firm-level object, which `can_access_client(NULL)` answers true for.
--
--     SELECT   the firm, the client's assignment.
--     INSERT   the same, and the member must be one who may WRITE: a document, an
--              accounting record or a year-end pack. Three resources, because
--              three routes upload through the caller's own token (the API runs
--              as the user under USE_USER_JWT, which is what these policies are
--              FOR): `document:write` (documents.py, document_intelligence_v1),
--              `accounting:write` (the debit and purchase-credit note
--              attachments) and `year_end:write` (the year-end exports). Naming
--              only the first would refuse a Partner's per-person grant of
--              accounting write to a Reviewer at the very last step, which is
--              the failure `my_permission` exists to prevent.
--     DELETE   the same assignment, and PARTNER ONLY — `my_role_at_least`, the
--              predicate `client_documents_role_delete` (261) and
--              `documents_role_delete` (260/415) already use for the row. The two have to
--              agree: a blob a member could delete and a row they could not is a
--              row pointing at nothing, which is the worse of the two outcomes.
--
--   'year-end-exports' is the same, with its own resource: the API signs a
--   download after `rbac("year_end", "read")` and writes after `year_end:write`,
--   so the policies ask the same two pairs. Its DELETE policy is DROPPED rather
--   than scoped: nothing in apps/api removes a year-end export under a member's
--   token (the one `.remove` in the API is shared_reports', on a different
--   bucket and under the service key), the service-role policy remains for any
--   job that has to, and a delete door nothing uses is only a door.
--
-- WHAT IS NOT CHANGED, AND WHY
--   * The service-role policies. The backend's own service-key uploads stay as
--     204 and 426 left them.
--   * The browser can still hard-delete a blob a PARTNER may delete. Moving the
--     five browser delete handlers onto an API soft-delete needs an API door for
--     `client_documents`, which has none (`/api/documents` is the `documents`
--     table — a different one), and a retention decision beside it. It is named
--     in CLAUDE.md as the next step rather than half-built here. What changes is
--     WHO: a delete is now at most what the row's own policy already allowed.
--   * A member who is not a Partner, pressing Delete: Storage answers a denied
--     remove with an EMPTY LIST and no error, and the screens go on to delete
--     the row (also denied, also silent, since 261) and drop the line from the
--     page. That has been true of the row since 261 and is not new; what is new
--     is that the file is no longer deleted while the row stays.
--
-- THE ROLE THESE ARE EVALUATED AS
--   204 records that storage-api's own connection executes as
--   `supabase_storage_admin`, not as the caller's role, so every function a
--   policy calls has to be executable by it. `get_my_firm_id` was granted there
--   by 204; `can_access_client` has no ACL (PUBLIC executes it); `my_permission`
--   and `my_role_at_least` were revoked from PUBLIC by 415 and 260 and granted
--   to three named roles — not this one. Without the two grants below every
--   upload would fail with "permission denied for function my_permission", which
--   is exactly the shape of the incident 204's header describes for
--   get_my_firm_id. Both are SECURITY DEFINER, so what they call runs as their
--   owner and needs nothing more.
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE; GRANT is idempotent).
-- Reversible: 469_a_stored_file_opens_only_for_the_staff_assigned_to_its_client_rollback.sql.

GRANT EXECUTE ON FUNCTION public.can_access_client(text)          TO supabase_storage_admin;
GRANT EXECUTE ON FUNCTION public.my_permission(text, text, text)  TO supabase_storage_admin;
GRANT EXECUTE ON FUNCTION public.my_role_at_least(text)           TO supabase_storage_admin;

-- ── the 'Documents' bucket ───────────────────────────────────────────────────
DROP POLICY IF EXISTS "documents_storage_select" ON storage.objects;
CREATE POLICY "documents_storage_select" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
    AND public.can_access_client((storage.foldername(name))[2])
  );

DROP POLICY IF EXISTS "documents_storage_insert" ON storage.objects;
CREATE POLICY "documents_storage_insert" ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
    AND public.can_access_client((storage.foldername(name))[2])
    AND (   public.my_permission('document',   'write', 'Executive')
         OR public.my_permission('accounting', 'write', 'Manager')
         OR public.my_permission('year_end',   'write', 'Executive'))
  );

DROP POLICY IF EXISTS "documents_storage_delete" ON storage.objects;
CREATE POLICY "documents_storage_delete" ON storage.objects
  FOR DELETE USING (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
    AND public.can_access_client((storage.foldername(name))[2])
    AND public.my_role_at_least('Partner')
  );

-- ── the 'year-end-exports' bucket ────────────────────────────────────────────
DROP POLICY IF EXISTS "year_end_exports_storage_select" ON storage.objects;
CREATE POLICY "year_end_exports_storage_select" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'year-end-exports'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
    AND public.can_access_client((storage.foldername(name))[2])
    AND public.my_permission('year_end', 'read', 'Executive')
  );

DROP POLICY IF EXISTS "year_end_exports_storage_insert" ON storage.objects;
CREATE POLICY "year_end_exports_storage_insert" ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'year-end-exports'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
    AND public.can_access_client((storage.foldername(name))[2])
    AND public.my_permission('year_end', 'write', 'Executive')
  );

DROP POLICY IF EXISTS "year_end_exports_storage_delete" ON storage.objects;
