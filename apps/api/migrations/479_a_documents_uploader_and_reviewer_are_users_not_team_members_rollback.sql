-- Rollback for migration 479: documents.uploaded_by and documents.reviewed_by
-- reference team_members(id) again, exactly as migration 001 declared them.
--
-- Rolling back RESTORES the defect 479 repairs: team_members holds no rows, so
-- every upload through POST /api/documents/upload is refused by the foreign key
-- again. The constraints come back NOT VALID so the rollback cannot fail over
-- rows written (against `users` ids) while 479 was in force.

ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_uploaded_by_fkey;
ALTER TABLE public.documents
  ADD CONSTRAINT documents_uploaded_by_fkey
  FOREIGN KEY (uploaded_by) REFERENCES public.team_members(id) NOT VALID;

ALTER TABLE public.documents DROP CONSTRAINT IF EXISTS documents_reviewed_by_fkey;
ALTER TABLE public.documents
  ADD CONSTRAINT documents_reviewed_by_fkey
  FOREIGN KEY (reviewed_by) REFERENCES public.team_members(id) NOT VALID;
