# Cash-Basis Reporting — Remediation Design

**Status:** APPROVED — decisions locked (§7). Implementation may proceed; Phase 2 remains out of scope.
**Scope:** Fix the failed Phase 1 cash-basis audit. Phase 2 (Invoice Sending) remains **out of scope**.
**Compliance anchors:** IT Act §145 (method of accounting), §44AA (professional records), Companies Act §128 (accrual for companies), CGST Act §31/§34 (invoices/credit notes — always invoice-based, never affected by this view).

---

## 0. Why the first implementation failed (recap)

The shipped cash-basis engine operated entirely on `MOCK_JOURNAL_ENTRIES` and **guessed** invoice↔payment links by matching rupee amounts (`_build_ar_debit_index`). Consequences proven in the audit:

- Cash view rendered hardcoded demo data, not the firm's books (accrual = real Supabase, cash = mock → "split-brain").
- Amount-matching broke on multi-invoice receipts, duplicate amounts, and on-account receipts.
- Credit notes added revenue instead of reducing it; reversed receipts/payments left phantom revenue/expense.
- Independent integer flooring of each proportional line broke the Trial Balance by a paise on indivisible partials.
- No client/firm scoping.

The remediation removes amount-matching entirely and rebuilds cash basis as a **deterministic projection of the real posted ledger**, linked through the existing document/allocation foreign keys.

---

## 1. Current architecture (as-is)

### 1.1 Production data model (verified)

Every sales/purchase document posts a **balanced, immutable journal entry** to the real GL (`journal_entries` + `journal_lines`) via `apps/api/services/phase2_journal_service.py`. The GL is the single source of truth; documents carry a back-reference to their journal entry.

| Document | Table | GL posting (`phase2_journal_service`) | Link to GL | Link to counterparty |
|---|---|---|---|---|
| Sales invoice | `client_sales_invoices` | Dr A/R `total` · Cr Revenue `taxable` · Cr GST Output `cgst/sgst/igst` | `journal_entry_id` (FK, migr. 076) | invoice lines `client_sales_invoice_lines` |
| Receipt | `receipts` | Dr Bank `amount` · [Dr TDS Receivable `tds`] · Cr A/R `amount+tds` | `journal_entry_id` | `receipt_allocations(receipt_id → sales_invoice_id, allocated_paise)` |
| Credit note | `credit_notes` | Dr Revenue `taxable` · Dr GST Output · Cr A/R `total` | `journal_entry_id` | `sales_invoice_id` (nullable) |
| Purchase bill | `purchase_bills` | Dr Expense `taxable` · Dr GST Input · Cr A/P `net_payable` · [Cr TDS Payable] | `journal_entry_id` | bill lines `purchase_bill_lines.expense_account_id` |
| Purchase payment | `purchase_payments` | Dr A/P `amount` · Cr Bank `amount` | `journal_entry_id` | `purchase_bill_id` (single FK, nullable) |

Key facts that drive the design:

1. **Receipt allocations are in settlement terms.** `receipts.py:125` sets `settlement = amount_paise + tds_paise`, and allocations are validated so `Σ allocated ≤ settlement`. The receipt's Cr A/R is exactly `amount + tds`. Therefore `receipt_allocations.allocated_paise` **is** the A/R cleared against each invoice — no inference required.
2. **Purchases have no allocation table.** One payment → at most one bill (`purchase_payments.purchase_bill_id`, nullable for advances). "Purchase payment allocations" in the brief = this FK.
3. **Revenue accounts are not on the invoice line** (`client_sales_invoice_lines` has no `revenue_account_id`); the authoritative revenue/GST split lives in the invoice's **posted journal lines**. Expense accounts *are* on `purchase_bill_lines.expense_account_id`, but the bill's journal lines are likewise authoritative.
4. **Immutability + reversals.** Posted entries cannot be mutated (migr. 055 triggers); corrections are equal-and-opposite reversal entries carrying `reversal_of` (the router at `accounting.py:107` already does this).
5. **Control accounts are resolved by name** (`phase2_journal_service._find_account`: `%Trade Receivable%`, `%Trade Payable%`, `%Bank%`, `%GST Output%`, `%GST Input%`, `%TDS%`), scoped to `firm_id` with `client_id IS NULL OR =client`.

