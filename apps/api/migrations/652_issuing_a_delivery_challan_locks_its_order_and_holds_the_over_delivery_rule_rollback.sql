-- Rollback of migration 652: the issue is the API's compare-and-set again.
DROP FUNCTION IF EXISTS public.issue_delivery_challan_atomic(uuid, uuid, uuid, timestamptz);
