-- ============================================================================
-- 291 — give the 26AS reconciliation the columns it needs to be honest
--
-- WHAT WAS WRONG
--     The reconciliation compared Form 26AS against `tds_deductions`. Those are
--     opposite directions of TDS. 26AS lists tax that OTHERS deducted out of
--     payments made TO the client (deductor_name / deductor_tan);
--     tds_deductions records tax the CLIENT deducted from its own vendors
--     (deductee_name / deductee_pan) and appears in each vendor's 26AS, never
--     in the client's. The lookup was additionally built keyed on
--     deductee_pan and read back by deductor_tan — two different identifier
--     formats that can never be equal — so in practice every 26AS row was
--     reported as missing from the books.
--
-- WHERE THE BOOKS ACTUALLY HOLD THIS
--     As the `Dr TDS Receivable` leg of a receipt
--     (services/phase2_journal_service.receipt_journal_lines): the customer
--     paid net of TDS, and the withheld amount became a receivable claimable
--     against the client's income tax. `receipts.tds_paise` is the amount and
--     `receipts.customer_id` is the deductor.
--
-- 1. customers.tan
--     A deductor is identified in 26AS by TAN. A TAN is 4 alpha + 5 numeric +
--     1 alpha and is NOT derivable from a PAN — it shares no characters with
--     one — so there is no way to compute this and it has to be recorded.
--     Without it the engine can only match on deductor name, which it does,
--     but marks needing confirmation. Nullable, because the overwhelming
--     majority of existing customer rows will not have one and a reconciliation
--     that name-matches with a flag is far more useful than one that refuses to
--     run.
--
--     The CHECK mirrors customers_pan_format (migration 112): NOT VALID, so it
--     governs new and updated rows without failing the migration on historical
--     data nobody has cleaned yet.
--
-- 2. form_26as_reconciliations — the books→26AS direction
--     Rule 37BA(1) gives TDS credit "on the basis of information relating to
--     deduction of tax furnished by the deductor". A credit in the books that
--     the deductor never reported is therefore NOT claimable, and it is the
--     single most consequential thing this screen can tell a CA before filing.
--     The old summary had no field for it, because the old code only ever
--     iterated the 26AS side. total_tds_books_paise additionally only
--     accumulated for MATCHED rows, which made the variance agree with itself
--     by construction.
--
-- 3. form_26as_records — how a row was matched
--     match_basis records whether the row matched on TAN (exact identity) or on
--     deductor name (needs a human to confirm). matched_receipt_id replaces
--     matched_tds_deduction_id, which pointed at the wrong table; the old
--     column is left in place rather than dropped so historical rows keep
--     whatever they recorded, but nothing writes it any more.
--
-- NO DATA IS REWRITTEN
--     Every existing form_26as_reconciliations row was produced by the broken
--     comparison. The new books_source column is NULL on all of them, which is
--     what distinguishes them; re-running the reconciliation is the fix, and
--     that is a CA action, not a migration's.
-- ============================================================================

-- ─── 1. The deductor's TAN, on the customer master ──────────────────────────
ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS tan TEXT;

COMMENT ON COLUMN public.customers.tan IS
  'Tax Deduction and Collection Account Number of this customer when it deducts '
  'TDS on payments to the client. 4 alpha + 5 numeric + 1 alpha. Not derivable '
  'from the PAN; recorded so Form 26AS rows match on identity rather than name. '
  'See migration 291 and domain/income_tax/form26as_matcher.py.';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'customers_tan_format'
  ) THEN
    ALTER TABLE public.customers
      ADD CONSTRAINT customers_tan_format
      CHECK (tan IS NULL OR tan ~ '^[A-Z]{4}[0-9]{5}[A-Z]$') NOT VALID;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_customers_tan
  ON public.customers (firm_id, client_id, tan)
  WHERE tan IS NOT NULL;

-- ─── 2. The reconciliation summary ──────────────────────────────────────────
ALTER TABLE public.form_26as_reconciliations
  ADD COLUMN IF NOT EXISTS not_in_26as_count          INT    NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS unsupported_credit_paise   BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS needs_confirmation_count   INT    NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS provisional_credit_count   INT    NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS provisional_credit_paise   BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS net_variance_paise         BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS gl_control_paise           BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS unreconciled_gl_paise      BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS books_source               TEXT,
  ADD COLUMN IF NOT EXISTS deductor_summary           JSONB  NOT NULL DEFAULT '[]';

COMMENT ON COLUMN public.form_26as_reconciliations.not_in_26as_count IS
  'Book TDS credits with no counterpart in 26AS.';
COMMENT ON COLUMN public.form_26as_reconciliations.unsupported_credit_paise IS
  'Value of those credits. Not claimable under Rule 37BA(1) until the deductor '
  'corrects their TDS statement — the figure a CA needs before filing.';
COMMENT ON COLUMN public.form_26as_reconciliations.needs_confirmation_count IS
  'Rows matched on deductor NAME only because no TAN was recorded on the '
  'customer. A human has to confirm these.';
COMMENT ON COLUMN public.form_26as_reconciliations.provisional_credit_paise IS
  'TDS on 26AS rows whose TRACES booking status is not F (final) — unmatched, '
  'overbooked or provisional challans. Reported by the deductor but not a '
  'settled credit. IT Act s.205 bars a direct demand on the deductee, but that '
  'is an assessment defence, not a credit available in the return.';
COMMENT ON COLUMN public.form_26as_reconciliations.net_variance_paise IS
  'Signed: 26AS total minus books total. variance_paise stays the absolute '
  'value the summary has always shown.';
