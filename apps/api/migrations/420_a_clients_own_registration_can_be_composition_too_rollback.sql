-- Rollback for 420. Additive-only migration, so the rollback is exactly three
-- DROP COLUMNs and nothing else to undo.

BEGIN;

ALTER TABLE public.client_gst_registrations
  DROP COLUMN IF EXISTS composition_category;

ALTER TABLE public.clients
  DROP COLUMN IF EXISTS composition_category,
  DROP COLUMN IF EXISTS gst_registration_type;

COMMIT;
