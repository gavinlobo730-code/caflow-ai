-- PracticeSync AI — Migration 087: Demo (simulated) filings.
--
-- Backs the DEMO MODE filing simulation (PR-3). A demo filing is a WORKFLOW
-- SIMULATION ONLY — nothing is ever submitted to any government portal. To
-- guarantee a simulated filing can never be mistaken for a real one, demo
-- filings live in their OWN table and NEVER touch compliance_calendar.filing_status.
-- Real compliance status stays pristine (a real deadline still reads pending /
-- overdue); the UI overlays a clearly-labelled "Demo Filed" badge from this table.
--
-- Additive, idempotent, reversible.

CREATE TABLE IF NOT EXISTS public.demo_filings (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL,
  client_id            UUID,
  -- Soft link to compliance_calendar.id (no FK: additive + tolerant of reseeds).
  compliance_entry_id  UUID,
  compliance_type      TEXT NOT NULL,
  period_start         DATE,
  period_end           DATE,
  -- Demo-only reference: always DEMO-ARN-… / DEMO-SRN-… / SIM-GST-… (never a
  -- realistic government reference). Enforced again in the app layer.
  demo_reference       TEXT NOT NULL,
  demo_status          TEXT NOT NULL DEFAULT 'demo_filed'
                       CHECK (demo_status IN ('demo_filed')),
  simulated_by         UUID,
  simulated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_demo_filings_firm  ON public.demo_filings(firm_id);
CREATE INDEX IF NOT EXISTS idx_demo_filings_entry ON public.demo_filings(compliance_entry_id);
-- At most one demo filing per real compliance entry (re-simulating upserts).
CREATE UNIQUE INDEX IF NOT EXISTS uq_demo_filings_entry
  ON public.demo_filings(compliance_entry_id) WHERE compliance_entry_id IS NOT NULL;

ALTER TABLE public.demo_filings ENABLE ROW LEVEL SECURITY;

-- Firm-scoped: any authenticated member of the firm may read/write its demo
-- filings (this is a sandbox feature, so no per-role restriction).
DROP POLICY IF EXISTS "demo_filings_firm_rw" ON public.demo_filings;
CREATE POLICY "demo_filings_firm_rw" ON public.demo_filings
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

GRANT ALL ON public.demo_filings TO authenticated;
GRANT ALL ON public.demo_filings TO service_role;

COMMENT ON TABLE public.demo_filings IS
  'PR-3: DEMO MODE filing simulations. Workflow simulation only — never submitted to any portal and never written to compliance_calendar.filing_status. UI shows these as "Demo Filed".';
