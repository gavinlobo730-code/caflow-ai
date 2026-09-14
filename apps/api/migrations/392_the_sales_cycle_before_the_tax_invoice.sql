-- 392 — the sales cycle before the tax invoice (SALES-21).
--
-- WHAT WAS WRONG
--     The sales cycle started at the invoice. A client quotes, takes an order,
--     delivers against it and bills afterwards, and none of the first three
--     documents existed — so the CA either raised the tax invoice EARLY,
--     declaring a supply that had not happened and paying tax on it a month
--     before the money arrived, or kept the quotation in a spreadsheet and
--     re-typed every line when it converted.
--
--     The delivery challan is the one that costs money by being absent. CGST
--     Rule 55 prescribes it for four movements, and two of them start a clock
--     whose expiry is a DEEMED SUPPLY: s.143(3)/(4) for job work (one year for
--     inputs, three for capital goods) and s.31(7) for goods sent on approval
--     (six months). Neither clock is visible in a ledger — the goods left,
--     nothing was billed, no journal moved — so the challan is the only place
--     it can be computed from, and there was no challan.
--
-- SIX TABLES, AND WHY QUOTATION AND PROFORMA SHARE ONE
--     `sales_quotations` carries a `kind` of 'quotation' or 'proforma'. Their
--     particulars, their lines and their lifecycle are identical; only the
--     heading and the numbering series differ, and two near-identical tables
--     would mean two of every query for no gain. The delivery challan does NOT
--     join them: it carries Rule 55 particulars a quotation has no column for
--     — the reason for the movement, the transporter, the job worker, the
--     kind of goods and the date they came back.
--
-- NOTHING HERE POSTS A JOURNAL AND NOTHING HERE REACHES A RETURN
--     No revenue is earned on an offer and no receivable exists, so there is
--     no `journal_entry_id` on any of these tables and no posting path reads
--     them. GSTR-1 is built from documents that DECLARE a supply; a proforma
--     is the trap, because it looks like an invoice and is often numbered like
--     one, and a GSTR-1 that picked one up would declare a supply that never
--     happened. `domain/sales/order_cycle.py` states the rule and
--     `tests/test_the_sales_cycle_before_the_tax_invoice.py` asserts that no
--     return builder reads any of these six tables.
--
-- A PROFORMA IS NEVER NUMBERED FROM THE TAX-INVOICE SERIES
--     Rule 46(b) requires a tax invoice's serial number to be CONSECUTIVE and
--     unique for the financial year. Consuming a number for a document that
--     may never become a supply puts a permanent gap in the series, and if the
--     number is later reused for the real invoice, two documents bear it. Each
--     kind here has its own series, unique per client per kind — the same
--     shape migration 388 gave the two reverse-charge documents.
--
-- `goods_kind` IS NULLABLE WITH NO DEFAULT, and that is s.143 in this table.
--     One year for inputs, three for capital goods, and moulds, dies, jigs,
--     fixtures and tools outside both (second proviso to s.143(1)). Defaulting
--     to inputs would report a deemed supply two years before one arises;
--     defaulting to capital goods would hide one for two years. The CA says
--     which, and a job-work challan that does not is REPORTED as a gap rather
--     than given a clock.
--
-- A DOCUMENT-LEVEL DISCOUNT IS s.15(3)(a) AND IS HERE; s.15(3)(b) IS NOT
--     A discount given BEFORE or at the time of supply and recorded in the
--     document reduces the value of supply, and a quotation that offered one
--     is the document that becomes the invoice that must show it. A
--     POST-supply discount is a different remedy entirely — s.15(3)(b) needs
--     an agreement made at or before the supply, linkage to the invoices AND
--     the recipient's reversal of the attributable ITC — and that is the s.34
--     credit note itself, never a field on one. No note table carries a
--     discount column and
--     `tests/test_a_discount_cannot_make_a_supply_negative_pg.py` holds the
--     line, now stated as the rule rather than as one list of tables.
--
-- WHAT IS NOT HERE, DELIBERATELY
--     * FORM GST ITC-04. Rule 45(3) reports the job-work challans of a period
--       in it, and the period turns on the principal's own aggregate turnover
--       in the preceding financial year — a figure no column holds. The
--       domain module reports both readings and picks neither.
--     * An e-way bill. Rule 55(3)/(4) says a challan movement is declared as
--       Rule 138 specifies, and `eway_bill_records` already exists; linking
--       the two is a later step and not a column here.
--     * Any stock movement. Goods leaving on a challan have not been sold, so
--       `inventory_stock_ledger` must not move. A job-work despatch IS a
--       genuine stock question and it is a different one (stock with a third
--       party), which is INV-03's schema rather than this one.

