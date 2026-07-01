# 05 — Manual Journals

A production, DB-backed manual journal module that posts through the single kernel. (Before Phase 0.5 the manual-journal endpoint was an in-memory mock that never wrote the database; the mock now serves dev/demo only.)

## Endpoint & flow

`POST /api/accounting/journal` (`routers/accounting.py`, `accounting.write`):
- **Dev/demo** (no `SUPABASE_URL`): the in-memory `domain/accounting_service.AccountingService` (used by unit tests).
- **Production**: `services/manual_journal_service.ManualJournalService.create(db, firm_id, payload, actor_id)` → `phase2_journal_service._create_journal`. No alternative posting path.

## Request model — `JournalEntryIn` (`models/accounting.py`)

```
client_id, entry_date, reference_no?, narration?,
entry_type = "Journal"          # ∈ Journal, Contra, Payment, Receipt, Sales, Purchase, Opening
status     = "draft"            # "draft" (off-books) | "posted" (to the ledger)
attachments = []                # [{name, url}, ...]
lines: [ { account_id, debit_paise, credit_paise, narration? }, ... ]
```

Validation (at the model boundary, so both paths are covered):
- each line has exactly one non-negative side (debit XOR credit);
- **at least 2 lines**;
- **balanced**: Σ debit = Σ credit;
- `entry_type` and `status` restricted to the allowed sets.

## What the service does

`manual_journal_service.create`:
1. re-checks entry_type/status, ≥2 lines, non-empty, and base balance;
2. if `status="posted"`, runs the **FY-lock** check (`validate_posting_date`) — a draft is validated later at approval;
3. generates a unique `reference_no` (`MJ-<8hex>`) when none is given, so the kernel's `(ref, date, client)` dedup never collapses two blank-reference journals;
4. posts via `_create_journal` with `source_type="manual"`, `created_by=<internal users.id>`, and `attachments`.

## Capabilities

| Capability | How |
|---|---|
| Unlimited balanced lines | list of `lines`, validated + kernel-asserted |
| Draft / Posted | `status` → `is_posted`; drafts are off-books |
| Narration | entry + per-line |
| Attachments | `journal_entries.attachments` JSONB (migration `138`) |
| Approval-ready | drafts approved via `journal_posting_service.post_draft` (`POST /api/accounting/journals/{id}/post`, `accounting.approve`) |
| Reversal | any posted manual journal reverses via `POST /api/accounting/journal/{id}/reverse` (`02-posting-kernel.md`) |
| Audit | `log_event` on create + `trg_audit_capture`; posting/approval audited by the posting service |

## Identification

Manual entries carry `source_type = "manual"`, distinguishing them from auto-generated journals (invoices, receipts, bank, opening balances) in the approval queue and audit trail.

## Multi-currency note

When multi-currency lands (`06-multi-currency-phase0.md`), manual journals gain per-line `txn_currency` + `exchange_rate` + foreign amount, balanced in base INR by the kernel; the model/service are the natural place to capture and validate them.

## Tests

`tests/test_manual_journal.py` — draft stays off-books; posted hits the GL balanced; unbalanced / <2-lines / invalid entry_type rejected; unlimited lines + attachments persisted; manual-journal → reverse round-trips to zero. `tests/test_accounting_journal.py` covers the in-memory dev engine.
