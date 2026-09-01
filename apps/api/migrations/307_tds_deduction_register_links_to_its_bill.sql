-- Migration 307: link a TDS deduction to the bill that made it, so the
-- register can be kept in step with the books.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IS BROKEN
-- ═══════════════════════════════════════════════════════════════════════════
-- TDS is computed correctly on a purchase bill and withheld from what the
-- vendor is paid — routers/purchase_bills.py resolves the section, honours the
-- s.194C FY aggregate threshold, and floors the rate at 20% under s.206AA when
-- the vendor has no PAN. The figure lands on purchase_bills.tds_paise and is
-- netted off net_payable_paise.
--
-- And then it stops. NOTHING in this codebase has ever written a row to
-- tds_deductions. routers/tds.py and routers/tds_workspace.py only READ it,
-- and tds_workspace's own 26AS docstring says of the reconciliation that "it
-- does not reconcile against tds_deductions, and it never has."
--
-- So the money is deducted from the vendor in the books and is then invisible
-- to the compliance side: GET /api/tds/deductions/{client_id} returns nothing,
-- there is no challan to pay by the 7th of the following month (Rule 30), and
-- 26Q cannot be assembled for the quarter (Rule 31A). Found by driving one
-- client through a full year — twelve job-work bills, seven of them deducting,
-- and an empty register.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A COLUMN AND NOT JUST AN INSERT
-- ═══════════════════════════════════════════════════════════════════════════
-- The register has to FOLLOW the bill, not snapshot it. A bill can be edited
-- (the amount changes, so the deduction changes), cancelled (the deduction
-- never happened) or deleted. Without a link back, a corrected bill leaves its
-- old deduction standing and the return is filed on a figure the books no
-- longer hold.
--
-- purchase_bill_id is nullable because the register is not only for bills:
-- rows entered by hand, and any future deduction on a direct payment, have no
-- bill.
--
-- The unique index is PLAIN, not partial, and that is load-bearing. A partial
-- index (WHERE purchase_bill_id IS NOT NULL) reads as the tidier statement of
-- intent and breaks the write: Postgres can only infer a partial index for
-- ON CONFLICT when the statement repeats its predicate, PostgREST's upsert
-- emits none, and the insert fails with "there is no unique or exclusion
-- constraint matching the ON CONFLICT specification". Checked on 16 before
-- choosing. A plain unique index costs nothing here because Postgres treats
-- NULLs as distinct by default, so any number of hand-entered rows with no
-- bill are still allowed — also checked.
--
-- ON DELETE CASCADE: a hard-deleted bill takes its deduction with it. Soft
-- deletion and cancellation are handled in services/tds_register_service.py,
-- which removes the row when the bill leaves the books.
--
-- Additive and idempotent.

BEGIN;

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS purchase_bill_id uuid
    REFERENCES public.purchase_bills(id) ON DELETE CASCADE;

COMMENT ON COLUMN public.tds_deductions.purchase_bill_id IS
    'The purchase bill this deduction came from, so the register follows the '
    'book rather than snapshotting it — an edited bill updates its row, a '
    'cancelled or deleted one loses it. NULL for deductions with no bill '
    'behind them (entered by hand). Migration 307.';

-- One register row per bill; NULLS DISTINCT (the default) leaves the
-- hand-entered rows unconstrained. See the header for why this is not partial.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tds_deductions_purchase_bill
    ON public.tds_deductions (purchase_bill_id);

-- The register is read per client per financial year, and per quarter when a
-- return is assembled.
CREATE INDEX IF NOT EXISTS idx_tds_deductions_client_date
    ON public.tds_deductions (firm_id, client_id, transaction_date);

COMMIT;
