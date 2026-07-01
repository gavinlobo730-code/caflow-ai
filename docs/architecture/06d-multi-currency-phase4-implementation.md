# 06d — Multi-Currency Phase 4 (FX Accounting) — Implementation

Implements realized and unrealized foreign-exchange accounting (Ind AS 21 / AS 11)
on top of the foreign documents from Phase 3. The GL keeps balancing entirely in
the base (INR) functional currency; every FX difference is an **append-only**
journal through the single posting kernel; historical documents and their booked
rates are never modified. **Feature-gated / dormant by default.**

Out of scope (Phase 5): foreign TB/BS/P&L, presentation currency, translation
reserve (OCI/FCTR), consolidation.

## Realized FX (Tasks 1–3)

A settlement at a rate different from the document's booked rate now posts the
difference to **Realized FX Gain/Loss** instead of being rejected:

- **Receipt:** `Dr Bank` (cash at the receipt rate R1) / `Cr AR` (relieved at the
  invoice's booked rate R0) / `Cr Realized FX Gain` or `Dr Realized FX Loss`.
- **Payment:** `Dr AP` (at the bill's R0) / `Cr Bank` (cash at R1) / FX plug.
- **Partial / multiple / over-payment:** the foreign amount settled is tracked on
  the document (`paid_txn`) so the foreign outstanding is exact; the base is snapped
  to clear exactly on the final settlement — **no rounding drift**. An unallocated
  excess is carried as a customer advance at R1.
- Dedicated paths (`services/receipt_service.create_foreign_receipt`,
  `routers/purchase_payments._create_foreign_payment`); the INR path is untouched.

## Unrealized FX — period-end revaluation (Tasks 4–6)

`domain/currency/fx_revaluation_service.FXRevaluationService.revalue(...)`:

- Revalues open foreign **AR and AP** at the closing rate: `Dr/Cr control account`
  vs `Unrealized FX Gain/Loss`, dated period-end, and **auto-reverses on day 1 of
  the next period** (via the kernel's `reverse_entry`). The sub-ledger and each
  document keep their booked rates — the overlay is temporary.
- **Idempotent / self-healing:** each run posts only the DELTA needed to reach the
  new target (`target − cumulative already posted`, from the append-only
  `fx_revaluations` log). Same rate ⇒ delta 0 ⇒ nothing posted. Rate changed before
  close ⇒ the delta corrects it. Distinct per-run reference numbers keep the
  kernel's idempotency dedup from collapsing a genuine delta.
- **Validations:** missing closing rate, unsupported currency, and a locked/closed
  period (period-end and its reversal day) are rejected with clear messages.
- Foreign **bank-balance** revaluation is structurally supported but has no data
  source until foreign-currency bank accounts exist (deferred master) — a no-op.

## Database — migration 149 (additive)

`fx_realized` / `fx_unrealized` P&L accounts seeded per firm; `paid_txn` on
`client_sales_invoices` + `purchase_bills`; `fx_revaluations` (append-only run log)
and `fx_adjustments` (immutable audit: original/settlement/closing rate, FX source,
journal ref, timestamp, user) with RLS. No existing column removed/altered.

## Audit (Task 7)

Every realized and unrealized difference writes an `fx_adjustments` row (never
overwritten) alongside the append-only FX journal, and the journal itself carries
the Phase-2 rate provenance (rate source, rate-selecting user, timestamp).

## Verification

- Full backend suite **2099 passed / 23 pre-existing DB-connectivity failures
  (unchanged) / 43 skipped**. New: 9 Phase-4 tests + updated Phase-3 tests.
- Realized: FX **gain** ($1000 @80 booked, received @83 → +₹3,000 to Realized FX,
  AR cleared, GL balanced) and **loss** (@78 → +₹2,000 debit); vendor payment loss;
  partial-then-final ($400@82 + $600@85) clears with **no residual paise** and
  ₹3,800 realized gain.
- Unrealized: AR revaluation posts +₹4,000 @84 with auto-reversal; **re-run @84 is a
  no-op (delta 0)**; **re-run @86 self-heals (+₹2,000 delta)**; AP revaluation posts
  the loss; GL balances throughout.
- GL always balances in base; historical documents/rates immutable (asserted).
- Dormant unless env `MULTI_CURRENCY_ENABLED` + firm entitlement + client enablement.
