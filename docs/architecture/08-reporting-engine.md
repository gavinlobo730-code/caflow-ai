# 08 — Reporting Engine

One engine (`apps/api/domain/reporting/`) computes the financial statements from posted `journal_lines`. Pure integer-paise arithmetic. **The arithmetic is one thing (`builders.py`, DB-agnostic); the read path is not**: a report reads the ledger through one of several paths, and which one is decided by the size of its answer (see *Source of truth*).

## Source of truth

The figures have one source: **posted, non-deleted** `journal_entries` with their `journal_lines`, firm- and client-scoped, integer paise. What is *not* single is how a report reads it. There are two ledger sources behind one `LedgerSource` interface and several read paths over them.

**Two sources.** `SupabaseLedgerSource` (`sources.py`) is production. `InMemoryLedgerSource` serves dev, demo and the unit suite from `mock_ledger_source`; it has no SQL functions, so every rule that lives in SQL keeps a Python twin that the same builders run (below). `LedgerSnapshot` (`model.py`) is the immutable value object the replay hands to the builders.

**The rule** (CLAUDE.md, *Reporting performance*): no report may fetch rows proportional to transaction volume. A report reads exactly one of a **trigger-maintained pre-aggregated table** or a **SQL function that returns finished rows**. Fetching raw rows and computing in Python is the degradation target, not a design: it is what a path falls back to when the fast one errors, and what mock mode runs.

### Read paths of `ReportingService`

| Report | Basis | Read path | Migrations | Python twin and parity |
|---|---|---|---|---|
| Trial Balance, P&L, Balance Sheet, one client | accrual | `account_period_balances` monthly buckets (`fetch_buckets`) projected through `balance_cache.project_lines`, plus at most two partial edge months replayed from raw (`fetch_edge_month_entries`) | 227 (table), 228 (triggers), 249 (rebuild) | the full-history replay (`source.snapshot`), which is also the fallback; `tests/test_passbook_read_path.py` |
| P&L and Balance Sheet, "All Clients" | accrual | the same buckets summed across the caller's own clients (`_firm_wide_buckets`, narrowed by `allowed_client_ids`); the read Schedule III's "All Clients" runs on | same | the replay; `tests/test_passbook_firm_wide_scope.py` |
| Trial Balance, P&L, Balance Sheet | cash | **always the replay**: `CashBasisProjector` over the whole base fetch, because the transformation spans documents in different periods. A cash-basis trial balance is inception-to-date only (`CASH_PERIOD_GAP`) | none | none |
| Cash Flow, one client | AS-3 | `public.cash_flow_report` via `db.rpc`: classification needs each entry's legs together, which a monthly bucket has thrown away | 277, 279, latest 434 | `builders.cash_flow`; `tests/test_cash_flow_sql_parity_pg.py`. On an error: the passbook path, then the replay |
| Cash Flow, all clients or mock | AS-3 | the replay (the function is per-client) | none | `builders.cash_flow` |
| General Ledger, one account, paged | cumulative | `public.account_ledger_page` via `db.rpc` when a client and a limit are both given; the running balance runs over the account's whole history and is sliced afterwards | 283, latest 400 | `builders.ledger` over `_entries(account_id=...)`; `tests/test_account_ledger_sql_parity_pg.py` |
| Schedule III (current and prior period) | accrual | `profit_loss` and `balance_sheet` above, twice each | as above | as above |
| Multi-year trend, budgets | accrual | one bucket read, every window projected in memory (`multi_year_trend`, `period_net_by_account`) | 227/228 | the replay |

The switch is `REPORTING_PASSBOOK_MODE`: `off` (replay only), `shadow` (serve the replay, compute the buckets too and log a mismatch) or `on` (serve the buckets, degrade to the replay on any error). It defaults to `on`; the unit suite forces `off` because its fake databases hold no buckets. The Cash Flow SQL function is deliberately *not* routed through that switch, so turning the passbook off does not also turn it off.

### Reports that do not go through `ReportingService`

These answer a different question and each has its own function, for the same reason.

| Report | Read path | Migrations | Python twin and parity |
|---|---|---|---|
| Schedule III ageing (receivables five columns, payables four) | `public.schedule_iii_ageing` (`services/ageing_schedule_service.py`) | 303, 305, 436 | `domain/reporting/ageing.py`; `tests/test_schedule_iii_ageing_parity_pg.py` |
| Closing stock as at a date; by godown and batch; stock ageing | `stock_position_as_at`, `stock_position_detail_as_at`, `stock_ageing_as_at` | 363, 398, 408 | `domain/reporting/stock_position.py` and `stock_ageing.py`; `tests/test_stock_position_parity_pg.py`, `tests/test_stock_ageing_parity_pg.py` |
| AR and AP ageing per document | filters on the generated `outstanding_paise`, so what crosses the wire is what is owed | 278 | none needed |
| Report exports (PDF and Excel) | the server calls the same functions the screens call and renders the dict | none | none |

## Reports (`builders.py`, via `ReportingService` in `service.py`)

| Report | Basis | Notes |
|---|---|---|
| **General Ledger** | cumulative | per-account opening/running/closing (debit-positive); opening = cumulative debit−credit strictly before the window start |
| **Trial Balance** | cumulative to `as_of` | per-account net; `is_balanced = grand_dr == grand_cr` (integer paise) |
| **Balance Sheet** | point-in-time (`as_of`) | assets debit-positive; L/E credit-positive; retained earnings synthesised from income/expense nets |
| **Profit & Loss** | period | income = credit−debit, expense = debit−credit; net profit = revenue − opex |
| **Cash Flow** | period | AS-3 indirect; O+I+F = Δcash = closing−opening (a paise identity) |

