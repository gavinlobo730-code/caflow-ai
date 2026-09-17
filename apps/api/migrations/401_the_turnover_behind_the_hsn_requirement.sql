-- ═══════════════════════════════════════════════════════════════════════════
-- 401 — public.client_gst_turnover: the aggregate turnover Table 12's HSN
--       digit requirement reads on, recorded per financial year (GST-17).
--
-- WHAT WAS WRONG
--     Notification 78/2020-Central Tax sets the minimum HSN digits on a GSTR-1
--     Table 12 row from the taxpayer's "aggregate turnover in the preceding
--     Financial Year". Nothing in this product held that figure, so
--     `lib/data/gst.ts` sent `aggregate_turnover_paise: 0` on every build —
--     and 0 is a REAL turnover meaning "below every threshold", so every
--     client was silently told HSN was optional. The requirement was never
--     reported and never enforced.
--
-- WHY A TABLE AND NOT A COLUMN ON `clients`
--     The figure is PER FINANCIAL YEAR, and the year that governs is the one
--     BEFORE the return's own. A single column would be overwritten each April
--     and a belated GSTR-1 for an earlier period would then rebuild at the
--     wrong tier — the same reason `client_gst_registrations` is a table
--     rather than a second column beside `clients.gstin`.
--
-- WHY IT IS NOT DERIVED
--     CGST s.2(6) aggregate turnover is computed on the PAN, ALL-INDIA, and
--     includes exempt supplies, exports and inter-State supplies between
--     distinct persons. A second registration's supplies count toward it, and
--     this product holds one client's books. It is not
--     `tax_audits.turnover_paise` either: that is s.44AB turnover for the year
--     under audit, a different figure in a different year.
--
--     So the CA records it, and an unrecorded year is a NAMED GAP rather than
--     a zero. That is the whole point: the absence has to be distinguishable
--     from a client who genuinely turned over nothing.
--
-- NO DEFAULT AND NO BACKFILL, for the reason above. There is nothing to
-- back-fill FROM, and inventing a figure here is inventing the answer to the
-- question the table exists to ask.
--
-- Idempotent, and safe to re-run.
-- ═══════════════════════════════════════════════════════════════════════════

BEGIN;

CREATE TABLE IF NOT EXISTS public.client_gst_turnover (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                   UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id                 UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The financial year the figure IS, canonical 'YYYY-YY'. A GSTR-1 for a
  -- period inside FY 2026-27 reads the row for FY 2025-26, and that hop is
  -- done in `domain/gst/hsn_digits` rather than stored, so a row cannot be
  -- filed under the year it governs instead of the year it measures.
  financial_year            TEXT NOT NULL
                            CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),

  -- CGST s.2(6), integer paise. NOT NULL: a row exists only because somebody
  -- recorded a figure, and "recorded as nothing" is 0 — which is a real
  -- answer and a different one from having no row at all.
  aggregate_turnover_paise  BIGINT NOT NULL CHECK (aggregate_turnover_paise >= 0),

  -- Who said so and when. The figure comes off a return filed elsewhere or
  -- off the client's own accounts, so the source is worth keeping.
  source_note               TEXT,
  recorded_by               UUID REFERENCES public.users(id),
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

  UNIQUE (client_id, financial_year)
);

COMMENT ON TABLE public.client_gst_turnover IS
  'CGST s.2(6) aggregate turnover per client per financial year. Read by the '
  'GSTR-1 Table 12 HSN digit requirement (Notification 78/2020-Central Tax), '
  'which asks about the PRECEDING financial year. NO ROW means nobody has '
  'recorded one — the return reports that as a gap and shows the strictest '
  'requirement; it must never be read as zero. Migration 401, GST-17.';

COMMENT ON COLUMN public.client_gst_turnover.financial_year IS
  'The year this figure MEASURES, not the year it governs. The preceding-year '
  'hop is done in domain/gst/hsn_digits.';

CREATE INDEX IF NOT EXISTS idx_client_gst_turnover_client
  ON public.client_gst_turnover (client_id, financial_year);

ALTER TABLE public.client_gst_turnover ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS client_gst_turnover_own_firm ON public.client_gst_turnover;
CREATE POLICY client_gst_turnover_own_firm ON public.client_gst_turnover
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scoping, declared here rather than left to its
-- one-shot DO loop, which has never re-run (CLAUDE.md).
DROP POLICY IF EXISTS client_gst_turnover_assignment_scope ON public.client_gst_turnover;
CREATE POLICY client_gst_turnover_assignment_scope ON public.client_gst_turnover
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_gst_turnover TO authenticated;

COMMIT;