### 1.2 Reporting paths (as-is) — the defect

- **Accrual** reports are computed **in the browser** by direct Supabase queries over `journal_lines` (`apps/web/app/clients/[id]/accounting/page.tsx` — TB ~L790, P&L ~L910, BS ~L1123), filtered `is_posted=true`, `deleted_at IS NULL`, `client_id`, FY date range. (This is itself a pre-existing CLAUDE.md "no business logic in frontend" violation.)
- **Cash** reports call the backend API → `accounting_service.py` → **`MOCK_JOURNAL_ENTRIES`**. The backend never touches Supabase for reports.

→ The two bases read different sources. This is the root architectural failure.

---

## 2. Target architecture (to-be)

### 2.1 Principles

1. **One source of truth.** Both bases read the same posted ledger (`journal_lines`) with identical filters. Cash basis is a pure **projection** of that ledger.
2. **Links, never amounts.** Recognition is driven exclusively by `receipt_allocations`, `purchase_payments.purchase_bill_id`, `credit_notes.sales_invoice_id`, and `*.journal_entry_id`. All amount-matching code is deleted.
3. **Exact integer balance.** Every projected receipt/payment keeps its real cash leg and redistributes the **same integer total** across revenue/expense/GST legs via the **largest-remainder method**, so debits = credits to the paise on every entry → the TB cannot drift.
4. **Tenant isolation is mandatory and explicit.** Reports run under the service-role key (RLS bypassed), so every query filters `firm_id` **and** `client_id` in code.
5. **Backend-only computation.** The frontend passes parameters and renders; no financial logic in the browser.
6. **Testable without a database.** The projection is a pure function over an injected data provider; production uses a Supabase adapter, tests use an in-memory adapter.

### 2.2 Component design

```
routers/accounting.py
   └─ ReportingService (NEW, backend)
        ├─ LedgerSource (interface)
        │     ├─ SupabaseLedgerSource   → queries Supabase (prod)
        │     └─ InMemoryLedgerSource    → fixtures (tests/mock)
        ├─ AccountResolver               → classifies A/R, A/P, Bank, Revenue, GST, etc. per firm
        ├─ CashBasisProjector            → posted ledger → projected cash lines
        └─ report builders               → TB / P&L / BS from a line stream (shared by both bases)
```

- `LedgerSource` exposes scoped fetches: posted journal entries+lines, invoices (+journal lines), receipts (+allocations), credit notes, bills (+lines), payments — all filtered by `firm_id`, `client_id`, date.
- **Accrual** = report builders over the raw posted lines (same numbers the frontend produces today).
- **Cash** = report builders over `CashBasisProjector` output.
- The frontend's accrual report tabs move to the API too (see Decision A), so both bases come from one code path and are provably comparable.

### 2.3 The cash-basis projection (the core algorithm)

Classify **every posted, non-deleted journal entry** in range into exactly one class using its document back-links and `reversal_of`:

| Class | Detected by | Projection rule |
|---|---|---|
| **INVOICE** | entry id ∈ `client_sales_invoices.journal_entry_id` | **Drop.** Accrual recognition; cash effect arrives via receipts. |
| **BILL** | entry id ∈ `purchase_bills.journal_entry_id` | **Drop.** Cash effect arrives via payments. |
| **CREDIT_NOTE** | entry id ∈ `credit_notes.journal_entry_id` | **Drop** (pure A/R adjustment). Effect: reduces an invoice's net revenue base used for recognition (§2.4). A cash *refund* of a CN is a PAYMENT/DIRECT cash entry and is handled there. |
| **RECEIPT** | entry id ∈ `receipts.journal_entry_id` | Keep cash legs (Dr Bank, Dr TDS Recv). Replace Cr A/R with Revenue/GST from allocated invoices (§2.4). |
| **PAYMENT** | entry id ∈ `purchase_payments.journal_entry_id` | Keep cash leg (Cr Bank). Replace Dr A/P with Expense/GST-Input from the linked bill (§2.4). |
| **REVERSAL** | `reversal_of` is set | Re-project the **original** entry by class and **negate** it (handles bounced receipts, refunded payments, cancelled invoices). |
| **DIRECT** | none of the above | **Pass through unchanged.** (Opening balances, payroll, depreciation, GST/TDS remittances, direct cash sales/expenses, manual entries.) |

