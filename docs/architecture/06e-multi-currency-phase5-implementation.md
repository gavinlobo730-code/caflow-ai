# 06e — Multi-Currency Phase 5 (Reporting, Financial Statements & Production Validation) — Implementation

The final Multi-Currency phase. It adds **read-only** foreign-exchange reporting,
dual-currency visibility on statements/aging, foreign-currency bank accounts, and
production validation — all on top of the Phase 1–4 engine. Nothing here changes the
posting kernel or any historical posting. **Additive, feature-gated, and byte-for-byte
identical for INR-only clients.** Every figure is computed server-side and derived
from posted accounting data; the functional (INR) ledger stays authoritative and all
reports reconcile with the General Ledger.

## Multi-currency lifecycle (end to end)

1. **Enablement (Phase 1):** env `MULTI_CURRENCY_ENABLED` + `firms.multi_currency_entitled`
   + `clients.multi_currency_enabled` (functional currency INR). `resolve_currency_policy`
   is the single decision point; off ⇒ INR-only.
2. **Transaction (Phase 3):** a document is entered in a transaction currency at a frozen
   booking rate; base (INR) components are converted and posted; both are stored.
3. **Posting (Phase 2):** the single kernel stamps immutable per-line currency metadata
   and always balances in base.
4. **Settlement (Phase 4):** receipts/payments at a rate ≠ the booked rate post **realized**
   FX to P&L; `paid_txn` tracks the foreign amount settled (no drift).
5. **Period end (Phase 4/5):** `FXRevaluationService` revalues open foreign AR/AP **and now
   foreign bank balances** at the closing rate (**unrealized** FX), auto-reversed on day 1
   of the next period; idempotent/self-healing via the append-only delta log.
6. **Reporting (Phase 5, this doc):** the statements, aging and the five FX reports present
   the above — never recomputing a historical rate.

## FX accounting principles (unchanged, restated)

- Base-currency-authoritative: `debit_paise`/`credit_paise` (INR) drive every report; foreign
  figures are display memo (`txn_*` + frozen `exchange_rate`).
- Immutable historical rates (G3): documents keep their booked rate; rate changes only affect
  new transactions, settlement (realized) and period-end revaluation (new, auto-reversing).
- Realized vs unrealized: settlement → Realized FX (`fx_realized`); period-end retranslation of
  open monetary items → Unrealized FX (`fx_unrealized`), reversed next day.
- Sign convention: `base_delta_paise > 0` is a **gain**, `< 0` is a **loss** (both realized and
  unrealized), as written by the posting paths.

## Reporting rules (Task 1 & Task 2)

- **General Ledger** gains OPTIONAL transaction-currency visibility: each genuinely foreign line
  carries `txn_currency`, `txn_debit_minor`/`txn_credit_minor`, `exchange_rate`, and the ledger
  sets `has_foreign_lines: true`. INR lines emit no new keys ⇒ an INR ledger is unchanged.
  Implemented additively on `JournalLine` (optional FX memo, defaults None) + a probed source
  select (`sources.py` degrades to base-only if migration 147 is absent) + `builders.ledger`.
- **Trial Balance / Balance Sheet / P&L / Cash Flow** stay base-authoritative — they cannot
  meaningfully aggregate mixed currencies — and automatically absorb the realized/unrealized
  FX P&L accounts. Reconciliation with the GL (incl. foreign activity) is asserted by tests.
- **Customer/Vendor statements** add `base_currency` + `outstanding_by_currency`
  (foreign + base per currency, Σ base == closing balance). Emitted only when the party has
  foreign activity. Shared helper: `services/statement_currency.py`.
- **AR aging** (new client-scoped `GET /api/customers/ar-aging`) and **AP aging**
  (`GET /api/vendors/ap-aging`) add per-foreign-item `txn_currency`, `exchange_rate`,
  `outstanding_foreign_minor`, `outstanding_base_paise` and a `by_currency` breakdown — gated on
  foreign presence, so INR aging is unchanged.

## FX reports (Task 3) — `GET /api/fx-reports/*` (read-only, client-scoped)

`services/fx_reporting_service.py`, all derived from posted data:

1. `/realized` — realized gain/loss per settlement (from `fx_adjustments` kind=realized), dated
   by the settlement journal's `entry_date` (period-accurate), with gain/loss/net + by-currency.
2. `/unrealized` — period-end revaluation runs (from `fx_revaluations`): closing rate, cumulative
   delta, run count, journal + reversal ids per (period, currency, item).
3. `/exposure` — open foreign monetary exposure by currency: AR + bank − AP (foreign + base).
4. `/rate-audit` — every rate used (document bookings + FX adjustments) with full provenance and
   an override count.
5. `/open-balances` — each open foreign document's foreign + base outstanding at the booked rate,
   plus foreign bank balances.

## Dashboard & UX (Task 4)