-- ── Quotations and proforma invoices ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.sales_quotations (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)     ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id)   ON DELETE CASCADE,
  customer_id    UUID NOT NULL REFERENCES public.customers(id) ON DELETE RESTRICT,

  kind           TEXT NOT NULL CHECK (kind IN ('quotation', 'proforma')),
  document_no    TEXT NOT NULL,
  document_date  DATE NOT NULL,
  -- The offer's own expiry. NULL means the client stated none, which is NOT
  -- "still valid" — an offer open indefinitely is a thing a client may mean,
  -- and the domain module answers None rather than False.
  valid_until    DATE,

  status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'sent', 'accepted', 'declined',
                                     'converted', 'cancelled')),

  -- Snapshotted from the customer at the moment the document was raised, the
  -- same reason the tax invoice snapshots them: a customer who later changes
  -- address must not silently change what a document already sent out said.
  customer_name    TEXT,
  customer_gstin   TEXT,
  place_of_supply  TEXT,
  supply_state_code TEXT,
  is_inter_state   BOOLEAN NOT NULL DEFAULT false,
  currency         TEXT NOT NULL DEFAULT 'INR',

  -- CGST s.15(3)(a) at DOCUMENT level, stored exactly as the tax invoice
  -- stores it. The allocated per-line share is on the lines; these two are
  -- what the CA TYPED, and without them an amendment that re-sends the lines
  -- and not the header discount would silently drop it.
  discount_percent_bps INTEGER,
  discount_paise       BIGINT,

  -- Totals, in integer paise, derived from the lines at save time. Stored
  -- rather than generated because the line-level GST arithmetic lives in
  -- Python (`domain/gst/discount.py` and the cess module) and a SQL twin of it
  -- would be the second implementation this codebase keeps having to remove.
  taxable_paise   BIGINT NOT NULL DEFAULT 0,
  cgst_paise      BIGINT NOT NULL DEFAULT 0,
  sgst_paise      BIGINT NOT NULL DEFAULT 0,
  igst_paise      BIGINT NOT NULL DEFAULT 0,
  cess_paise      BIGINT NOT NULL DEFAULT 0,
  total_paise     BIGINT NOT NULL DEFAULT 0,

  -- Where it went, once it did. Both nullable: most quotations become
  -- neither.
  converted_to_order_id   UUID,
  converted_to_invoice_id UUID REFERENCES public.client_sales_invoices(id) ON DELETE SET NULL,

  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     UUID REFERENCES public.users(id),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT sales_quotations_document_no_not_blank
    CHECK (length(trim(document_no)) > 0),
  -- Rule 46(b)'s shape is enforced in `domain/gst/invoice_series.py` for the
  -- documents the rule reaches. It is imposed HERE too, on documents the rule
  -- does not reach, for one practical reason: a quotation becomes an invoice,
  -- and a number that cannot be a tax invoice number is a conversion that
  -- fails at the last step.
  CONSTRAINT sales_quotations_document_no_length CHECK (length(document_no) <= 16)
);

-- Per client PER KIND. A quotation and a proforma may bear the same number —
-- they are different series — and two quotations may not.
CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_quotation_no_per_client_kind
  ON public.sales_quotations (client_id, kind, upper(document_no));

