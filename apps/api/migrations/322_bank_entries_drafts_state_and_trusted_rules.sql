-- Migration 322: bank entries — the draft on the row, its state, and trusted rules
--
-- The design is docs/architecture/09-bank-entries.md. In one paragraph: a
-- statement line becomes a voucher (Receipt / Payment / Contra — decided by
-- direction, never chosen); the machine always writes its best proposal ONTO
-- the line, graded ready or proposed, with the reason; the CA passes ready
-- drafts in bulk and answers the rest; and a rule a Manager has marked
-- TRUSTED passes its lines with no click, on the authority of the person who
-- trusted it.
--
-- WHY THE DRAFT IS STORED
--     The queue used to rebuild rules, payee history and five candidate pools
--     on every page read and hand the result to the browser, which then had
--     its own copy of "which rows are confident" (readyRow / confidentMatch in
--     page.tsx). Nothing persisted, so "what did Apply suggestions just do"
--     had no answer once the outcome panel was dismissed, and "how many lines
--     are ready" could not be asked at all without reading every open line.
--     With the draft on the row the state is a SQL filter, the counts are a
--     SQL count, and "Pass N ready" is a query.
--
-- WHY entry_state IS A TRIGGER, NOT A WRITE SITE
--     Eight services write the columns that decide it (set_account, match,
--     unmatch, splits, pair/unpair, post, undo, ignore). Computing it in each
--     is the copy-drift CLAUDE.md warns about; computing it once, from the
--     row's own columns, in a BEFORE trigger cannot drift from itself. The
--     Python twin (domain/banking/entry.py::entry_state) exists for mock mode
--     and is pinned to this function by tests/test_bank_entry_state_parity_pg.py.
--
-- WHY has_splits IS A COLUMN
--     entry_state must be decidable from the row alone (a BEFORE trigger
--     cannot query its own table's other rows reliably, and the screen filters
--     on it). A split line has null account_id and null category and is
--     nonetheless fully answered. The flag is maintained by a trigger on
--     bank_transaction_splits so no write path has to remember it.
--
-- TRUSTED RULES
--     Reverses the 2026-08-02 audit's Tier 4.3 ("auto-add may reach draft
--     only") — an owner decision of 2026-09-03, recorded in the design doc. A
--     trusted rule must name a ledger (it cannot post without one) and a
--     person (its lines post as journal_entries.created_by = trusted_by; there
--     is no system user because there is no such person to answer for it).
--     The CHECK refuses either omission, and refuses clearing the ledger on a
--     rule that is still trusted.

BEGIN;

