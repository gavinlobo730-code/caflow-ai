# 04 — Opening Balances

Master records carry onboarding opening balances that must appear in the general ledger so the Trial Balance and Balance Sheet reconcile. They are kept in sync with the GL by an **append-only** model — no posted entry is ever deleted or mutated.

## Source data

Integer paise on the master tables (the single source of truth for opening positions):
- `customers.opening_balance_paise` (+ `opening_balance_date`)
- `vendors.opening_balance_paise`
- `bank_accounts.opening_balance_paise` (+ optional `coa_account_id` mapping)

## The opening family

`services/opening_balance_service.py` maintains, per client, an **opening family** of journal entries identified by `source_type = "Opening"` (entry_type `"Opening"`). Their net effect is:

```
Dr Trade Receivables   = Σ active customers' opening_balance_paise
Dr Bank (per account)  = Σ active bank accounts' opening_balance_paise
Cr Trade Payables      = Σ active vendors' opening_balance_paise
Cr/Dr Opening Balance Equity = balancing contra
```

- The **Opening Balance Equity** control account (code `3004`) is seeded firm-wide (migration `135`, `coa_seed_service`).
- Entries are dated at the client's `financial_year_start` and post through the single kernel (`_create_journal`, `is_posted=True`, `source_type="Opening"`, unique `reference_no = OPENING-BALANCE-<hex>`). No GST (book figures, not supplies).
- `source_type="Opening"` distinguishes the auto-maintained family from a user's *manual* journal that happens to use entry_type "Opening" (`source_type="manual"`), which this service never touches.

## Append-only regeneration (delta model)

`post_opening_balances(firm_id, client_id, opening_date=None, created_by=None)` reconciles the GL to the masters by posting **one balanced adjusting entry for the difference**:
1. read active customers/vendors/banks; compute the **target** net per control account;
2. compute the **current** net per account across the existing opening family;
3. `validate_posting_date` (FY lock) **before** any write;
4. post a single balanced **delta** journal for `target − current` (contra Opening Balance Equity). If the delta is zero, it is a **no-op**.

Properties:
- **Immutable / append-only** — never deletes or updates a posted entry, so it is compatible with the journal-immutability triggers (`02-posting-kernel.md`). *(Verified against the production trigger: delete-and-recreate is still blocked; the append-only delta posts successfully.)*
- **Idempotent** — a re-run with no master change computes a zero delta → posts nothing.
- **Self-healing** — any drift between the GL family and the masters is corrected by the next delta.
- `created_by` is the internal `users.id`.

Example: customer opening ₹5,000 → ₹8,000 posts one `+₹3,000` delta (Dr AR / Cr OBE); the original ₹5,000 entry is left untouched. The AR/OBE net = ₹8,000.

## Automatic posting

Opening balances post automatically — no manual "post to ledger" step:
- `customers`/`vendors`/`bank_accounts` create/update call `post_opening_balances` **only when the opening balance actually changed**.
- On failure the master write is rolled back and the caller returns a friendly error.
- `POST /api/accounting/opening-balances` remains as an internal/backfill re-post.

## Bill-wise opening documents and the opening register

The family above is **three totals** (aggregate Trade Receivables, aggregate Trade Payables, each bank), which is right for the general ledger and useless for ageing: every AR/AP ageing screen and the Schedule III ageing note bucket by the due date of each open document, and a control-account total has no dates. Two further doors take an opening position in the shape the rest of the product needs. **Neither posts a journal**, and each says so on every answer.

**Opening documents** (migration 391; `domain/accounting/opening_documents.py`, `services/opening_document_service.py`, `routers/opening_documents.py`, `POST /api/opening-documents` and `/bulk`):
- An opening document is an ordinary row in `client_sales_invoices` or `purchase_bills` carrying the **old system's own number and date**, with `is_opening` true. A receipt allocates against it, a statement lists it and the bank match queue offers it, all unchanged.
- It is the **bill-wise breakup** of `customers.opening_balance_paise`, which stays the single source of the ledger's AR leg, so it posts nothing. `reconcile()` names the difference between the documents and the master rather than absorbing it.
- It declares no tax and withholds nothing (the GST was declared where the document was issued): every tax field is zero. Every reader that feeds a statutory output excludes it with `without_carried_over`.
- `double_openings` reports an account opened by **both** mechanisms (the masters and an imported trial balance), because nothing else compares them; it offers no difference, since which of the two is the mistake is the CA's answer.

**The fixed-asset opening register** (migration 456; `services/opening_register_service.py`, `POST /api/fixed-assets/opening-register`): states where each asset stands on one 31 March (cost and accumulated depreciation), recorded as `fixed_assets.opening_position_date`. It posts no journal, because the ledger already carries the asset through the opening balances; the register-to-ledger tie-out is named, not computed.

**A trial balance import** (`services/trial_balance_import_service.py`, `POST /api/accounting/trial-balance/import`) is a third door and posts, under `source_type = 'TrialBalance'`, deliberately separate from `'Opening'` so the delta model never touches it.

## Design note — why deltas (not delete-recreate, not reverse-and-repost)

- **Delete-and-recreate** (original) conflicted with immutability — deleting the posted opening journal is blocked by `prevent_posted_journal_delete`, so regeneration failed whenever a journal already existed (this was the true, recurring "Unable to save customer" cause).
- **Reverse-and-repost** preserves immutability but regenerates the whole journal each change, cluttering the AR/OBE ledgers with net-zero reversal pairs.
- **Deltas** preserve immutability *and* keep the books clean (one small, meaningful entry per actual change) with **no trigger exemption / no special case** — opening balances follow the same append-only, kernel-routed discipline as every transaction. This is the chosen long-term architecture.

## Multi-currency note

**Opening balances are INR only today.** The multi-currency design (`06-multi-currency-phase0.md`) anticipated each master gaining a currency with the opening entry recording the foreign amount, and that was not built for opening balances: `customers` and `vendors` carry no currency, `bank_accounts.currency` exists (migration 150) but `opening_balance_service` reads no currency at all, and the opening family posts INR at rate 1 through the kernel. The delta model is unchanged.

## Tests

`tests/test_opening_balance_journal.py` (balanced deltas, reconciliation, idempotent no-op, **append-only: original never deleted/mutated**, self-healing, zeroing nets to zero), `tests/test_opening_balance_autopost.py` (auto-post on create/edit, rollback on failure, internal-id `created_by`).