CREATE INDEX IF NOT EXISTS idx_sales_quotations_client
  ON public.sales_quotations (firm_id, client_id, document_date DESC);
CREATE INDEX IF NOT EXISTS idx_sales_quotations_customer
  ON public.sales_quotations (customer_id);

CREATE TABLE IF NOT EXISTS public.sales_quotation_lines (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  quotation_id   UUID NOT NULL REFERENCES public.sales_quotations(id) ON DELETE CASCADE,
  line_order     INTEGER NOT NULL DEFAULT 0,

  description    TEXT NOT NULL,
  hsn_sac        TEXT,
  quantity       NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit           TEXT,
  rate_paise     BIGINT NOT NULL DEFAULT 0,
  gst_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18,
  is_service     BOOLEAN NOT NULL DEFAULT false,
  service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL,

  -- CGST s.15(3)(a), the same pair the sales invoice line carries.
  discount_percent_bps INTEGER,
  discount_paise       BIGINT,
  -- GST (Compensation to States) Act s.8(2)'s two limbs, as migration 374
  -- named them on the invoice line.
  cess_rate_bps                INTEGER,
  cess_specific_paise_per_unit BIGINT,

  taxable_amount_paise BIGINT NOT NULL DEFAULT 0,
  cgst_paise     BIGINT NOT NULL DEFAULT 0,
  sgst_paise     BIGINT NOT NULL DEFAULT 0,
  igst_paise     BIGINT NOT NULL DEFAULT 0,
  line_cess_paise BIGINT NOT NULL DEFAULT 0,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_quotation_lines_parent
  ON public.sales_quotation_lines (quotation_id);

-- ── Sales orders ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.sales_orders (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)     ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id)   ON DELETE CASCADE,
  customer_id    UUID NOT NULL REFERENCES public.customers(id) ON DELETE RESTRICT,

  document_no    TEXT NOT NULL,
  document_date  DATE NOT NULL,
  -- The customer's own purchase-order reference. A fact about THEIR document,
  -- so it is free text and never validated as one of ours.
  customer_po_no   TEXT,
  customer_po_date DATE,
  expected_delivery_date DATE,

  status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'confirmed', 'partially_delivered',
                                     'delivered', 'closed', 'cancelled')),

  quotation_id   UUID REFERENCES public.sales_quotations(id) ON DELETE SET NULL,

  customer_name    TEXT,
  customer_gstin   TEXT,
  place_of_supply  TEXT,
  supply_state_code TEXT,
  is_inter_state   BOOLEAN NOT NULL DEFAULT false,
  currency         TEXT NOT NULL DEFAULT 'INR',

  -- CGST s.15(3)(a) at document level — see sales_quotations.
  discount_percent_bps INTEGER,
  discount_paise       BIGINT,

  taxable_paise   BIGINT NOT NULL DEFAULT 0,
  cgst_paise      BIGINT NOT NULL DEFAULT 0,
  sgst_paise      BIGINT NOT NULL DEFAULT 0,
  igst_paise      BIGINT NOT NULL DEFAULT 0,
  cess_paise      BIGINT NOT NULL DEFAULT 0,
  total_paise     BIGINT NOT NULL DEFAULT 0,

  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     UUID REFERENCES public.users(id),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT sales_orders_document_no_not_blank CHECK (length(trim(document_no)) > 0),
  CONSTRAINT sales_orders_document_no_length CHECK (length(document_no) <= 16)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_sales_order_no_per_client
  ON public.sales_orders (client_id, upper(document_no));
CREATE INDEX IF NOT EXISTS idx_sales_orders_client
  ON public.sales_orders (firm_id, client_id, document_date DESC);
CREATE INDEX IF NOT EXISTS idx_sales_orders_customer
  ON public.sales_orders (customer_id);
CREATE INDEX IF NOT EXISTS idx_sales_orders_open
  ON public.sales_orders (firm_id, client_id)
  WHERE status IN ('confirmed', 'partially_delivered');

