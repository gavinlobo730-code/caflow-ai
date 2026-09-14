-- 389 — A BILL OF ENTRY, SO IMPORT IGST REACHES THE BOOKS AND THE RETURN
--       (PUR-18)
--
-- WHAT WAS MISSING
--   An importing client pays IGST — often the largest single ITC item of the
--   month — to CUSTOMS, against a Bill of Entry. The supplier never charges it:
--   IGST Act s.5(1) proviso puts the levy on imported goods under Customs
--   Tariff Act s.3(7), collected under the Customs Act at the point of
--   Customs Act s.12. So there is no purchase bill that can carry it.
--
--   This product had no such document. Putting the duty on the vendor's bill
--   overstates Trade Payables by the whole of it (the supplier was never owed
--   it); leaving it off loses the credit entirely. Either way GSTR-3B Table
--   4(A)(1) filed NIL against a GSTR-2B whose own `impg` section shows the
--   Bill of Entry, and the CA completed the return on the portal.
--
-- WHY A DOCUMENT AND NOT A FLAG ON purchase_bills
--   A Bill of Entry is not a supplier's invoice under a different name. It has
--   its own number and date (the customs house's, not the supplier's), its own
--   port, its own assessable value under Customs Act s.14 — which is NOT the
--   invoice value — and it settles against CUSTOMS rather than the supplier.
--   It also carries duties that are not tax at all.
--
-- WHAT IS CREDITABLE AND WHAT IS COST
--   IGST and compensation cess paid on a Bill of Entry are input tax: CGST Act
--   s.2(62)(a) includes "the integrated goods and services tax charged on
--   import of goods" in input tax, and Rule 36(1)(d) makes the bill of entry
--   the document the credit rests on.
--   BASIC CUSTOMS DUTY AND THE SOCIAL WELFARE SURCHARGE ARE NOT. They are
--   recoverable from nobody, so AS-2 (and Ind AS 2) paragraph 6 puts them in
--   the cost of purchase — "duties and taxes (other than those subsequently
--   recoverable by the enterprise from the taxing authorities)". They are
--   posted to an expense account the CA names. They are deliberately NOT
--   apportioned across inventory lines: the apportionment basis (by value? by
--   quantity? by weight?) is the open half of INV-05 and an owner decision,
--   and guessing one here would move closing stock.
--
-- SEZ IS ITS OWN SECTION OF THE PORTAL FILE and so is its own column: GSTR-2B
-- carries `impg` and `impgsez` separately, so a reconciliation that cannot
-- tell them apart cannot match either.

BEGIN;

