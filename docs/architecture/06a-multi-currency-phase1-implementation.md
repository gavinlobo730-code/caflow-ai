# 06a — Multi-Currency Phase 1 (Foundation) — Implementation

Implements the **foundation slice** of the frozen Phase 0 architecture
(`06-multi-currency-phase0.md`). **Additive and feature-OFF by default** — with
`MULTI_CURRENCY_ENABLED` unset the platform is byte-for-byte identical to before,
and the existing accounting test-suite passes unchanged. No posting kernel,
journal, GST, or report code was touched.

## What was built

1. **Currency master (G1).** `currencies` table — `code` (ISO 4217, PK), `symbol`,
   `display_name`, `minor_unit` (exponent: JPY 0, INR 2, KWD 3), `is_active`.
   Seeded with 66 currencies (majors + every non-2-decimal exception). Unlimited:
   any ISO code can be added. No currency list is hardcoded in code — the master
   is the source of truth (`domain/currency/currency_service.py`).

2. **Feature gating — three levels (G2).**
   - L1 platform: env `MULTI_CURRENCY_ENABLED` (`core/feature_flags.py`).
   - L2 firm: `firms.multi_currency_entitled` (default FALSE).
   - L3 client: `clients.multi_currency_enabled` (default FALSE).
   - `resolve_currency_policy(firm, client) -> {active, functional_currency}`
     (`domain/currency/policy.py`): `active = L1 AND L2 AND L3 AND functional==INR`.
     Pure, total, fail-safe — any missing/ambiguous input ⇒ `{False, "INR"}`.

3. **Functional currency.** `clients.functional_currency` (CHAR(3), default `'INR'`,
   FK → `currencies.code`). Capability A only: a non-INR functional currency is
   Capability B (not implemented) and is rejected → policy stays inactive/INR.

4. **Provider abstraction (G5).** `RateProvider` ABC (`providers/base.py`) with
   `ManualRateProvider` (reads `fx_rates`), `RBIRateProvider`, `ECBRateProvider`.
   RBI/ECB are abstraction-only — automatic fetching raises `NotImplementedError`
   (deferred to a later phase). `fx_rates` created but **empty** — nothing is fetched.

5. **Exchange rate service.** `ExchangeRateService.get_quote(...)` returns an
   immutable frozen `RateQuote` (Decimal rate, never float). Identity (X→X = 1)
   needs no provider/data; cross-currency delegates to a provider; unknown
   `rate_type` → `ValueError`; missing rate → `RateNotFound`. Depends only on the
   `RateProvider` interface. No posting/journal interaction.

6. **Read-only API.** `GET /api/currencies` (master) and
   `GET /api/currencies/policy?client_id=` (resolved policy) — additive, guarded.

## Database — migration 146 (additive only)

`currencies`, `fx_rates` (`rate NUMERIC(18,8)`, `rate_type ∈ {booking,
gst_notified, customs, closing}`, unique per base/quote/date/type/source),
`firms.multi_currency_entitled`, `clients.functional_currency` +
`clients.multi_currency_enabled`. RLS enabled with read-for-authenticated
policies on the two reference tables. No existing column removed or altered.

## Explicitly NOT in this slice

Journal/kernel FX columns and base-balancing; master `default_currency` columns;
FX gain/loss/rounding accounts; foreign invoices/payments/journals; conversion;
realized/unrealized FX; revaluation; FX reporting. (Phases 2–5.)

## Verification

- Backward compat: full backend suite **2068 passed / 23 pre-existing failures
  (unchanged) / 43 skipped**; existing accounting tests unchanged.
- Live DB (project pbgoeyjvmllrafzavkgx): all existing clients defaulted to
  `functional_currency='INR', multi_currency_enabled=false`; both firms
  `multi_currency_entitled=false`; security advisor reports no new issues.
- 35 new unit tests (`tests/test_multi_currency_phase1.py`).
