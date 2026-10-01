-- Rollback for migration 469: the 'Documents' and 'year-end-exports' policies
-- go back to 005's and 426's firm-folder-only form, and the delete door on
-- the year-end bucket is reopened.
--
-- Rolling back RE-OPENS the hole 469 closes: any member of a firm can list,
-- read, overwrite and delete any of that firm's clients' files.

DROP POLICY IF EXISTS "documents_storage_select" ON storage.objects;
CREATE POLICY "documents_storage_select" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "documents_storage_insert" ON storage.objects;
CREATE POLICY "documents_storage_insert" ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "documents_storage_delete" ON storage.objects;
CREATE POLICY "documents_storage_delete" ON storage.objects
  FOR DELETE USING (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

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

REVOKE EXECUTE ON FUNCTION public.can_access_client(text)         FROM supabase_storage_admin;
REVOKE EXECUTE ON FUNCTION public.my_permission(text, text, text) FROM supabase_storage_admin;
REVOKE EXECUTE ON FUNCTION public.my_role_at_least(text)          FROM supabase_storage_admin;