CREATE TABLE IF NOT EXISTS public.sales_order_lines (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  order_id       UUID NOT NULL REFERENCES public.sales_orders(id) ON DELETE CASCADE,
  line_order     INTEGER NOT NULL DEFAULT 0,

  description    TEXT NOT NULL,
  hsn_sac        TEXT,
  quantity       NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit           TEXT,
  rate_paise     BIGINT NOT NULL DEFAULT 0,
  gst_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18,
  is_service     BOOLEAN NOT NULL DEFAULT false,
  service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL,

  discount_percent_bps INTEGER,
  discount_paise       BIGINT,
  cess_rate_bps                INTEGER,
  cess_specific_paise_per_unit BIGINT,

  taxable_amount_paise BIGINT NOT NULL DEFAULT 0,
  cgst_paise     BIGINT NOT NULL DEFAULT 0,
  sgst_paise     BIGINT NOT NULL DEFAULT 0,
  igst_paise     BIGINT NOT NULL DEFAULT 0,
  line_cess_paise BIGINT NOT NULL DEFAULT 0,

  -- NO delivered_qty OR invoiced_qty COLUMN, and that is the same decision
  -- migration 278 took for `outstanding_paise`: what is left to deliver and
  -- what is left to bill are FUNCTIONS of the documents raised against the
  -- order, so a stored figure is wrong the moment a challan or an invoice is
  -- cancelled. `domain/sales/order_cycle.open_quantities` derives both.
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sales_order_lines_parent
  ON public.sales_order_lines (order_id);

-- ── Delivery challans (CGST Rule 55) ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.delivery_challans (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- NULLABLE: a job-work despatch goes to a JOB WORKER, who is a vendor and
  -- not a customer, and a movement "for reasons other than by way of supply"
  -- may go to the client's own second premises. Requiring a customer here
  -- would make the two commonest Rule 55 cases unrecordable.
  customer_id    UUID REFERENCES public.customers(id) ON DELETE RESTRICT,
  vendor_id      UUID REFERENCES public.vendors(id)   ON DELETE RESTRICT,

  document_no    TEXT NOT NULL,
  document_date  DATE NOT NULL,

  -- Rule 55(1)(a)-(c) with the two later sub-rules. The reason decides which
  -- clock runs and which particulars the document must carry, so it is a
  -- closed vocabulary rather than free text.
  reason         TEXT NOT NULL
                   CHECK (reason IN ('liquid_gas_quantity_unknown', 'job_work',
                                     'other_than_supply', 'sale_on_approval',
                                     'supply_invoice_to_follow',
                                     'skd_ckd_or_lots')),

  status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'issued', 'received_back',
                                     'cancelled')),

  -- CGST s.143. NULL means NOT RECORDED: one year for inputs, three for
  -- capital goods, and outside both for moulds, dies, jigs, fixtures and
  -- tools. No default, because every default is wrong for two of the three.
  goods_kind     TEXT
                   CHECK (goods_kind IS NULL OR goods_kind IN (
                     'inputs', 'capital_goods',
                     'moulds_dies_jigs_fixtures_tools')),
  -- When the goods actually came back. NULL is outstanding, not overdue.
  received_back_on DATE,
  -- The proviso to s.143(1) lets the Commissioner extend the period. An order
  -- addressed to this taxpayer, so it is recorded and never assumed, and is
  -- honoured only where it is LATER than the statutory date.
  extended_to    DATE,

  -- Rule 55(5): the complete invoice precedes the FIRST consignment and every
  -- subsequent challan references it.
  sales_invoice_id UUID REFERENCES public.client_sales_invoices(id) ON DELETE SET NULL,
  order_id         UUID REFERENCES public.sales_orders(id) ON DELETE SET NULL,

  consignee_name    TEXT,
  consignee_gstin   TEXT,
  consignee_address TEXT,
  transporter_name  TEXT,
  transporter_id    TEXT,
  vehicle_no        TEXT,
  place_of_supply   TEXT,
  is_inter_state    BOOLEAN NOT NULL DEFAULT false,

  -- Rule 55(1)(vi) taxable value always; (vii) tax only where the movement is
  -- a supply to the consignee. The columns exist on every row because a
  -- movement's reason can be corrected, and a nil on a job-work challan is
  -- the right answer rather than a missing one.
  taxable_paise  BIGINT NOT NULL DEFAULT 0,
  cgst_paise     BIGINT NOT NULL DEFAULT 0,
  sgst_paise     BIGINT NOT NULL DEFAULT 0,
  igst_paise     BIGINT NOT NULL DEFAULT 0,
  cess_paise     BIGINT NOT NULL DEFAULT 0,
  total_paise    BIGINT NOT NULL DEFAULT 0,

  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     UUID REFERENCES public.users(id),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT delivery_challans_document_no_not_blank
    CHECK (length(trim(document_no)) > 0),
  -- Rule 55(1) says "serially numbered not exceeding sixteen characters",
  -- which is the same limit Rule 46(b) puts on a tax invoice. This one IS the
  -- rule, not a convenience.
  CONSTRAINT delivery_challans_document_no_length CHECK (length(document_no) <= 16),
  -- s.143 reaches only a job-work movement. Recording a kind of goods on any
  -- other challan asserts a clock that does not run.
  CONSTRAINT delivery_challans_goods_kind_is_job_work
    CHECK (goods_kind IS NULL OR reason = 'job_work'),
  CONSTRAINT delivery_challans_extension_is_job_work
    CHECK (extended_to IS NULL OR reason = 'job_work')
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_challan_no_per_client
  ON public.delivery_challans (client_id, upper(document_no));
