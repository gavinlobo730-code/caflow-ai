-- Migration 257: who the money actually went to or came from (Tier 1.3).
--
-- WHY THIS EXISTS
-- A bank transaction records an amount and a narration, and nothing else about
-- the other side. "NEFT DR HDFC0000123 ACME PVT LTD SALARY" tells a human who
-- was paid; it tells the system nothing, because the counterparty is buried in
-- a string. So every screen that wants to group, filter or learn by payee has
-- had nothing to group by.
--
-- The narration parser (Tier 6.2) already extracts a counterparty from that
-- string. What was missing is somewhere to PUT it once a human has confirmed
-- it, and a way to point at the customer or vendor it corresponds to.
--
-- ── WHY payee_id HAS NO FOREIGN KEY ─────────────────────────────────────────
-- A payee is often neither a customer nor a vendor. The landlord, the
-- electricity board, the bank itself, a director drawing money — none of them
-- exist in customers or vendors, and creating a vendor record for the
-- electricity board just to name it on a bank line would be worse than the
-- problem. So payee_name stands alone and payee_id is an OPTIONAL pointer,
-- qualified by payee_type, into whichever table that type names.
--
-- A polymorphic reference cannot carry a foreign key, which is a real cost:
-- nothing stops payee_id going stale if the customer is deleted. That is
-- accepted deliberately here — payee_id is a convenience for filtering and
-- matching, never a settlement target. The settlement path uses
-- matched_entity_type/matched_entity_id, which is checked against the real
-- table on every use. The CHECK below at least keeps the pair coherent.
--
-- ── WHAT TIER 1.4 DOES WITH IT ──────────────────────────────────────────────
-- "Last time this payee was coded to X." The learning key is payee_id when a
-- party is linked, and the NORMALISED counterparty from the narration
-- otherwise (domain/banking/narration.normalise_party_name — so 'Acme Pvt.
-- Ltd.' and 'ACME PRIVATE LIMITED' learn as one payee, not two). Suggestions
-- only: nothing here is applied without a human accepting it.

BEGIN;

ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS payee_name TEXT,
  ADD COLUMN IF NOT EXISTS payee_type TEXT,
  ADD COLUMN IF NOT EXISTS payee_id   UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_transactions'::regclass
      AND conname  = 'bank_transactions_payee_type_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_payee_type_check
      CHECK (payee_type IS NULL OR payee_type IN ('customer', 'vendor', 'other'));
  END IF;
END $$;

-- A payee_id without a type cannot be resolved to a table, and a 'customer' or
-- 'vendor' type without an id names a party we cannot point at. 'other' is the
-- case for a payee that is neither — it carries a name and no id.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.bank_transactions'::regclass
      AND conname  = 'bank_transactions_payee_pair_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_payee_pair_check
      CHECK (
        (payee_id IS NULL AND payee_type IN ('other') ) OR
        (payee_id IS NULL AND payee_type IS NULL)       OR
        (payee_id IS NOT NULL AND payee_type IN ('customer', 'vendor'))
      );
  END IF;
END $$;

-- The Tier 1.4 lookup: "what has this client coded this payee to before?"
-- Partial, because a row with no payee teaches nothing and there is no reason
-- to carry it in the index.
CREATE INDEX IF NOT EXISTS idx_bank_txns_payee_history
    ON public.bank_transactions (client_id, payee_id)
    WHERE payee_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_bank_txns_payee_name
    ON public.bank_transactions (client_id, payee_name)
    WHERE payee_name IS NOT NULL;

COMMENT ON COLUMN public.bank_transactions.payee_name IS
    'Tier 1.3 — who the money went to / came from, as confirmed by a human. '
    'Seeded from the narration parser''s counterparty but never written without '
    'confirmation.';
COMMENT ON COLUMN public.bank_transactions.payee_type IS
    'customer | vendor | other. Qualifies payee_id; ''other'' means a payee that '
    'is neither (a landlord, a utility, the bank itself).';
COMMENT ON COLUMN public.bank_transactions.payee_id IS
    'OPTIONAL pointer into customers/vendors per payee_type. Deliberately NOT a '
    'foreign key — the reference is polymorphic. It is a convenience for '
    'filtering and learning, never a settlement target; settlement uses '
    'matched_entity_type/matched_entity_id, which is re-checked on every use.';

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
DECLARE missing text[] := ARRAY[]::text[]; c text;
BEGIN
    FOREACH c IN ARRAY ARRAY['payee_name','payee_type','payee_id'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='bank_transactions'
                          AND column_name=c) THEN
            missing := missing || c;
        END IF;
    END LOOP;
    IF array_length(missing, 1) > 0 THEN
        RAISE EXCEPTION 'Migration 257 failed: missing %', array_to_string(missing, ', ');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conrelid = 'public.bank_transactions'::regclass
                      AND conname = 'bank_transactions_payee_pair_check') THEN
        RAISE EXCEPTION 'Migration 257 failed: the payee id/type coherence CHECK is missing.';
    END IF;

    -- Every existing row must satisfy the new CHECKs (they all have NULL payee
    -- columns, so this is a no-op today — assert it rather than assume).
    IF EXISTS (SELECT 1 FROM public.bank_transactions
                WHERE payee_id IS NOT NULL AND payee_type NOT IN ('customer','vendor')) THEN
        RAISE EXCEPTION 'Migration 257 failed: an existing row has an unresolvable payee.';
    END IF;
END
$verify$;

COMMIT;
