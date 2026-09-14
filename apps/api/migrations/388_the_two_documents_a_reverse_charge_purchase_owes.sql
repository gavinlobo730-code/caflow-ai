-- 388 — the two documents a reverse-charge purchase owes (PUR-19).
--
-- WHAT WAS MISSING
--     The reverse-charge ACCOUNTING is complete: `_compute_bill_lines_and_totals`
--     keeps the tax out of what the vendor is owed, `phase2_journal_service`
--     self-accounts the output liability per head, and GSTR-3B declares it at
--     3.1(d) with the credit at Table 4(A)(3) or 4(A)(5). What the product has
--     never produced is the two DOCUMENTS the CGST Act makes the RECIPIENT
--     issue. On an inward supply from an unregistered person the s.31(3)(f)
--     self-invoice IS the document the credit rests on — Rule 36(1)(b) with
--     s.16(2)(a) — so the product claimed a credit it could not evidence.
--
-- TWO KINDS IN ONE TABLE, BECAUSE THEY SHARE EVERYTHING BUT THEIR TRIGGER
--     Both carry a Rule 46(b)-shaped serial number, a date, a supplier, the tax
--     per head and a reverse-charge declaration. What differs is what they hang
--     off and when they fall due:
--
--       self_invoice     s.31(3)(f)  the BILL, and ONLY where the supplier is
--                                    NOT REGISTERED on the date of receipt
--       payment_voucher  s.31(3)(g)  the PAYMENT, for EVERY s.9(3)/(4)
--                                    liability, registered supplier or not
--
--     s.31(3)(f) carries that limitation in its own charging words and
--     s.31(3)(g) carries no such limb, so they are two rules and not one rule
--     with two names. `kind` says which, and exactly one of `purchase_bill_id`
--     / `purchase_payment_id` is set — a CHECK rather than a convention,
--     because a voucher hanging off a bill would be dated by the wrong event.
--
-- `vendors.gst_registration_status` IS NULLABLE WITH NO DEFAULT
--     s.31(3)(f) turns on whether the supplier is registered, and a blank
--     `vendors.gstin` does not answer it: a GSTIN PRESENT is the registration
--     (s.25 issues one on registration), but a GSTIN ABSENT means only that
--     nobody recorded one. Guessing "unregistered" mints a document the Act
--     does not ask for; guessing "registered" withholds the one the credit
--     rests on. So the third state is real and is NAMED — the same shape as
--     `vendors.msme_status` (303) and `fixed_assets.rule_43_use` (372).
--
-- THE PARTICULARS ARE STORED, NOT RE-DERIVED
--     A document is a DOCUMENT. Re-deriving it after the bill is edited would
--     change what was issued, which is the one thing a statutory record may
--     not do. The live rule stays in `domain/gst/rcm_documents.py` and a
--     re-read is COMPARED against the stored copy rather than replacing it.

ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS gst_registration_status TEXT;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                  WHERE conname = 'vendors_gst_registration_status_check') THEN
    ALTER TABLE public.vendors
      ADD CONSTRAINT vendors_gst_registration_status_check
      CHECK (gst_registration_status IS NULL
             OR gst_registration_status IN ('registered', 'unregistered'));
  END IF;
END $$;

COMMENT ON COLUMN public.vendors.gst_registration_status IS
  'CGST Act s.31(3)(f) asks whether the supplier is registered. A GSTIN in '
  'vendors.gstin IS the registration and answers it; this column answers it '
  'where there is no GSTIN. NULL means nobody has recorded it — NOT that the '
  'supplier is unregistered — and domain/gst/rcm_documents.py names that gap '
  'rather than guessing either way, because one guess mints a document the Act '
  'does not ask for and the other withholds the one the input credit rests on.';

