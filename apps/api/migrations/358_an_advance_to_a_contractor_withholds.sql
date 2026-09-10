-- Migration 358: TDS on a vendor payment, because §194 charges the EARLIER event.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (PUR-10)
-- ═══════════════════════════════════════════════════════════════════════════
-- `routers/purchase_payments.py` opens with "IT Act Section 194C/194I/194J: TDS
-- already deducted at bill stage; payment is net amount", and the module has no
-- TDS logic at all — a grep for `tds` across the router and the service returns
-- that comment and one other like it. `purchase_payments` has no tds_paise
-- column, while the accounts-receivable mirror `receipts` gained one in
-- migration 077.
--
-- The comment is true of a payment AGAINST A BILL and false of the case
-- migration 050 explicitly built this table to support. Its own line 318 says
-- purchase_bill_id is "nullable to support advance payments before bill
-- receipt", and every §194-series charging section — and §195 — reads
--
--     "at the time of credit of such sum to the account of the [payee] or at
--      the time of payment thereof ... WHICHEVER IS EARLIER"
--
-- so an advance paid before any bill exists is the earlier event and is exactly
-- when the tax falls due. Today it withholds nothing. A ₹5,00,000 mobilisation
-- advance to a contractor deducts ₹0 where §194C charges ₹10,000, interest runs
-- under §201(1A) from the payment date, and the §40(a)(ia) disallowance reaches
-- 30% of the whole expenditure.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THESE COLUMNS ARE, AND WHAT amount_paise STILL MEANS
-- ═══════════════════════════════════════════════════════════════════════════
-- `amount_paise` is UNCHANGED: the sum credited or paid to the vendor, which is
-- what the allocations are drawn against and what the bills are settled by.
-- What changes is the journal — the bank is now credited with
-- `amount_paise − tds_paise`, and the difference is credited to TDS Payable.
-- Every existing row carries tds_paise 0, so every existing journal is exactly
-- what it was.
--
-- `tds_base_paise` is the UNALLOCATED part of the payment — the advance. A
-- payment against a bill has already been charged at the bill, and charging it
-- again at payment would deduct the same sum twice.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- HOW THE SAME EXPENDITURE IS NOT CHARGED TWICE WHEN THE BILL ARRIVES
-- ═══════════════════════════════════════════════════════════════════════════
-- An advance of ₹5,00,000 and the ₹5,00,000 bill it is later adjusted against
-- are ONE expenditure, and the statute charges it once — at the earlier event.
-- Simply adding both into the year's aggregate would charge ₹10,00,000, so the
-- ledger would hold ₹20,000 against ₹5,00,000 credited: Trade Payables ends up
-- with a ₹10,000 DEBIT balance, which is the vendor owing the client the tax
-- that was over-withheld.
--
-- So a BILL absorbs so much of the outstanding advance pool as it can, and
-- records what it absorbed in `purchase_bills.tds_advance_adjusted_paise`. Its
-- own charged base is `taxable − adjusted`; the absorbed part was charged when
-- the advance was paid and is already in the aggregate through the payment row.
-- Storing what each bill absorbed is what stops the SECOND bill claiming the
-- same pool again, and it needs no matching table: the pool is
--
--     Σ purchase_payments.tds_base_paise − Σ purchase_bills.tds_advance_adjusted_paise
--
-- over the vendor, the section's parent and the financial year.
-- services/vendor_tds.py::aggregate_so_far is the authority and carries the
-- worked examples; §200 (tax already deducted is not deducted again) carries
-- the credit side unchanged.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- AND THE REGISTER, BECAUSE A DEDUCTION NOBODY CAN FILE IS NOT A DEDUCTION
-- ═══════════════════════════════════════════════════════════════════════════
-- tds_deductions gained purchase_bill_id in migration 307 so the register would
-- follow the book. An advance has no bill — having none is what makes it an
-- advance — so it needs its own link, or the deduction is real in the ledger
-- and absent from the challan and from 26Q. Rule 31A's deductee annexure asks
-- for the amount paid or credited ON A DATE, which an advance has.

BEGIN;

-- ── 1. The payment withholds ────────────────────────────────────────────────

ALTER TABLE public.purchase_payments
    ADD COLUMN IF NOT EXISTS tds_paise            BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tds_base_paise       BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tds_section          TEXT,
    ADD COLUMN IF NOT EXISTS tds_rate_bps         INTEGER,
    -- §195 reports tax, surcharge and cess in separate columns of Form 27Q's
    -- deductee annexure, so the split has to survive from the payment to the
    -- register. Always 0 on a §194-series advance, which deducts at the bare
    -- section rate and carries neither.
    ADD COLUMN IF NOT EXISTS tds_surcharge_paise  BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tds_cess_paise       BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tds_nature_of_income TEXT,
    ADD COLUMN IF NOT EXISTS tds_basis            TEXT;

