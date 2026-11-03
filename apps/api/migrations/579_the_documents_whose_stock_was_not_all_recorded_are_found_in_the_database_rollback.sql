-- Rollback of migration 579: the finder goes. Roll the API change back first (the stock panel calls it); against a database without
-- it the panel says it could not check, which is its answer for any failed read.
DROP FUNCTION IF EXISTS public.documents_with_unrecorded_stock(uuid, uuid);
