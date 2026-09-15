-- 393 — the purchase cycle before the bill (PUR-25).
--
-- WHAT WAS WRONG
--     The purchase cycle started at the bill. A client raises a purchase
--     order, receives the goods against it and only then books the supplier's
--     invoice; neither of the first two documents existed, so there was
--     nothing to check the bill against — a supplier who short-shipped or
--     over-charged was paid in full unless somebody remembered — and, worse,
--     no record at all of WHEN the goods arrived.
--
--     That second absence is statutory, in two places:
--
--       * CGST s.16(2)(b) allows the input tax credit only where the recipient
--         "has received the goods or services". The supplier's invoice is not
--         evidence of that: an invoice dated March for goods that arrive in
--         April carries credit that belongs to April, and nothing in the books
--         recorded receipt at all, so the condition could not be tested.
--       * MSMED s.15 requires payment before the appointed day, which s.2(b)
--         fixes at fifteen days from the day of ACCEPTANCE — and the
--         Explanation to s.2(b) makes acceptance the day of ACTUAL DELIVERY,
--         unless the buyer objects in writing within fifteen days of delivery,
--         when it is the day the objection is removed.
--         `domain/income_tax/section_43b_h.py` has had to use the BILL date as
--         a proxy and carries `ACCEPTANCE_DATE_NOT_HELD` on every answer. A
--         goods receipt is the real date, and `objection_raised_on` /
--         `objection_removed_on` carry the Explanation's second limb.
--
-- FOUR TABLES, AND WHY THE GOODS RECEIPT IS NOT A FLAG ON THE ORDER
--     One purchase order is received in several consignments — that is the
--     ordinary case, not the exception — and each consignment has its own
--     date, its own carrier and its own condition on arrival. A
--     `received_on` column on the order line could hold one of them, and the
--     s.15 clock needs the LAST. So a goods receipt is its own document with
--     its own lines, each naming the order line it delivers against.
--
-- NOTHING HERE POSTS A JOURNAL AND NOTHING HERE MOVES STOCK
--     A purchase order commits the client to buy; a goods receipt records an
--     arrival. The expense, the input credit and the payable all arise when
--     the BILL is received, which is the existing path
--     (`routers/purchase_bills.py` with `domain/inventory_service`) and is
--     untouched. There is no `journal_entry_id` on any of these tables.
--
--     The stock question is deliberately left where it is. INV-05a costs a
--     receipt at the BILL's taxable value plus its s.17(5)-blocked tax, so
--     moving stock here would either cost it at a price the supplier has not
--     yet invoiced or move it twice. Goods received and not yet billed are a
--     real accrual — and building it needs a Goods Received Not Invoiced
--     account and a reversal path, which is an owner decision rather than
--     this one.
--
-- `received_on` IS A DATE AND IS REQUIRED; `objection_removed_on` IS NULLABLE
-- WITH NO DEFAULT.
--     A receipt with no date answers neither statutory question, so the column
--     is NOT NULL. The objection is the Explanation's second limb and most
--     receipts have none — NULL means no objection was raised, which is the
--     ordinary case and not a gap.

-- ── Purchase orders ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.purchase_orders (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  vendor_id      UUID NOT NULL REFERENCES public.vendors(id) ON DELETE RESTRICT,

  document_no    TEXT NOT NULL,
  document_date  DATE NOT NULL,
  expected_date  DATE,

  status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'approved', 'partially_received',
                                     'received', 'closed', 'cancelled')),

  -- Snapshotted from the vendor when the order was raised, for the reason the
  -- bill snapshots them: a vendor who later changes address must not silently
  -- change what a document already sent out said.
  vendor_name    TEXT,
  vendor_gstin   TEXT,
  place_of_supply TEXT,
  is_inter_state BOOLEAN NOT NULL DEFAULT false,
  currency       TEXT NOT NULL DEFAULT 'INR',

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

  CONSTRAINT purchase_orders_document_no_not_blank
    CHECK (length(trim(document_no)) > 0),
  CONSTRAINT purchase_orders_document_no_length CHECK (length(document_no) <= 32)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_order_no_per_client
  ON public.purchase_orders (client_id, upper(document_no));
CREATE INDEX IF NOT EXISTS idx_purchase_orders_client
  ON public.purchase_orders (firm_id, client_id, document_date DESC);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_vendor
  ON public.purchase_orders (vendor_id);
CREATE INDEX IF NOT EXISTS idx_purchase_orders_open
  ON public.purchase_orders (firm_id, client_id)
  WHERE status IN ('approved', 'partially_received');

