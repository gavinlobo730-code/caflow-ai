# 04 — Opening Balances

Master records carry onboarding opening balances that must appear in the general ledger so the Trial Balance and Balance Sheet reconcile.

## Source data

Integer paise on the master tables:
- `customers.opening_balance_paise` (+ `opening_balance_date`)
- `vendors.opening_balance_paise`
- `bank_accounts.opening_balance_paise` (+ optional `coa_account_id` mapping)

## The opening journal

`services/opening_balance_service.py` posts **one balanced journal per client**, identified by the fixed `reference_no = "OPENING-BALANCE"` and `entry_type = "Opening"`:

```
Dr Trade Receivables   = Σ active customers' opening_balance_paise
Dr Bank (per account)  = Σ active bank accounts' opening_balance_paise
Cr Trade Payables      = Σ active vendors' opening_balance_paise
Cr/Dr Opening Balance Equity = balancing contra
```

- The **Opening Balance Equity** control account (code `3004`) is seeded firm-wide (migration `135_opening_balance_equity_account.sql`, `coa_seed_service`).
- Dated at the client's `financial_year_start` (else earliest master `opening_balance_date`, else April 1).
- Posts through the single kernel (`_create_journal`, `is_posted=True`). No GST is computed (opening balances are book figures, not supplies).

## Idempotent regeneration

`post_opening_balances(firm_id, client_id, opening_date=None, created_by=None)`:
1. reads active customers/vendors/banks and sums opening balances;
2. `validate_posting_date` (FY lock) **before** any mutation;
3. `_delete_existing` — removes the prior `OPENING-BALANCE` journal (+ its lines);
4. re-derives and posts a fresh balanced journal from current masters (nothing if all zero).

Because it is keyed by `reference_no`, it never touches a user's own manually-created "Opening" entry, and re-running always reflects the current figures (single source of truth). `created_by` must be the internal `users.id`.

## Automatic posting

Opening balances post automatically — there is no manual "post to ledger" step:
- `customers` create/update, `vendors` create/update, and `bank_accounts` create/update call `post_opening_balances` **only when the opening balance actually changed**.
- On failure the master write is rolled back and the caller returns a friendly error (e.g. "Unable to save customer. Please try again.").
- `POST /api/accounting/opening-balances` remains as an internal/backfill re-post for records entered before auto-posting existed.

## ⚠️ Known issue — regeneration vs journal immutability

`_delete_existing` **hard-deletes** the prior opening journal, but that journal is `is_posted=TRUE` and the DB trigger `trg_journal_immutability_delete` (`prevent_posted_journal_delete`) **blocks deleting any posted entry** (see `02-posting-kernel.md`).

Effect: the **first** opening-balance customer for a client posts fine (INSERT only), but any subsequent add/edit that triggers regeneration calls `_delete_existing` on the now-posted journal → the delete is blocked → `post_opening_balances` raises → the master save rolls back → **"Unable to save customer."** This is invisible to the test suite because `FakeDB` has no triggers.

**Recommended fix (open):** exempt the system-generated `OPENING-BALANCE` journal from the immutability delete/update guards (it is regenerable by design, not a hand-entered transaction), so regeneration works while real transactions stay immutable. Until then, regeneration only succeeds when no posted opening journal already exists.

## Multi-currency note

In Phase 1+, opening balances become currency-aware: each master gains a currency, and the opening journal records the INR-equivalent (base) alongside the foreign amount (`06-multi-currency-phase0.md`). The regeneration model above (and the fix) is a prerequisite.

## Tests

`tests/test_opening_balance_journal.py` (balanced journal, reconciliation, idempotency), `tests/test_opening_balance_autopost.py` (auto-post on create/edit, rollback on failure, internal-id `created_by`).
