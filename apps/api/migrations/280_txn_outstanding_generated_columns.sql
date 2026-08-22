-- Migration 280: txn_outstanding as a generated column, so the FX open-balance
-- reports fetch only the foreign documents that are actually open.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 278 did this for AR/AP aging in base currency. The FX reports have
-- the identical bug in foreign currency and were missed, because 278 was applied
-- where the bug was reported rather than everywhere the pattern occurred:
--
--     rows = _paginate_all(... .eq("client_id", client_id))      -- every invoice
--     for r in rows:
--         if cur == _BASE or status in _DEAD: continue           -- in Python
--         foreign_out = txn_total - paid_txn
--         if foreign_out > 0: ...                                -- in Python
--
-- _open_foreign_invoices and _open_foreign_bills each fetch every document the
-- client has ever raised — 5,662 invoices and 759 bills on the live client — to
-- return the handful still open in a foreign currency. On that client the answer
-- is EMPTY: every document there is INR.
--
-- Three of those four conditions are ordinary column comparisons and move into
-- the query on their own. The fourth is arithmetic, and PostgREST can filter a
-- column but not an expression — which is exactly what stopped 278, and gets the
-- same answer: make the expression a column.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- GENERATED ALWAYS ... STORED, so Postgres maintains it on every write: no
-- trigger to forget, no backfill, and no second place the formula can be edited.
-- The services READ this column instead of recomputing the subtraction, so a
-- document's foreign outstanding cannot depend on which code path asked.
--
-- Formulas transcribed from the services they replace:
--   * AR (client_sales_invoices): txn_total       - paid_txn
--   * AP (purchase_bills):        txn_net_payable - paid_txn
--
-- These are MINOR UNITS of the transaction currency (cents, fils), not paise —
-- hence the name. The base-currency figure stays outstanding_paise from 278 and
-- stays authoritative; this one exists so the foreign side can be filtered and
-- so the CA sees what the customer actually owes in the currency they owe it in.
--
-- COALESCE on every term. txn_total and txn_net_payable are both nullable, and a
-- NULL anywhere makes the whole expression NULL — which as a filter (`> 0`)
-- silently drops the row, an open foreign invoice vanishing from the report
-- rather than an error. The Python being replaced coalesced too.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE INDEX PREDICATE NAMES THE CURRENCY
-- ═══════════════════════════════════════════════════════════════════════════
-- INR documents carry txn_total as well (5,659 of the live client's 5,662 have
-- it populated, mirroring total_paise, with paid_txn 0), so `txn_outstanding > 0`
-- alone is true for nearly every row in the table and an index predicated on it
-- would cover the whole table. It is `txn_currency <> 'INR'` that makes the set
-- small. Both columns are NOT NULL, so the comparison is exact.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SAFETY
-- ═══════════════════════════════════════════════════════════════════════════
-- Adding a STORED generated column rewrites the table under ACCESS EXCLUSIVE.
-- client_sales_invoices is 6.7 MB / 5,662 rows and purchase_bills 1.4 MB / 759
-- across every firm, so the lock is held for a moment, not a maintenance window.
--
-- Purely additive: nothing dropped or renamed, and a new column changes no
-- existing frontend select. Idempotent, and safe to re-run.

BEGIN;

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS txn_outstanding bigint
  GENERATED ALWAYS AS (
      COALESCE(txn_total, 0)
    - COALESCE(paid_txn, 0)
  ) STORED;

COMMENT ON COLUMN public.client_sales_invoices.txn_outstanding IS
    'Amount still recoverable in the TRANSACTION currency, in minor units: '
    'txn_total - paid_txn. Generated, so it cannot drift from its parts. The FX '
    'open-balance and exposure reports filter on it instead of fetching every '
    'invoice and subtracting in Python. The base-currency figure is '
    'outstanding_paise (migration 278) and stays authoritative. Migration 280.';

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS txn_outstanding bigint
  GENERATED ALWAYS AS (
      COALESCE(txn_net_payable, 0)
    - COALESCE(paid_txn, 0)
  ) STORED;

COMMENT ON COLUMN public.purchase_bills.txn_outstanding IS
    'Amount still payable in the TRANSACTION currency, in minor units: '
    'txn_net_payable - paid_txn. Generated, so it cannot drift from its parts. '
    'The FX open-balance and exposure reports filter on it instead of fetching '
    'every bill and subtracting in Python. The base-currency figure is '
    'outstanding_paise (migration 278) and stays authoritative. Migration 280.';

-- Partial indexes matching the FX open-balance query exactly: one client's open
-- FOREIGN documents. Partial because the INR rows and the settled foreign ones
-- are precisely what these reports must stop reading, so indexing them would
-- reintroduce the cost this migration exists to remove. _DEAD there is
-- draft/cancelled/paid — a fully paid document is not an open balance.
CREATE INDEX IF NOT EXISTS idx_csi_open_foreign
    ON public.client_sales_invoices (firm_id, client_id, invoice_date)
 WHERE txn_currency <> 'INR'
   AND txn_outstanding > 0
   AND status NOT IN ('draft', 'cancelled', 'paid');

CREATE INDEX IF NOT EXISTS idx_pb_open_foreign
    ON public.purchase_bills (firm_id, client_id, bill_date)
 WHERE txn_currency <> 'INR'
   AND txn_outstanding > 0
   AND status NOT IN ('draft', 'cancelled', 'paid');

COMMIT;
