-- GST compensation cess reaches the document and the ledger (PUR-20, SALES-20).
--
-- WHAT WAS MISSING
--
-- Nothing in the product could record compensation cess. `purchase_bills`
-- carried `ineligible_itc_cess_paise` (migration 240) and `tds_cess_paise`
-- (migration 309, the s.195 health-and-education cess, an unrelated tax) and
-- no `cess_paise` at all; `purchase_bill_lines`, `client_sales_invoices` and
-- `client_sales_invoice_lines` carried none of the three. Both return
-- builders were already waiting for the data — `gstr1_builder` reads
-- `inv.cess_paise` and `line.cess_paise` into `csamt` on every table, and
-- `gstr3b_computer` keeps a whole cess head with its own liability, ITC and
-- set-off — so `services/gst_return_service.py` read `cess_paise` off six
-- document tables through `select("*")`, found nothing, and silently
-- resolved 0.
--
-- The consequence is not a missing disclosure. A client dealing in aerated
-- waters, pan masala, tobacco, coal or motor vehicles pays cess on every
-- inward invoice and charges it on every outward one, and the product could
-- record neither: GSTR-1 `csamt` was zero on every row, GSTR-3B Table 4(A)
-- cess was nil so the credit was never claimed, and the trade payable to the
-- vendor was understated by the cess actually owed.
--
-- WHY TWO RATE COLUMNS AND NOT ONE
--
-- GST (Compensation to States) Act 2017 s.8(2): the cess is levied "on the
-- basis of VALUE, QUANTITY or on such basis at such rate not exceeding the
-- rate set forth in the corresponding entry in column (4) of the Schedule".
-- Real entries use each basis — aerated waters and motor vehicles ad
-- valorem, coal at so much per tonne, cigarettes at a percentage PLUS a
-- figure per thousand. One percentage column could express the first and
-- would silently under-charge the other two.
--
-- `cess_specific_paise_per_unit` is deliberately the same name migration 181
-- gave the firm HSN library, so the library can feed these lines later
-- without a translation step. `cess_rate_bps` is basis points rather than
-- 181's `cess_rate_pct` because every other rate on a LINE in this schema is
-- bps (`gst_rate_bps`), and integer paise arithmetic is the house rule.
--
-- `cess_paise` is DERIVED from the two, by `domain/gst/compensation_cess.py`,
-- for the same reason cgst/sgst/igst are derived from `gst_rate_bps`: an
-- amount no rate produces cannot be checked and drifts on the first edit.
--
-- WHY THE LEDGERS ARE SEEDED HERE
--
-- `phase2_journal_service._find_account` RAISES where an account cannot be
-- resolved, so the first cess-bearing bill a firm receives would fail to post
-- rather than post wrongly — correct, and useless to the CA meeting it.
-- `coa_seed_service.STANDARD_COA` gains both accounts for new firms, and it
-- skips a firm that already has any firm-wide account, so existing charts are
-- backfilled here. Mirrors migration 174, which did exactly this for the
-- 'Round Off' ledger.
--
-- THE NAMES AVOID '%GST Input%' AND '%GST Output%' ON PURPOSE. Those are the
-- ILIKE fallbacks `_find_account` uses for the CGST/SGST/IGST heads, matched
-- with `.limit(1)` and no ordering, so an account called "GST Compensation
-- Cess Output" could be returned for a CGST lookup on a chart that has no
-- per-head accounts — which is every chart this product seeds. "Compensation
-- Cess Payable" and "Compensation Cess Input Credit" match neither pattern,
-- nor any other pattern in the posting kernel.
--
-- s.11(2) of the Compensation Act, proviso: credit of this cess "shall be
-- utilised only towards payment of cess". It is therefore its own asset and
-- its own liability, never folded into the GST Input / GST Output ledgers —
-- a set-off the electronic credit ledger will not perform must not be
-- performed in the books either.
--
-- Every column is additive with a NOT NULL DEFAULT 0, so every existing
-- invoice, bill and line is byte-for-byte unchanged and every derived figure
-- built on them (`outstanding_paise`, migration 278) is unmoved.

BEGIN;

-- ── 1) Sales invoice: the header total and the per-line charge ─────────────

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.client_sales_invoice_lines
  ADD COLUMN IF NOT EXISTS cess_rate_bps INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_specific_paise_per_unit BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

-- ── 2) Purchase bill: the same, plus the blocked-credit split ──────────────
-- `ineligible_itc_cess_paise` already exists (migration 240) and had nothing
-- to hold; it is the s.17(5) portion of the header `cess_paise` below.

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.purchase_bill_lines
  ADD COLUMN IF NOT EXISTS cess_rate_bps INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_specific_paise_per_unit BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

-- ── 3) Non-negative, on every one of them ──────────────────────────────────
-- No UPPER bound on the rate: Schedule column (4) carries entries well above
-- 100% (unmanufactured tobacco, the pan-masala entries), so a ceiling would be
-- invented and would refuse a lawful charge.