CREATE TABLE IF NOT EXISTS public.bills_of_entry (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                     UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                   UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The customs house's own number and date. NOT ours: Rule 46(b)'s series
  -- rule is about documents the taxpayer issues, and this is one they receive.
  be_number                   TEXT NOT NULL,
  be_date                     DATE NOT NULL,
  -- ICEGATE port code. Nullable because a CA entering last month's duty from a
  -- challan may not have the document in front of them; the 2B match names it
  -- as missing rather than the row being refused.
  port_code                   TEXT,

  -- The overseas supplier and their invoice, where either is recorded. Both
  -- nullable and neither is required: the Bill of Entry exists whether or not
  -- the supplier's invoice has been entered, and the duty is owed to customs
  -- regardless. NO ACCOUNTS PAYABLE IS TOUCHED by this document.
  vendor_id                   UUID REFERENCES public.vendors(id) ON DELETE SET NULL,
  purchase_bill_id            UUID REFERENCES public.purchase_bills(id) ON DELETE SET NULL,

  -- Customs Act s.14 value plus the additions Rule 10 of the Customs Valuation
  -- (Determination of Value of Imported Goods) Rules 2007 makes. Recorded
  -- because it is the base the duties were assessed on and a CA checks it; the
  -- journal is built from the duty figures, never from this.
  assessable_value_paise      BIGINT NOT NULL DEFAULT 0,

  -- NOT CREDITABLE — cost, per AS-2 paragraph 6.
  basic_customs_duty_paise    BIGINT NOT NULL DEFAULT 0,
  social_welfare_surcharge_paise BIGINT NOT NULL DEFAULT 0,
  -- Anti-dumping, safeguard, agriculture infrastructure and development cess,
  -- and anything else the assessment carries. One column rather than a row per
  -- levy: none of them changes the accounting, and a column per levy would be
  -- a list this file has to keep in step with the Finance Act.
  other_duty_paise            BIGINT NOT NULL DEFAULT 0,

  -- CREDITABLE — CGST Act s.2(62)(a), Rule 36(1)(d).
  igst_paise                  BIGINT NOT NULL DEFAULT 0,
  cess_paise                  BIGINT NOT NULL DEFAULT 0,
  -- The part of the two above that CGST Act s.17(5) blocks. Same shape as
  -- purchase_bill_lines' ineligible_* columns (migration 240): the tax was
  -- still paid and is still cost, it simply is not credit.
  ineligible_igst_paise       BIGINT NOT NULL DEFAULT 0,
  ineligible_cess_paise       BIGINT NOT NULL DEFAULT 0,

  -- GSTR-2B keeps `impg` and `impgsez` in separate sections.
  is_sez                      BOOLEAN NOT NULL DEFAULT false,

  -- WHERE THE MONEY WENT AND WHERE THE NON-CREDITABLE DUTY LANDED. Both are
  -- required at POSTING time and neither is defaulted: a duty account guessed
  -- by name would put customs duty wherever the first ILIKE matched.
  payment_account_id          UUID REFERENCES public.chart_of_accounts(id),
  duty_expense_account_id     UUID REFERENCES public.chart_of_accounts(id),

  status                      TEXT NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft', 'posted')),
  journal_entry_id            UUID REFERENCES public.journal_entries(id),
  notes                       TEXT,

  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by                  UUID REFERENCES public.users(id),
  posted_at                   TIMESTAMPTZ,
  posted_by                   UUID REFERENCES public.users(id),
  deleted_at                  TIMESTAMPTZ,

  -- Every figure is a sum of money and none of them can be negative. A refund
  -- of duty is its own event (a s.27 claim), not a negative Bill of Entry.
  CONSTRAINT bills_of_entry_amounts_are_not_negative CHECK (
    assessable_value_paise >= 0 AND basic_customs_duty_paise >= 0
    AND social_welfare_surcharge_paise >= 0 AND other_duty_paise >= 0
    AND igst_paise >= 0 AND cess_paise >= 0
    AND ineligible_igst_paise >= 0 AND ineligible_cess_paise >= 0),

  -- Blocked credit is a PART of the tax paid, never more than it. The same
  -- invariant migration 240 states for a purchase bill line.
  CONSTRAINT bills_of_entry_blocked_credit_is_a_part_of_the_tax CHECK (
    ineligible_igst_paise <= igst_paise AND ineligible_cess_paise <= cess_paise),

  CONSTRAINT bills_of_entry_number_not_blank CHECK (btrim(be_number) <> ''),

  -- A posted document has both accounts and its journal. Enforced rather than
  -- left to the service: a posted row with no journal is a credit claimed on
  -- the return with nothing in the ledger behind it.
  CONSTRAINT bills_of_entry_posted_rows_are_complete CHECK (
    status <> 'posted' OR (journal_entry_id IS NOT NULL
                           AND payment_account_id IS NOT NULL
                           AND duty_expense_account_id IS NOT NULL))
);

-- ONE ROW PER BILL OF ENTRY PER CLIENT. The customs house's number is unique
-- per port per year rather than globally, so the port is part of the key —
-- and a NULL port cannot participate in a unique index, which is why a second
-- index covers exactly that case. Both partial on deleted_at, so a document
-- entered in error can be withdrawn and re-entered.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bill_of_entry_per_client_port
  ON public.bills_of_entry (client_id, be_number, be_date, port_code)
  WHERE deleted_at IS NULL AND port_code IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_bill_of_entry_per_client_no_port
  ON public.bills_of_entry (client_id, be_number, be_date)
  WHERE deleted_at IS NULL AND port_code IS NULL;

-- The return reads a period: client + date, with the soft-delete filter.
CREATE INDEX IF NOT EXISTS idx_bills_of_entry_client_date
  ON public.bills_of_entry (client_id, be_date)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_bills_of_entry_firm
  ON public.bills_of_entry (firm_id);