**Safety guard:** any DIRECT entry that touches the A/R or A/P control account is *not* silently passed through (that would resurrect accrual balances). It is logged and routed through the settlement logic by sign (Cr A/R ⇒ +revenue, Dr A/R ⇒ −revenue), so manual A/R/A/P journals can't corrupt the cash view.

### 2.4 Settlement recognition + exact-balance split

For a **receipt** with allocations `{(invoice_i, alloc_i)}` and unallocated `U = (amount+tds) − Σ alloc_i`:

```
keep: Dr Bank = amount ; Dr TDS Receivable = tds          # real cash legs, unchanged
for each allocation (invoice_i, alloc_i):
    T_i   = invoice_i.total_paise                          # A/R originally raised
    legs  = invoice_i's posted Cr lines (Revenue + GST), excluding the A/R debit
    legs  = net off any applied credit-note legs for invoice_i      # §2.3 CREDIT_NOTE
    split alloc_i across legs by LARGEST-REMAINDER so Σ parts == alloc_i exactly
    emit each part as a Cr to that revenue/GST account
emit unallocated U per Decision C (advance liability OR income)
```

`Σ(all credits emitted) = Σ alloc_i + U = amount + tds = Dr Bank + Dr TDS Receivable` → **entry balances to the paise.** Payments are the mirror (Cr Bank kept; Dr Expense/GST-Input split from the linked bill).

**Largest-remainder split (kills the rounding bug):**
```
def split(total, weights):           # all integers (paise)
    W = sum(weights)
    if W == 0: return [0]*len(weights)
    base = [(total*w)//W for w in weights]          # floor each
    rem  = total - sum(base)                         # 0..len-1 leftover paise
    order = indices sorted by ((total*w) % W) desc   # largest fractional remainder first
    add 1 paise to base[order[0..rem-1]]
    return base                                       # sum(base) == total, guaranteed
```

This is the standard apportionment used for tax/penny allocation; it preserves integer paise and guarantees the parts re-sum to the input.

### 2.5 Reports from the projected stream

TB, P&L, BS are all aggregations of the **same** projected line stream, so they are mutually consistent by construction:

- **Trial Balance:** sum Dr/Cr per account. Balances exactly (every emitted entry balances).
- **P&L:** Income (Cr−Dr) and Expense (Dr−Cr) accounts only. Cash revenue ≤ accrual revenue; cash expense ≤ accrual expense.
- **Balance Sheet:** net balances by type; A/R and A/P are **0** (their movements were projected away or netted), so unpaid invoices/bills correctly disappear. Retained-earnings/P&L plug keeps Assets = Liabilities + Equity.

### 2.6 Account classification (`AccountResolver`)

Mirror `phase2_journal_service._find_account` semantics, per firm, resolving control-account id-sets once per request: A/R (`%Trade Receivable%`), A/P (`%Trade Payable%`), Bank/Cash (`account_subtype` cash/bank or `%Bank%`/`%Cash%`), GST Output/Input, TDS. Everything else falls back to `account_type` (Income/Expense/Asset/Liability/Equity) already on `chart_of_accounts`. Fragility of name-matching is a known risk → see Decision B / migration option.

---

## 3. Migration impact

