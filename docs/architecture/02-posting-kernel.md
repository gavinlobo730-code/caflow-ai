# 02 — The Posting Kernel

**Principle: one posting engine, no alternative paths.** Every accounting event that touches the general ledger is written by `Phase2JournalService._create_journal` (`apps/api/services/phase2_journal_service.py`). This was made universal in **Phase 0.5** (journal reversal and manual journals previously bypassed it).

## `_create_journal(...)` — the kernel

Signature (integer paise throughout):

```
_create_journal(db, firm_id, client_id, entry_date, reference_no, narration,
                entry_type, lines,
                is_posted=True, source_type=None, source_id=None, created_by=None,
                reversal_of=None, attachments=None,
                txn_currency=None, exchange_rate=None, rate_source=None,
                rate_type=None, rate_date=None, rate_selected_by=None,
                rate_overridden=False, currency_policy=None) -> entry_id
```

The last eight parameters are the multi-currency metadata (`06b`): every one defaults to the INR, rate 1 identity, so a caller that passes none is unchanged.

What it guarantees, in order:
1. **Double-entry balance** — sums `debit_paise` / `credit_paise` across `lines`; raises `ValueError` if `total_debit != total_credit`, and refuses a balanced but zero-value journal. Nothing unbalanced ever reaches the GL.
2. **The period is not closed** — `period_lock_service.closure_reason` (the SQL `period_closure_reason`, migration 361) refuses a date inside a financial year the firm locked or a client year-end that was finalised, and raises its CA-facing sentence. A date it cannot read is itself a refusal. The *filed-return* branch is deliberately not asked here; see `03-financial-years.md`.
3. **Currency** — a non-INR line or a rate other than 1 is refused unless an active `CurrencyPolicy` is supplied (`06b`).
4. **Dedup** — if a live entry with the same `(client_id, reference_no, entry_date)` exists (not reversed, not soft-deleted: the unique index is partial on exactly those), it returns that id instead of duplicating (idempotency for auto-posted sources).
5. **Insert** — the `post_journal_atomic` RPC (migration 152) writes one `journal_entries` row and its `journal_lines` in one transaction, recording each line's position in the array as `journal_lines.line_order` (migration 384; a posted line from before it keeps `NULL` and `domain/accounting/line_order.py` orders it at read time). Only a database double with no `rpc` takes the two-insert fallback, which stamps `line_order` too.

Entry payload fields: `firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status(=posted/draft), posted_at, posted_by, created_by, source_type, source_id` — plus the additive, optional `reversal_of` and `attachments` (written only when supplied, so every existing caller is unchanged).

> `created_by` / `posted_by` FK to **`public.users.id`** (the internal user id), **not** the Supabase auth id (`current_user["id"]`, never `current_user["auth_user_id"]`). Passing the auth id violates `journal_entries_created_by_fkey`.

`entry_type` must be one of the CHECK values: `Sales, Purchase, Payment, Receipt, Journal, Contra, Opening`.

## Account resolution — `_find_account`

Callers reference accounts by intent, not id. `_find_account(db, firm_id, client_id, name_pattern, system_key=None)` resolves a `chart_of_accounts.id` by **`system_account_key` first** (firm-wide, stable), then falls back to **`account_name ILIKE`** (client OR firm-template scope). Raises `ValueError` if neither finds an active account.

**In practice the name match does most of the work, and that is worth knowing before renaming an account.** `seed_firm_coa` (`services/coa_seed_service.py`) writes no `system_account_key` on any row, so a freshly seeded firm resolves every account by name. Keys exist only where a migration stamped them: 092 back-filled the control accounts by name once, and later migrations (098, 149, 374, 375, 389, 397, 425) stamp the accounts they add. The payroll accounts (Salaries Expense, Net Salary Payable, the PF, ESI and PT payables, TDS Payable - Salary) are looked up by name only (the posting functions pass no key), so a renamed one stops a payroll finalising, and a key would not yet help for the TDS pair: migration 092 stamped `tds_payable` on both TDS accounts. The key branch itself is firm-wide and unordered (`.limit(1)`, no client scope), safe only for firm-level rows; migration 360's trigger refuses another client's account on a line. **The fix is not built**: one vocabulary of payroll keys and one client-scoped resolver, with the readers moved to it in the same change as the writers (switching only the posting functions would let the accrual and `tds_return_service`'s tie-out look the same accounts up differently).

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
- `trg_journal_immutability` → `prevent_posted_journal_update` (blocks UPDATE of a posted entry, except the draft→posted transition, the `is_reversed` stamp a reversal sets on its original (migration 274), and a write inside `app.journal_edit`).
- `trg_journal_immutability_delete` → `prevent_posted_journal_delete` (blocks hard DELETE of any `is_posted=TRUE` entry).
- `trg_audit_capture` (audit) and `trg_journal_updated_at` (timestamps).

A consequence: a posted entry can never be **hard-deleted or rewritten in place**. Workflows that keep derived GL state in sync (e.g. opening balances) therefore use **append-only adjusting entries**, never delete-and-recreate — see `04-opening-balances.md`.

That is narrower than "immutable", and deliberately so. `app.journal_edit` is a transaction-local GUC that only two SECURITY DEFINER functions may set, and both apply the same gate — `journal_period_lock_reason`, which returns a CA-facing sentence or nothing:

- `edit_posted_journal` (migration 266) rewrites a **manual** entry's lines while its period is open.
- `discard_posted_journal` (275, 276) soft-deletes one — `deleted_at`, which every read path and `apb_rebuild_client` already filter, so the entry leaves every screen, report and return at once while the row and its lines stay. On `p_with_pair` a reversed entry and its reversal go together: the pair strands nothing and nets to zero, so no balance moves. Half a pair alone is refused either way round.

Both write to `audit_log` — the edit through `trg_audit_capture_line`, the deletion through an explicit in-transaction INSERT carrying the whole entry, every line, and the account codes and names resolved. That INSERT has **no exception handler**, unlike every audit trigger in the schema: those swallow so auditing can never break a user's write, which is the right trade only when the row survives the failure.

The statutory basis is the proviso to Rule 3(1) of the Companies (Accounts) Rules 2014, which mandates an **edit log** of each change — presupposing that entries change. TallyPrime 3.0's Edit Log meets the same rule and still permits deleting a voucher. What must be immutable is the log.

## Attachments

`journal_entries.attachments` (`JSONB`, default `[]`, migration `138`) stores supporting-document references (`[{name, url}]`), written by the kernel only when a caller supplies them (manual journals today).

## Testing

`tests/e2e_harness.py` provides a `FakeDB` PostgREST double so real routers/services post against shared in-memory state. Note: `FakeDB` has **no DB triggers or CHECK constraints**, so trigger/constraint behaviour must also be verified against the real database.
