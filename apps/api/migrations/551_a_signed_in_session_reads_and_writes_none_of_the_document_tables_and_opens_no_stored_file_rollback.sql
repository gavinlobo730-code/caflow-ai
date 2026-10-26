-- Rollback of migration 551: gives `authenticated` back the privileges the earlier migrations granted on the five document tables,
-- and re-creates the five object policies on `storage.objects` exactly as migration 469 wrote them (469 had dropped the sixth, the year-end delete).
-- THIS RE-OPENS THE HOLE: a person with their own sign-in can read and write, over PostgREST and not through the API, whatever the
-- row policies let them of the document register, the requests, the extractions and the risks, and can open, store and (a Partner)
-- remove files under `{firm}/{client}/...` in the `Documents` and `year-end-exports` buckets through Storage directly. Roll back the
-- code that depends on the revoke first (there is none: the API runs as the server on these tables and on Storage since POST-A-339).
-- It restores exactly what a database built from the migrations held before 551: SELECT, INSERT, UPDATE and DELETE on the five
-- tables for `authenticated`. It does NOT restore the TRUNCATE privilege that 551 also revoked, because no migration ever granted it
-- (it came from the hosting platform's defaults) and a signed-in role has no use for it.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'documents', 'client_documents', 'document_requests', 'document_extractions', 'document_risks'
    ] LOOP
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
END $$;

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
