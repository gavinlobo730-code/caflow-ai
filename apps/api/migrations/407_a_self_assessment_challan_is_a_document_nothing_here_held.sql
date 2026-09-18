-- §140A self-assessment tax: the challan the return is accompanied by (IT-13).
--
-- WHAT WAS MISSING
--
-- IT Act §140A(1): where any tax is payable on the basis of a return — after
-- taking into account the tax already deducted or collected, advance tax paid,
-- relief under §90, §90A or §91, and credit under §115JAA or §115JD — the
-- assessee "shall be liable to pay such tax together with interest and fee
-- payable ... before furnishing the return and the return shall be accompanied
-- by proof of payment of such tax, interest and fee".
--
-- That proof is a Challan 280 (ITNS 280), and this product held no record of
-- one. Three things followed:
--
--   * Schedule IT of every ITR asks for each challan's BSR code, date of
--     deposit, serial number and amount, and a CA had them on a bank receipt
--     and nowhere else.
--   * the ITR keying sheet (IT-17) prints `self_assessment_tax` as NIL on every
--     return and says why, because there was no source for it;
--   * `advance_tax_payments` could not hold it: that table is keyed
--     `UNIQUE (client_id, financial_year, installment_number)` with the number
--     CHECKed to 1..4, which is §208's four instalments. Self-assessment tax is
--     not an instalment of anything — it is what is left when the return is
--     drawn up — and giving it a fifth instalment number would put a payment
--     the statute does not schedule into a schedule §211 fixes.
--
-- WHY THE FIVE-WAY SPLIT IS STORED — AND WHAT IT DELIBERATELY DOES NOT DRIVE
--
-- It is stored because it is what the DOCUMENT says. Challan 280 carries the
-- tax, surcharge, cess, interest and fee apart, a CA reconciling a bank receipt
-- against a computation needs to see the same five boxes, and this product
-- records documents as they are rather than as a total somebody can re-derive.
--
-- It does NOT drive the appropriation, and that is the easy thing to get wrong
-- here. §140A(1)'s own Explanation says: "where the amount paid ... falls short
-- of the aggregate of the tax, interest and fee, the amount so paid shall first
-- be adjusted towards the fee payable and thereafter towards the interest
-- payable and the balance, if any, shall be adjusted towards the tax payable".
--
-- The order is the STATUTE's and it runs off what is DUE, not off what the
-- taxpayer wrote on the challan. So a short payment tendered with "interest
-- ₹12,000" typed into the interest box still settles the §234F fee first if a
-- fee is due — the Explanation overrides the payer's own labelling, which is
-- the whole reason it exists. Reading the appropriation off these five columns
-- would give a taxpayer who mis-typed a box a different outstanding tax, and
-- therefore different §234A and §234B interest, from one who did not.
--
-- `domain/income_tax/self_assessment.py` is the authority for the
-- appropriation; this table only records what was paid.
--
-- THE HEADS ARE RECORDED, NOT DERIVED
--
-- Challan 280's MINOR head for self-assessment tax is 300 (100 is advance tax,
-- 400 is tax on regular assessment), and the MAJOR head is 0020 for a company
-- and 0021 for any other assessee. Both are defaulted to the self-assessment
-- case and both are settable, because a challan records what somebody actually
-- paid under — the same reasoning migration 037's `minor_head` takes for
-- Challan 281, and the reason that column exists rather than being inferred
-- from the table it sits in.
--
-- NO UNIQUE KEY ON (client, year). A return may be accompanied by SEVERAL
-- challans — a CA who pays in two instalments on two days has two, Schedule IT
-- has a row for each, and a constraint admitting one would make the second
-- unrecordable. Uniqueness is on the CHALLAN's own identity instead: the same
-- BSR code, date and serial number is the same payment, and recording it twice
-- would double the credit claimed on the return.

