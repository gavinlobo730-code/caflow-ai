# 06 — Multi-Currency (Phase 0 — FROZEN design)

**Status: FROZEN v1.0 — DESIGN ONLY. Not implemented.** The engine is single-currency (INR) today; this is the approved architecture for adding multi-currency as an additive layer. Nothing here changes behaviour until implemented phase-by-phase. Reopens only for a critical architectural issue (change-controlled).

## Scope decision

- **Capability A only** — INR-functional books that *transact* in foreign currency; FX differences → P&L (IAS 21 remeasurement). This is the enterprise-common case (exporters/importers).
- **Deferred (Capability B)** — presentation-currency translation (functional ≠ presentation → FCTR/OCI in equity) and consolidation. A future, separately-scoped track.

## Principle

Additive, base-currency-authoritative, INR-default. The **base (INR) amount stays in the existing `debit_paise`/`credit_paise` columns**, so the reporting engine and all reports keep working unchanged. Everything defaults to INR / rate = 1; with the feature off (the default), behaviour is byte-for-byte today's.

Why it's contained (not a rewrite): there is **one posting kernel** and **one GL read path**, and money is already integer-only — so the change concentrates in the schema + kernel + a few new behaviours.

## Three-level model

| Level | Owner | Question | Where |
|---|---|---|---|
| **L1 Platform** | Ops/Eng | switched on at all? (kill switch) | env `MULTI_CURRENCY_ENABLED` (no DB dependency) |
| **L2 Firm** | Commercial | is the practice entitled? (plan/beta) | `firms.multi_currency_entitled` |
| **L3 Client** | Accounting | does this entity transact in foreign currency? | `clients.functional_currency` (default `INR`), `clients.multi_currency_enabled` |

`resolveCurrencyPolicy(firm, client) -> { active, functional_currency }` where `active = env AND firm.entitled AND client.enabled`. It is the **single decision point, enforced authoritatively in the posting kernel** (the kernel rejects any non-INR line / rate≠1 when inactive — UI/API gating is convenience only). Off / ambiguous / missing-rate ⇒ INR-only. (There is no `reporting_currency` on the client; non-INR functional currency is rejected until Capability B.)

## Guarantees

- **G1 Unlimited ISO currencies** via a `currencies` master (code, symbol, `minor_unit` exponent) — no hardcoded currency lists; a JPY amount uses 0 decimals, not "paise".
- **G2 Single `resolveCurrencyPolicy()`** enforced in the kernel, fail-safe to INR.
- **G3 Immutable rates on posted transactions** — the booking rate/base are frozen at posting; historical documents are never recalculated. Rate changes only affect new transactions, settlement (realized), and period-end revaluation (new, auto-reversing entries). Corrections via reverse + re-post.
- **G4 Permanent dual storage** — every posted line keeps `txn_currency`, `exchange_rate`, foreign amount, **and** the INR base (`debit_paise`/`credit_paise`).
- **G5 Provider abstraction** — a `RateProvider` interface (manual / RBI / ECB / future feeds) behind one `ExchangeRateService`; the accounting engine depends only on the service, never a provider (add a feed = implement + register, zero kernel/report changes).
- **G6 Extended FX audit provenance** — each posting permanently records txn currency, base currency, exchange rate, rate source, `rate_date`, posting timestamp, posting user, and the rate-selecting user (nullable when system-resolved); plus a structured `audit_log` event.

## Accounting standards

**Ind AS 21 / AS 11** (IAS 21 is their global parent). Implemented (A): initial recognition at the transaction-date rate; **monetary items** retranslated at closing rate, non-monetary at historical; exchange differences → P&L. **Indian statutory:** GST on a foreign supply is computed on the **INR-equivalent at the CGST Rule 34 notified rate**; imports use the customs rate; exports zero-rated; GST/TDS/Schedule III remain INR (see `07-gst-engine.md`).

## Data model (Phase 0 objects + Phase 1 columns, designed)

- `currencies` (ISO 4217 master, `minor_unit`), `fx_rates` (`base, quote, rate_date, rate_type ∈ {booking, gst_notified, customs, closing}, rate NUMERIC(18,8), source`).
- Flags: `firms.multi_currency_entitled`, `clients.functional_currency`, `clients.multi_currency_enabled` (all safe defaults → behaviour-inert).
- `journal_lines` (+): `txn_currency`, `base_currency`, `exchange_rate NUMERIC(18,8)`, `txn_debit`, `txn_credit`, `rate_source`, `rate_date`, `rate_type` — **base stays in `debit_paise`/`credit_paise`**.
- `journal_entries` (+): `rate_selected_by`, `rate_overridden`, `rate_selected_at` (posting timestamp/user already exist).
- Masters: `customers.default_currency`, `vendors.default_currency`, `bank_accounts.currency`. COA: FX Gain/Loss (realized/unrealized) + FX Rounding accounts (`system_account_key` `fx_realized`/`fx_unrealized`/`fx_rounding`).

