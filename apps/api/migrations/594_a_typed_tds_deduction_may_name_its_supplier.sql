-- Migration 594: a deduction typed on the TDS screen may name the supplier it was paid to (ledger POST-A-078, part 1 of 2).
--
-- WHAT WAS WRONG
--   A deduction typed on the TDS screen carried a name and a PAN and nothing else, so its year was added up with other typed deductions
--   for the same PAN and never with the supplier's purchase bills and advances, which are added up per supplier
--   (services/vendor_tds.aggregate_so_far). The two halves of one payee's year never met: a Rs 30,000 professional fee typed here and four
--   Rs 30,000 bills for the same supplier each judged the s.194J yearly threshold on their own half, and the tax already withheld on one
--   half was not credited (s.200) on the other. A typed deduction also missed what the bill path asks of the supplier: its s.197
--   certificate (held per supplier) and its s.194A interest class.
--
-- WHAT THIS DOES
--   tds_deductions.vendor_id: the supplier a TYPED deduction was paid to. Nullable, because a typed deduction legitimately has no supplier
--   (a dividend, a partner's remuneration, a winning, a landowner's compensation are paid to people who are not suppliers), and a row a
--   purchase bill or a vendor advance wrote never carries it (a CHECK holds that: the document already names its supplier, and two
--   readers of one fact drift). ON DELETE RESTRICT, so a supplier a typed deduction names is not deleted from under it. That the supplier
--   is one of the row's own client's is asked by the shared guard every table with a vendor key carries (migration 565,
--   `guard_client_firm`), not by a trigger of its own, so the rule is worded once.
--   BACKFILL, typed rows only: a row gets the supplier when exactly ONE active, not non-resident supplier of the same firm and client holds
--   the row's PAN (a real PAN shape, compared in capitals without spaces); a row with no such supplier, or with two, stays without one and
--   is still added up by its PAN with the other typed rows that have none. A non-resident supplier is left out because a payment to it is
--   withheld under s.195, which the typed door does not charge, so a row linked to one could never be corrected there. Production held
--   one typed row on 15-11-2026.
--
-- DEPLOY ORDER. Part 1 of 2: the column, its CHECK, its index and the backfill, and nothing in the API reads or writes the column yet. The
-- code that does (part 2) must merge only once this migration is applied in production, because the bill path's withholding reads the
-- column on every purchase bill and advance of a supplier that withholds, and an API serving that code before the column exists would
-- refuse every such bill. Until part 2, a supplier the backfill linked to a typed row cannot be deleted (the key refuses; the supplier's
-- delete names the typed deductions only from part 2 on).
--
-- Idempotent. Reversible: 594_..._rollback.sql.

BEGIN;

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS vendor_id UUID REFERENCES public.vendors(id) ON DELETE RESTRICT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.tds_deductions'::regclass
                      AND conname = 'tds_deductions_supplier_only_on_a_typed_row') THEN
        ALTER TABLE public.tds_deductions
          ADD CONSTRAINT tds_deductions_supplier_only_on_a_typed_row
          CHECK (vendor_id IS NULL OR (purchase_bill_id IS NULL AND purchase_payment_id IS NULL));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tds_deductions_typed_supplier
  ON public.tds_deductions (firm_id, vendor_id, transaction_date)
  WHERE vendor_id IS NOT NULL;

-- The shared guard (565): with a vendor key on the table it now also installs row_vendor_in_client_ins and row_vendor_in_client_upd,
-- which refuse a supplier of another client; the client-in-firm triggers it re-creates are the ones the table already had.
DO $$
BEGIN
    PERFORM public.guard_client_firm('public.tds_deductions');
END $$;

-- The backfill: a typed row whose PAN exactly one active, not non-resident supplier of its client holds.
UPDATE public.tds_deductions AS d
   SET vendor_id = m.vendor_id
  FROM (
        SELECT d2.id AS deduction_id, min(v.id::text)::uuid AS vendor_id
          FROM public.tds_deductions AS d2
          JOIN public.vendors AS v
            ON v.firm_id = d2.firm_id
           AND v.client_id = d2.client_id
           AND v.is_active IS NOT FALSE
           AND v.residential_status IS DISTINCT FROM 'non_resident'
           AND upper(btrim(v.pan)) = upper(btrim(d2.deductee_pan))
         WHERE d2.vendor_id IS NULL
           AND d2.purchase_bill_id IS NULL
           AND d2.purchase_payment_id IS NULL
           AND upper(btrim(d2.deductee_pan)) ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
         GROUP BY d2.id
        HAVING count(*) = 1
       ) AS m
 WHERE d.id = m.deduction_id;

COMMENT ON COLUMN public.tds_deductions.vendor_id IS
  'The supplier a deduction TYPED on the TDS screen was paid to (POST-A-078, migration 594). NULL on a typed deduction paid to someone who '
  'is not a supplier, and always NULL on a row a purchase bill or a vendor advance wrote (the document names its supplier; a CHECK holds '
  'it). The supplier''s yearly s.194 total counts the typed rows that name it (services/vendor_tds.aggregate_so_far).';

COMMIT;
