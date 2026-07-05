# 02 — The Posting Kernel

**Principle: one posting engine, no alternative paths.** Every accounting event that touches the general ledger is written by `Phase2JournalService._create_journal` (`apps/api/services/phase2_journal_service.py`). This was made universal in **Phase 0.5** (journal reversal and manual journals previously bypassed it).

## `_create_journal(...)` — the kernel

Signature (integer paise throughout):

```
_create_journal(db, firm_id, client_id, entry_date, reference_no, narration,
                entry_type, lines,
                is_posted=True, source_type=None, source_id=None, created_by=None,
                reversal_of=None, attachments=None) -> entry_id
```

What it guarantees, in order:
1. **Double-entry balance** — sums `debit_paise` / `credit_paise` across `lines`; raises `ValueError` if `total_debit != total_credit`. Nothing unbalanced ever reaches the GL.
2. **Dedup** — if a posted entry with the same `(client_id, reference_no, entry_date)` exists, it returns that id instead of duplicating (idempotency for auto-posted sources).
3. **Insert** — writes one `journal_entries` row + its `journal_lines`.

Entry payload fields: `firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status(=posted/draft), posted_at, posted_by, created_by, source_type, source_id` — plus the additive, optional `reversal_of` and `attachments` (written only when supplied, so every existing caller is unchanged).

> `created_by` / `posted_by` FK to **`public.users.id`** (the internal user id), **not** the Supabase auth id (`current_user["id"]`, never `current_user["auth_user_id"]`). Passing the auth id violates `journal_entries_created_by_fkey`.

`entry_type` must be one of the CHECK values: `Sales, Purchase, Payment, Receipt, Journal, Contra, Opening`.

## Account resolution — `_find_account`

Callers reference accounts by intent, not id. `_find_account(db, firm_id, client_id, name_pattern, system_key=None)` resolves a `chart_of_accounts.id` by **`system_account_key` first** (firm-wide, stable), then falls back to **`account_name ILIKE`** (client OR firm-template scope). Raises `ValueError` if neither finds an active account.

## Posting surface (every path → kernel)

| Workflow | Builder → kernel |
|---|---|
| Sales invoice (on issue) | `journal_for_sales_invoice` → `_create_journal` |
| Purchase bill (on receive) | `journal_for_purchase_bill` |
| Customer receipt | `journal_for_receipt` (via `receipt_service`) |
| Vendor payment | `journal_for_purchase_payment` |
| Credit note (on issue) | `journal_for_credit_note` |
| Debit note (on issue) | `journal_for_debit_note` |
| Bank transaction | `journal_for_bank_transaction` / `bank_posting_service` (draft) |
| Payroll / Fixed assets | `journal_for_payroll` / `journal_for_asset_*` |
| Opening balances | `opening_balance_service.post_opening_balances` → `_create_journal` |
| **Manual journal** | `manual_journal_service.create` → `_create_journal` |
| **Reversal** | `routers/accounting.reverse_journal_entry` → `_create_journal` |

## Draft → Approve → Post lifecycle

`services/journal_posting_service.py` is the single Draft→Post path:
- A journal can be created as a **draft** (`is_posted=False`, off-books).
- `post_draft(db, firm_id, journal_id, actor_id)` re-checks balance, enforces the **FY lock**, flips `is_posted=True` (allowed exactly once by the immutability trigger), audits, and fires any deferred downstream action recorded on the draft's `source_type`/`source_id` (e.g. bank settlement).
- Endpoints: `POST /api/accounting/journals/{id}/post` (approve a draft), `GET /api/accounting/journals` (approval queue).

## Reversals

`POST /api/accounting/journal/{entry_id}/reverse` (Partner only). Since Phase 0.5 it:
- fetches the original **firm-scoped** (tenant isolation);
- rejects reversing an unposted entry, a reversal, or an already-reversed entry;
- validates the reversal date against the **FY lock**;
- builds equal-and-opposite legs (swap debit ↔ credit) and posts them **through `_create_journal`** (balance validated there), with `reversal_of` linking back and `reference_no = REV-<original>`;
- leaves the original entry **immutable** (never modified); audits + timelines the reversal.

## Immutability (DB triggers)

On `journal_entries`:
- `trg_journal_immutability` → `prevent_posted_journal_update` (blocks UPDATE of a posted entry, except the draft→posted transition).
- `trg_journal_immutability_delete` → `prevent_posted_journal_delete` (blocks DELETE of any `is_posted=TRUE` entry — "create a reversal instead").
- `trg_audit_capture` (audit) and `trg_journal_updated_at` (timestamps).

A consequence: a posted entry can never be deleted or replaced in place. Workflows that keep derived GL state in sync (e.g. opening balances) therefore use **append-only adjusting entries**, never delete-and-recreate — see `04-opening-balances.md`.

## Attachments

`journal_entries.attachments` (`JSONB`, default `[]`, migration `138`) stores supporting-document references (`[{name, url}]`), written by the kernel only when a caller supplies them (manual journals today).

## Testing

`tests/e2e_harness.py` provides a `FakeDB` PostgREST double so real routers/services post against shared in-memory state. Note: `FakeDB` has **no DB triggers or CHECK constraints**, so trigger/constraint behaviour must also be verified against the real database.
