# Batch 3.1 Completion Report — Internal-client accounting hardening

**Amendment v1.1 (Phase 10B) · Batch 3.1 (hardening) · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14 · **Migration:** `076_invoice_journal_link.sql` (+ rollback)

Closes the financial-integrity risks from the deployment-readiness review: missing
firm-wide CoA, account-name mismatch, issued-but-unposted invoices, and no recovery path.

## 1. Firm master CoA seeding

- `services/coa_seed_service.py` — `seed_firm_coa(firm_id)`: idempotent (skips if the
  firm already has firm-wide accounts), firm-wide (`client_id = NULL`, per the
  Migration-057 architecture), inserting a standard Schedule III CA-practice chart.
- **Names match the posting engine's `_find_account` ILIKE patterns** — `Trade
  Receivables` (`%Trade Receivable%`), `Sales Revenue` (`%Sales%`), `GST Output Tax
  Payable` (`%GST Output%`), `Bank Account` (`%Bank%`), plus Trade Payables, GST
  Input, TDS Payable (+Salary), PF/ESI/PT Payable, Net Salary Payable, the six fixed-
  asset categories, Accumulated Depreciation, Depreciation Expense, Purchases,
  General Expenses, and Profit/Loss on Asset Disposal.
- **Invoked in `create_firm` onboarding** (before internal-client provisioning),
  idempotent + non-fatal. Existing firms can be backfilled by re-running it (a
  deployment step; the function is firm-scoped and safe to call repeatedly).

## 2. Atomic invoice issue

- `routers/sales_invoices.py::issue_invoice` reordered: the **journal is posted
  FIRST**; the invoice becomes `issued` (and stores `journal_entry_id`, migration
  076) only after posting succeeds. A posting failure (`ValueError` from missing
  CoA) returns a clear error and **leaves the invoice a re-tryable DRAFT** — the
  issued-but-unposted state is now impossible for new issues.
- In mock mode the journal is a no-op (returns None) and a sentinel link is stored,
  so the happy path is unchanged.

## 3. Recovery / remediation

- **Detection:** `GET /api/sales-invoices/maintenance/unposted` lists issued
  invoices with `journal_entry_id IS NULL` (partial index `idx_client_sales_invoices_unposted`).
  The internal client's invoices are visible only to Partners (G1).
- **Remediation:** `POST /api/sales-invoices/{id}/repost-journal` posts the missing
  journal and sets the link. Idempotent — if a journal already exists it is reused
  (`_create_journal` de-dups by `reference_no + entry_date + client_id`); Partner-only
  for the internal client (G1).
- Migration 076 adds `client_sales_invoices.journal_entry_id` (+ FK to
  `journal_entries`, + the partial detection index).

## 4. Files

**New:** `services/coa_seed_service.py`, `migrations/076_invoice_journal_link.sql`
(+ rollback), `tests/test_batch3_1_hardening.py`, `tests/test_batch3_1_migration.py`,
`tests/sql/batch3_1_hardening_verify.sql`.
**Modified:** `routers/onboarding.py` (CoA seed hook), `routers/sales_invoices.py`
(atomic issue + unposted/repost endpoints + G1 guards).

## 5. Verification

- **Posting succeeds with seeded CoA:** SQL harness inserts the firm-wide seed and
  resolves Trade Receivables / Sales / GST Output / Bank for the **internal client**
  via the exact `_find_account` predicate — PASS.
- **Missing CoA leaves a retryable draft:** posting raises → invoice stays `draft`,
  no journal link; re-issue after setup succeeds — PASS.
- **No issued-but-unposted for new issues:** issue is journal-first — PASS.
- **Detection + remediation:** legacy issued-but-unposted invoice is detected,
  reposted (idempotent), then no longer listed; Partner-only for internal — PASS.
- **Seed coverage:** every `_find_account` pattern has a matching seeded name — PASS.
- **Migration 076:** column + FK + partial index present; clean rollback — PASS.
- **No regression:** full suite **999 passed**; the same **23 pre-existing
  Supabase-503 environmental failures** — unchanged.

## 6. Residual notes

- **Existing-firm CoA backfill** is a deployment action (re-run `seed_firm_coa` per
  firm, or apply once via the onboarding path); idempotent and safe.
- **True transactional atomicity:** issue posts the journal then updates status in
  two statements over the service-role client (no single SQL transaction wrapper).
  The ordering guarantees no issued-but-unposted state; the only residual edge is a
  crash *between* a successful journal insert and the status update, which leaves a
  posted journal with the invoice still `draft` — re-issue is safe because
  `_create_journal` de-dups, so no double-posting. Documented; full DB-transaction
  wrapping is a later enhancement.

**Status: Batch 3.1 complete and passing. Awaiting review before Batch 4.**