CREATE TABLE IF NOT EXISTS public.purchase_order_lines (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  order_id       UUID NOT NULL REFERENCES public.purchase_orders(id) ON DELETE CASCADE,
  line_order     INTEGER NOT NULL DEFAULT 0,

  description    TEXT NOT NULL,
  hsn_sac        TEXT,
  quantity       NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit           TEXT,
  rate_paise     BIGINT NOT NULL DEFAULT 0,
  gst_rate_percent NUMERIC(5,2) NOT NULL DEFAULT 18,
  is_service     BOOLEAN NOT NULL DEFAULT false,
  service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL,
  expense_account_id   UUID REFERENCES public.chart_of_accounts(id) ON DELETE SET NULL,

  -- CGST s.17(5), decided by the CA on the ORDER and carried forward to the
  -- bill. Defaulting it at conversion would re-decide blocked credit every
  -- time an order is billed, which is the same argument migration 379's
  -- recurring template makes.
  itc_eligible   BOOLEAN NOT NULL DEFAULT true,
  blocked_credit_reason TEXT,
  tds_applicable BOOLEAN NOT NULL DEFAULT false,
  cess_rate_bps                INTEGER,
  cess_specific_paise_per_unit BIGINT,

  taxable_amount_paise BIGINT NOT NULL DEFAULT 0,
  cgst_paise     BIGINT NOT NULL DEFAULT 0,
  sgst_paise     BIGINT NOT NULL DEFAULT 0,
  igst_paise     BIGINT NOT NULL DEFAULT 0,
  line_cess_paise BIGINT NOT NULL DEFAULT 0,

  -- NO received_qty OR billed_qty COLUMN: both are FUNCTIONS of the receipts
  -- and bills raised against the order, so a stored figure is wrong the moment
  -- one is cancelled. Migration 278's reasoning, applied to a quantity.
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_purchase_order_lines_parent
  ON public.purchase_order_lines (order_id);

-- ── Goods receipts ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.goods_receipt_notes (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  vendor_id      UUID NOT NULL REFERENCES public.vendors(id) ON DELETE RESTRICT,
  order_id       UUID REFERENCES public.purchase_orders(id) ON DELETE SET NULL,

  document_no    TEXT NOT NULL,
  -- WHEN THE GOODS ARRIVED. Required, because a receipt with no date answers
  -- neither CGST s.16(2)(b) nor MSMED s.2(b).
  received_on    DATE NOT NULL,

  status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'recorded', 'cancelled')),

  -- MSMED s.2(b), Explanation, SECOND LIMB: where the buyer objects in
  -- writing within fifteen days of delivery, the day of acceptance is the day
  -- the objection is removed. NULL means no objection was raised, which is
  -- the ordinary case and NOT a gap — so no default is needed and none is
  -- given.
  objection_raised_on  DATE,
  objection_removed_on DATE,

  vendor_name    TEXT,
  vendor_challan_no TEXT,
  vendor_challan_date DATE,
  transporter_name  TEXT,
  vehicle_no     TEXT,
  notes          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by     UUID REFERENCES public.users(id),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT goods_receipt_notes_document_no_not_blank
    CHECK (length(trim(document_no)) > 0),
  CONSTRAINT goods_receipt_notes_document_no_length
    CHECK (length(document_no) <= 32),
  -- An objection cannot be removed before it was raised, and a removal with
  -- no objection behind it is not the Explanation's second limb.
  CONSTRAINT goods_receipt_notes_objection_order
    CHECK (objection_removed_on IS NULL
           OR (objection_raised_on IS NOT NULL
               AND objection_removed_on >= objection_raised_on))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_goods_receipt_no_per_client
  ON public.goods_receipt_notes (client_id, upper(document_no));
CREATE INDEX IF NOT EXISTS idx_goods_receipt_notes_client
  ON public.goods_receipt_notes (firm_id, client_id, received_on DESC);
CREATE INDEX IF NOT EXISTS idx_goods_receipt_notes_order
  ON public.goods_receipt_notes (order_id);
CREATE INDEX IF NOT EXISTS idx_goods_receipt_notes_vendor
  ON public.goods_receipt_notes (vendor_id);

CREATE TABLE IF NOT EXISTS public.goods_receipt_lines (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id      UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  receipt_id     UUID NOT NULL REFERENCES public.goods_receipt_notes(id) ON DELETE CASCADE,
  -- Which order line arrived. NULL on a receipt against no order, which is
  -- ordinary — a delivery can precede the paperwork.
  order_line_id  UUID REFERENCES public.purchase_order_lines(id) ON DELETE SET NULL,
  line_order     INTEGER NOT NULL DEFAULT 0,

  description    TEXT NOT NULL,
  hsn_sac        TEXT,
  quantity       NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit           TEXT,
  -- What was REJECTED on arrival, out of the quantity above. A separate
  -- figure rather than a smaller `quantity`, because the s.16(2)(b) question
  -- is what was received and the s.15 question is what was accepted, and a
  -- single number cannot answer both.
  rejected_qty   NUMERIC(10,3) NOT NULL DEFAULT 0,
  rejection_reason TEXT,
  service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT goods_receipt_lines_rejected_within_received
    CHECK (rejected_qty >= 0 AND rejected_qty <= quantity)
);

