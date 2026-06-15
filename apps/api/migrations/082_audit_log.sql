-- PracticeSync AI — Migration 082: audit_log table (Module 9.0 / M1)
--
-- Problem: services/audit_service.py inserts into `audit_log`, and routers/audit.py
-- reads it, but NO migration ever created the table. It existed only out-of-band in
-- the hosted DB: undefined, unversioned, no RLS, no immutability, and absent in any
-- fresh environment. `log_event` swallows all exceptions, so a missing table failed
-- silently with zero audit capture.
--
-- This migration makes the table authoritative: matches the columns the code writes,
-- enforces append-only immutability, applies firm-scoped RLS (defense-in-depth), and
-- adds query indexes. Idempotent — safe over the pre-existing out-of-band table.
-- Rollback: 082_audit_log_rollback.sql.

CREATE TABLE IF NOT EXISTS public.audit_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID NOT NULL,
  actor_id    UUID,
  actor_email TEXT,
  entity_type TEXT NOT NULL,
  entity_id   TEXT,
  action      TEXT NOT NULL,
  old_data    JSONB,
  new_data    JSONB,
  metadata    JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for the audit viewer (routers/audit.py): firm timeline + entity history.
CREATE INDEX IF NOT EXISTS idx_audit_log_firm_created  ON public.audit_log(firm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_entity        ON public.audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_actor         ON public.audit_log(actor_id);

-- Append-only immutability: block UPDATE and DELETE at the database level so the
-- "immutable audit trail" promise in audit_service.py is actually enforced.
CREATE OR REPLACE FUNCTION public.audit_log_block_mutation()
RETURNS TRIGGER AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only; % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_audit_log_no_update ON public.audit_log;
CREATE TRIGGER trg_audit_log_no_update
  BEFORE UPDATE ON public.audit_log
  FOR EACH ROW EXECUTE FUNCTION public.audit_log_block_mutation();

DROP TRIGGER IF EXISTS trg_audit_log_no_delete ON public.audit_log;
CREATE TRIGGER trg_audit_log_no_delete
  BEFORE DELETE ON public.audit_log
  FOR EACH ROW EXECUTE FUNCTION public.audit_log_block_mutation();

-- RLS (defense-in-depth; the backend uses the service_role key which bypasses RLS).
-- Reads are firm-scoped; only Partners may read (audit is leadership-only). Writes go
-- exclusively through the service role (no INSERT policy for authenticated).
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "audit_log_partner_read" ON public.audit_log;
CREATE POLICY "audit_log_partner_read" ON public.audit_log
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id() AND public.get_my_role() = 'Partner');

GRANT SELECT ON public.audit_log TO authenticated;
GRANT ALL    ON public.audit_log TO service_role;

COMMENT ON TABLE public.audit_log IS
  'Module 9.0/M1: authoritative, append-only audit trail. Written by services/audit_service.log_event via the service role; read (Partner-only) by routers/audit.py.';
