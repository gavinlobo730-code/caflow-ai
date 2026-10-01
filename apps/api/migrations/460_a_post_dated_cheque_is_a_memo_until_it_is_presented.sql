-- accounting-21 — the post-dated cheque register.
--
-- WHAT WAS MISSING
--     A customer hands over three cheques dated for the next three months, and
--     a client hands its suppliers cheques dated ahead. Indian SMEs run on
--     this, and the product had nowhere to hold one: a CA either recorded the
--     receipt now (putting money in the bank ledger that is not in the bank,
--     and settling an invoice with a cheque that has not cleared) or kept a
--     list outside the product.
--
-- A PDC IS A MEMORANDUM, AND THIS TABLE POSTS NOTHING
--     A post-dated cheque is not money until its date: until then it is a
--     promise on a piece of paper. So this table has NO journal_entry_id and
--     nothing here reaches the ledger. The books are UNCHANGED the day a cheque
--     is recorded. On or after the cheque's date it shows as DUE, and one click
--     converts it into an ORDINARY receipt (or vendor payment) through the same
--     engine a receipt typed on the Receipts screen goes through
--     (services/receipt_service.create_receipt_core, which is also what the
--     bank-statement match queue calls) — so the journal, the invoice
--     settlement, the period lock and the GST advance rules are exactly a normal
--     receipt's, and there is NO second posting path.
--
-- DIRECTION, AND WHICH PARTY
--     `direction` is `received` (a customer's cheque, banked into the client's
--     account) or `issued` (the client's cheque to a supplier). A received
--     cheque names a customer and an issued one a vendor, never both and never
--     neither: the CHECK below makes the other combinations unrepresentable.
--
-- THE INVOICES IT IS MEANT FOR ARE STATED UP FRONT
--     `allocations` is the list of invoices (or bills) the cheque is meant to
--     settle, as the receipt/payment engine takes them: [{sales_invoice_id |
--     purchase_bill_id, allocated_paise}]. It is a STATEMENT OF INTENT, not a
--     claim on the invoice — nothing is reserved against the invoice, and the
--     engine re-validates every allocation against the LIVE outstanding when
--     the cheque is converted. Empty means the money lands unallocated, which
--     is what a receipt with no allocations is.
--
-- STATUS
--     held -> converted | cancelled. `converted` records WHICH receipt or
--     payment it became. A cheque that BOUNCES after conversion is reversed on
--     the Receipts screen like any other receipt (reversal_service); this table
--     does not model a dishonour.
--
-- NOTHING BACKFILLED. No cheque has ever been recorded here.
-- ADDITIVE AND IDEMPOTENT.

CREATE TABLE IF NOT EXISTS public.post_dated_cheques (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id             UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  direction             TEXT        NOT NULL,
  customer_id           UUID        REFERENCES public.customers(id) ON DELETE CASCADE,
  vendor_id             UUID        REFERENCES public.vendors(id)   ON DELETE CASCADE,
  cheque_no             TEXT        NOT NULL,
  cheque_date           DATE        NOT NULL,
  amount_paise          BIGINT      NOT NULL,
  -- The drawee bank, as written on the cheque (a received cheque's issuer's
  -- bank; for an issued cheque the client's own bank is `bank_account_id`).
  drawee_bank           TEXT,
  -- The CLIENT's bank account the cheque is banked into (received) or drawn on
  -- (issued). Optional: where it is absent the engine falls back to the firm's
  -- general Bank ledger and says it did (domain/accounting/payment_account).
  bank_account_id       UUID        REFERENCES public.bank_accounts(id) ON DELETE SET NULL,
  allocations           JSONB       NOT NULL DEFAULT '[]'::jsonb,
  status                TEXT        NOT NULL DEFAULT 'held',
  notes                 TEXT,
  converted_receipt_id  UUID        REFERENCES public.receipts(id)          ON DELETE SET NULL,
  converted_payment_id  UUID        REFERENCES public.purchase_payments(id) ON DELETE SET NULL,
  converted_at          TIMESTAMPTZ,
  converted_by          UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  cancelled_at          TIMESTAMPTZ,
  cancel_reason         TEXT,
  created_by            UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT post_dated_cheques_direction_check
    CHECK (direction IN ('received', 'issued')),
  CONSTRAINT post_dated_cheques_status_check
    CHECK (status IN ('held', 'converted', 'cancelled')),
  -- A received cheque is a CUSTOMER's, an issued one a VENDOR's; the other
  -- three combinations are unrepresentable rather than left to every writer.
  CONSTRAINT post_dated_cheques_party_matches_direction
    CHECK ((direction = 'received' AND customer_id IS NOT NULL AND vendor_id IS NULL)
        OR (direction = 'issued'   AND vendor_id   IS NOT NULL AND customer_id IS NULL)),
  CONSTRAINT post_dated_cheques_amount_positive CHECK (amount_paise > 0),
  CONSTRAINT post_dated_cheques_cheque_no_present CHECK (btrim(cheque_no) <> ''),
  CONSTRAINT post_dated_cheques_allocations_is_a_list
    CHECK (jsonb_typeof(allocations) = 'array')
);

COMMENT ON TABLE public.post_dated_cheques IS
  'accounting-21. A MEMORANDUM register of post-dated cheques received from customers '
  'or issued to vendors. It has no journal_entry_id and posts NOTHING: the '
  'books are unchanged until a cheque is converted, and conversion is an '
  'ordinary receipt / vendor payment through the one receipt and payment '
  'engines (receipt_service.create_receipt_core, '
  'purchase_payment_service.create_payment_core). Never a second posting path.';

COMMENT ON COLUMN public.post_dated_cheques.allocations IS
  'The invoices (received) or bills (issued) this cheque is meant to settle, '
  'as the receipt/payment engine takes them: [{sales_invoice_id | '
  'purchase_bill_id, allocated_paise}]. A statement of intent, not a '
  'reservation: nothing is held against the invoice, and the engine '
  're-validates each allocation against the live outstanding at conversion.';

-- The same cheque number twice for the same party is a keying slip, not a
-- second cheque. A CANCELLED row is out of the way, so a cheque re-entered
-- after a correction is not refused by its own corpse.
CREATE UNIQUE INDEX IF NOT EXISTS uq_post_dated_cheques_party_cheque_no
  ON public.post_dated_cheques
     (client_id, direction, coalesce(customer_id, vendor_id), lower(btrim(cheque_no)))
  WHERE status <> 'cancelled';

CREATE INDEX IF NOT EXISTS idx_post_dated_cheques_client_status_date
  ON public.post_dated_cheques (client_id, status, cheque_date);

-- ── Row-level security ───────────────────────────────────────────────────────

ALTER TABLE public.post_dated_cheques ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.post_dated_cheques;
CREATE POLICY "firm_isolation" ON public.post_dated_cheques
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "post_dated_cheques_assignment_scope" ON public.post_dated_cheques;
CREATE POLICY "post_dated_cheques_assignment_scope" ON public.post_dated_cheques
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Reads only for the signed-in role; every write goes through the API, where
-- rbac() runs and the client scope is checked (services/post_dated_cheque_service.py).
GRANT SELECT ON public.post_dated_cheques TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.post_dated_cheques TO service_role;
