# 06b — Multi-Currency Phase 2 (Accounting Foundation) — Implementation

Makes the general ledger **currency-aware** per the frozen architecture
(`06-multi-currency-phase0.md`), building on the Phase 1 foundation. **Additive
and dormant by default** — with the gates off (the default) the engine is
byte-for-byte identical: the full existing accounting suite passes unchanged and
every posting stays INR. No foreign documents, FX gain/loss, revaluation,
settlement, conversion, or reporting changes (those are later phases).

## What changed

1. **GL currency model (migration 147, additive).**
   - `journal_lines` (+): `txn_currency`, `base_currency` (both `CHAR(3)` DEFAULT
     `'INR'`), `exchange_rate NUMERIC(18,8)` DEFAULT 1, `txn_debit`/`txn_credit`
     (BIGINT, foreign minor units), `rate_source`, `rate_type` (DEFAULT `'booking'`,
     CHECK vocabulary), `rate_date`.
   - `journal_entries` (+): `rate_selected_by` (UUID), `rate_overridden`
     (BOOLEAN DEFAULT FALSE), `rate_selected_at` (TIMESTAMPTZ).
   - **The base (INR) amount stays authoritative in `debit_paise`/`credit_paise`**
     — reports read those, unchanged. `ADD COLUMN ... DEFAULT` backfilled existing
     rows to the INR identity without firing row triggers; foreign-amount/rate
     columns stay NULL for history (they are INR: foreign == base) and are
     populated forward by the kernel.

2. **Currency-aware posting kernel (`_create_journal`).**
   - Still validates and balances in **base** (`debit_paise == credit_paise`) and
     still refuses zero/imbalanced entries — unchanged.
   - Stamps immutable per-line currency metadata (G4 dual storage). For every
     current (INR) posting: `txn_currency = base_currency = 'INR'`,
     `exchange_rate = 1`, `txn_debit/credit = debit/credit_paise`,
     `rate_type = 'booking'`, `rate_date = entry_date`, `rate_source = 'identity'`.
   - **Authoritative gate (G2):** a non-INR `txn_currency` or `rate ≠ 1` is refused
     unless an **active** `CurrencyPolicy` is passed — fail-safe to INR. No current
     caller passes foreign values, so this branch is dormant.
   - Entry provenance (`rate_selected_by/overridden/at`) is written only when a rate
     is actually selected, so INR entries keep an unchanged insert payload.

3. **ExchangeRateService integration (Task 3).** `phase2_journal_service.exchange_rate_service(db)`
   exposes the service (Manual provider by default) to the posting pipeline. It is
   **not** invoked for INR (same-currency is the inline identity), so the INR path
   stays zero-overhead. Rates are never fetched automatically; a selected rate is
   frozen on the line and never recalculated (G3).

## Immutability (Task 4/G3)

The new columns are immutable to **exactly the same degree as the existing base
amounts**: the append-only kernel writes each line once and never updates it;
corrections go through reverse + re-post; and `trg_journal_immutability`
(+ `_delete`) freeze a posted `journal_entries` row. (Observation: the live DB
carries no line-level UPDATE trigger — pre-existing drift from migration 055;
re-adding it is a separate hardening, deliberately out of this additive,
no-behaviour-change phase.)

## Invariants preserved (Task 5)

Base debit == base credit; integer paise only (rate is `Decimal`/`NUMERIC`, never
float); posted journals immutable; append-only corrections; date-based FY locks
unaffected; RBAC/tenant isolation unchanged (no query lost its `firm_id` scope);
zero new posting behaviour.

## Verification

- Full backend suite **2076 passed / 23 pre-existing DB-connectivity failures
  (unchanged) / 43 skipped**; 8 new kernel tests (`test_multi_currency_phase2_kernel.py`).
- Live DB (pbgoeyjvmllrafzavkgx): all existing journal lines backfilled to the INR
  identity; **0 imbalanced entries**; all entries inert (`rate_overridden=false`);
  base amounts untouched; immutability triggers intact.
- Feature remains fully dormant unless env `MULTI_CURRENCY_ENABLED` **and**
  `firms.multi_currency_entitled` **and** `clients.multi_currency_enabled` are all on.