CREATE INDEX IF NOT EXISTS idx_delivery_challans_client
  ON public.delivery_challans (firm_id, client_id, document_date DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_challans_order
  ON public.delivery_challans (order_id);
-- The outstanding job-work and approval movements, which is what the deemed
-- supply runs on and the only query that needs to be fast.
CREATE INDEX IF NOT EXISTS idx_delivery_challans_outstanding
  ON public.delivery_challans (firm_id, client_id, document_date)
  WHERE received_back_on IS NULL
    AND status = 'issued'
    AND reason IN ('job_work', 'sale_on_approval');

CREATE TABLE IF NOT EXISTS public.delivery_challan_lines (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  challan_id     UUID NOT NULL REFERENCES public.delivery_challans(id) ON DELETE CASCADE,
  -- Which order line this consignment is against, where there is one. NULL on
  -- a job-work despatch, which has no order behind it.
  order_line_id  UUID REFERENCES public.sales_order_lines(id) ON DELETE SET NULL,
  line_order     INTEGER NOT NULL DEFAULT 0,

  description    TEXT NOT NULL,
  hsn_sac        TEXT,
  quantity       NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit           TEXT,
  -- Rule 55(1)(v): "provisional, where the exact quantity being supplied is
  -- not known" — which is Rule 55(1)(a)'s whole case. Recorded so the printed
  -- challan can say so; it changes no arithmetic.
  quantity_is_provisional BOOLEAN NOT NULL DEFAULT false,
  rate_paise     BIGINT NOT NULL DEFAULT 0,
  gst_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
  is_service     BOOLEAN NOT NULL DEFAULT false,
  service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL,

  taxable_amount_paise BIGINT NOT NULL DEFAULT 0,
  cgst_paise     BIGINT NOT NULL DEFAULT 0,
  sgst_paise     BIGINT NOT NULL DEFAULT 0,
  igst_paise     BIGINT NOT NULL DEFAULT 0,
  line_cess_paise BIGINT NOT NULL DEFAULT 0,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_delivery_challan_lines_parent
  ON public.delivery_challan_lines (challan_id);
CREATE INDEX IF NOT EXISTS idx_delivery_challan_lines_order_line
  ON public.delivery_challan_lines (order_line_id);

-- ── Comments the next reader needs ──────────────────────────────────────────

COMMENT ON TABLE public.sales_quotations IS
  'Quotations and proforma invoices. NEITHER IS A TAX INVOICE: no supply has '
  'been made, no journal is posted and nothing here reaches GSTR-1. A proforma '
  'is the trap, because it looks like an invoice and is often numbered like '
  'one — it draws from its OWN series, never the tax-invoice series, because '
  'consuming a Rule 46(b) number for a document that may never become a supply '
  'puts a permanent gap in a series the rule requires to be consecutive.';
COMMENT ON COLUMN public.sales_quotations.valid_until IS
  'The offer''s own expiry. NULL means none was stated, which is NOT the same '
  'as still valid — an offer open indefinitely is a thing a client may mean.';
COMMENT ON TABLE public.sales_orders IS
  'The customer''s acceptance. CGST s.7 charges a SUPPLY and an order is a '
  'promise to make one, so nothing posts and nothing is declared. What is '
  'still open is DERIVED from the challans and invoices raised against it '
  '(domain/sales/order_cycle.open_quantities) and deliberately not stored.';
COMMENT ON TABLE public.delivery_challans IS
  'CGST Rule 55 — goods moved without a tax invoice. TWO reasons start a clock '
  'whose expiry is a deemed supply: job work (s.143(3)/(4), one year for '
  'inputs and three for capital goods) and goods sent on approval (s.31(7), '
  'six months). Neither is visible in a ledger, so this document is the only '
  'place the expiry can be computed from. domain/gst/delivery_challan.py is '
  'the authority.';
COMMENT ON COLUMN public.delivery_challans.goods_kind IS
  'CGST s.143: one year for inputs, three for capital goods, and outside both '
  'for moulds, dies, jigs, fixtures and tools (second proviso to s.143(1)). '
  'NULL means NOT RECORDED and has no default — defaulting to inputs would '
  'report a deemed supply two years early, and to capital goods would hide one '
  'for two years. A job-work challan with none is reported as a gap.';
COMMENT ON COLUMN public.delivery_challans.received_back_on IS
  'When the goods actually came back. NULL is OUTSTANDING, not overdue — the '
  'period is run against the challan date by the domain module.';
COMMENT ON COLUMN public.delivery_challan_lines.quantity_is_provisional IS
  'CGST Rule 55(1)(v): quantity may be provisional "where the exact quantity '
  'being supplied is not known", which is Rule 55(1)(a)''s whole case. Printed '
  'on the challan; changes no arithmetic.';

-- ── RLS ─────────────────────────────────────────────────────────────────────

ALTER TABLE public.sales_quotations       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_quotation_lines  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_orders           ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sales_order_lines      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delivery_challans      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delivery_challan_lines ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['sales_quotations', 'sales_quotation_lines',
                           'sales_orders', 'sales_order_lines',
                           'delivery_challans', 'delivery_challan_lines'] LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS "firm_staff_read_%1$s" ON public.%1$I', t);
    EXECUTE format(
      'CREATE POLICY "firm_staff_read_%1$s" ON public.%1$I '
      'FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id())', t);

    -- Migration 084's assignment-scope loop has never run again (see 370), so
    -- a table created now carries only its firm-wide policy unless it says so
    -- here. These six are read from the browser, so they must say so.
    EXECUTE format(
      'DROP POLICY IF EXISTS "%1$s_assignment_scope" ON public.%1$I', t);
    EXECUTE format(
      'CREATE POLICY "%1$s_assignment_scope" ON public.%1$I '
      'AS RESTRICTIVE FOR ALL '
      'USING (public.can_access_client(client_id::text)) '
      'WITH CHECK (public.can_access_client(client_id::text))', t);

    EXECUTE format('GRANT SELECT ON public.%1$I TO authenticated', t);
    EXECUTE format(
      'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%1$I TO service_role', t);
  END LOOP;
END $$;