CREATE INDEX IF NOT EXISTS idx_goods_receipt_lines_parent
  ON public.goods_receipt_lines (receipt_id);
CREATE INDEX IF NOT EXISTS idx_goods_receipt_lines_order_line
  ON public.goods_receipt_lines (order_line_id);

-- ── Linking a bill line back to what was ordered ────────────────────────────
--
-- NULLABLE, with no backfill and no default. Most purchases a practice sees —
-- professional fees, rent, utilities — are never ordered, so an unlinked line
-- is ordinary and not a finding; and every bill already on the books predates
-- this feature, so filling it in would be a guess dressed as a fact.
ALTER TABLE public.purchase_bill_lines
  ADD COLUMN IF NOT EXISTS purchase_order_line_id UUID
    REFERENCES public.purchase_order_lines(id) ON DELETE SET NULL;

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS purchase_order_id UUID
    REFERENCES public.purchase_orders(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_purchase_bill_lines_order_line
  ON public.purchase_bill_lines (purchase_order_line_id);
CREATE INDEX IF NOT EXISTS idx_purchase_bills_order
  ON public.purchase_bills (purchase_order_id);

-- ── Comments the next reader needs ──────────────────────────────────────────

COMMENT ON TABLE public.purchase_orders IS
  'A commitment to buy. Posts NO journal: the expense, the input tax credit '
  'and the payable all arise when the supplier''s bill is received. What is '
  'still open is DERIVED from the receipts and bills raised against it '
  '(domain/purchases/order_cycle.open_quantities) and deliberately not stored.';
COMMENT ON TABLE public.goods_receipt_notes IS
  'When the goods actually arrived — the fact CGST s.16(2)(b) conditions the '
  'input tax credit on, and the day MSMED s.15''s fifteen days run from '
  '(s.2(b), Explanation: the day of ACTUAL DELIVERY). '
  'domain/income_tax/section_43b_h.py has had to use the bill date as a proxy '
  'and says so on every answer; this is the real date. Posts no journal and '
  'moves no stock — INV-05a costs a receipt at the BILL''s taxable value, so '
  'moving stock here would cost it at a price the supplier has not yet '
  'invoiced.';
COMMENT ON COLUMN public.goods_receipt_notes.received_on IS
  'The day of actual delivery. NOT NULL: a receipt with no date answers '
  'neither CGST s.16(2)(b) nor MSMED s.2(b).';
COMMENT ON COLUMN public.goods_receipt_notes.objection_removed_on IS
  'MSMED s.2(b), Explanation, second limb: where the buyer objects IN WRITING '
  'within fifteen days of delivery, the day of acceptance is the day the '
  'objection is removed — which is LATER than delivery, so it lengthens the '
  'period and cannot manufacture a s.43B(h) disallowance. NULL means no '
  'objection, which is the ordinary case and not a gap.';
COMMENT ON COLUMN public.goods_receipt_lines.rejected_qty IS
  'What was rejected on arrival, out of the quantity received. A separate '
  'figure rather than a smaller quantity, because s.16(2)(b) asks what was '
  'RECEIVED and MSMED s.2(b) asks what was ACCEPTED, and one number cannot '
  'answer both.';
COMMENT ON COLUMN public.purchase_bill_lines.purchase_order_line_id IS
  'Which purchase-order line this bill line is for, where the CA linked it. '
  'NULLABLE with no backfill: most purchases a practice sees are never '
  'ordered, so an unlinked line is ordinary — and every bill already on the '
  'books predates this column, so filling it in would be a guess.';

-- ── RLS ─────────────────────────────────────────────────────────────────────

ALTER TABLE public.purchase_orders      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.purchase_order_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.goods_receipt_notes  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.goods_receipt_lines  ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['purchase_orders', 'purchase_order_lines',
                           'goods_receipt_notes', 'goods_receipt_lines'] LOOP
    EXECUTE format(
      'DROP POLICY IF EXISTS "firm_staff_read_%1$s" ON public.%1$I', t);
    EXECUTE format(
      'CREATE POLICY "firm_staff_read_%1$s" ON public.%1$I '
      'FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id())', t);

    -- Migration 084's assignment-scope loop has never run again (see 370), so
    -- a table created now carries only its firm-wide policy unless it says so
    -- here. All four are read from the browser.
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
