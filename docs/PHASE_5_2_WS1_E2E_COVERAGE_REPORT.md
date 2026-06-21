# Phase 5.2 WS-1 — End-to-End Coverage Report

**Scope:** Complete E2E business-cycle test suite — sales, purchases, banking,
customer statements, payment reminders, recurring invoices, compliance, portal
access, online payments. Every cycle includes negative tenant-isolation legs and
(where the cycle touches the ledger) accounting reconciliation.

**Result:** **51 new E2E tests, all passing.** Full backend regression after
WS-1: **1602 passed / 7 skipped / 24 failed** — the 24 are the pre-existing
environmental set (external-service 503s in test_hardening/phase3_gst/mca/tds +
the stale Phase-14 router-mount introspection test) that are green in CI.
**Zero regressions** (+51 vs. the 1551 pre-WS-1 baseline = exactly the new tests).

## Approach

A shared in-memory Supabase/PostgREST double (`tests/e2e_harness.py`) lets the
REAL routers/services run a full lifecycle in sequence against one DB, with
journals posting for real — so AR/AP, trial balance, statements and
reconciliations are asserted as cross-module outcomes, not mocked. `wire_e2e()`
routes the code at the shared DB, flips modules out of mock mode, and neutralises
only incidental I/O (audit log, timeline, locked-period checks, HSN learning,
e-mail transport). Integer paise throughout.

## Coverage by cycle

| Cycle | Tests | Lifecycle driven (real endpoints/engine) | Reconciliation asserted | Isolation leg |
|-------|:----:|------------------------------------------|-------------------------|---------------|
| Sales | 5 | create → issue → receipt; partial; inter-state | journal balanced; AR total→0; Bank Dr | foreign issue 404 (no journal); receipt can't allocate foreign invoice 422 |
| Purchase | 5 | create → receive → payment; no-TDS; inter-state | TDS from taxable; journal balanced; AP net→0; Bank Cr | foreign receive/cancel 404 (no journal) |
| Customer statements | 4 | statement over real invoices/receipts/CN | closing = opening + inv − rcpt − CN; window carry-forward; draft excluded | foreign firm 404 |
| Compliance | 5 | create → list → get → status chain → Filed | VALID_TRANSITIONS enforced; filed_date; risk int | foreign get/update 404 |
| Portal access | 5 | invite → list → re-invite → resend → deactivate → reactivate | status machine; idempotent per email | foreign sees none; can't resend/deactivate 404 |
| Online payments | 4 | issue → create_link → signed capture webhook → receipt | **real** receipt journal Dr Bank/Cr AR; AR→0; replay once | foreign-firm link 404 |
| Banking | 8 | create account → import → dedup re-import → set GL | double-entry direction (in⇒Dr Bank, out⇒Cr Bank); balanced | foreign sees no accounts; can't set GL |
| Recurring invoices | 5 | create_template → preview → run → re-run → pause | deterministic cadence; DRAFT-only; one-occurrence-one-invoice | foreign not visible; can't run |
| Payment reminders | 10 | assess_invoice; send_invoice_reminder; history | aging buckets; outstanding paise; overdue-only gate | foreign remind 404; history empty |

## Findings

### Tenant isolation — NO failures
Every cycle's by-id / by-firm guard held under the service-role (RLS-bypassed)
model: foreign-firm reads and writes were denied (404 / 422 / empty result) with
no state mutation. This confirms the Phase 5.1 remediation holds at the
**workflow** level, not just per-endpoint.

### Accounting correctness — verified
Sales, purchase and online-payment journals balance (Dr = Cr); AR and AP move
correctly through each lifecycle and net to zero on full settlement; the customer
statement reconciles to its documents; bank double-entry direction is correct;
all arithmetic is integer paise.

### Data-integrity / workflow gaps (non-blocking; recommend follow-up)
1. **Vendor payments are not bill-linked.** `PurchasePaymentIn` has no
   `purchase_bill_id`, so a payment posts `Dr Trade Payables / Cr Bank` at the
   ledger but **never moves the bill's status** (it stays `received`). AP is
   correct in aggregate, but bill-level paid tracking is inert through the
   payments API. *(Same root cause as OOS-1; the bill-status writer is
   unreachable.)* Fix: add an optional `purchase_bill_id` to the model and wire
   the existing `_update_bill_payment_status`.
2. **`banking_service._get_txn` error contract.** It assumes `.single()` returns
   empty data on no-row, but PostgREST `.single()` **raises** (PGRST116) on 0
   rows — so a missing/foreign bank transaction surfaces as a 500-class error
   rather than the intended **404**. Isolation is unaffected (nothing is
   mutated), but the error contract is wrong. Fix: use `.limit(1)` + explicit
   check (as the OOS-5 write guards do) or catch the no-row error.

### Minor observations
3. **Compliance status vocabulary mismatch.** `ComplianceRecordIn.status`
   defaults to `"pending"`, which is **not** in the domain state machine
   (`Not Started`, `In Progress`, …). A record created with the model default
   would carry a status outside `VALID_TRANSITIONS` (risk scoring/transitions
   assume the domain vocabulary). Callers currently pass an explicit status;
   recommend aligning the model default to `"Not Started"`.
4. **`assess_invoice.days_overdue` sign.** For a not-due open invoice the field
   is negative (days *until* due), not 0. Correct, but consumers must branch on
   `is_overdue` rather than `days_overdue > 0` only. Cosmetic.

## Coverage notes / complementary suites
- **Banking** — the full post → draft-journal → approve → reconcile chain has
  Phase-3.5 draft semantics and is covered by `tests/test_bank_posting.py` and
  `tests/test_bank_reconciliation.py`. WS-1 adds the cross-module import
  lifecycle, isolation, and the double-entry rule.
- **Online payments** — `tests/test_online_payments.py` covers the gateway
  plumbing (signature, dedupe, idempotency, concurrency) but **mocks the
  journal**; WS-1 adds the real receipt-journal reconciliation.
- **Test artifact (documented):** calling endpoint functions directly bypasses
  FastAPI's `Query()` default resolution, so optional list filters must be passed
  explicitly as `None` (otherwise the unresolved `Query` object becomes a filter).

## Conclusion
All nine business cycles are exercised end-to-end with accounting reconciliation
and negative tenant-isolation. No tenant-isolation failures and no broken
core-accounting workflows were found. Two non-blocking data-integrity items
(bill-link on payments; banking 404 contract) and two minor observations are
logged above for follow-up. **WS-1 is complete and verified;** the validated
lifecycles become the basis for the WS-2 UAT scenario catalogue.
