-- Rollback of migration 610: recreates `public.provision_internal_client` as migration 073 wrote it, with the EXECUTE grants migration
-- 086 left (service role only) and the search_path migration 144 set. For fidelity with the previous schema, not for use: nothing calls it,
-- and it does less than `services/internal_client_service.provision` (no state, no state code, no race handling).
CREATE OR REPLACE FUNCTION public.provision_internal_client(
  p_firm_id     UUID,
  p_legal_name  TEXT,
  p_entity_type TEXT,
  p_pan         TEXT,
  p_gstin       TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
  v_existing UUID;
  v_new      UUID;
BEGIN
  SELECT internal_client_id INTO v_existing FROM firms WHERE id = p_firm_id;
  IF v_existing IS NOT NULL AND EXISTS (
       SELECT 1 FROM clients WHERE id = v_existing AND is_internal
     ) THEN
    RETURN v_existing;  -- idempotent: already provisioned
  END IF;

  INSERT INTO clients (firm_id, client_name, legal_name, entity_type, pan, gstin, is_internal, status)
  VALUES (p_firm_id, p_legal_name, p_legal_name, p_entity_type, p_pan, p_gstin, true, 'active')
  RETURNING id INTO v_new;

  UPDATE firms SET internal_client_id = v_new WHERE id = p_firm_id;
  RETURN v_new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

ALTER FUNCTION public.provision_internal_client(uuid, text, text, text, text) SET search_path = public, pg_catalog;

COMMENT ON FUNCTION public.provision_internal_client(UUID, TEXT, TEXT, TEXT, TEXT) IS
  'Amd v1.1 foundation: idempotently create the firm-as-internal-client row and link firms.internal_client_id. Invoked by Batch 2 (provisioning + guardrails) with real firm details.';

REVOKE EXECUTE ON FUNCTION public.provision_internal_client(uuid, text, text, text, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.provision_internal_client(uuid, text, text, text, text) TO service_role;