Exposed at `GET /api/accounting/{ledger,trial-balance,balance-sheet,profit-loss,cash-flow}`, and beside them `schedule-iii`, `schedule-iii/ageing`, `schedule-iii/ratios`, `schedule-iii/trend`, `budgets`, `cash-book` and `GET /api/report-exports/{report}` for the server-made PDF or Excel. All amounts are raw integer `*_paise`; formatting to ₹ happens in the frontend.

### `period_net_by_account` — N windows, one fetch

Not a report; the primitive a report made of several windows is built on.
`ReportingService.period_net_by_account(firm_id, client_id, windows)` takes
`[(label, start, end), …]` and returns the net movement per account for each,
fetching the chart and the `account_period_balances` buckets **once** and
projecting every window through the same `_passbook_lines` the Trial Balance
uses.

It exists because Budget vs Actuals needs the same accounts over the four
quarters of a financial year, and four `trial_balance` calls would be eight
Singapore-to-Mumbai round trips for one screen. `trial_balance`'s own docstring
had already stated the rule — *adding a period must not add a Mumbai round trip
to a report that already has one* — and Cash Flow was the first caller to need
two windows off one fetch, which is why `_passbook_lines` was split out of
`_passbook_accrual_lines`. This is the same seam used for N.

Windows should be **month-aligned** for the fast path to be exact with no edge
month to replay; `core.ist_clock.fy_quarters` guarantees that for the four
quarters, deriving them from `fy_bounds` rather than restating April. A window
that is not aligned is still correct — `_passbook_lines` replays the partial
edge months — it simply costs more.

**Budgets** (`account_budgets`, migration 376; `services/budget_service.py`;
`GET`/`PUT /api/accounting/budgets`) are the first caller. The screen used to
compute its own actuals in the browser with four unpaged reads of
`journal_lines`, firm-wide — PostgREST truncates at ~1000 rows and reports
nothing, so every variance on a real client was wrong (ACC-06).

## Accrual vs cash

Both bases run through the **same** builders over one source. Cash basis is derived from real allocation links via `CashBasisProjector` (`projector.py`) and is **management reporting only** (IT Act §145) — it never affects GST/ITR filings, which stay invoice-based.

## Financial-year boundaries

Balances are cumulative sums of posted lines, so multi-year carry-forward is correct: GL opening = everything before the window; TB/BS cut at `(None, as_of)`; P&L/Cash-Flow use a period window with opening/closing cash cut at the period edges. Opening balances (`04-opening-balances.md`) enter as a normal posted journal, so they are included automatically.

## Snapshot / cache

The **DB-backed cache is `account_period_balances`**: one row per account per month per client, kept by triggers (migrations 227/228) and rebuilt by 249. It is what turns a read proportional to the ledger into one proportional to the number of months, and it is exact for a month-aligned window (a financial year, a quarter, a calendar month); a window with a partial edge month replays at most two months from raw.

Request-scoped memoizations sit on top (no report-cache *table* beyond the one above):
- `SupabaseLedgerSource._base_cache`: the date-independent base fetch keyed `(firm_id, client_id)`; `snapshot()` re-applies the date filter in memory. A fresh source is built per request (`routers/accounting._reporting_service`).
- `ReportingService._firm_wide_cache`: the accounts and summed buckets for an "All Clients" report, so Schedule III's four calls cost one read.
- `LedgerSnapshot` (an in-memory value object) and `CashBasisProjector._dist_cache` (per-invoice memo).

**`ledger_balances` is dead.** It is a table from migration 003 that nothing writes (no migration creates a trigger or function that does, and nothing in `apps/api` or `apps/web` inserts into it) and that no report reads. Its only reader is the disposability check in `routers/banking.py`, which refuses to delete a bank account's chart row while a `ledger_balances` row names it. Its production row count was **not** checked from here; a person with read access can run `select count(*) from ledger_balances`. A DROP is the end state and moves both sides of the production-fixture comparison at once, so it needs the refresh in `docs/schema-drift.md` (migration 371's decision about `tds_section_limits`); it is not proposed here.

## Customer & vendor ledgers

Party statements read the master `opening_balance_paise` plus their invoices/receipts; in aggregate they agree with the GL control accounts (the opening journal puts the same opening figures into the GL), so each figure is counted exactly once per report.

## Multi-currency note (`06-multi-currency-phase0.md`)

The base (INR) amount stays in `debit_paise`/`credit_paise`, so **every report keeps working unchanged** under multi-currency, and `is_balanced`/`reconciles` remain **base-only** checks. Foreign columns are additive and optional: the General Ledger shows a line's transaction currency and rate where it has one (`builders.ledger`), and the five FX reports (`/api/fx-reports/*`, `services/fx_reporting_service.py`) are read-only views over posted data.

**The two forward hooks this section used to describe did not happen, and are not needed.** Period-end FX revaluation shipped as ordinary posted journals that auto-reverse on day 1 of the next period (`domain/currency/fx_revaluation_service.py`, door `routers/fx_revaluation.py`), written through the posting kernel. A revalued figure therefore reaches every report as posted lines and as buckets, with nothing injected into `ReportingService._lines` or `_cash_balance`, and no as-of or rate dimension was added to any cache key: a report is the posted ledger as at its date, revaluation entry included. What is **not** built is Cash Flow's "effect of exchange-rate changes on cash" line; `builders.cash_flow` has none.

## Tests

`tests/test_reporting_snapshot_cache.py` (memoization), plus report assertions in `tests/test_accounting_journal.py` and the completion/e2e suites (TB/BS/P&L balanced, integer paise, cumulative running balances). The parity tests named in the tables hold each SQL path identical to its Python twin. `tests/test_the_reporting_doc_names_the_read_paths_the_code_uses.py` fails when the code reads through a SQL function or switch this document does not name.
