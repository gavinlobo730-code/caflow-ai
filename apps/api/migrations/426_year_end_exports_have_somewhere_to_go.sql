-- 426: the year-end export bucket exists, with the Documents bucket's policies.
--
-- WHY
--   routers/year_end_exports.py uploads every financial-statements, notes and
--   complete-pack PDF to the storage bucket 'year-end-exports' and signs its
--   download link there. No migration ever created that bucket: production
--   has exactly two, 'Documents' (migration 005) and 'firm-assets'. So every
--   export failed with "Storage upload failed ... Bucket not found" — the one
--   output of the year-end workflow a CA hands to a client or signs.
--
--   The upload also ran as `anon` (supabase-py's storage client carried the
--   anon key, fixed in core/supabase_client.get_user_supabase in the same
--   change), so a bucket alone would not have been enough.
--
-- WHAT THIS DOES
--   Creates the bucket PRIVATE — a year-end pack is a client's audited
--   accounts, and every read goes through a signed link the API mints after
--   rbac() and the engagement-scope check — and gives it the same firm-folder
--   policies migration 005 gave 'Documents': the first path segment is the
--   caller's own firm, which `_storage_path` always writes first
--   (`{firm_id}/{client_id}/{financial_year}/{filename}`). The service-role
--   policies mirror 005's too.
--
--   Idempotent: ON CONFLICT on the bucket, DROP POLICY IF EXISTS on each policy.

BEGIN;

INSERT INTO storage.buckets (id, name, public)
VALUES ('year-end-exports', 'year-end-exports', false)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "year_end_exports_storage_select" ON storage.objects;
CREATE POLICY "year_end_exports_storage_select" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'year-end-exports'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "year_end_exports_storage_insert" ON storage.objects;
CREATE POLICY "year_end_exports_storage_insert" ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'year-end-exports'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "year_end_exports_storage_delete" ON storage.objects;
CREATE POLICY "year_end_exports_storage_delete" ON storage.objects
  FOR DELETE USING (
    bucket_id = 'year-end-exports'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "year_end_exports_storage_service_role_select" ON storage.objects;
CREATE POLICY "year_end_exports_storage_service_role_select" ON storage.objects
  FOR SELECT USING (bucket_id = 'year-end-exports' AND auth.role() = 'service_role');

DROP POLICY IF EXISTS "year_end_exports_storage_service_role_insert" ON storage.objects;
CREATE POLICY "year_end_exports_storage_service_role_insert" ON storage.objects
  FOR INSERT WITH CHECK (bucket_id = 'year-end-exports' AND auth.role() = 'service_role');

DROP POLICY IF EXISTS "year_end_exports_storage_service_role_delete" ON storage.objects;
CREATE POLICY "year_end_exports_storage_service_role_delete" ON storage.objects
  FOR DELETE USING (bucket_id = 'year-end-exports' AND auth.role() = 'service_role');

COMMIT;