`apps/web` — an **FX Reports** card in the client accounting workspace's Reports hub
(`app/clients/[id]/accounting/page.tsx`, Reports tab → Foreign Currency) with five views
(Exposure, Realized, Unrealized, Open Balances, Rate Audit), a currency filter, currency badges,
exchange-rate display, coloured gain/loss (FX adjustment) indicators, foreign balance indicators
and revaluation history. The card is shown **only when `GET /api/currencies/policy` reports
active**, so an INR-only client sees no added complexity. (It was a top-level Accounting tab
until the Reports hub landed; the views themselves are unchanged.) New helper `formatMoney(minor, currency, minorUnits)` in
`lib/services/formatting.ts`; new API methods under `api.accounting.fxReports.*`,
`api.currencies.*`, `api.banking.accountBalance`. Zero business logic in the frontend — it only
presents the backend's figures.

## Foreign-currency bank accounts (Task 5)

- `bank_accounts.currency` (migration 150, default INR, FK to `currencies`). A non-INR account is
  allowed only when multi-currency is active for the client and the code is in the master
  (`_guard_foreign_bank_currency` in `routers/banking.py`).
- `GET /api/banking/accounts/{id}/balance` returns the authoritative base balance and — for a
  foreign account — the foreign balance, both **derived** from posted journal lines (no stored
  balance).
- **Period-end revaluation** now covers foreign bank balances: `FXRevaluationService` revalues each
  foreign bank account against its own GL account, keyed by `fx_revaluations.item_ref` (migration
  150) so multiple same-currency accounts never collide. The foreign balance and its carrying base
  are read **only from lines in the account's own currency**, which excludes the INR revaluation
  overlay and keeps the self-healing delta idempotent (same rule AR/AP use by reading the document,
  not the overlay).

## Database — migration 150 (additive)

`bank_accounts.currency` (CHAR(3) NOT NULL DEFAULT 'INR', FK `currencies(code)`);
`fx_revaluations.item_ref` (UUID, nullable — NULL for aggregate AR/AP, the bank GL account for a
bank revaluation) + a supporting index. No existing column removed/altered. Applied to
`pbgoeyjvmllrafzavkgx`; advisors show no new issues; existing RLS still covers both tables.

## Files (Phase 5)

- Backend: `domain/reporting/{model,sources,builders}.py` (GL FX memo, probed); `services/`
  `statement_currency.py` (new), `customer_statement_service.py` (+`ar_aging`, outstanding-by-ccy),
  `vendor_statement_service.py` (+dual-ccy `ap_aging`), `fx_reporting_service.py` (new);
  `routers/` `fx_reports.py` (new), `customers.py` (+`/ar-aging`), `banking.py` (currency guard +
  balance endpoint), `main.py` (register); `models/banking.py` (+currency);
  `domain/currency/fx_revaluation_service.py` (bank revaluation); `migrations/150_*.sql` (new).
- Frontend: `app/clients/[id]/accounting/page.tsx` (FX Reports card in the Reports hub + policy gate), `lib/api/index.ts`
  (fxReports/currencies/accountBalance), `lib/services/formatting.ts` (`formatMoney`).
- Tests: `tests/test_multi_currency_phase5.py` (27 tests across Tasks 1–6).

## User & admin workflow

- **Admin (enable MC):** set env `MULTI_CURRENCY_ENABLED`; mark the firm entitled; enable the client
  (functional currency INR). Seed the required `currencies` and `fx_rates`.
- **User (transact & report):** create foreign documents (Phase 3), settle them (Phase 4 realized
  FX), run period-end revaluation (Phase 4/5). Open Accounting → Reports → FX Reports for exposure, realized /
  unrealized FX, rate audit and open foreign balances; statements and aging show foreign + base
  outstanding. Foreign bank accounts are created from Banks with a currency and revalue at period end.

## Verification

- Full backend suite: **2126 passed / 23 pre-existing DB-connectivity failures (unchanged) / 43
  skipped**. 27 new Phase-5 tests. Frontend `tsc`, `eslint` and `next build` all clean.
- Reconciliation proven with foreign activity: TB balanced, BS balanced, P&L absorbs realized FX,
  cash flow reconciles; statements/aging Σ-by-currency == closing/total; exposure = AR+bank−AP.
- Production validation: INR-only (empty FX reports, unchanged statements), mixed INR+foreign,
  multiple currencies (USD+EUR realized), multi-year (realized in the settlement year), foreign
  bank revaluation (idempotent), tenant isolation on every FX report.

## Known limitations (carried forward / Phase 5)

- **Capability A only:** INR-functional books transacting in foreign currency. Presentation-currency
  translation / consolidation (FCTR/OCI, Capability B) remains out of scope.
- **Correction documents (credit/debit notes) are INR-only** — they have no currency columns, so a
  credit note against a foreign invoice is recorded in INR. Foreign correction documents are a
  future additive change (not required for MVP reporting).
- **Foreign-amount display precision:** the frontend formats foreign amounts at 2 decimals; a
  zero-decimal currency (e.g. JPY) shows trailing zeros. The base (INR) amount is always exact.
- **Rate providers:** manual `fx_rates` only; RBI/ECB feeds are stubbed (Phase 1 abstraction).