COMMENT ON COLUMN public.purchase_payments.tds_paise IS
    'Tax withheld on this payment under the §194 series or §195. Non-zero only on '
    'the UNALLOCATED part — a payment against a bill was already charged at the '
    'bill. The bank leg of the journal is amount_paise minus this. Migration 358.';
COMMENT ON COLUMN public.purchase_payments.tds_base_paise IS
    'The sum tds_paise was computed on: the unallocated (advance) part of the '
    'payment. Stored rather than re-derived, because a later allocation changes '
    'unallocated_paise and must not change what was already withheld.';
COMMENT ON COLUMN public.purchase_payments.tds_rate_bps IS
    'Basis points, so 1% is 100 — the same unit as vendors.tds_rate_bps and '
    'purchase_bills.tds_rate_bps.';
COMMENT ON COLUMN public.purchase_payments.tds_basis IS
    'How a §195 figure was arrived at — not_chargeable / treaty / act / '
    '206aa_floor — so a NIL can be told apart from an absence months later. '
    'NULL on a resident-section advance.';

DO $$
BEGIN
    -- Tax without a base is a figure nobody can check, and a base without a
    -- section is a deduction under no charging provision. A §195 NIL is the one
    -- case with a base and no tax: the remittance still belongs on 27Q with a
    -- reason, so a base and a section without tax is allowed and tax without
    -- either is not.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'purchase_payments_tds_is_explained') THEN
        ALTER TABLE public.purchase_payments
            ADD CONSTRAINT purchase_payments_tds_is_explained
            CHECK (
                (COALESCE(tds_paise, 0) = 0 AND COALESCE(tds_base_paise, 0) = 0)
                OR
                (COALESCE(tds_base_paise, 0) > 0 AND tds_section IS NOT NULL)
            );
    END IF;

    -- The tax cannot exceed the payment it was withheld out of: the bank leg is
    -- amount_paise − tds_paise and a negative one would be a payment that took
    -- money OUT of the vendor.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'purchase_payments_tds_within_the_payment') THEN
        ALTER TABLE public.purchase_payments
            ADD CONSTRAINT purchase_payments_tds_within_the_payment
            CHECK (COALESCE(tds_paise, 0) >= 0
                   AND COALESCE(tds_surcharge_paise, 0) >= 0
                   AND COALESCE(tds_cess_paise, 0) >= 0
                   AND COALESCE(tds_paise, 0) <= COALESCE(amount_paise, 0)
                   AND COALESCE(tds_base_paise, 0) <= COALESCE(amount_paise, 0));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_purchase_payments_tds
    ON public.purchase_payments (firm_id, vendor_id, payment_date)
    WHERE tds_base_paise > 0;

-- ── 2. The bill records what it absorbed ────────────────────────────────────

ALTER TABLE public.purchase_bills
    ADD COLUMN IF NOT EXISTS tds_advance_adjusted_paise BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.purchase_bills.tds_advance_adjusted_paise IS
    'How much of this bill''s taxable value was already charged to TDS as an '
    'advance to the same vendor under the same section, and is therefore not '
    'charged again (§194 — credit or payment, whichever is earlier). Stored so '
    'the NEXT bill knows the advance pool was consumed. Migration 358.';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'purchase_bills_advance_adjustment_is_within_the_bill') THEN
        ALTER TABLE public.purchase_bills
            ADD CONSTRAINT purchase_bills_advance_adjustment_is_within_the_bill
            CHECK (COALESCE(tds_advance_adjusted_paise, 0) >= 0
                   AND COALESCE(tds_advance_adjusted_paise, 0)
                       <= COALESCE(taxable_amount_paise, 0));
    END IF;
END $$;

-- ── 3. The register can point at a payment ──────────────────────────────────

ALTER TABLE public.tds_deductions
    ADD COLUMN IF NOT EXISTS purchase_payment_id uuid
        REFERENCES public.purchase_payments(id) ON DELETE CASCADE;

COMMENT ON COLUMN public.tds_deductions.purchase_payment_id IS
    'The vendor PAYMENT this deduction came from, where the charge fell on the '
    'payment rather than the credit (§194 — whichever is earlier). Mutually '
    'exclusive with purchase_bill_id: a row records one event. NULL on the '
    'bill-driven and hand-entered rows. Migration 358.';

-- One register row per payment. NULLS DISTINCT (the default) leaves every
-- bill-driven and hand-entered row unconstrained, exactly as migration 307's
-- index does for purchase_bill_id.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tds_deductions_purchase_payment
    ON public.tds_deductions (purchase_payment_id);

DO $$
BEGIN
    -- A deduction row is about ONE event. Both links set would mean the same
    -- tax was deducted at the credit and at the payment, which is the double
    -- charge this whole migration exists to prevent.
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'tds_deductions_records_one_event') THEN
        ALTER TABLE public.tds_deductions
            ADD CONSTRAINT tds_deductions_records_one_event
            CHECK (purchase_bill_id IS NULL OR purchase_payment_id IS NULL);
    END IF;
END $$;

COMMIT;
