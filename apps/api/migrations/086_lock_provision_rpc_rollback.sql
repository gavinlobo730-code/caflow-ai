-- Rollback for 086_lock_provision_rpc.sql — restore the default PUBLIC EXECUTE grant.
GRANT EXECUTE ON FUNCTION public.provision_internal_client(uuid, text, text, text, text) TO PUBLIC;
