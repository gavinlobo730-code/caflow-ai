-- 313: the same supplier invoice cannot be booked twice.
--
-- WHY
--   routers/purchase_bills has a duplicate guard on the BULK import path and
--   none on the ordinary create path, and no constraint behind either.
--   purchase_bills carried exactly one unique index: its primary key.
--
--   Walking a client with foreign suppliers through a year booked HEL/04 twice
--   — same vendor, same number, same date, same amount — and got two bills,
--   two posted journals and TWO Form 27Q rows for one supplier invoice:
--   Rs 1,04,000 withheld where Rs 52,000 was due. Nothing warned.
--
--   A duplicated purchase bill is double-counted expenditure, double input GST
--   credit under CGST s.16, and a duplicated deductee row in a filed TDS
--   return. It is the kind of error that survives a review precisely because
--   both copies look correct.
--
-- WHY AN INDEX AND NOT ONLY AN APPLICATION CHECK
--   Three code paths insert here — ordinary create, bulk import, and the AI
--   extraction draft — and CLAUDE.md records that the frontend also writes
--   ~83 tables directly through PostgREST, where rbac() never runs. A check in
--   one router closes one door. This closes the table.
--
--   Verified against production before writing it: ZERO existing duplicate
--   (client, vendor, bill_no) groups, so the index cannot fail on the live
--   database when this migration applies on merge.
--
-- WHAT IS DELIBERATELY OUTSIDE THE INDEX
--   * A CANCELLED bill. Cancelling is a credit undone — a CA who cancels
--     INV-001 because the amount was wrong and re-enters INV-001 correctly is
--     doing the right thing, and refusing that would be worse than the bug.
--   * A SOFT-DELETED bill, for the same reason.
--   * A bill with NO number. Blank is not a value: several blank-numbered
--     bills from one vendor are not duplicates of each other, and NULLS
--     DISTINCT would not help here because '' is not NULL.
--
--   Matched case- and whitespace-insensitively, because "INV-001", "inv-001"
--   and " INV-001 " are one supplier invoice and a CA typing the second one
--   is making exactly the mistake this exists to catch.
--
-- NOTHING UPSERTS THIS TABLE — checked before choosing a partial index. A
-- partial index is only inferable for ON CONFLICT when the statement repeats
-- its predicate, and PostgREST emits none (migration 307 learned this the hard
-- way). All three paths use a plain INSERT, so there is nothing to infer.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS uq_purchase_bills_vendor_invoice
  ON public.purchase_bills (client_id, vendor_id, lower(btrim(bill_no)))
  WHERE deleted_at IS NULL
    AND status <> 'cancelled'
    AND coalesce(btrim(bill_no), '') <> '';

COMMENT ON INDEX public.uq_purchase_bills_vendor_invoice IS
    'One supplier invoice, one bill. Excludes cancelled and soft-deleted bills '
    '(re-entering a corrected INV-001 after cancelling the wrong one is '
    'legitimate) and bills with no number (blank is not a value). Migration 313.';

COMMIT;