COMMENT ON COLUMN public.form_26as_reconciliations.gl_control_paise IS
  'Net debits to the TDS Receivable control account for the year, read from '
  'account_period_balances. The line-by-line population is receipts; anything '
  'in the ledger outside it lands in unreconciled_gl_paise, so a manual journal '
  'to TDS Receivable cannot sit silently outside the reconciliation.';
COMMENT ON COLUMN public.form_26as_reconciliations.books_source IS
  'Which books population was reconciled. NULL identifies a row produced by the '
  'pre-291 comparison against tds_deductions, which was the wrong direction of '
  'TDS entirely — see migration 291.';

-- ─── 3. Per-record match provenance ─────────────────────────────────────────
ALTER TABLE public.form_26as_records
  ADD COLUMN IF NOT EXISTS match_basis        TEXT,
  ADD COLUMN IF NOT EXISTS matched_receipt_id UUID,
  ADD COLUMN IF NOT EXISTS variance_paise     BIGINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.form_26as_records.match_basis IS
  'tan = matched on the deductor''s TAN (exact identity). name = matched on the '
  'deductor name only, because no TAN is recorded on the customer — needs '
  'confirmation. NULL = unmatched.';
COMMENT ON COLUMN public.form_26as_records.matched_receipt_id IS
  'The receipt whose TDS leg this 26AS row matched. Replaces '
  'matched_tds_deduction_id, which pointed at tds_deductions — tax the client '
  'deducted from its vendors, the opposite direction of TDS and never in the '
  'client''s own 26AS. The old column is kept for historical rows and is no '
  'longer written.';
COMMENT ON COLUMN public.form_26as_records.variance_paise IS
  'Signed: 26AS TDS minus the matched book credit.';

-- ─── 4. Two different features share form_26as_uploads ──────────────────────
--     `POST /api/form-26as/uploads` (domain/income_tax/form26as_service.py) is
--     the client's OWN 26AS: upload → parse → reconcile, with parse_status and
--     total_records driving the page at /clients/{id}/tax/26as.
--
--     `POST /api/tds-workspace/form26as/upload` (routers/tds_workspace.py) is a
--     different thing wearing the same name: the caller posts BOTH sides
--     already paired, nothing is read from the database, and it is the
--     client-as-DEDUCTOR self-check on TDS withheld from its own vendors. It
--     writes a row here too, and never sets parse_status.
--
--     parse_status defaults to 'pending' (migration 234), so every such row
--     appears in the 26AS page's Upload History as a spinner that never
--     resolves, over "0 records". Neither feature is wrong on its own; sharing
--     one table with incompatible semantics is.
--
--     `source` separates them, and list_uploads plus the page filter on it.
--
--     FIRST, THOUGH: this table's shape differs between the CI template and the
--     live database, and the first cut of this migration failed in production
--     because of it — "column status does not exist" on the backfill below.
--
--     Migration 052 declares form_26as_uploads with file_url / raw_data /
--     reconciliation_result / status / created_by. Production's copy has none
--     of those; it has uploaded_by (NOT NULL) instead. The CI template is built
--     with --continue-on-error, so 052's shape is what every local run and
--     every column check has seen, while the live table has always been the
--     other one. Nothing compared the two, so the divergence was invisible.
--
--     The consequence is not cosmetic. create_upload writes created_by and
--     never writes uploaded_by, so on the live database every 26AS upload
--     insert violates a NOT NULL on a column the code does not know exists —
--     which is why form_26as_uploads holds zero rows in production. The
--     tds_workspace path writes status / file_url / raw_data /
--     reconciliation_result and fails the same way.
--
--     So converge the two before touching anything else. Every ADD is
--     IF NOT EXISTS and nullable, which makes this a no-op on whichever side
--     already has the column and never re-imposes a constraint: production
--     keeps its NOT NULL on uploaded_by, and the code now writes both keys.
ALTER TABLE public.form_26as_uploads
  ADD COLUMN IF NOT EXISTS uploaded_by           UUID,
  ADD COLUMN IF NOT EXISTS created_by            UUID,
  ADD COLUMN IF NOT EXISTS status                TEXT,
  ADD COLUMN IF NOT EXISTS file_url              TEXT,
  ADD COLUMN IF NOT EXISTS raw_data              JSONB,
  ADD COLUMN IF NOT EXISTS reconciliation_result JSONB;

COMMENT ON COLUMN public.form_26as_uploads.uploaded_by IS
  'Who uploaded the statement. Present in the live database as NOT NULL and '
  'absent from migration 052 — see migration 291. Written alongside created_by '
  'so one insert satisfies both shapes.';

ALTER TABLE public.form_26as_uploads
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'form_26as_pipeline';

COMMENT ON COLUMN public.form_26as_uploads.source IS
  'form_26as_pipeline = the upload/parse/reconcile flow for the client''s own '
  '26AS. tds_workspace = the caller-supplied deductor-side comparison in '
  'routers/tds_workspace.py, which shares this table but has no parse step. '
  'See migration 291.';

-- Backfill on evidence, not on a guess: only the tds_workspace path writes a
-- reconciliation_result, and only it sets status='reconciled'. The 26AS
-- pipeline writes neither, so rows carrying both are unambiguously its.
--
-- Both columns are guaranteed to exist by the converging ALTER above, so this
-- no longer depends on which shape the database started from. On the live
-- database it matches nothing — those columns were only just added, and the
-- table is empty because the insert has never succeeded there.
UPDATE public.form_26as_uploads
   SET source = 'tds_workspace'
 WHERE source = 'form_26as_pipeline'
   AND status = 'reconciled'
   AND reconciliation_result IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_form_26as_uploads_source
  ON public.form_26as_uploads (firm_id, client_id, source);