COMMENT ON TABLE public.bills_of_entry IS
  'Customs assessment on an import of goods (PUR-18). IGST and compensation '
  'cess here are INPUT TAX — CGST Act s.2(62)(a) with Rule 36(1)(d) — and '
  'reach GSTR-3B Table 4(A)(1); basic customs duty and the social welfare '
  'surcharge are recoverable from nobody and are COST (AS-2 paragraph 6). No '
  'accounts payable is touched: the duty is owed to customs, not to the '
  'supplier. Migration 389.';

COMMENT ON COLUMN public.bills_of_entry.assessable_value_paise IS
  'Customs Act s.14 value. NOT the supplier invoice value, and nothing is '
  'posted from it — it is recorded because it is the base the duties were '
  'assessed on.';

COMMENT ON COLUMN public.bills_of_entry.basic_customs_duty_paise IS
  'NOT creditable. AS-2 paragraph 6 puts a duty recoverable from nobody in the '
  'cost of purchase. Posted to duty_expense_account_id and deliberately NOT '
  'apportioned across inventory lines — the basis is the open half of INV-05.';

COMMENT ON COLUMN public.bills_of_entry.is_sez IS
  'GSTR-2B carries impg and impgsez as separate sections, so a reconciliation '
  'that cannot tell them apart cannot match either.';

COMMENT ON COLUMN public.bills_of_entry.port_code IS
  'ICEGATE port code. Nullable: a CA entering last month''s duty from a challan '
  'may not hold the document, and the 2B match names it as missing rather than '
  'refusing the row.';

ALTER TABLE public.bills_of_entry ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_bills_of_entry" ON public.bills_of_entry;
CREATE POLICY "firm_staff_read_bills_of_entry" ON public.bills_of_entry
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

-- Migration 084's loop has never run again (see 370), so a table created now
-- is firm-wide unless it says otherwise here — and an Executive would
-- otherwise see every client's imports.
DROP POLICY IF EXISTS "bills_of_entry_assignment_scope" ON public.bills_of_entry;
CREATE POLICY "bills_of_entry_assignment_scope"
  ON public.bills_of_entry AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Read-only from the browser. Every write goes through the API so rbac() runs
-- and the posting kernel, the period lock and the account resolution are asked.
GRANT SELECT ON public.bills_of_entry TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bills_of_entry TO service_role;

-- ── The ledger the non-creditable duty lands in ───────────────────────────
-- Seeded so the CA has something to pick rather than being sent to create an
-- account before they can record an import. Same shape as migration 374's two
-- cess ledgers: guarded by NOT EXISTS on key or name, ON CONFLICT on
-- (firm_id, account_code), NULL cast to uuid explicitly.
--
-- THE SUBTYPE IS 'Cost of Materials' AND IT IS LOAD-BEARING.
-- `domain/reporting/schedule_iii.pl_bucket` scans the SUBTYPE for keywords and
-- has no entry for 'Direct Expense' — which is exactly why migration 197 moved
-- accounts 5000 and 5001 off it. A customs duty landing in Other Expenses
-- would present below the gross margin, when Schedule III Division I Part II
-- puts the cost of materials consumed above it and duty on imported goods is
-- part of what those materials cost.
--
-- 5022 because 5021 is Depreciation Expense (migration 093) and ON CONFLICT
-- DO NOTHING would have silently skipped the insert for every firm that has
-- it — an account nobody could find rather than an error anybody would see.

INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
SELECT DISTINCT c.firm_id, NULL::uuid, '5022', 'Customs Duty',
       'Expense', 'Cost of Materials', TRUE, 'customs_duty'
FROM public.chart_of_accounts c
WHERE c.client_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.chart_of_accounts r
    WHERE r.firm_id = c.firm_id
      AND r.client_id IS NULL
      AND (r.system_account_key = 'customs_duty'
           OR r.account_name ILIKE 'Customs Duty')
  )
ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;

UPDATE public.chart_of_accounts
   SET system_account_key = 'customs_duty'
 WHERE client_id IS NULL
   AND system_account_key IS NULL
   AND account_name ILIKE 'Customs Duty';

COMMIT;
