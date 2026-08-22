-- Migration 278: outstanding_paise as a generated column, so aging fetches only
-- what is actually outstanding.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule: what crosses the wire must be proportional to the
-- size of the ANSWER, not the size of the ledger. AR and AP aging both broke it,
-- and both broke it the same way — they fetched EVERY non-deleted document for
-- the client and decided in Python which ones were still open:
--
--     invs = _paginate_all(... .eq("client_id", client_id).is_("deleted_at", "null"))
--     for inv in invs:
--         if (inv.get("status") or "") in _DEAD_INVOICE: continue
--         outstanding = total + debit_note - paid - credited
--         if outstanding <= 0: continue
--
-- Two filters, both applied after the rows had already crossed the wire. On the
-- live client that is 5,655 invoices and 759 bills today; the cost grows with
-- billing HISTORY rather than with what is owed, so a client five years in pays
-- for every settled invoice it has ever raised, on every load.
--
-- Unlike the cash flow statement (migration 277), the answer here is genuinely
-- one row per open document — the screen lists them. So this does not need the
-- work moved into a function; it needs the FILTER moved into the query. What
-- stopped that was arithmetic: PostgREST can filter a column, not an expression,
-- and "outstanding" is four columns subtracted.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Makes the expression a column. GENERATED ALWAYS ... STORED, so Postgres
-- maintains it on every write and there is no trigger to forget, no backfill to
-- run, and no second place the formula can be edited.
--
-- That last point is why a generated column rather than a plain one kept in step
-- by application code: the services now READ this column instead of recomputing
-- the subtraction, so the formula exists exactly once, in the schema, and an
-- invoice's outstanding figure cannot disagree with itself depending on which
-- code path asked.
--
-- The formulas are transcribed from the services they replace, including the
-- credit/debit-note terms:
--   * AR (client_sales_invoices): total + debit notes - paid - credited
--   * AP (purchase_bills):        net payable + credit notes - paid - debited
-- CGST Act §34 is what puts the note columns in there: a credit note reduces the
-- amount recoverable and a debit note increases it, and aging must follow the
-- amount actually recoverable rather than the invoice's face value.
--
-- COALESCE on every term. These columns are nullable and a NULL anywhere would
-- make the whole expression NULL, which as a filter (`> 0`) silently drops the
-- row — an open invoice vanishing from aging rather than an error. The Python
-- being replaced coalesced too; this keeps that exactly.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SAFETY
-- ═══════════════════════════════════════════════════════════════════════════
-- Adding a STORED generated column rewrites the table and takes an ACCESS
-- EXCLUSIVE lock. At current size that is trivial — client_sales_invoices is
-- 6.7 MB / 5,662 rows and purchase_bills 1.4 MB / 759 rows across every firm —
-- so the lock is held for a moment, not a maintenance window.
--
-- Purely additive: no column is dropped or renamed, and the frontend's direct
-- PostgREST reads are unaffected (a new column changes no existing select).
-- Idempotent, and safe to re-run.

BEGIN;

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS outstanding_paise bigint
  GENERATED ALWAYS AS (
      COALESCE(total_paise, 0)
    + COALESCE(debit_note_paise, 0)
    - COALESCE(paid_paise, 0)
    - COALESCE(credited_paise, 0)
  ) STORED;

COMMENT ON COLUMN public.client_sales_invoices.outstanding_paise IS
    'Amount still recoverable, in paise: total + debit notes - paid - credited '
    '(CGST Act §34). Generated, so it cannot drift from its parts. AR aging '
    'filters on it instead of fetching every invoice and subtracting in Python. '
    'Migration 278.';

ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS outstanding_paise bigint
  GENERATED ALWAYS AS (
      COALESCE(net_payable_paise, 0)
    + COALESCE(credit_note_paise, 0)
    - COALESCE(paid_paise, 0)
    - COALESCE(debited_paise, 0)
  ) STORED;

COMMENT ON COLUMN public.purchase_bills.outstanding_paise IS
    'Amount still payable, in paise: net payable + credit notes - paid - debited '
    '(CGST Act §34). Generated, so it cannot drift from its parts. AP aging '
    'filters on it instead of fetching every bill and subtracting in Python. '
    'Migration 278.';

-- Partial indexes matching the aging query exactly — the open documents for one
-- client. Partial rather than full because the settled rows are precisely what
-- these reports must stop reading, so there is no reason to index them: on a
-- mature client the index stays the size of the answer while the table grows.
CREATE INDEX IF NOT EXISTS idx_csi_open_for_aging
    ON public.client_sales_invoices (firm_id, client_id, due_date)
 WHERE deleted_at IS NULL
   AND outstanding_paise > 0
   AND status NOT IN ('draft', 'cancelled');

CREATE INDEX IF NOT EXISTS idx_pb_open_for_aging
    ON public.purchase_bills (firm_id, client_id, due_date)
 WHERE deleted_at IS NULL
   AND outstanding_paise > 0
   AND status NOT IN ('draft', 'cancelled');

COMMIT;
