-- Migration 379: recurring PURCHASE bills (PUR-26).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═══════════════════════════════════════════════════════════════════════════
-- Recurring SALES invoices have existed since migration 107 (Phase 4.3) and
-- recurring JOURNALS since 377. The purchase side had nothing: monthly rent
-- (s.194I), a consultant's retainer (s.194J), electricity, telecom and software
-- subscriptions were re-keyed by hand for every client, every month.
--
-- Those are exactly the bills TDS attaches to, and a missed month is no longer
-- only a missed expense. Most of the s.194 series charges on the YEAR'S
-- AGGREGATE (see domain/tds/section_rates.py), so a month nobody entered
-- changes what the NEXT bill should withhold — and, further down, whether the
-- Rule 30(2) deposit and the quarterly statement are right.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE SHAPE IS 107's AND 377's, DELIBERATELY
-- ═══════════════════════════════════════════════════════════════════════════
-- A template, its LINES, and a runs ledger keyed (template, occurrence) that
-- is both the history a screen shows and the record that makes generation
-- idempotent. Three features, one set of habits, one catch-up rule and one
-- answer to "did this month already generate". The cadence arithmetic itself
-- is NOT copied — `domain/recurrence.py` owns it since 377, for the reason
-- CLAUDE.md gives: two cadence engines drifting means one feature posts in a
-- month the other skips.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IT GENERATES, AND THE ONE FIELD IT CANNOT INVENT
-- ═══════════════════════════════════════════════════════════════════════════
-- A DRAFT purchase bill, through the existing bill engine
-- (routers.purchase_bills.create_purchase_bill), so GST, the s.17(5) split,
-- the vendor's TDS section and the FY lock are all the ordinary ones. Never a
-- RECEIVED bill: receiving is what posts the AP journal and claims the credit,
-- and this product acts unprompted in exactly one place — a bank rule a
-- Manager has marked trusted — which was a recorded owner decision and not a
-- default to copy.
--
-- `purchase_bills.bill_no` IS THE VENDOR'S OWN DOCUMENT NUMBER and is left
-- NULL on a generated draft. A landlord's invoice number is a fact about the
-- landlord's books; inventing one would put a number the supplier never issued
-- onto a document that feeds GSTR-2B matching, where the document number is
-- half the key. `our_reference` — the firm's own tracking number — is stamped,
-- because that one IS ours to choose.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A LINE HERE MIRRORS PurchaseBillLineIn AND NOT THE SALES LINE
-- ═══════════════════════════════════════════════════════════════════════════
-- A purchase line carries three things a sales line does not, and all three
-- decide money: `itc_eligible` (CGST s.17(5) — blocked credit is a COST, and
-- migration 240 exists for it), `expense_account_id` (which ledger the charge
-- lands on, and therefore the Schedule III caption), and `tds_applicable`.
-- Defaulting any of them at generation time would silently re-decide, every
-- month, something the CA decided once.
--
-- Additive. Idempotent. Reversible: 379_..._rollback.sql.

