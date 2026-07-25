-- Migration 248: one-time correction of EXISTING invoices that were created
-- while round-off was mandatory (companion data migration to 247, which made
-- rounding opt-in going forward).
--
-- Background
-- ----------
-- Before 247, journal_for_sales_invoice ALWAYS rounded an INR invoice's grand
-- total to the nearest rupee and pushed the -49..+50 paise difference to the
-- 'Round Off' ledger. Product Owner has reversed that product decision: an
-- invoice must show its exact calculated amount unless the CA explicitly opts
-- that invoice in. This migration retro-fits existing rows to the new rule.
--
-- What it changes, per affected invoice:
--   1. Trade Receivables debit  -> reduced by round_off_paise, so AR equals the
--      exact invoice total (this is what the customer actually owes).
--   2. The 'Round Off' journal line -> deleted. It only ever existed as the
--      contra to the rounding adjustment; with (1) applied the entry still
--      balances exactly, so no replacement line is needed.
--   3. Invoice header -> total_paise/txn_total reduced by round_off_paise,
--      round_off_paise zeroed, round_off_enabled left FALSE.
--
-- What it deliberately does NOT change:
--   * taxable_amount_paise, cgst/sgst/igst — the tax computed under s.15 CGST
--     Act read with the applicable rate notification is unaffected by
--     presentation rounding, so no GST figure moves. GSTR-1/3B totals already
--     filed from these invoices remain byte-identical.
--   * Revenue and GST Output Tax Payable journal lines — untouched for the
--     same reason. Only the AR side carried the rounding.
--   * The 'Round Off' chart_of_accounts row — kept active, because it is still
--     the posting target whenever a CA opts an invoice back IN via
--     round_off_enabled. Its balance simply becomes zero.
--
-- Rounding under GST: s.170 CGST Act permits rounding the tax payable to the
-- nearest rupee, it does not mandate rounding the invoice's grand total.
-- Presenting the exact total is compliant; this migration does not alter any
-- amount of tax.
--
-- Safety: idempotent (re-running is a no-op once round_off_paise = 0
-- everywhere), scoped strictly to invoices with a non-zero round_off_paise,
-- and wrapped so that an unexpected shape aborts the whole thing.
-- Draft invoices have no posted journal, so they get the header fix only.

BEGIN;

-- Resolve the affected set once, with its journal lines, so the mutations
-- below all target the same verified rows.
CREATE TEMP TABLE _mig248_targets ON COMMIT DROP AS
SELECT csi.id              AS invoice_id,
       csi.status          AS invoice_status,
       csi.round_off_paise AS round_off_paise,
       ar.id               AS ar_line_id,
       ro.id               AS ro_line_id
FROM public.client_sales_invoices csi
LEFT JOIN public.journal_entries je
       ON je.reference_no = csi.invoice_no
      AND je.client_id    = csi.client_id
      AND je.firm_id      = csi.firm_id
      AND je.status       = 'posted'
LEFT JOIN public.journal_lines ar
       ON ar.journal_entry_id = je.id
      AND ar.account_id = (SELECT id FROM public.chart_of_accounts
                            WHERE account_name = 'Trade Receivables'
                              AND client_id IS NULL
                              AND firm_id = csi.firm_id
                            LIMIT 1)
LEFT JOIN public.journal_lines ro
       ON ro.journal_entry_id = je.id
      AND ro.account_id = (SELECT id FROM public.chart_of_accounts
                            WHERE system_account_key = 'round_off'
                              AND client_id IS NULL
                              AND firm_id = csi.firm_id
                            LIMIT 1)
WHERE csi.round_off_paise <> 0;

-- Guard: every ISSUED invoice in scope must have exactly the pair of lines we
-- are about to rewrite. If the shape is unexpected anywhere, abort rather than
-- half-correct the ledger.
DO $guard$
DECLARE v_bad int;
BEGIN
  SELECT count(*) INTO v_bad
    FROM _mig248_targets
   WHERE invoice_status = 'issued'
     AND (ar_line_id IS NULL OR ro_line_id IS NULL);
  IF v_bad > 0 THEN
    RAISE EXCEPTION
      'Migration 248 aborted: % issued invoice(s) with round-off are missing '
      'their Trade Receivables and/or Round Off journal line', v_bad;
  END IF;
END
$guard$;

-- 1. Trade Receivables back to the exact amount owed.
UPDATE public.journal_lines jl
   SET debit_paise = jl.debit_paise - t.round_off_paise,
       txn_debit   = CASE WHEN jl.txn_debit IS NULL THEN NULL
                          ELSE jl.txn_debit - t.round_off_paise END
  FROM _mig248_targets t
 WHERE jl.id = t.ar_line_id
   AND t.invoice_status = 'issued';

-- 2. Drop the now-unnecessary Round Off contra line. Entry stays balanced
--    because step 1 removed exactly this amount from the debit side.
DELETE FROM public.journal_lines jl
 USING _mig248_targets t
 WHERE jl.id = t.ro_line_id
   AND t.invoice_status = 'issued';

-- 3. Invoice header shows the exact total; rounding stays opt-out.
UPDATE public.client_sales_invoices csi
   SET total_paise       = csi.total_paise - csi.round_off_paise,
       txn_total         = csi.txn_total   - csi.round_off_paise,
       round_off_paise   = 0,
       round_off_enabled = FALSE
  FROM _mig248_targets t
 WHERE csi.id = t.invoice_id;

-- Post-conditions: no rounding residue anywhere, and every posted entry that
-- we touched still balances to the paise.
DO $verify$
DECLARE
  v_residue     int;
  v_unbalanced  int;
BEGIN
  SELECT count(*) INTO v_residue
    FROM public.client_sales_invoices
   WHERE round_off_paise <> 0;
  IF v_residue > 0 THEN
    RAISE EXCEPTION 'Migration 248 failed: % invoice(s) still carry round_off_paise', v_residue;
  END IF;

  SELECT count(*) INTO v_unbalanced FROM (
    SELECT je.id
      FROM public.journal_entries je
      JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
     WHERE je.status = 'posted'
     GROUP BY je.id
    HAVING sum(jl.debit_paise) <> sum(jl.credit_paise)
  ) x;
  IF v_unbalanced > 0 THEN
    RAISE EXCEPTION 'Migration 248 failed: % posted journal entr(ies) do not balance', v_unbalanced;
  END IF;
END
$verify$;

COMMIT;
