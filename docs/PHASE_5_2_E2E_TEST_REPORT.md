# Phase 5.2 — End-to-End Test Report

**Deliverable 1 of the Final QuickBooks Roadmap Completion Sprint.**

**Result:** **86 automated E2E tests** (+3 demo-fixture verification tests) across
every business cycle, all passing. Full backend regression with the suite in
place: **1637 passed / 7 skipped / 24 failed** — the 24 are the pre-existing
environmental set (external-service 503s in test_hardening/phase3_gst/mca/tds +
the stale Phase-14 router-mount introspection test) that are green in CI.
**Zero regressions.**

## Method

A shared in-memory Supabase/PostgREST double (`tests/e2e_harness.py`) runs the
**real** routers/services through full lifecycles against one DB, with journals
posting for real — so AR/AP, trial balance, statements and reconciliations are
asserted as cross-module outcomes. Role/permission checks use the same
`core.permissions.can()` the `rbac()` dependency calls. Integer paise throughout.

## Cycle coverage (positive · negative · permission · isolation)

| Cycle | File(s) | Tests | Positive | Negative | Isolation |
|-------|---------|:----:|----------|----------|-----------|
| **Customer (integrated)** | `test_e2e_customer_cycle.py` | 3 | Customer→Invoice→Issue→Reminder→Statement→Receipt→AR cleared (journal balances; statement reflects invoice then receipt; AR→0) | reminder only when overdue (422) | foreign issue/remind/statement → 404 |
| Sales | `test_e2e_sales_cycle.py` | 5 | issue posts Dr AR/Cr Sales+GST; full/partial receipt; IGST vs CGST/SGST | — | foreign issue 404; receipt can't allocate foreign invoice 422 |
| **Vendor** | `test_e2e_purchase_cycle.py` | 5 | bill→receive→payment; TDS from taxable; AP→0; Bank Cr | no-TDS, IGST variants | foreign receive/cancel 404 |
| **Banking (import + double-entry)** | `test_e2e_banking.py` | 8 | account + import; dedup; bank_txn_lines direction | empty import; zero-amount | foreign sees no accounts; can't set GL |
| **Banking (reconcile + reporting)** | `test_e2e_banking_reconcile.py` | 6 | posted txn journal → trial balance; open→reconcile→complete (tie-out) | complete blocked: unreconciled / not-tied-out (422) | foreign can't open (422) or touch session |
| **Compliance (records)** | `test_e2e_compliance.py` | 5 | create→list→get→Filed; filed_date; risk score | invalid transition 422 | foreign get/update 404 |
| **Compliance (engagement chain)** | `test_e2e_compliance_cycle.py` | 4 | engagement→obligation→assign→file→complete; obligation inherits preparer/approver | idempotent generation; invalid transition | foreign assign 404 / transition NotFound |
| **Portal (CA-side)** | `test_e2e_portal_access.py` | 5 | invite→resend→deactivate→reactivate; idempotent | resend-after-deactivate 422; bad email 422 | foreign sees none; can't resend/deactivate 404 |
| **Portal (client-side)** | `test_e2e_portal_cycle.py` | 6 | invoice + statement + client-safe compliance access; ownership gate | — | **other portal client can't see/access; unlinked client sees nothing** |
| **Payments** | `test_e2e_online_payments.py` | 4 | link→signed webhook→receipt→**real** Dr Bank/Cr AR; replay once | failed event → no accounting | foreign-firm link 404 |
| Customer statements | `test_e2e_customer_statements.py` | 4 | reconciles (open+inv−rcpt−CN); window carry-forward | draft excluded | foreign firm 404 |
| Recurring invoices | `test_e2e_recurring_invoices.py` | 5 | template→preview→run (DRAFT only); idempotent | invalid frequency 422 | foreign not visible; can't run |
| Payment reminders | `test_e2e_payment_reminders.py` | 10 | aging buckets; reminder send; history | not-overdue 422; no-email 422 | foreign remind 404; history empty |
| **Permissions (RBAC matrix)** | `test_e2e_permissions.py` | 16 | role×action matrix for all 5 roles; only-Partner-firm-wide | unknown role fail-closed; Client lockout | assignment-scope model asserted |
| Demo fixtures | `test_uat_fixtures.py` | 3 | dataset builds, deterministic, usable | — | cross-firm 404 on the fixture |

Every required cycle from the sprint brief is covered: **Customer, Vendor,
Banking, Compliance, Portal, Payments** — each with positive, negative,
permission, and cross-firm/cross-client isolation legs.

## Findings (no new Critical/High; carried for follow-up)

- **No tenant-isolation failures** across any cycle — cross-firm and cross-client
  access is consistently denied (404/422/empty) with no state mutation, under the
  service-role (RLS-bypassed) model. Confirms the Phase 5.1 remediation holds at
  the workflow level.
- **Accounting correctness verified** — journals balance (Dr=Cr); AR/AP move and
  net to zero on settlement; statements tie to documents; bank reconciliation
  enforces tie-out; integer paise throughout.
- **Data-integrity items (MEDIUM/LOW, non-blocking):**
  - K1 — vendor payments aren't bill-linked (`PurchasePaymentIn` lacks
    `purchase_bill_id`); AP is correct but the bill's paid status doesn't move.
  - K2 — `banking_service._get_txn` / `bank_reconciliation_service._get_session`
    use `.single()`, so a missing/foreign id yields a 500-class error instead of
    404 (isolation unaffected — nothing mutated).
  - K3 — `ComplianceRecordIn` default status `"pending"` is outside the domain
    state machine; callers must pass an explicit status.
  - K4 — `assess_invoice.days_overdue` is negative when not-due (consumers must
    branch on `is_overdue`).

See `PHASE_5_2_WS4_RELEASE_READINESS.md` for the defect register and launch call.