-- ── 1. The draft, on the row ────────────────────────────────────────────────
ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS draft_account_id     UUID REFERENCES public.chart_of_accounts(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS draft_category       TEXT,
  ADD COLUMN IF NOT EXISTS draft_entity_type    TEXT,
  ADD COLUMN IF NOT EXISTS draft_entity_id      UUID,
  ADD COLUMN IF NOT EXISTS draft_source         TEXT,
  ADD COLUMN IF NOT EXISTS draft_rule_id        UUID REFERENCES public.bank_matching_rules(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS draft_grade          TEXT,
  ADD COLUMN IF NOT EXISTS draft_label          TEXT,
  ADD COLUMN IF NOT EXISTS draft_reason         TEXT,
  ADD COLUMN IF NOT EXISTS draft_gst_rate_bps   INTEGER,
  ADD COLUMN IF NOT EXISTS draft_is_interstate  BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS draft_error          TEXT,
  ADD COLUMN IF NOT EXISTS drafted_at           TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS posted_by_rule_id    UUID REFERENCES public.bank_matching_rules(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS has_splits           BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS entry_state          TEXT NOT NULL DEFAULT 'needs_you';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_transactions'::regclass
                   AND conname = 'bank_transactions_draft_source_check') THEN
    ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_draft_source_check
      CHECK (draft_source IS NULL OR draft_source IN ('rule', 'document', 'history', 'transfer'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_transactions'::regclass
                   AND conname = 'bank_transactions_draft_grade_check') THEN
    ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_draft_grade_check
      CHECK (draft_grade IS NULL OR draft_grade IN ('ready', 'proposed'));
  END IF;
  -- A grade without a source, or a source without a grade, describes nothing.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_transactions'::regclass
                   AND conname = 'bank_transactions_draft_pair_check') THEN
    ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_draft_pair_check
      CHECK ((draft_source IS NULL) = (draft_grade IS NULL));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_transactions'::regclass
                   AND conname = 'bank_transactions_entry_state_check') THEN
    ALTER TABLE public.bank_transactions ADD CONSTRAINT bank_transactions_entry_state_check
      CHECK (entry_state IN ('needs_you', 'proposed', 'ready', 'covered', 'passed', 'set_aside'));
  END IF;
END $$;

COMMENT ON COLUMN public.bank_transactions.draft_source IS
  'Where the proposal came from: rule (a human wrote it), document (an open '
  'invoice/bill/receipt/payment with this amount), history (how this payee was '
  'coded before), transfer (the counterpart line on another own account). '
  'NULL = nothing defensible to propose. Written only by bank_entry_service.redraft.';
COMMENT ON COLUMN public.bank_transactions.draft_grade IS
  'ready = can be passed as it stands and is included in "Pass N ready"; '
  'proposed = a human should look. Never a percentage: a CA cannot audit 92%.';
COMMENT ON COLUMN public.bank_transactions.draft_label IS
  'What the draft points at, as a person would say it: the document ("INV-042 '
  '· Acme Pvt Ltd"), the counterpart account, or the rule''s ledger. draft_reason '
  'is WHY — "exact amount", "coded this way 8 of the last 9 times".';
COMMENT ON COLUMN public.bank_transactions.draft_error IS
  'Why the last attempt to pass this line failed, in the words shown on the '
  'row. Cleared by a redraft, and by any answer the CA gives (see the trigger).';
COMMENT ON COLUMN public.bank_transactions.posted_by_rule_id IS
  'Set when a TRUSTED rule passed this line with no click. The journal''s '
  'created_by is the rule''s trusted_by — the person on whose authority it posted.';
COMMENT ON COLUMN public.bank_transactions.entry_state IS
  'needs_you | proposed | ready | covered | passed | set_aside. Maintained by '
  'bank_transaction_entry_state() from this row''s own columns; never written '
  'by application code. Python twin: domain/banking/entry.py::entry_state.';

-- ── 2. Trusted rules ────────────────────────────────────────────────────────
ALTER TABLE public.bank_matching_rules
  ADD COLUMN IF NOT EXISTS is_trusted  BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS trusted_by  UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS trusted_at  TIMESTAMPTZ;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_matching_rules'::regclass
                   AND conname = 'bank_matching_rules_trusted_check') THEN
    ALTER TABLE public.bank_matching_rules ADD CONSTRAINT bank_matching_rules_trusted_check
      CHECK (NOT is_trusted
             OR (trusted_by IS NOT NULL AND trusted_at IS NOT NULL
                 AND suggested_account_id IS NOT NULL));
  END IF;
END $$;

COMMENT ON COLUMN public.bank_matching_rules.is_trusted IS
  'A trusted rule passes its lines with no click — after an import and in the '
  'daily sweep. Promotion needs banking.approve (Manager+). Its lines post as '
  'created_by = trusted_by. Un-trusting stops it at once: the sweep reads this '
  'flag at pass time, not from the draft.';