DO $$
DECLARE
  t TEXT;
  c TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['client_sales_invoices', 'purchase_bills'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = t || '_cess_paise_check') THEN
      EXECUTE format(
        'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (cess_paise >= 0)',
        t, t || '_cess_paise_check');
    END IF;
  END LOOP;

  FOREACH t IN ARRAY ARRAY['client_sales_invoice_lines', 'purchase_bill_lines'] LOOP
    FOREACH c IN ARRAY ARRAY['cess_rate_bps', 'cess_specific_paise_per_unit', 'cess_paise'] LOOP
      IF NOT EXISTS (SELECT 1 FROM pg_constraint
                      WHERE conname = t || '_' || c || '_check') THEN
        EXECUTE format(
          'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK (%I >= 0)',
          t, t || '_' || c || '_check', c);
      END IF;
    END LOOP;
  END LOOP;
END $$;

COMMENT ON COLUMN public.client_sales_invoice_lines.cess_rate_bps IS
  'GST compensation cess, ad valorem limb, in basis points (1200 = 12%). '
  'Charged on taxable_amount_paise — the value AFTER a s.15(3)(a) discount. '
  'Compensation Act s.8(2) "on the basis of value". Migration 374.';
COMMENT ON COLUMN public.client_sales_invoice_lines.cess_specific_paise_per_unit IS
  'GST compensation cess, specific limb, in paise PER UNIT OF THIS LINE''S OWN '
  'UQC — nothing converts tonnes to kilograms. Compensation Act s.8(2) "on the '
  'basis of ... quantity". Added to the ad valorem limb, not compared with it. '
  'Same name as firm_hsn_rate_history''s column (migration 181) so the library '
  'can feed it later. Migration 374.';
COMMENT ON COLUMN public.client_sales_invoice_lines.cess_paise IS
  'The line''s compensation cess: ad valorem + specific, computed by '
  'domain/gst/compensation_cess.py. Derived, never typed. Migration 374.';
COMMENT ON COLUMN public.client_sales_invoices.cess_paise IS
  'Sum of the lines'' compensation cess. Included in total_paise, so '
  'outstanding_paise (migration 278) carries it. GSTR-1 csamt. Migration 374.';

COMMENT ON COLUMN public.purchase_bill_lines.cess_rate_bps IS
  'GST compensation cess, ad valorem limb, in basis points. See the matching '
  'column on client_sales_invoice_lines. Migration 374.';
COMMENT ON COLUMN public.purchase_bill_lines.cess_specific_paise_per_unit IS
  'GST compensation cess, specific limb, in paise per unit of this line''s own '
  'UQC. See the matching column on client_sales_invoice_lines. Migration 374.';
COMMENT ON COLUMN public.purchase_bill_lines.cess_paise IS
  'The line''s compensation cess: ad valorem + specific. Derived. Migration 374.';
COMMENT ON COLUMN public.purchase_bills.cess_paise IS
  'Sum of the lines'' compensation cess. Included in total_paise and therefore '
  'in net_payable_paise and outstanding_paise. The s.17(5) blocked portion of '
  'it is ineligible_itc_cess_paise (migration 240), which had nothing to hold '
  'until now. Migration 374.';

-- ── 4) The two ledgers, for every firm that already has a chart ────────────
-- Idempotent twice over: guarded by NOT EXISTS on the key or the name, and
-- ON CONFLICT on (firm_id, account_code) so a firm already using 1302 or 2010
-- keeps its own account and the migration does not abort. NULL is cast to
-- uuid explicitly — a bare NULL in a SELECT list is typed text, which
-- mismatches the uuid client_id column (migration 174 hit this).

INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
SELECT DISTINCT c.firm_id, NULL::uuid, '1302', 'Compensation Cess Input Credit',
       'Asset', 'Tax', TRUE, 'gst_cess_input'
FROM public.chart_of_accounts c
WHERE c.client_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.chart_of_accounts r
    WHERE r.firm_id = c.firm_id
      AND r.client_id IS NULL
      AND (r.system_account_key = 'gst_cess_input'
           OR r.account_name ILIKE 'Compensation Cess Input Credit')
  )
ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;

INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype,
   is_active, system_account_key)
SELECT DISTINCT c.firm_id, NULL::uuid, '2010', 'Compensation Cess Payable',
       'Liability', 'Current Liability', TRUE, 'gst_cess_output'
FROM public.chart_of_accounts c
WHERE c.client_id IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM public.chart_of_accounts r
    WHERE r.firm_id = c.firm_id
      AND r.client_id IS NULL
      AND (r.system_account_key = 'gst_cess_output'
           OR r.account_name ILIKE 'Compensation Cess Payable')
  )
ON CONFLICT ON CONSTRAINT chart_of_accounts_firm_code_unique DO NOTHING;

-- Backfill the system key onto any pre-existing account carrying the name but
-- no key, so key-first resolution works for those firms too (migration 174's
-- step 3, same reasoning).
UPDATE public.chart_of_accounts
   SET system_account_key = 'gst_cess_input'
 WHERE client_id IS NULL
   AND system_account_key IS NULL
   AND account_name ILIKE 'Compensation Cess Input Credit';

UPDATE public.chart_of_accounts
   SET system_account_key = 'gst_cess_output'
 WHERE client_id IS NULL
   AND system_account_key IS NULL
   AND account_name ILIKE 'Compensation Cess Payable';

COMMIT;
