# 08 — Reporting Engine

One engine (`apps/api/domain/reporting/`) computes all five financial statements from posted `journal_lines`. Pure integer-paise arithmetic; DB-agnostic builders over a single ledger snapshot.

## Source of truth

- `SupabaseLedgerSource._entries` (`sources.py`) selects **posted, non-deleted** `journal_entries` with nested `journal_lines(account_id, debit_paise, credit_paise)`, firm- and client-scoped, coercing to `int`. Production reads Supabase; dev/demo reads an in-memory seed (`mock_ledger_source`). One code path, one source.
- `LedgerSnapshot` (`model.py`) is the immutable value object handed to builders (holds the in-range lines + full history + document maps).

## Reports (`builders.py`, via `ReportingService` in `service.py`)

| Report | Basis | Notes |
|---|---|---|
| **General Ledger** | cumulative | per-account opening/running/closing (debit-positive); opening = cumulative debit−credit strictly before the window start |
| **Trial Balance** | cumulative to `as_of` | per-account net; `is_balanced = grand_dr == grand_cr` (integer paise) |
| **Balance Sheet** | point-in-time (`as_of`) | assets debit-positive; L/E credit-positive; retained earnings synthesised from income/expense nets |
| **Profit & Loss** | period | income = credit−debit, expense = debit−credit; net profit = revenue − opex |
| **Cash Flow** | period | AS-3 indirect; O+I+F = Δcash = closing−opening (a paise identity) |

Exposed at `GET /api/accounting/{ledger,trial-balance,balance-sheet,profit-loss,cash-flow}`. All amounts are raw integer `*_paise`; formatting to ₹ happens in the frontend.

## Accrual vs cash

Both bases run through the **same** builders over one source. Cash basis is derived from real allocation links via `CashBasisProjector` (`projector.py`) and is **management reporting only** (IT Act §145) — it never affects GST/ITR filings, which stay invoice-based.

## Financial-year boundaries

Balances are cumulative sums of posted lines, so multi-year carry-forward is correct: GL opening = everything before the window; TB/BS cut at `(None, as_of)`; P&L/Cash-Flow use a period window with opening/closing cash cut at the period edges. Opening balances (`04-opening-balances.md`) enter as a normal posted journal, so they are included automatically.

## Snapshot / cache

Three request-scoped memoizations (no DB-backed report-cache table):
- `SupabaseLedgerSource._base_cache` — date-independent base fetch keyed `(firm_id, client_id)`; `snapshot()` re-applies the date filter in memory. A fresh source is built per request (`routers/accounting._reporting_service`).
- `LedgerSnapshot` (in-memory value object) and `CashBasisProjector._dist_cache` (per-invoice memo).

There is a materialized `ledger_balances` table in the schema, but the reporting engine does **not** read it — reports recompute live from `journal_lines`.

## Customer & vendor ledgers

Party statements read the master `opening_balance_paise` plus their invoices/receipts; in aggregate they agree with the GL control accounts (the opening journal puts the same opening figures into the GL), so each figure is counted exactly once per report.

## Multi-currency note (`06-multi-currency-phase0.md`)

The base (INR) amount stays in `debit_paise`/`credit_paise`, so **every report keeps working unchanged** under multi-currency. Foreign columns are additive/optional (per-currency sub-grouping, dual-currency display), and `is_balanced`/`reconciles` remain **base-only** checks. Two forward hooks:
- Period-end **FX revaluation** of monetary foreign balances slots into `ReportingService._lines` / `_cash_balance` (the same place `CashBasisProjector` already transforms the stream); Balance Sheet's `(None, as_of)` cut is the injection point; Cash Flow gains an "effect of exchange-rate changes on cash" line.
- Before revaluation lands, the snapshot cache key must gain an **as-of / rate** dimension (currently `(firm_id, client_id)` only) or a revalued report could be served at the wrong rate.

## Tests

`tests/test_reporting_snapshot_cache.py` (memoization), plus report assertions in `tests/test_accounting_journal.py` and the completion/e2e suites (TB/BS/P&L balanced, integer paise, cumulative running balances).
