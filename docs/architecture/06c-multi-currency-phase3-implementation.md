# 06c — Multi-Currency Phase 3 (Foreign-Currency Documents) — Implementation

Adds foreign-currency **operational documents** (sales invoices, purchase bills,
receipts, payments) on top of the currency-aware GL from Phase 2. The general
ledger continues to balance **entirely in the base (INR) functional currency**;
foreign amounts are stored alongside. **Feature-gated and dormant by default** —
INR documents are byte-for-byte unchanged and the full existing suite passes.

Out of scope (Phases 4–5): realized/unrealized FX, revaluation, translation,
presentation currency, foreign TB/BS/P&L, consolidation.

## Model

A document is entered in a transaction currency; the line amounts are that
currency's minor units. At create, the currency is validated and the booking rate
frozen; each component is converted to base paise (`to_base_minor`, Decimal
HALF_UP) and the **base total is the SUM of the converted components**, so the GL
balances exactly with no FX-rounding account. The existing `*_paise` columns hold
the base (INR) amounts (authoritative — GL, GST, reports, TDS read these); new
`txn_*` columns hold the foreign amounts + frozen rate + provenance.

## What changed

- **Migration 148 (additive):** `txn_currency`, `exchange_rate`, foreign amount(s)
  (`txn_taxable`/`txn_total_gst`/`txn_total`, `txn_net_payable` on bills,
  `txn_amount` on receipts/payments) and rate provenance on
  `client_sales_invoices`, `purchase_bills`, `receipts`, `purchase_payments`. All
  default to the INR/rate-1 state.
- **`domain/currency/conversion.py`** — `to_base_minor` / `to_txn_minor` (exact).
- **`domain/currency/document_currency.py`** — `resolve_document_currency()`
  (validate policy + master + rate, freeze) and `document_currency_from_row()`
  (reconstruct the frozen rate at posting). Single place for the Task-6 validations.
- **Sales invoices / purchase bills** — create resolves + freezes the currency,
  computes base (summed) + foreign totals, persists both. TDS is computed on the
  **base (INR)** taxable (statutory). Posting (`issue` / `receive`) goes through the
  Phase-2 kernel, which stamps each line's foreign amount and the frozen rate.
- **Receipts / payments** — a foreign receipt/payment settles a **same-currency**
  document **at its frozen rate**, converted to base up front so all settlement
  runs in base. Phase-3 limit: **full settlement only** (partial-foreign / cross-rate
  / foreign advances / foreign TDS are rejected with a clear message — they need
  realized FX, next phase).
- **Statements** — customer & vendor statements now show `txn_currency`,
  `exchange_rate` and `txn_amount` beside the authoritative base amounts.
- **Kernel** — `_currency_kwargs()` reconstructs the frozen rate from the document
  row, stamps per-line foreign (memo) amounts, and re-resolves the policy so the
  authoritative gate is satisfied; INR ⇒ no-op (byte-for-byte).

## Validations (Task 6, all backend)

Missing rate, disabled policy, unsupported/inactive currency, invalid /
zero / negative rate → 422 at document create; currency mismatch between a
settlement and its document, and cross-rate settlement → 422 at receipt/payment.

## Guarantees

GL balances in base (dr == cr in paise); integer paise, Decimal/`NUMERIC` rates
(never float); frozen rate on posted documents, never recalculated (G3); full FX
provenance persisted (G6); RBAC/tenant isolation unchanged; multi-year unaffected.

## Verification

- Full backend suite **2092 passed / 23 pre-existing DB-connectivity failures
  (unchanged) / 43 skipped**; new: 9 conversion tests + 7 end-to-end Phase-3 tests
  (foreign sales cycle, foreign purchase cycle, and 5 validation cases).
- Live DB (pbgoeyjvmllrafzavkgx): migration 148 applied; all existing documents
  default to INR / rate 1.
- Foreign sales cycle proven: USD 1,180.00 @ 83.5 → AR ₹98,530.00 (base), TB
  balanced, journal lines carry USD; USD receipt clears AR to zero. Purchase cycle
  mirrors on AP.
- Dormant unless env `MULTI_CURRENCY_ENABLED` **and** `firms.multi_currency_entitled`
  **and** `clients.multi_currency_enabled` are all enabled.
