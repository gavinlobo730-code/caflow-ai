-- 103 — Banking B.4 remediation (F2): freeze completed reconciliations.
--
-- Additive + idempotent. A single jsonb column holds the frozen report payload
-- (summary, counts, tie-out, reconciled/unreconciled/exception lines, and the
-- reconciled transaction ids) captured at completion. Completed reconciliations
-- read this snapshot instead of recomputing from live transactions, so a
-- historical reconciliation can never silently change.

ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS snapshot jsonb;

COMMENT ON COLUMN bank_reconciliations.snapshot IS
    'B.4 frozen report captured at completion (F2). NULL while open/in_progress; '
    'completed sessions serve this verbatim — no live recomputation.';
