# 01 — Accounting Engine (Overview)

PracticeSync keeps a full **double-entry general ledger per client**. This document is the map; the numbered docs beside it drill into each subsystem.

> Money rule (everywhere, no exceptions): every monetary value is an **integer number of paise** (`*_paise`, `BIGINT`). Never floating point. ₹1 = 100 paise.

## Entities & scope

```
firm (CA practice / tenant)
 └── client (the accounting entity — its own GL, TB, BS, P&L, GST, statements)
      ├── chart_of_accounts        (firm templates + client accounts)
      ├── customers / vendors / bank_accounts   (masters, carry opening_balance_paise)
      └── journal_entries → journal_lines        (the live double-entry GL)
```

- The **client** is the accounting entity. Every report, balance, and statutory filing is client-scoped.
- The **firm** is the tenant. All rows carry `firm_id`; access is firm-scoped (RLS + explicit `.eq("firm_id", …)` under the service role).

## The general ledger

The live GL is **`journal_entries` + `journal_lines` only** (migration `003_phase3a_foundation.sql`).

- `journal_entries`: `firm_id, client_id, entry_date, reference_no, narration, entry_type, is_posted, status, posted_at, posted_by, created_by, source_type, source_id, reversal_of, attachments, deleted_at, …`
  - `entry_type` CHECK ∈ `Sales | Purchase | Payment | Receipt | Journal | Contra | Opening`.
  - `is_posted` is the authoritative on-books flag (reports read posted only). `status` mirrors it (`posted`/`draft`).
- `journal_lines`: `journal_entry_id, account_id, debit_paise, credit_paise, narration` with CHECK `NOT (debit>0 AND credit>0)`.
- **Chart of accounts** (`chart_of_accounts`): `account_type ∈ Asset/Liability/Equity/Revenue/Expense`, optional `system_account_key` (stable control-account id, e.g. `ar`, `ap`, `bank`, `gst_output`, …), `client_id NULL` = firm-level template.

## The single posting kernel

**Every** accounting workflow posts through one function — `phase2_journal_service._create_journal` — which validates double-entry balance and writes the entry + lines. There are no alternative posting paths (enforced as of Phase 0.5; see `02-posting-kernel.md`).

```
Sales · Purchases · Receipts · Payments             ┐
Credit Notes · Debit Notes · Banking (import/       ├─▶ _create_journal ─▶ journal_entries
settlement) · Payroll · Fixed Assets · Opening       │        + journal_lines ─▶ Reporting
Balances · Manual Journals · Reversals               ┘
```

*(Debit notes: full document + GL posting, `apps/api/routers/debit_notes.py`, migration `145`;
frontend UI on the Purchases page.)*

## Core invariants

| Invariant | Where enforced |
|---|---|
| Integer paise only (no float) | Everywhere; kernel + models + reporting |
| Double-entry (Σ debit = Σ credit) | `_create_journal` (asserts before insert) |
| Posted entries are never hard-deleted or rewritten in place | DB triggers `trg_journal_immutability` (update) / `trg_journal_immutability_delete` (delete). A **manual** entry may be edited or soft-deleted while its period is open — `edit_posted_journal` / `discard_posted_journal`, both gated on `journal_period_lock_reason` (migrations 266, 275, 276) |
| No posting into a closed period | `period_validation_service.validate_posting_date` on the posting/edit paths, **and the kernel itself** (`period_lock_service.closure_reason`: the firm locked the year, or the client's year-end is finalised, migration 361), so a path that never calls the validator is still refused. A *filed return* is asked only where a document that feeds a return is written, not by the kernel (see `03-financial-years.md`) |
| Multi-tenant isolation | RLS + firm-scoped writes; `created_by` FKs to internal `users.id` |
| Auditability | `trg_audit_capture` + `services/audit_service.log_event` |

## API & money conventions

- All endpoints return the envelope `{ success: bool, data: any, error: string | null }` (`models/common.api_response`).
- Money crosses the API as raw integer `*_paise`; the **frontend** formats to ₹ (base currency INR). No business logic in the frontend.

## Subsystem docs

| Doc | Subsystem |
|---|---|
| `02-posting-kernel.md` | The single posting kernel, draft/post lifecycle, reversals |
| `03-financial-years.md` | Indian FY, year locking, period validation |
| `04-opening-balances.md` | Master opening balances → the opening journal |
| `05-manual-journals.md` | Manual journal module |
| `06-multi-currency-phase0.md` | Multi-currency architecture: design frozen, Capability A implemented and gated off (read its status banner first) |
| `06a-multi-currency-phase1-implementation.md` | Phase 1: currencies master, rates, the three gates (migration 146) |
| `06b-multi-currency-phase2-implementation.md` | Phase 2: a currency-aware GL, the kernel stamps each line's currency (147) |
| `06c-multi-currency-phase3-implementation.md` | Phase 3: foreign sales invoices, purchase bills, receipts and payments (148) |
| `06d-multi-currency-phase4-implementation.md` | Phase 4: realized FX on settlement, and the AS 11 year-end revaluation (149) |
| `06e-multi-currency-phase5-implementation.md` | Phase 5: FX reports and foreign-currency bank accounts (150) |
| `07-gst-engine.md` | GST computation, GSTR-1/3B/2B |
| `08-reporting-engine.md` | GL, Trial Balance, Balance Sheet, P&L, Cash Flow, and the read paths behind them |
| `09-bank-entries.md` | A bank statement line becomes a voucher: Receipt, Payment or Contra |
| `10-payroll.md` | Payroll, the bureau model (a design record, partly superseded; read its status box) |

## Current phase

An **INR-functional** production engine. Multi-currency **Capability A** (INR books that transact in foreign currency) is **implemented** (Phases 0.5 to 5, migrations 146 to 150) and **gated OFF by default**: a foreign-currency transaction needs the environment switch `MULTI_CURRENCY_ENABLED`, `firms.multi_currency_entitled` and `clients.multi_currency_enabled`, and the two database gates are writable by a Partner (`PUT /api/currencies/entitlement` and `/policy`). The AS 11 year-end revaluation has a door (`routers/fx_revaluation.py`). **Not built:** Capability B (presentation-currency translation; a non-INR functional currency is refused) and foreign credit and debit notes. See the status banner on `06-multi-currency-phase0.md`; where it and `06a` to `06e` disagree with this overview, they and the code win.
