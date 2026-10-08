# 03 — Financial Years & Period Locking

## Indian financial year

The FY runs **1 April → 31 March**. Helper `get_fy_for_date(date)` (`services/period_validation_service.py`) returns the label, e.g. `2025-07-15 → "2025-26"`, `2026-01-10 → "2025-26"`, `2026-04-01 → "2026-27"`. The FY boundary is hardcoded April–March (not configurable per firm).

## Year locking

A firm can lock closed financial years so nothing can post into them.

- Storage: `firms.locked_financial_years TEXT[]` (e.g. `{'2024-25','2025-26'}`), migration `020_lock_financial_year.sql`.
- **Only** `year_lock_service.set_lock(...)` may change it — Partner-gated (`accounting.approve`), PIN-verifiable, audited (`POST /api/accounting/year-lock`).
- A DB trigger `guard_locked_financial_years` (migration `136_protect_year_locks.sql`, **SECURITY INVOKER**) blocks every other session from modifying the array directly, so the lock can't be bypassed by a stray update.
- Read state: `GET /api/accounting/year-lock` → `{locked_financial_years, pin_set}` (the PIN itself is never returned).

## The lock check — `is_fy_locked`

Postgres function `is_fy_locked(p_firm_id uuid, p_date date) -> boolean` derives the FY for `p_date` and tests membership in the firm's `locked_financial_years`.

- Migration `137_fix_is_fy_locked_backend_callable.sql` scopes it by `p_firm_id` alone (the old body also required `get_my_firm_id()`, which is NULL under the service-role backend, so it returned NULL for every backend call). It now `coalesce(...,false)` → always a definitive boolean.

## Enforcement — `validate_posting_date`

`period_validation_service.validate_posting_date(firm_id, date_str)`:
- **Mock mode** (no `SUPABASE_URL`): always allows.
- Calls the `is_fy_locked` RPC. A definitive **`True` blocks** (HTTP 422). `False`/`None` → allow (the function returns a real boolean; `None` means "no value" → treated as not-locked).
- **Fail-closed on error**: if the RPC/DB call *raises*, the posting is **blocked** (422), never silently allowed — accounting integrity over availability.

### Where it runs

Called before mutating on every posting/editing path: sales invoice edit + issue, purchase bill edit + receive, credit-note issue, opening-balance (re)post, manual-journal post, draft approval (`journal_posting_service.post_draft`), and journal reversal. It runs **before** the posting kernel so a locked-year block never partially writes.

### Two kinds of closed

The firm's locked financial year is one of **two deliberate closures**; the other is a client's year-end that has been finalised (migration 289). `public.period_closure_reason` (migration 361) answers both in one call, and the **posting kernel asks it for every entry** (`services/period_lock_service.closure_reason`), so a path that never calls `validate_posting_date` is still refused.

`public.period_lock_reason` adds a third: **a return covering the date has been filed**. That one is asked only where a document that *feeds* a return is written (sales invoices, purchase bills, credit and debit notes, the manual journal, and the edit and delete paths of migrations 266/275/276) and is deliberately **not** in the kernel: GSTR-1 for June is filed on 11 July and GSTR-3B on 20 July, while June's bank reconciliation happens after both, so a kernel refusal would stop every June receipt, payment, bank entry, depreciation charge and payroll accrual from the 11th. `services/period_lock_service.py` holds the Python twins, pinned to the SQL by `tests/test_period_lock_reason_parity_pg.py`.

## Multi-year behaviour

Reports are cumulative over posted `journal_lines`, so balances carry across years correctly (see `08-reporting-engine.md`); opening balances are dated at the client's FY start (see `04-opening-balances.md`). The frontend persists the selected FY and flags non-current years.

## Multi-currency note

FY handling is purely **date-based** and therefore currency-irrelevant — it needs no change for multi-currency (per `06-multi-currency-phase0.md`). Period-end FX revaluation is built (`domain/currency/fx_revaluation_service.py`, behind `routers/fx_revaluation.py`: `POST /api/fx-revaluation/preview` and `/run`) and respects these locks: it calls `validate_posting_date` for the period end **and** for the reversal day (the next day, on which it auto-reverses), and the kernel then asks the client's own year-end closure for each entry it posts. The filed-return branch is deliberately not asked: CGST Rule 34 fixes the rate of exchange at the time of supply, so restating the rupee carrying amount afterwards changes no figure a filed GSTR-1 or GSTR-3B reported.

## Tests

`tests/test_fy_lock_enforcement.py` (validator: blocks locked / allows open / fails-closed on RPC error / allows on NULL; and every posting path blocks in a locked year), `tests/test_year_lock_management.py`, and `tests/test_period_lock_reason_parity_pg.py` (the SQL closure and lock functions against their Python twins).
