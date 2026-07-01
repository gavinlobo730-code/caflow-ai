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
Sales · Purchases · Receipts · Payments · Credit Notes ┐
Banking (import/settlement) · Payroll · Fixed Assets   ├─▶ _create_journal ─▶ journal_entries
Opening Balances · Manual Journals · Reversals         ┘        + journal_lines ─▶ Reporting
```

*(Debit notes do not exist yet as a document — only a GST classification string.)*

## Core invariants

| Invariant | Where enforced |
|---|---|
| Integer paise only (no float) | Everywhere; kernel + models + reporting |
| Double-entry (Σ debit = Σ credit) | `_create_journal` (asserts before insert) |
| Posted entries are immutable | DB triggers `trg_journal_immutability` (update) / `trg_journal_immutability_delete` (delete) |
| No posting into a locked FY | `period_validation_service.validate_posting_date` on every posting/edit path (see `03-financial-years.md`) |
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
| `06-multi-currency-phase0.md` | Frozen multi-currency architecture (design; not yet implemented) |
| `07-gst-engine.md` | GST computation, GSTR-1/3B/2B |
| `08-reporting-engine.md` | GL, Trial Balance, Balance Sheet, P&L, Cash Flow |

## Current phase

Single-currency (**INR**) production engine. Multi-currency is designed (frozen Phase 0) and gated OFF; nothing currency-aware is implemented yet — see `06-multi-currency-phase0.md`.
