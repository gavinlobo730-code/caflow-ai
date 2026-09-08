-- 339 — gstr3b_returns records the CASH payable, not only the set-off residual
-- (GST-01, the half that was left).
--
-- WHAT WAS WRONG
--     §49(4) allows the electronic credit ledger to pay only "output tax", and
--     §2(82) defines output tax as EXCLUDING "tax payable by him on reverse
--     charge basis". So §9(3)/(4) tax is always cash, always on top of whatever
--     the Table 6 set-off leaves. The computer knows this — it has carried
--     `rcm_cash_paise` and `cash_payable_paise` since the first half of GST-01 —
--     and the RECORD did not: `gstr3b_returns` holds `net_igst/cgst/sgst_paise`
--     and `net_tax_paise`, every one of them the credit-settled figure.
--
--     `filings.tax_payable_paise` is written from `net_tax_paise`
--     (routers/gst_workspace.py, record_filing), so a return with any reverse
--     charge on it recorded a tax payable SMALLER than the challan the CA
--     actually paid. The books and the payment then disagree, and the row that
--     is supposed to be the evidence of what was filed is the one that is wrong.
--
--     Worked: one intra-state sale (CGST 90,000p + SGST 90,000p) with one RCM
--     inward supply of IGST 500p. The set-off residual is 1,79,500p; the challan
--     is 1,80,000p. The stored figure was 1,79,500p.
--
-- WHY TWO COLUMNS AND NOT ONE
--     `cash_payable_paise` is the challan. `rcm_cash_paise` is the part of it
--     that credit could never have touched. Storing only the total would leave
--     the reader unable to tell a return with reverse charge from one where the
--     credit simply ran out — which is the same "0 and 0 mean opposite things"
--     problem `itc_carried_forward_paise` exists to solve on the other side.
--
-- DEFAULT 0 IS HONEST HERE, unlike itc_2a_*. A return with no reverse charge
-- genuinely has rcm_cash_paise = 0, and for an existing row cash_payable_paise
-- of 0 is read alongside net_tax_paise by the code, which falls back to
-- net_tax_paise when the cash figure has never been written. A backfill would
-- have to re-run the set-off against books that may have moved since; the
-- fallback states the old figure instead of inventing a new one.

ALTER TABLE public.gstr3b_returns
  ADD COLUMN IF NOT EXISTS rcm_cash_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS cash_payable_paise BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.gstr3b_returns.rcm_cash_paise IS
  'Table 3.1(d) reverse-charge tax. Always cash: §49(4) with §2(82) bars the '
  'credit ledger from paying it.';
COMMENT ON COLUMN public.gstr3b_returns.cash_payable_paise IS
  'The challan figure — the Table 6 set-off residual PLUS rcm_cash_paise. '
  '0 on rows saved before migration 339; callers fall back to net_tax_paise, '
  'which is the set-off residual alone.';
