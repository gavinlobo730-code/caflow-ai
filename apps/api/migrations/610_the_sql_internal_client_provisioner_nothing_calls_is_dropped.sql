-- Migration 610: drop `public.provision_internal_client(uuid, text, text, text, text)`, the SQL copy of the internal-client provisioner
-- that nothing calls (ledger POST-A-169, docs/REVENUE_OPS_BRIDGE.md B2-4).
--
-- Migration 073 created it as the "foundation" the Batch 2 provisioner would invoke; Batch 2 provisioned in Python instead
-- (`services/internal_client_service.provision`, run at firm creation and by `POST /api/practice/provision`), and migration 086 revoked
-- EXECUTE from every role but the service role because the application does not call it. Checked on 16-11-2026: no Python module, no
-- browser module and no other database function in the migrations calls it. The two copies had already DRIFTED: the Python path records
-- the practice's `state` and `state_code` and reads the winner of a race off `uq_clients_one_internal_per_firm` (migration 080), and the
-- SQL one does neither. A second copy that nothing exercises is a door that quietly does less, so it is dropped, not kept in step.
--
-- WHAT THIS DOES NOT DO. It does not touch the Python provisioner, the internal client, `firms.internal_client_id`, the unique index or
-- `my_internal_client_id()` (an RLS helper the policies call). One transaction; idempotent. Reversible: the _rollback file recreates the
-- function as 073 wrote it, with 086's grants and 144's search_path.

DROP FUNCTION IF EXISTS public.provision_internal_client(uuid, text, text, text, text);
