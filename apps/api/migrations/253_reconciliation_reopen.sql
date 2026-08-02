-- Migration 253: let a completed reconciliation be REOPENED — deliberately,
-- by a Partner, with a reason, and without losing what was certified.
--
-- WHY THIS EXISTS
-- A completed reconciliation is immutable (bank_reconciliation_service.
-- _require_mutable), and that is right: it is a period a CA has certified. But
-- "immutable" with no escape hatch at all is its own failure mode. A
-- reconciliation completed against a mistake — a transaction reconciled to the
-- wrong period, a closing balance typed from the wrong statement page — is
-- currently permanent. The only remedy was to leave it wrong.
--
-- QuickBooks gives accountants an explicit Undo for exactly this reason. The
-- discipline is not in forbidding the action; it is in making it visible: who,
-- when, why, and with the prior certification preserved rather than overwritten.
--
-- WHAT THIS ADDS
--   reopened_at / reopened_by / reopen_reason   the last reopen, for display
--   reopen_count                                how many times, at a glance
--   reopen_history                              every reopen, each carrying the
--                                               FROZEN SNAPSHOT as it stood at
--                                               that completion
--
-- The history column is the point. `snapshot` holds the certification for the
-- CURRENT completion and is overwritten when a reopened period is completed
-- again. Pushing the old snapshot into reopen_history before that happens means
-- no certified figure is ever destroyed — the report a CA signed off remains
-- retrievable even after the period is redone.
--
-- Immutability is NOT weakened. _require_mutable still refuses every edit to a
-- completed session; the only way out is this explicit, Partner-gated reopen
-- (routers/banking.py uses rbac("accounting", "approve"), the same gate as
-- posting a journal and setting a year lock).

BEGIN;

ALTER TABLE public.bank_reconciliations
  ADD COLUMN IF NOT EXISTS reopened_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS reopened_by    UUID,
  ADD COLUMN IF NOT EXISTS reopen_reason  TEXT,
  ADD COLUMN IF NOT EXISTS reopen_count   INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS reopen_history JSONB   NOT NULL DEFAULT '[]'::jsonb;

-- A reopened session must carry its reason. Enforced in the database rather
-- than only in the service, so no code path can reopen anonymously.
ALTER TABLE public.bank_reconciliations
  DROP CONSTRAINT IF EXISTS bank_reconciliations_reopen_reason_required;
ALTER TABLE public.bank_reconciliations
  ADD CONSTRAINT bank_reconciliations_reopen_reason_required
  CHECK (
    reopen_count = 0
    OR (reopen_reason IS NOT NULL AND length(btrim(reopen_reason)) >= 10)
  );

-- reopen_count must agree with the history it summarises.
ALTER TABLE public.bank_reconciliations
  DROP CONSTRAINT IF EXISTS bank_reconciliations_reopen_count_matches_history;
ALTER TABLE public.bank_reconciliations
  ADD CONSTRAINT bank_reconciliations_reopen_count_matches_history
  CHECK (reopen_count = jsonb_array_length(reopen_history));

CREATE INDEX IF NOT EXISTS idx_bank_reconciliations_reopened
    ON public.bank_reconciliations (firm_id, client_id)
    WHERE reopen_count > 0;

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
DECLARE missing text[] := ARRAY[]::text[]; c text;
BEGIN
    FOREACH c IN ARRAY ARRAY['reopened_at','reopened_by','reopen_reason',
                             'reopen_count','reopen_history'] LOOP
        IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='bank_reconciliations'
                          AND column_name=c) THEN
            missing := missing || c;
        END IF;
    END LOOP;
    IF array_length(missing, 1) > 0 THEN
        RAISE EXCEPTION 'Migration 253 failed: missing %', array_to_string(missing, ', ');
    END IF;

    -- Every existing row must satisfy the new constraints (they all have
    -- reopen_count = 0, so this is a no-op today — assert it rather than assume).
    IF EXISTS (SELECT 1 FROM public.bank_reconciliations
                WHERE reopen_count <> jsonb_array_length(reopen_history)) THEN
        RAISE EXCEPTION 'Migration 253 failed: reopen_count disagrees with reopen_history';
    END IF;
END
$verify$;

COMMIT;
