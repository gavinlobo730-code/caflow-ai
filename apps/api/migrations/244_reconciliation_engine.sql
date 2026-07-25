-- Migration 244: reconciliation_runs / reconciliation_findings.
--
-- Comparative-reliability review finding: this platform had no standing,
-- automated way to catch a "books don't tie out" class of bug — everything
-- found in today's audit (the ₹38.14L inventory cache/ledger drift, the
-- ₹15,036.14 gap from 5 sales invoices whose COGS journal silently never
-- posted) was found by a human running one-off SQL by hand. QuickBooks ships
-- a first-party Verify/Rebuild tool for exactly this reason: books drift, and
-- a mature product gives the CA a way to check and a way to see what was
-- found, rather than relying on someone noticing.
--
-- services/reconciliation_service.py runs a fixed set of checks (trial
-- balance, missing COGS/inventory-receipt journals, inventory cache-vs-ledger
-- drift, AR/AP sub-ledger vs GL) — deliberately REPORT-ONLY, never
-- auto-fixing (unlike services/balance_cache_service.py's cache-audit job,
-- which safely self-heals a pure derived cache; correcting a genuine
-- missing-journal or ledger-drift finding needs the same human judgment this
-- session's own manual fixes did, not a blind automated rewrite of financial
-- records). Runs persist here so a CA can see history, not just a live log
-- line — both the scheduled daily job (jobs/scheduler.py) and the on-demand
-- "Verify Books" endpoint (routers/reconciliation.py) write to the same
-- tables, so there is exactly one code path producing findings.

CREATE TABLE IF NOT EXISTS public.reconciliation_runs (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL,
  client_id      UUID NOT NULL,
  trigger        TEXT NOT NULL CHECK (trigger IN ('scheduled', 'manual')),
  status         TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
  started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at   TIMESTAMPTZ,
  checks_run     INTEGER NOT NULL DEFAULT 0,
  findings_count INTEGER NOT NULL DEFAULT 0,
  triggered_by   UUID,
  error          TEXT
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_runs_firm_client
  ON public.reconciliation_runs (firm_id, client_id, started_at DESC);

CREATE TABLE IF NOT EXISTS public.reconciliation_findings (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id          UUID NOT NULL REFERENCES public.reconciliation_runs(id) ON DELETE CASCADE,
  firm_id         UUID NOT NULL,
  client_id       UUID NOT NULL,
  check_name      TEXT NOT NULL,
  severity        TEXT NOT NULL CHECK (severity IN ('critical', 'warning')),
  summary         TEXT NOT NULL,
  details         JSONB NOT NULL DEFAULT '{}',
  amount_paise    BIGINT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at     TIMESTAMPTZ,
  resolved_by     UUID,
  resolution_note TEXT
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_findings_run       ON public.reconciliation_findings (run_id);
CREATE INDEX IF NOT EXISTS idx_reconciliation_findings_firm_client_open
  ON public.reconciliation_findings (firm_id, client_id) WHERE resolved_at IS NULL;

-- RLS (defense-in-depth; the backend uses the service_role key which bypasses
-- RLS). Partner-only read, matching audit_log's own posture (migration 082)
-- — book-integrity findings are leadership-visibility, same as the audit
-- trail. Writes go exclusively through the service role.
ALTER TABLE public.reconciliation_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reconciliation_findings  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "reconciliation_runs_partner_read" ON public.reconciliation_runs;
CREATE POLICY "reconciliation_runs_partner_read" ON public.reconciliation_runs
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id() AND public.get_my_role() = 'Partner');

DROP POLICY IF EXISTS "reconciliation_findings_partner_read" ON public.reconciliation_findings;
CREATE POLICY "reconciliation_findings_partner_read" ON public.reconciliation_findings
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id() AND public.get_my_role() = 'Partner');

GRANT SELECT ON public.reconciliation_runs, public.reconciliation_findings TO authenticated;
GRANT ALL    ON public.reconciliation_runs, public.reconciliation_findings TO service_role;

COMMENT ON TABLE public.reconciliation_runs IS
  'task #244: one row per books-integrity check run (services/reconciliation_service.py), scheduled or on-demand ("Verify Books"). Partner-visible.';
COMMENT ON TABLE public.reconciliation_findings IS
  'task #244: individual discrepancies found by a reconciliation run — report-only, never auto-fixed. A CA marks resolved_at/resolved_by/resolution_note once reviewed and actioned outside this table (the actual fix is a real ledger/journal correction, done deliberately, not by this system).';