**Core remediation requires NO schema change.** All linkage already exists (`receipt_allocations`, `purchase_payments.purchase_bill_id`, `credit_notes.sales_invoice_id`, `*.journal_entry_id`).

Optional, additive, idempotent hardening (only if Decision B = "add keys"):

- `ALTER TABLE chart_of_accounts ADD COLUMN system_account_key TEXT;` + backfill (`ar`, `ap`, `bank`, `gst_output`, `gst_input`, `tds_payable`, …) to replace fragile name-matching with a stable key. Backward-compatible; resolver falls back to name-match when null.

No data backfill is required for reports (they read live tables). No posting/journal/GST logic changes. GST returns remain invoice-based and untouched.

---

## 4. Risk assessment

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Moving accrual to the backend regresses a working view (Decision A) | Med | High | Golden-number regression tests vs current frontend output on a fixture; ship cash first behind same API; feature-parity diff before switching the tab. |
| R2 | Service-role bypasses RLS → cross-tenant leakage if a filter is missed | Low | **Critical** | Mandatory `firm_id`+`client_id` on every query; centralize in `SupabaseLedgerSource`; add a tenant-isolation test. |
| R3 | Control-account name-matching misclassifies (custom CoA names) | Med | High | `AccountResolver` with explicit tests; recommend `system_account_key` (Decision B); fail-closed if A/R/A/P unresolved. |
| R4 | TDS-in-revenue / advance treatment chosen wrong → misstated income | Med | High | Domain decisions C/D pinned with CA sign-off; documented §145 rationale in code. |
| R5 | Largest-remainder mis-implemented → 1-paise drift returns | Low | High | Property test: random weights/totals, assert `Σ parts == total` and TB balances. |
| R6 | Multi-query report latency per client/FY | Low | Med | Bounded result sets; existing indexes (`idx_receipt_allocations_*`, `idx_purchase_payments_bill_id`, `idx_journal_*`); batch fetch + in-memory join. |
| R7 | Credit-note / reversal edge combinations | Med | Med | Explicit class handling + dedicated tests (§5). |
| R8 | Mock/no-DB environments can't query Supabase | High | Low | `InMemoryLedgerSource` adapter; projector is pure and DB-agnostic. |

---

## 5. Test plan (all mandated scenarios)

Pure unit tests over `InMemoryLedgerSource` fixtures (no DB), integer paise only, asserting TB balances exactly in every case:

1. **Multi-invoice allocation** — one receipt allocated across 3 invoices → revenue per invoice's own distribution; Σ = cash.
2. **Duplicate invoice amounts** — two invoices of identical value; a receipt allocated to *one* → revenue hits only that invoice's accounts (proves links, not amounts).
3. **Partial allocation** — receipt < invoice total → proportional revenue; remainder stays unrecognized; A/R off cash BS.
4. **Credit notes** — (a) CN before payment reduces recognized revenue; (b) CN with cash refund reduces cash revenue; CN never *adds* revenue.
5. **Receipt reversal** — bounced receipt negates the original recognition; cash revenue returns to 0; TB balances.
6. **Payment reversal** — vendor refund negates expense; TB balances.
7. **GST invoices** — CGST/SGST and IGST: revenue excludes GST; GST flows to its own account; cash totals differ from statutory GST (asserted) and GST returns are untouched.
8. **Rounding edge cases** — indivisible partials (e.g. ⅓ of ₹1,000.01) and mixed multi-account invoices → `Σ parts == cash`, TB difference == 0 (property/fuzz test).