-- ── 3. entry_state, from the row's own columns ──────────────────────────────
-- Order matters and is the same in the Python twin:
--   posted            -> passed
--   ignored           -> set_aside
--   paired counterpart-> covered   (the primary carries the journal; this side
--                                   never needs anything and never posts)
--   coded by the CA   -> ready     (a ledger, a document, a split, a confirmed
--                                   pair as primary, or a control-account
--                                   category that needs no ledger)
--   draft_error       -> needs_you (a machine draft that failed to pass; a CA's
--                                   own coding above outranks the complaint)
--   draft ready       -> ready
--   draft proposed    -> proposed
--   otherwise         -> needs_you
CREATE OR REPLACE FUNCTION public.bank_transaction_entry_state()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
BEGIN
  -- An answer from a human clears the machine's complaint. Compared on
  -- UPDATE only; an INSERT has no OLD.
  IF TG_OP = 'UPDATE' AND NEW.draft_error IS NOT NULL AND (
       NEW.account_id        IS DISTINCT FROM OLD.account_id
    OR NEW.matched_entity_id IS DISTINCT FROM OLD.matched_entity_id
    OR NEW.category          IS DISTINCT FROM OLD.category
    OR NEW.transfer_pair_id  IS DISTINCT FROM OLD.transfer_pair_id
    OR NEW.has_splits        IS DISTINCT FROM OLD.has_splits
    OR NEW.match_status      IS DISTINCT FROM OLD.match_status
  ) THEN
    NEW.draft_error := NULL;
  END IF;

  NEW.entry_state :=
    CASE
      WHEN NEW.match_status = 'posted'  THEN 'passed'
      WHEN NEW.match_status = 'ignored' THEN 'set_aside'
      WHEN NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = false THEN 'covered'
      WHEN NEW.account_id IS NOT NULL
        OR NEW.matched_entity_id IS NOT NULL
        OR NEW.has_splits
        OR (NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = true)
        OR NEW.category IN ('Customer Payment', 'Vendor Payment', 'GST Payment')
        THEN 'ready'
      WHEN NEW.draft_error IS NOT NULL   THEN 'needs_you'
      WHEN NEW.draft_grade = 'ready'     THEN 'ready'
      WHEN NEW.draft_grade = 'proposed'  THEN 'proposed'
      ELSE 'needs_you'
    END;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_bank_transaction_entry_state ON public.bank_transactions;
CREATE TRIGGER trg_bank_transaction_entry_state
    BEFORE INSERT OR UPDATE ON public.bank_transactions
    FOR EACH ROW EXECUTE FUNCTION public.bank_transaction_entry_state();

-- ── 4. has_splits, from the splits table ────────────────────────────────────
-- SECURITY DEFINER: the caller is the authenticated role writing a split under
-- RLS, and the parent update it implies must not depend on that role's UPDATE
-- policy on bank_transactions. search_path pinned, as every definer here is.
CREATE OR REPLACE FUNCTION public.bank_transaction_sync_has_splits()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
  v_txn UUID := COALESCE(NEW.bank_transaction_id, OLD.bank_transaction_id);
BEGIN
  UPDATE public.bank_transactions t
     SET has_splits = EXISTS (SELECT 1 FROM public.bank_transaction_splits s
                              WHERE s.bank_transaction_id = v_txn)
   WHERE t.id = v_txn
     AND t.has_splits IS DISTINCT FROM EXISTS (
           SELECT 1 FROM public.bank_transaction_splits s
           WHERE s.bank_transaction_id = v_txn);
  RETURN NULL;
END;
$$;
REVOKE ALL ON FUNCTION public.bank_transaction_sync_has_splits() FROM PUBLIC;

DROP TRIGGER IF EXISTS trg_bank_transaction_sync_has_splits ON public.bank_transaction_splits;
CREATE TRIGGER trg_bank_transaction_sync_has_splits
    AFTER INSERT OR UPDATE OR DELETE ON public.bank_transaction_splits
    FOR EACH ROW EXECUTE FUNCTION public.bank_transaction_sync_has_splits();

-- ── 5. Backfill ─────────────────────────────────────────────────────────────
-- has_splits first, because entry_state reads it. Then a no-op update so the
-- BEFORE trigger computes entry_state for every existing row.
UPDATE public.bank_transactions t
   SET has_splits = true
 WHERE has_splits = false
   AND EXISTS (SELECT 1 FROM public.bank_transaction_splits s
               WHERE s.bank_transaction_id = t.id);

UPDATE public.bank_transactions SET entry_state = entry_state;

-- ── 6. Indexes the screen and the sweep read ────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_bank_txns_entry_state
    ON public.bank_transactions (firm_id, client_id, entry_state, transaction_date, id);
-- The trusted-rule sweep: ready drafts that came from a rule.
CREATE INDEX IF NOT EXISTS idx_bank_txns_draft_rule
    ON public.bank_transactions (firm_id, draft_rule_id)
    WHERE draft_rule_id IS NOT NULL AND entry_state = 'ready';
-- "What has this rule passed" on the Rules tab.
CREATE INDEX IF NOT EXISTS idx_bank_txns_posted_by_rule
    ON public.bank_transactions (posted_by_rule_id)
    WHERE posted_by_rule_id IS NOT NULL;

COMMIT;
