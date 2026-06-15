-- PracticeSync AI — Migration 083: Governance approval_requests (Module 9.0 / M4)
--
-- Generic maker-checker store. A maker submits a request to perform a sensitive
-- action (user create/activate, role change, client assignment change, master
-- COA change); a Partner (checker) approves or rejects; on approval the action is
-- executed by services/approval_service handlers. Every transition is also written
-- to the immutable audit_log (migration 082).
--
-- Not append-only (status transitions). RLS is defense-in-depth (backend uses the
-- service_role key); reads are firm-scoped Manager+. Idempotent.

CREATE TABLE IF NOT EXISTS public.approval_requests (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID NOT NULL,
  request_type      TEXT NOT NULL,
  summary           TEXT,
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
  requested_by      UUID,
  requested_by_email TEXT,
  decided_by        UUID,
  decided_by_email  TEXT,
  decided_at        TIMESTAMPTZ,
  reason            TEXT,
  result            JSONB,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_firm_status
  ON public.approval_requests(firm_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approval_requests_type
  ON public.approval_requests(firm_id, request_type);

ALTER TABLE public.approval_requests ENABLE ROW LEVEL SECURITY;

-- Manager+ may read the firm's requests (the approval inbox); writes go through
-- the service role (backend). get_my_firm_id()/get_my_role() are SECURITY DEFINER
-- helpers defined in earlier migrations.
DROP POLICY IF EXISTS "approval_requests_read" ON public.approval_requests;
CREATE POLICY "approval_requests_read" ON public.approval_requests
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id()
         AND public.get_my_role() IN ('Partner', 'Manager'));

GRANT SELECT ON public.approval_requests TO authenticated;
GRANT ALL    ON public.approval_requests TO service_role;

COMMENT ON TABLE public.approval_requests IS
  'Module 9.0/M4: maker-checker governance requests for sensitive actions. Written by services/approval_service via the service role; decisions mirrored to audit_log.';