CREATE TABLE IF NOT EXISTS public.rcm_documents (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id           UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  vendor_id           UUID NOT NULL REFERENCES public.vendors(id),
  kind                TEXT NOT NULL
                        CHECK (kind IN ('self_invoice', 'payment_voucher')),

  -- Exactly one parent, and which one follows from the kind. s.31(3)(f) dates
  -- the document at the supply and s.31(3)(g) at the PAYMENT; a voucher
  -- pointing at a bill would take the wrong date and state tax for a
  -- consideration nobody had paid yet.
  purchase_bill_id    UUID REFERENCES public.purchase_bills(id),
  purchase_payment_id UUID REFERENCES public.purchase_payments(id),

  -- CGST Rule 46(b) for the invoice, Rule 52(b) for the voucher — worded
  -- identically, which is why domain/gst/invoice_series.py answers both.
  document_no         TEXT NOT NULL,
  document_date       DATE NOT NULL,

  -- What the document SAYS, as issued. See the header for why this is stored.
  particulars_json    JSONB NOT NULL DEFAULT '{}'::jsonb,

  -- Integer paise, the same units every other document carries.
  taxable_paise       BIGINT NOT NULL DEFAULT 0,
  cgst_paise          BIGINT NOT NULL DEFAULT 0,
  sgst_paise          BIGINT NOT NULL DEFAULT 0,
  igst_paise          BIGINT NOT NULL DEFAULT 0,
  cess_paise          BIGINT NOT NULL DEFAULT 0,
  -- Rule 52(f), the amount PAID. Nil on a self-invoice, which states a value
  -- of supply rather than a payment.
  amount_paid_paise   BIGINT NOT NULL DEFAULT 0,

  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          UUID REFERENCES public.users(id),
  deleted_at          TIMESTAMPTZ,

  CONSTRAINT rcm_documents_hangs_off_exactly_one
    CHECK (num_nonnulls(purchase_bill_id, purchase_payment_id) = 1),
  CONSTRAINT rcm_documents_kind_matches_its_parent
    CHECK ((kind = 'self_invoice'    AND purchase_bill_id    IS NOT NULL)
        OR (kind = 'payment_voucher' AND purchase_payment_id IS NOT NULL)),
  CONSTRAINT rcm_documents_number_not_blank
    CHECK (length(trim(document_no)) > 0)
);

-- Rule 46(b) / Rule 52(b): unique for a financial year. Enforced STRICTER —
-- per client full stop — the same decision migrations 151/209 took for the
-- sales series and for the same reason: a number reused across years is a
-- number a reader cannot resolve. Per KIND, because the rule expressly allows
-- "one or multiple series" and these are two.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rcm_document_no_per_client_kind
  ON public.rcm_documents (firm_id, client_id, kind, document_no)
  WHERE deleted_at IS NULL;

-- One document per parent. A second self-invoice for one bill is a duplicate
-- of a statutory record, not a correction.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rcm_document_per_bill
  ON public.rcm_documents (purchase_bill_id)
  WHERE purchase_bill_id IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_rcm_document_per_payment
  ON public.rcm_documents (purchase_payment_id)
  WHERE purchase_payment_id IS NOT NULL AND deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_rcm_documents_client_date
  ON public.rcm_documents (firm_id, client_id, document_date DESC);

COMMENT ON TABLE public.rcm_documents IS
  'The two documents CGST Act s.31(3) makes the RECIPIENT of a reverse-charge '
  'supply issue: the s.31(3)(f) self-invoice (only where the supplier is not '
  'registered) and the s.31(3)(g) payment voucher (every s.9(3)/(4) liability). '
  'domain/gst/rcm_documents.py is the rule.';
COMMENT ON COLUMN public.rcm_documents.particulars_json IS
  'The particulars AS ISSUED — Rule 46 for a self-invoice, Rule 52 for a '
  'payment voucher. Stored rather than re-derived: re-deriving after the bill '
  'is edited would change what was issued.';

ALTER TABLE public.rcm_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_rcm_documents" ON public.rcm_documents;
CREATE POLICY "firm_staff_read_rcm_documents" ON public.rcm_documents
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

-- Migration 084's loop has never run again (see 370), so a table created now
-- carries only its firm-wide policy unless it says otherwise here.
DROP POLICY IF EXISTS "rcm_documents_assignment_scope" ON public.rcm_documents;
CREATE POLICY "rcm_documents_assignment_scope"
  ON public.rcm_documents AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Read-only from the browser. Every write goes through the API so rbac() runs
-- and the numbering, the period lock and the s.31(3)(f) refusals are all asked.
GRANT SELECT ON public.rcm_documents TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.rcm_documents TO service_role;