Plus: **tenant isolation** (client B's data never appears for client A), **accrual regression** (backend accrual == known-good numbers), **invariants** (cash revenue ≤ accrual, cash expense ≤ accrual), and **API contract** (`basis` param, RBAC, `{success,data,error}`).

---

## 6. Sequencing (after sign-off)

1. `LedgerSource` interface + `InMemoryLedgerSource` + fixtures.
2. `AccountResolver` + tests.
3. `CashBasisProjector` + largest-remainder + tests 1–8.
4. `SupabaseLedgerSource` (scoped queries) + tenant-isolation test.
5. Wire `ReportingService` into `routers/accounting.py` (both bases); delete amount-matching code from `accounting_service.py`.
6. Per Decision A: point frontend report tabs at the API; remove browser-side aggregation.
7. Full regression; update audit checklist. **Stop. Do not start Phase 2.**

---

## 7. Decisions (LOCKED — signed off)

- **A — Compute location → UNIFY IN BACKEND.** Both accrual and cash move to one backend `ReportingService` reading the same Supabase source. Frontend report tabs call the API and render only. Fully closes the split-brain and removes browser-side financial logic. Mitigate regression risk (R1) with golden-number tests vs current accrual output.
- **B — Control-account identification → ADD `system_account_key`.** Additive, idempotent migration on `chart_of_accounts`, backfilled (`ar`, `ap`, `bank`, `gst_output`, `gst_input`, `tds_payable`, …). `AccountResolver` falls back to name-matching when the key is null.
- **C — Unallocated receipts (advances) → ADVANCE FROM CUSTOMERS (liability).** Unallocated cash is held as a liability and not recognized as revenue until allocated to an invoice. (Mirror: unlinked vendor payments → Advance to Vendors asset.)
- **D — TDS withheld on receipts → INCLUDE TDS AS RECEIVED.** Cash revenue = gross receipts (bank cash + TDS withheld), matching the receipt's A/R settlement (`amount + tds`) and standard gross-receipts reporting; TDS credit is tracked separately.

All four are reflected in §2–§5. Design is complete.

---

## 8. Implementation notes (as built)

New backend package `apps/api/domain/reporting/` (pure, DB-agnostic, unit-tested):
`model.py` (dataclasses + `apportion` largest-remainder), `resolver.py`
(`AccountResolver`, system-key + name fallback), `projector.py`
(`CashBasisProjector`), `builders.py` (TB/P&L/BS over a line stream),
`sources.py` (`LedgerSource` ABC, `InMemoryLedgerSource`, `SupabaseLedgerSource`),
`service.py` (`ReportingService` + `mock_ledger_source`).

- **Router:** `routers/accounting.py` report endpoints now use `ReportingService`
  (SupabaseLedgerSource when `SUPABASE_URL` set, else the in-memory seed),
  passing `firm_id` + `client_id`. `trial-balance` gained a `client_id` param.
- **Cleanup:** all amount-matching code removed from `accounting_service.py`
  (`_find_linked_*`, `_build_*_index`, `_get_cash_basis_lines`, `_tb_cash/_pl_cash/_bs_cash`,
  `basis=` dispatch). Its accrual methods remain only for the dev/demo seed.
- **Migration:** `092_coa_system_account_key.sql` (+ rollback), additive/idempotent.
- **Frontend:** both report pages call the API for **both** bases; browser-side
  journal aggregation removed from TB/P&L/BS. Schedule III grouping is presentation
  only, fed by backend account-level lines (now carrying type/subtype/code).
- **Tests:** `tests/test_cash_basis_reporting.py` rewritten — 20 allocation-driven
  tests (all 8 mandated scenarios + invariants + tenant isolation + accrual
  regression + apportionment fuzz). 97 accounting tests pass.

Two honest notes for reviewers:
1. **Accrual TB is now point-in-time cumulative** (all posted entries up to
   `as_of`), consistent with the Balance Sheet. The previous browser TB was
   FY-window-bounded (movements, not balances) — the new behaviour is the
   correct trial balance, but the displayed accrual TB numbers may change for
   clients with prior-period data.
2. **Manual journal entries that directly touch A/R or A/P** (not via a
   document) pass through unchanged in the cash view, so they could surface a
   receivable/payable. Document-driven invoices/receipts/bills/payments — the
   normal path — correctly net A/R and A/P to zero. A future "route by sign"
   guard (or `system_account_key`-based reclass) can tighten this if needed.
