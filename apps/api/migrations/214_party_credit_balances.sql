-- Migration 214: Party credit balances (task #102 — QuickBooks-style bank
-- overpayment handling).
--
-- When a bank transaction settling a customer/vendor is matched for MORE than
-- the invoice/bill's true outstanding, bank_posting_service._settle_doc clamps
-- the sub-ledger allocation to the outstanding — but the excess previously just
-- vanished from tracking (the GL side was already correct: the transaction's
-- full amount was posted to Trade Receivables/Payables, so the excess already
-- sits there; only the SUB-LEDGER "who does this belong to" tracking was
-- missing). This is deliberately NOT modelled with credit_notes/
-- purchase_credit_notes (migration 210) — those are real GST compliance
-- documents (HSN/SAC lines, tax rate breakdown, feed GSTR-1/2, CGST Act §34
-- supply-side adjustments) and would misrepresent a pure cash overpayment,
-- which has no GST/supply implication at all, as a tax-relevant document.
--
-- party_credit_balances: the CURRENT unapplied credit per (firm, client,
-- party). Mutated via compare-and-swap (mirrors purchase_bills.paid_paise) —
-- never written unconditionally.
CREATE TABLE IF NOT EXISTS party_credit_balances (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        uuid NOT NULL REFERENCES firms(id),
    client_id      uuid NOT NULL REFERENCES clients(id),
    party_type     text NOT NULL CHECK (party_type IN ('customer', 'vendor')),
    party_id       uuid NOT NULL,
    balance_paise  bigint NOT NULL DEFAULT 0 CHECK (balance_paise >= 0),
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (firm_id, client_id, party_type, party_id)
);

-- party_credit_ledger: append-only history of every grant/application —
-- the audit trail party_credit_balances.balance_paise is a running sum of.
-- amount_paise is signed: +ve = grant (credit created), -ve = application
-- (credit consumed against a specific invoice/bill).
CREATE TABLE IF NOT EXISTS party_credit_ledger (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id          uuid NOT NULL REFERENCES firms(id),
    client_id        uuid NOT NULL REFERENCES clients(id),
    party_type       text NOT NULL CHECK (party_type IN ('customer', 'vendor')),
    party_id         uuid NOT NULL,
    amount_paise     bigint NOT NULL CHECK (amount_paise <> 0),
    kind             text NOT NULL CHECK (kind IN ('grant', 'application')),
    source_type      text,       -- e.g. 'bank_overpayment' (grant)
    source_id        uuid,       -- e.g. bank_transactions.id (grant)
    applied_to_type  text,       -- 'sales_invoice' | 'purchase_bill' (application)
    applied_to_id    uuid,       -- the invoice/bill id credited (application)
    notes            text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    created_by       uuid
);

CREATE INDEX IF NOT EXISTS idx_party_credit_ledger_party
    ON party_credit_ledger (firm_id, client_id, party_type, party_id);
CREATE INDEX IF NOT EXISTS idx_party_credit_ledger_source
    ON party_credit_ledger (source_type, source_id) WHERE source_id IS NOT NULL;

-- Firm-scoped RLS (same shape as migration 212's fix for the credit/debit
-- note tables) — dormant while the backend reads via the service-role client,
-- but required before a future per-user-JWT cutover and defensively correct
-- to ship alongside the base GRANTs from day one.
ALTER TABLE public.party_credit_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.party_credit_ledger   ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS firm_party_credit_balances ON public.party_credit_balances;
CREATE POLICY firm_party_credit_balances ON public.party_credit_balances FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS firm_party_credit_ledger ON public.party_credit_ledger;
CREATE POLICY firm_party_credit_ledger ON public.party_credit_ledger FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id()) WITH CHECK (firm_id = public.get_my_firm_id());

GRANT SELECT, INSERT, UPDATE ON public.party_credit_balances TO authenticated;
GRANT SELECT, INSERT         ON public.party_credit_ledger   TO authenticated;
