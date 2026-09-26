-- 423 — THE ANNUAL RETURN AND THE AUDITED BOOKS ARE RECONCILED, GSTIN BY GSTIN
-- (GST-25, GSTR-9C — the third and last piece of GST-25's original mandate)
--
-- WHAT WAS WRONG
--   CGST Act s.44 with Rule 80(3): a registered person whose aggregate
--   turnover crosses the notified threshold in a financial year files a
--   self-certified reconciliation statement, FORM GSTR-9C, reconciling the
--   annual return (GSTR-9, already built — GST-10) against the turnover and
--   ITC figures in its OWN AUDITED FINANCIAL STATEMENTS. Nothing built it.
--
-- READ FROM THE GSTR-9C OFFLINE UTILITY'S OWN VBA
--   (docs/compliance/sources/gst-offline-utilities/gstr9c/) — five files read
--   in full: Variable_Initialize, Common_Module, Export_JSON_Module,
--   ValidateMod, Validate_Functions. The scoping report is
--   docs/audits/2026-09-26-gstr9c-scoping-report.md.
--
-- WHY THIS IS ITS OWN TABLE, NOT `gstr1_returns` A THIRD TIME
--   GSTR-9 was bolted onto `gstr1_returns` (`return_type='gstr9'`,
--   `period='FY<yyyy-yy>'`). Migration 390 narrowed that table's uniqueness
--   to `UNIQUE (client_id, period, coalesce(gstin, ''))` — NOT including
--   `return_type` — so a GSTR-9C row for the same client/GSTIN/FY would
--   collide with the GSTR-9 row already there on that same index. Widening
--   that constraint a second time touches a guarantee two other features
--   already depend on; a dedicated table is the lower-risk shape, the same
--   choice GSTR-8 made rather than folding into an existing return table.
--
-- WHY THREE TABLES, MATCHING THE OFFLINE UTILITY'S OWN SHEET STRUCTURE
--   `gstr9c_reconciliations` is Part A's flat figures (Tables 5, 7, 12, 16)
--   plus the three "reasons" arrays (Tables 6, 8, 13, 15) as `TEXT[]` — one
--   row per (client, gstin, financial_year), matching the offline utility's
--   own one-workbook-per-filing shape.
--   `gstr9c_rate_wise_lines` holds Tables 9, 11 and Part V's "tax_pay" array
--   in ONE table (`table_ref` distinguishes them) because all three share the
--   identical row shape confirmed from the VBA (a rate/description plus a
--   taxable value or "val" plus igst/cgst/sgst/cess) — three near-identical
--   tables would be three places the same rate-slab vocabulary could drift.
--   `gstr9c_expense_lines` is Table 14's expense-head array alone — a
--   genuinely different shape (value / total ITC / eligible ITC availed
--   against an expense head, not a tax rate).
--
-- WHAT IS DELIBERATELY NOT HERE
--   The whole Part B (i)/(ii) certification data model — signatory,
--   membership number, qualifications, PAN, certificate boilerplate text.
--   Confirmed from the VBA's own `PARTB_RESTRICTED_FY` list and its
--   `Export_JSON` sub: for FY 2020-21 through 2024-25 the workbook OMITS
--   `isauditor`, the whole `certificate`/`cert_text` block, and Part V's
--   signature/PAN block from the JSON entirely — the Finance Act 2021
--   removed CA/CMA certification, and this workbook's own current-version
--   export proves the return became a pure self-declaration for those years
--   with no third-party sign-off recorded anywhere in it. Building the
--   certification model now would be building dead machinery for a path
--   this product will most likely never exercise for a live client; if a
--   belated/revised pre-FY-2020-21 filing is ever asked for by name, that is
--   the moment to add it from the VBA's own `Write_PB1`/`Write_PB2` shapes.
--   No UDIN field exists anywhere in the schema either (confirmed by
--   full-text search across all five files) — nothing to carry here.
--
--   Table 14's per-expense-head figures are CA-typed with NO auto-fill: this
--   product's chart of accounts classifies for Schedule III captions, not
--   for GSTR-9C's 26 expense-head categories, and building that second
--   classification purely to answer one table is new modelling work with no
--   other consumer — comparable in scope to the Schedule III caption work
--   itself, not a quick add. Named as a gap in domain/gst/gstr9c.py.
--
--   Multi-GSTIN apportionment of PAN-level audited turnover (GST-20's own
--   shape: one client may hold several GSTINs, and the audited financial
--   statements are prepared at the PAN level, not per registration) has no
--   statutory formula in this product or anywhere this research could
--   confirm — it stays a CA-entered figure per registration, named as a gap
--   rather than apportioned by an invented "reasonable basis."
BEGIN;

-- ── Part A — the reconciliation itself, one row per (client, gstin, FY) ─────

CREATE TABLE IF NOT EXISTS public.gstr9c_reconciliations (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin                  TEXT NOT NULL
                         CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  financial_year         TEXT NOT NULL CHECK (financial_year ~ '^[0-9]{4}-[0-9]{2}$'),

  -- Home sheet.
  act_name               TEXT,   -- the Act under which the accounts are audited

  -- Table 5 "Reconciliation of Gross Turnover" — 5A-5O, CA-recorded (the
  -- offline utility itself reads every one of these as a cell value; it
  -- derives none of them). 5P/5Q/5R are NOT stored here — see the module
  -- docstring on why 5P's own sign convention is refused rather than
  -- guessed, and turnover_after_adjustments_paise below is what a CA who
  -- HAS worked out 5P types directly, kept apart from an auto-summed figure
  -- this migration does not attempt.
  turnover_per_audited_fs_paise         BIGINT,  -- 5A
  unbilled_revenue_begin_paise          BIGINT,  -- 5B
  unadjusted_advances_end_paise         BIGINT,  -- 5C
  deemed_supply_paise                   BIGINT,  -- 5D  (Schedule I)
  credit_notes_issued_post_fy_paise     BIGINT,  -- 5E
  trade_discount_not_permissible_paise  BIGINT,  -- 5F
  unbilled_revenue_end_paise            BIGINT,  -- 5H
  unadjusted_advances_begin_paise       BIGINT,  -- 5I
  credit_notes_in_fs_not_permissible_paise BIGINT, -- 5J
  sez_dta_adjustment_paise              BIGINT,  -- 5K
  composition_period_turnover_paise     BIGINT,  -- 5L
  section_15_adjustment_paise           BIGINT,  -- 5M
  forex_adjustment_paise                BIGINT,  -- 5N
  other_turnover_adjustment_paise       BIGINT,  -- 5O
  -- 5P — CA-entered because its own addition/subtraction sign per 5B-5O line
  -- is not textually present in the VBA (it reads a cell value, which may be
  -- an Excel formula this extraction cannot see). NULL means not worked out
  -- yet; 5R is derived from this (a plain subtraction) only once it is set.
  turnover_after_adjustments_paise      BIGINT,  -- 5P
  turnover_reasons                      TEXT[],  -- Table 6 — reasons for 5R

  -- Table 7 "Reconciliation of Taxable Turnover" — 7A is 5P carried forward,
  -- not re-typed (see domain/gst/gstr9c.py). 7B-7D CA-recorded; 7E is the
  -- same refused-sign shape as 5P.
  exempt_nil_nongst_turnover_paise      BIGINT,  -- 7B
  zero_rated_no_tax_turnover_paise      BIGINT,  -- 7C
  reverse_charge_turnover_paise         BIGINT,  -- 7D
  -- 7D(ecom) — FY >= 2024-25 only (confirmed from the VBA's own schema fork,
  -- `rev_sup_ecom`). This product cannot currently mark a supply as made
  -- through an e-commerce operator anywhere (the same gap GST-10 already
  -- names for GSTR-3B Table 3.1.1), so this is named as a gap for any such
  -- year rather than computed, whatever is recorded here.
  ecommerce_9_5_turnover_paise          BIGINT,
  taxable_turnover_after_adjustments_paise BIGINT, -- 7E, same refusal as 5P
  taxable_turnover_reasons              TEXT[],  -- Table 8

  -- Table 12 "Reconciliation of Net ITC" — 12A-12C CA-recorded. 12D (A+B-C)
  -- IS derived in domain/gst/gstr9c.py because that addition is the formula
  -- the row's own label states, not an assumed sign on an opaque adjustment
  -- — still carried with a caveat rather than asserted `[P]`-graded. 12E and
  -- 12F are never stored: 12E is read from the already-built GSTR-9
  -- (services.gstr9c_service), and storing it here would be a second, driftable
  -- copy of a figure that return already owns.
  itc_per_audited_fs_paise                    BIGINT,  -- 12A
  itc_booked_earlier_fy_claimed_this_fy_paise BIGINT,  -- 12B
  itc_booked_this_fy_claimed_later_fy_paise   BIGINT,  -- 12C
  itc_reasons                           TEXT[],  -- Table 13

  -- Table 16 "Tax payable on un-reconciled ITC" — a single figure per head,
  -- not rate-wise (confirmed from the VBA: sheet "PT IV (16)", column C,
  -- one row per head). Fully CA-recorded: it depends on 14T, and Table 14's
  -- expense-head reconciliation is not built (see the module docstring).
  unreconciled_itc_tax_igst_paise       BIGINT,
  unreconciled_itc_tax_cgst_paise       BIGINT,
  unreconciled_itc_tax_sgst_paise       BIGINT,
  unreconciled_itc_tax_cess_paise       BIGINT,
  unreconciled_itc_interest_paise       BIGINT,
  unreconciled_itc_penalty_paise        BIGINT,
  itc_reasons_16                        TEXT[],  -- Table 15

  notes                  TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr9c_reconciliation
  ON public.gstr9c_reconciliations (client_id, gstin, financial_year)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_gstr9c_reconciliations_fy
  ON public.gstr9c_reconciliations (client_id, gstin, financial_year)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr9c_reconciliations IS
  'GSTR-9C Part A (CGST Act s.44, Rule 80(3)) — the CA-recorded reconciling '
  'figures Tables 5, 7, 12 and 16 ask for, since the audited financial '
  'statements are not this product''s own books. domain/gst/gstr9c.py is '
  'the authority for what is derived from this row versus read from the '
  'already-built GSTR-9. GST-25, migration 423.';

ALTER TABLE public.gstr9c_reconciliations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr9c_reconciliations"
  ON public.gstr9c_reconciliations;
CREATE POLICY "firm_staff_read_gstr9c_reconciliations"
  ON public.gstr9c_reconciliations
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr9c_reconciliations_assignment_scope"
  ON public.gstr9c_reconciliations;
CREATE POLICY "gstr9c_reconciliations_assignment_scope"
  ON public.gstr9c_reconciliations AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr9c_reconciliations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr9c_reconciliations TO service_role;


-- ── Tables 9, 11 and Part V — one rate-wise shape, three uses ───────────────

CREATE TABLE IF NOT EXISTS public.gstr9c_rate_wise_lines (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  reconciliation_id      UUID NOT NULL REFERENCES public.gstr9c_reconciliations(id) ON DELETE CASCADE,

  -- '9' = Table 9 (rate-wise liability reconciliation, plus its interest/
  --       late-fee/penalty/other tail rows, described by rate_description);
  -- '11' = Table 11 (additional amount payable but not paid — same shape);
  -- 'partv' = Part V's own "tax_pay" array (additional liability recommended).
  table_ref              TEXT NOT NULL CHECK (table_ref IN ('9', '11', 'partv')),

  -- e.g. '5%', '12%', 'Interest', 'Late Fee', 'Penalty', 'Others' — the
  -- offline utility VLOOKUPs this from a fixed Master-sheet range per table,
  -- and this column carries the resolved text rather than re-deriving a
  -- lookup this product has no equivalent master sheet for.
  rate_description       TEXT NOT NULL,

  taxable_value_paise    BIGINT NOT NULL DEFAULT 0,
  igst_paise             BIGINT NOT NULL DEFAULT 0,
  cgst_paise             BIGINT NOT NULL DEFAULT 0,
  sgst_paise             BIGINT NOT NULL DEFAULT 0,
  cess_paise             BIGINT NOT NULL DEFAULT 0,

  line_order             INTEGER NOT NULL DEFAULT 0,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gstr9c_rate_wise_lines_recon
  ON public.gstr9c_rate_wise_lines (reconciliation_id, table_ref)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr9c_rate_wise_lines IS
  'GSTR-9C Tables 9, 11 and Part V''s rate-wise arrays — one shape, told '
  'apart by table_ref, matching migration 421''s own reasoning for keeping '
  'one identifier shape in one table rather than three near-identical '
  'ones. GST-25, migration 423.';

ALTER TABLE public.gstr9c_rate_wise_lines ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr9c_rate_wise_lines"
  ON public.gstr9c_rate_wise_lines;
CREATE POLICY "firm_staff_read_gstr9c_rate_wise_lines"
  ON public.gstr9c_rate_wise_lines
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr9c_rate_wise_lines_assignment_scope"
  ON public.gstr9c_rate_wise_lines;
CREATE POLICY "gstr9c_rate_wise_lines_assignment_scope"
  ON public.gstr9c_rate_wise_lines AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr9c_rate_wise_lines TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr9c_rate_wise_lines TO service_role;


-- ── Table 14 — the expense-head array, a genuinely different shape ─────────

CREATE TABLE IF NOT EXISTS public.gstr9c_expense_lines (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  reconciliation_id      UUID NOT NULL REFERENCES public.gstr9c_reconciliations(id) ON DELETE CASCADE,

  -- Purchases, Freight/Carriage, Power & Fuel, ... up to 10 CA-added "Any
  -- other expense" rows (the offline utility's own Common_Module.add_expense
  -- caps extra rows at 10). Free text rather than an enum: the fixed 15-head
  -- master list plus up to 10 CA-typed additions is exactly the shape a CHECK
  -- constraint cannot express without inventing the 10 "any other" slots as
  -- distinct values, which buys nothing over free text here.
  expense_head           TEXT NOT NULL,

  value_paise                BIGINT NOT NULL DEFAULT 0,
  total_itc_paise            BIGINT NOT NULL DEFAULT 0,
  eligible_itc_availed_paise BIGINT NOT NULL DEFAULT 0,

  line_order             INTEGER NOT NULL DEFAULT 0,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gstr9c_expense_lines_recon
  ON public.gstr9c_expense_lines (reconciliation_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr9c_expense_lines IS
  'GSTR-9C Table 14 — ITC availed on expenses per the audited financial '
  'statements, by expense head. CA-typed with no auto-fill: this product''s '
  'chart of accounts classifies for Schedule III captions, not these 26 '
  'GSTR-9C expense-head categories. GST-25, migration 423.';

ALTER TABLE public.gstr9c_expense_lines ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr9c_expense_lines"
  ON public.gstr9c_expense_lines;
CREATE POLICY "firm_staff_read_gstr9c_expense_lines"
  ON public.gstr9c_expense_lines
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr9c_expense_lines_assignment_scope"
  ON public.gstr9c_expense_lines;
CREATE POLICY "gstr9c_expense_lines_assignment_scope"
  ON public.gstr9c_expense_lines AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr9c_expense_lines TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr9c_expense_lines TO service_role;

COMMIT;