CREATE TABLE IF NOT EXISTS public.self_assessment_challans (
  id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id          UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- The PREVIOUS year the tax relates to, in this product's own YYYY-YY form.
  -- Not the assessment year: every other income-tax table here is keyed on the
  -- financial year and `models/fy.py` validates that shape.
  financial_year     TEXT        NOT NULL,

  -- Schedule IT's own three identifying particulars, exactly as the form asks.
  bsr_code           TEXT        NOT NULL,
  deposit_date       DATE        NOT NULL,
  challan_serial_no  TEXT        NOT NULL,

  -- The five-way split the challan carries. `total_paise` is what left the
  -- bank account and is the figure Schedule IT's "Amount" column takes; the
  -- other four are what it was paid TOWARDS, and §140A's Explanation needs
  -- them apart.
  tax_paise          BIGINT      NOT NULL DEFAULT 0,
  surcharge_paise    BIGINT      NOT NULL DEFAULT 0,
  cess_paise         BIGINT      NOT NULL DEFAULT 0,
  interest_paise     BIGINT      NOT NULL DEFAULT 0,
  fee_paise          BIGINT      NOT NULL DEFAULT 0,
  total_paise        BIGINT      NOT NULL DEFAULT 0,

  major_head         TEXT        NOT NULL DEFAULT '0021',
  minor_head         TEXT        NOT NULL DEFAULT '300',
  bank_name          TEXT,
  notes              TEXT,
  created_by         UUID,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT self_assessment_challans_major_head_check
    CHECK (major_head IN ('0020', '0021')),
  CONSTRAINT self_assessment_challans_minor_head_check
    CHECK (minor_head IN ('100', '300', '400')),
  -- Seven numeric digits, the SAME shape migration 112 gave
  -- `tds_challans.bsr_code`. Written as a plain CHECK rather than 112's NOT
  -- VALID because this table is new and has nothing to grandfather. A bank
  -- branch code is the half of Schedule IT's identity a typo is invisible in:
  -- the serial number is wrong-looking when it is wrong, and a six-digit BSR
  -- looks exactly like a seven-digit one until the return is processed.
  CONSTRAINT self_assessment_challans_bsr_code_format
    CHECK (bsr_code ~ '^[0-9]{7}$'),
  CONSTRAINT self_assessment_challans_serial_present
    CHECK (btrim(challan_serial_no) <> ''),
  -- Every figure is a sum of money paid over. None may be negative: a refund
  -- is not a negative challan, it is the assessment's business.
  CONSTRAINT self_assessment_challans_amounts_non_negative
    CHECK (tax_paise >= 0 AND surcharge_paise >= 0 AND cess_paise >= 0
           AND interest_paise >= 0 AND fee_paise >= 0 AND total_paise >= 0)
);

COMMENT ON TABLE public.self_assessment_challans IS
  'IT Act s.140A (IT-13). One Challan 280 accompanying a return. Several may '
  'exist for one client-year — Schedule IT has a row per challan — so there is '
  'deliberately no unique key on (client, financial_year); uniqueness is on '
  'the challan''s own identity below.';

-- DELIBERATELY NOT CHECKED: total_paise = tax + surcharge + cess + interest +
-- fee. On a challan the CA has in front of them the two agree, and where they
-- do not the position report SAYS so. A CHECK would refuse the one case that
-- makes the record worth having — a bank receipt showing only what left the
-- account — and a challan nobody can enter is a challan kept in a spreadsheet,
-- which is the state this table exists to end. See
-- `domain/income_tax/self_assessment.SPLIT_DOES_NOT_FOOT`.

COMMENT ON COLUMN public.self_assessment_challans.fee_paise IS
  's.234F fee. Stored apart from interest and tax because s.140A(1)''s '
  'Explanation appropriates a SHORT payment fee first, then interest, then '
  'tax — an order a single total cannot express.';

COMMENT ON COLUMN public.self_assessment_challans.minor_head IS
  'Challan 280 minor head: 300 = self-assessment tax (the default), 100 = '
  'advance tax, 400 = tax on regular assessment. Settable rather than inferred '
  'because a challan records what somebody actually paid under.';

COMMENT ON COLUMN public.self_assessment_challans.major_head IS
  'Challan 280 major head: 0020 for a company, 0021 for any other assessee.';

-- The same BSR code, date and serial number IS the same payment. Recording it
-- twice would double the credit claimed on the return, which is the one error
-- this table can cause on its own.
CREATE UNIQUE INDEX IF NOT EXISTS uq_self_assessment_challan_identity
  ON public.self_assessment_challans (firm_id, bsr_code, deposit_date, challan_serial_no);

CREATE INDEX IF NOT EXISTS idx_self_assessment_challans_client
  ON public.self_assessment_challans (client_id, financial_year);

ALTER TABLE public.self_assessment_challans ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.self_assessment_challans;
CREATE POLICY "firm_isolation" ON public.self_assessment_challans
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scope, applied here at creation rather than left
-- for a later sweep: this row names a client, and an Executive who is not
-- assigned to that client must not see their tax payments. See CLAUDE.md on
-- why 084's one-shot DO loop never runs again.
DROP POLICY IF EXISTS "self_assessment_challans_assignment_scope"
  ON public.self_assessment_challans;
CREATE POLICY "self_assessment_challans_assignment_scope"
  ON public.self_assessment_challans
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.self_assessment_challans TO authenticated;