CREATE TABLE IF NOT EXISTS public.recurring_purchase_bill_templates (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         uuid NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
    client_id       uuid NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    vendor_id       uuid NOT NULL REFERENCES public.vendors(id) ON DELETE CASCADE,
    title           text NOT NULL,
    description     text,
    -- The same five 107 and 377 allow, so one cadence helper serves all three.
    frequency       text NOT NULL
        CHECK (frequency IN ('weekly','monthly','quarterly','half_yearly','yearly')),
    start_date      date NOT NULL,
    end_date        date,
    next_run_date   date NOT NULL,
    notes           text,
    -- CGST s.7 with s.8 / IGST s.7: which pair of heads the bill charges. A
    -- fact about where the VENDOR is registered relative to the client, so it
    -- belongs on the template rather than being re-decided each month.
    is_inter_state  boolean NOT NULL DEFAULT false,
    -- CGST s.9(3)/(4): an inward supply on which the RECIPIENT pays the tax —
    -- a goods-transport agency, an advocate, an import of services. Recurring
    -- by nature, and getting it wrong understates output tax every month.
    is_reverse_charge boolean NOT NULL DEFAULT false,
    status          text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','paused','archived')),
    created_by      uuid REFERENCES public.users(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT recurring_purchase_bill_period_is_a_period
        CHECK (end_date IS NULL OR end_date >= start_date)
);

COMMENT ON TABLE public.recurring_purchase_bill_templates IS
    'A recurring supplier bill a CA set up: rent, a retainer, a utility. '
    'Generation produces a DRAFT purchase bill through the ordinary bill '
    'engine and never RECEIVES one — receiving is what posts the AP journal '
    'and claims the credit. Migration 379 (PUR-26).';

CREATE TABLE IF NOT EXISTS public.recurring_purchase_bill_template_lines (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id         uuid NOT NULL
        REFERENCES public.recurring_purchase_bill_templates(id) ON DELETE CASCADE,
    description         text NOT NULL,
    hsn_sac             text,
    unit                text,
    quantity            numeric NOT NULL DEFAULT 1,
    rate_paise          bigint  NOT NULL DEFAULT 0 CHECK (rate_paise >= 0),
    -- Basis points, as recurring_invoice_template_lines holds it: the bill
    -- engine takes a percentage and 18% is not representable as an integer
    -- percent for every rate the Council has notified.
    gst_rate_bps        integer NOT NULL DEFAULT 1800 CHECK (gst_rate_bps >= 0),
    is_service          boolean NOT NULL DEFAULT false,
    -- CGST s.17(5). CA-set only and never inferred — see migration 240. On a
    -- blocked line the tax is part of what the supply COST (PUR-04), so a
    -- default of true here is the safe one: it claims nothing the CA did not
    -- record, and the generated draft is reviewed before it is received.
    itc_eligible        boolean NOT NULL DEFAULT true,
    blocked_credit_reason text,
    tds_applicable      boolean NOT NULL DEFAULT false,
    expense_account_id  uuid REFERENCES public.chart_of_accounts(id) ON DELETE SET NULL,
    service_catalogue_id uuid REFERENCES public.service_catalogue(id) ON DELETE SET NULL,
    sort_order          integer NOT NULL DEFAULT 0
);

COMMENT ON TABLE public.recurring_purchase_bill_template_lines IS
    'The lines a recurring bill generates. Carries itc_eligible, '
    'expense_account_id and tds_applicable because each decides money and '
    'defaulting them at generation would re-decide, every month, what the CA '
    'decided once. Migration 379.';

-- Generation history AND the idempotency ledger, exactly as
-- recurring_invoice_runs (107) and recurring_journal_runs (377) are.
CREATE TABLE IF NOT EXISTS public.recurring_purchase_bill_runs (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id          uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    template_id      uuid NOT NULL
        REFERENCES public.recurring_purchase_bill_templates(id) ON DELETE CASCADE,
    occurrence_date  date NOT NULL,
    purchase_bill_id uuid REFERENCES public.purchase_bills(id) ON DELETE SET NULL,
    status           text NOT NULL DEFAULT 'generated'
        CHECK (status IN ('generated','skipped','failed')),
    detail           jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (template_id, occurrence_date)
);

COMMENT ON TABLE public.recurring_purchase_bill_runs IS
    'One row per (template, occurrence): the history a screen shows and the '
    'record that makes generation idempotent. A failed occurrence is RECORDED '
    'and the template does NOT advance — a template that cannot generate needs '
    'a CA, and advancing past a failure would skip the month silently. '
    'Migration 379.';

-- Traceability on the generated bill, mirroring 107 and 377.
ALTER TABLE public.purchase_bills
    ADD COLUMN IF NOT EXISTS recurring_template_id uuid
        REFERENCES public.recurring_purchase_bill_templates(id) ON DELETE SET NULL;
ALTER TABLE public.purchase_bills
    ADD COLUMN IF NOT EXISTS recurring_occurrence date;

COMMENT ON COLUMN public.purchase_bills.recurring_template_id IS
    'The recurring_purchase_bill_templates row that generated this bill, where '
    'one did. Migration 379.';

-- One bill per (template, occurrence) — the authoritative backstop behind the
-- runs table's own key, and what makes a catch-up sweep safe to re-run.
CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_bills_recurring
    ON public.purchase_bills (recurring_template_id, recurring_occurrence)
    WHERE recurring_template_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recurring_purchase_bill_templates_due
    ON public.recurring_purchase_bill_templates (firm_id, status, next_run_date);
CREATE INDEX IF NOT EXISTS idx_recurring_purchase_bill_lines_template
    ON public.recurring_purchase_bill_template_lines (template_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_recurring_purchase_bill_runs_template
    ON public.recurring_purchase_bill_runs (template_id, created_at DESC);

ALTER TABLE public.recurring_purchase_bill_templates      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recurring_purchase_bill_template_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.recurring_purchase_bill_runs           ENABLE ROW LEVEL SECURITY;

-- Firm isolation, assignment scope and role-guarded writes, in the shape
-- migrations 260/261 established and 377 last used. The assignment policy is
-- here at CREATE time rather than waiting for another sweep like 370's:
-- migration 084's one-shot DO loop has never run again.
--
-- Manager+ to create or change, the same tier a recurring JOURNAL takes: a
-- template here decides what supplier charge, at what rate, against which
-- expense account and with which TDS section, will be raised every month
-- without anyone typing it.
DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_recurring_purchase_bill_templates ON public.recurring_purchase_bill_templates';
  EXECUTE 'CREATE POLICY firm_recurring_purchase_bill_templates ON public.recurring_purchase_bill_templates '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  -- Kept contiguous in ONE string literal: tests/test_direct_write_tables_are_
  -- role_guarded.py reads the migration FILE, and a policy split across
  -- adjacent literals is valid SQL and invisible to that scan.
  EXECUTE 'DROP POLICY IF EXISTS recurring_purchase_bill_templates_assignment_scope ON public.recurring_purchase_bill_templates';
  EXECUTE 'CREATE POLICY recurring_purchase_bill_templates_assignment_scope '
          'ON public.recurring_purchase_bill_templates AS RESTRICTIVE '
          'FOR ALL USING (public.can_access_client(client_id::text)) '
          'WITH CHECK (public.can_access_client(client_id::text))';

  EXECUTE 'DROP POLICY IF EXISTS recurring_purchase_bill_templates_role_insert ON public.recurring_purchase_bill_templates';
  EXECUTE 'CREATE POLICY recurring_purchase_bill_templates_role_insert '
          'ON public.recurring_purchase_bill_templates AS RESTRICTIVE '
          'FOR INSERT WITH CHECK (public.my_role_at_least(''Manager''))';

  EXECUTE 'DROP POLICY IF EXISTS recurring_purchase_bill_templates_role_update ON public.recurring_purchase_bill_templates';
  EXECUTE 'CREATE POLICY recurring_purchase_bill_templates_role_update '
          'ON public.recurring_purchase_bill_templates AS RESTRICTIVE '
          'FOR UPDATE USING (public.my_role_at_least(''Manager'')) '
          'WITH CHECK (public.my_role_at_least(''Manager''))';

  EXECUTE 'DROP POLICY IF EXISTS recurring_purchase_bill_templates_role_delete ON public.recurring_purchase_bill_templates';
  EXECUTE 'CREATE POLICY recurring_purchase_bill_templates_role_delete '
          'ON public.recurring_purchase_bill_templates AS RESTRICTIVE '
          'FOR DELETE USING (public.my_role_at_least(''Manager''))';

  -- Lines are firm-scoped THROUGH their parent, the shape 107 and 377 use: the
  -- child has no firm_id of its own, so inventing one would be a second copy
  -- of a fact that can disagree.
  EXECUTE 'DROP POLICY IF EXISTS firm_recurring_purchase_bill_lines ON public.recurring_purchase_bill_template_lines';
  EXECUTE 'CREATE POLICY firm_recurring_purchase_bill_lines ON public.recurring_purchase_bill_template_lines '
          'FOR ALL TO authenticated '
          'USING (EXISTS (SELECT 1 FROM public.recurring_purchase_bill_templates t '
          '               WHERE t.id = template_id AND t.firm_id = public.get_my_firm_id())) '
          'WITH CHECK (EXISTS (SELECT 1 FROM public.recurring_purchase_bill_templates t '
          '                    WHERE t.id = template_id AND t.firm_id = public.get_my_firm_id()))';

  EXECUTE 'DROP POLICY IF EXISTS firm_recurring_purchase_bill_runs ON public.recurring_purchase_bill_runs';
  EXECUTE 'CREATE POLICY firm_recurring_purchase_bill_runs ON public.recurring_purchase_bill_runs '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_purchase_bill_templates TO authenticated';
  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_purchase_bill_template_lines TO authenticated';
  EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON public.recurring_purchase_bill_runs TO authenticated';
END $$;