## Precision & rounding

Rate exact `NUMERIC(18,8)` (never float); `base_paise = round(txn_minor × rate)` via `Decimal`, one documented rounding mode (recommend HALF_UP), residual to the FX Rounding account so entries balance exactly in base.

## Roadmap

- **Phase 0 (this):** frozen design. *No code.*
- **Phase 0.5 — Hardening (done):** single posting kernel — reversal + manual journal through the kernel; dead tables removed (see `02`/`05`).
- **Phase 1 — Foundation (done):** `currencies` master + `fx_rates` + `resolve_currency_policy()` + `RateProvider`/`ExchangeRateService` + the three gating flags (migration 146). Defaults INR/1; reports & existing tests unchanged; feature off ⇒ byte-for-byte today. See `06a-multi-currency-phase1-implementation.md`.
- **Phase 2 — Accounting Foundation / currency-aware GL (done):** additive FX columns on `journal_lines` (`txn_currency`, `base_currency`, `exchange_rate`, `txn_debit/credit`, `rate_source/type/date`) and `journal_entries` (`rate_selected_by/overridden/at`) via migration 147; the single posting kernel now stamps immutable per-line currency metadata (INR/rate 1 for all current postings), still balances in base, and is the authoritative gate that refuses a non-INR line / rate≠1 unless the policy is active. `ExchangeRateService` wired into the kernel (not invoked for INR). No foreign documents; reports & existing tests unchanged. See `06b-multi-currency-phase2-implementation.md`.
- **Phase 3 — Foreign-currency business documents (done):** foreign sales invoices, purchase bills, receipts and payments (migration 148 — additive document currency columns). Documents store txn currency + frozen rate + foreign amount; the base (INR) amount stays authoritative and posts to the GL, which still balances entirely in base; settlement is at the document's frozen rate only (cross-rate / partial-foreign rejected — realized FX is next phase); dual-currency statements. TDS/statutory stay INR. See `06c-multi-currency-phase3-implementation.md`.
- **Phase 4 — FX accounting (done):** realized FX on settlement (receipts/payments at a rate ≠ the document's booked rate → Realized FX Gain/Loss; partial/multiple/over-payment; `paid_txn` tracks foreign settled so no drift) and unrealized period-end revaluation of open foreign AR/AP at the closing rate (`FXRevaluationService` — idempotent/self-healing delta, auto-reversed on day 1 of the next period). All FX posts append-only through the kernel; documents/rates never modified; full audit in `fx_adjustments`. Migration 149. See `06d-multi-currency-phase4-implementation.md`.
- **Phase 5 — Reporting, financial statements & production validation (done):** read-only FX reporting and dual-currency visibility on top of the Phase 1–4 engine. General Ledger gains optional transaction-currency visibility (per foreign line); TB/BS/P&L/Cash-Flow stay base-authoritative and reconcile with the GL (absorbing the realized/unrealized FX P&L accounts). Customer/vendor statements + AR/AP aging show foreign + base outstanding by currency. Five FX reports (`/api/fx-reports/*`): realized, unrealized, currency exposure, exchange-rate audit, open foreign balances — all derived from posted data. Foreign-currency bank accounts (`bank_accounts.currency`, migration 150) with period-end revaluation integrated into `FXRevaluationService` (keyed by `fx_revaluations.item_ref`). Frontend FX Reports tab (policy-gated, so INR-only clients see no change). Additive; INR path byte-for-byte unchanged. See `06e-multi-currency-phase5-implementation.md`.
- **Future:** Capability B (presentation-currency translation / FCTR/OCI / consolidation) and foreign correction documents (credit/debit notes).

## Guarantees preserved

Double-entry (balanced in base), integer arithmetic (foreign minor units + base paise; rate NUMERIC; no float), auditability (freeze historical rate; full provenance), multi-year (date-based FY locks unaffected), performance (additive columns; INR path zero-overhead; reports read base unchanged), and **existing tests pass unchanged with the feature off** — the acceptance gate for every phase.
