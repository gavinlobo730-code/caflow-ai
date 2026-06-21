# Phase 5.2 WS-2 — UAT Catalogue, Seed Data & Sign-off Runbook

**Purpose:** Turn the WS-1-validated business cycles into a User Acceptance
Testing program a CA firm can execute against staging. Each scenario maps to a
real workflow proven in `tests/test_e2e_*.py`, with explicit preconditions,
steps, expected results and acceptance criteria — plus the cross-firm /
cross-assignment isolation cases that matter most for a multi-tenant platform.

**Prerequisite:** staging deployed from `main` (Phase 5.1 merged). Run the UAT
twice — once with `USE_USER_JWT=false` (current default) and once with it `true`
(WS-3) — so isolation is validated at both the app layer and the DB (RLS) layer.

---

## 1. Personas & roles

Authorization model (from `core/authz.py`, `core/permissions.py`):

| Persona | Role | Scope |
|---------|------|-------|
| **Priya** — Firm Partner | `Partner` | **Firm-wide** — every client in the firm |
| **Manish** — Manager | `Manager` | **Assigned book only** — clients assigned to him (cannot see another manager's book) |
| **Arjun** — Article/Executive | `Executive` | Assigned clients only |
| **Reena** — Reviewer | `Reviewer` | Assigned clients (read/review) |
| **Client owner** — Portal contact | `portal_contact` | One (or more) client(s) they're invited to; never staff data |

A **second firm (Firm-B)** with its own Partner is required for cross-tenant tests.

---

## 2. Demo environment & seed-data specification

Seed two firms so isolation is testable. All money in integer paise.

**Firm A (primary)**
- `firms`: Firm-A.
- `users`: Priya (Partner), Manish (Manager), Arjun (Executive), Reena (Reviewer).
- `clients`: **C1 "Acme Pvt Ltd"** (GSTIN `27ABCDE1234F1Z5`, state 27), **C2 "Bharat Traders"** (GSTIN `29PQRST5678K1Z2`, state 29).
- `user_client_assignments`: Manish → C1 only; Arjun → C1 only; Reena → C2 only. (Priya needs no assignment — firm-wide.)
- `chart_of_accounts` for each client: the standard COA incl. system keys
  `ar, ap, revenue, bank, gst_cgst/sgst/igst, gst_input, tds_receivable, tds_payable`
  and a `Purchases`/expense account (see `seed_standard_coa` in the E2E harness for the canonical set).
- `customers` (under C1): "Northwind" (state 27, intra-state), "Sunrise Exports" (state 29, inter-state), both with email.
- `vendors` (under C1): "OfficeSpace LLP" (TDS 194I @ 10%), "CloudVendor" (no TDS).
- A `bank_account` for C1; one portal contact invited for C1.

**Firm B (isolation foil)**
- `firms`: Firm-B; one Partner (Raj); one client **C9 "Zephyr Ltd"** with its own customer/vendor/invoice. Used only to attempt cross-firm access.

> Deliverable: a `scripts/seed_uat.py` (or SQL) that provisions the above is a
> small follow-up; the spec here is the contract. The E2E harness’
> `seed_standard_coa` documents the COA shape.

---

## 3. UAT scenario catalogue

Format: **ID · persona · steps → expected result (acceptance criterion).**

### Sales cycle
- **S1 · Arjun** — Create invoice for Northwind (₹10,000 @ 18% intra-state) → totals CGST ₹90 + SGST ₹90, total ₹118; status **draft**. *(GST split correct; no journal yet.)*
- **S2 · Arjun** — Issue S1 → status **issued**; a balanced journal posts (Dr AR ₹118 / Cr Sales ₹100 / Cr CGST ₹9 / Cr SGST ₹9). *(Trial balance ties out; AR = total.)*
- **S3 · Arjun** — Record full receipt allocated to S1 → invoice **paid**; AR nets to zero; Bank debited ₹118. *(AR cleared.)*
- **S4 · Arjun** — Create invoice for Sunrise Exports (inter-state) → **IGST** only. *(No CGST/SGST.)*
- **S5 · Arjun** — Partial receipt → status **partially_paid**; AR shows the remainder.

### Purchase cycle
- **P1 · Manish** — Create bill for OfficeSpace LLP (₹1,00,000 @ 18%, TDS 194I 10%) → TDS ₹10,000; net payable = total − TDS. *(TDS on taxable only.)*
- **P2 · Manish** — Receive P1 → balanced journal (Dr Purchases + GST Input / Cr Trade Payables + TDS Payable); AP = net payable. *(Trial balance ties out.)*
- **P3 · Manish** — Record vendor payment of the net payable → AP nets to zero; Bank credited. *(See Known Issue K1: the bill status will remain "received".)*

### Customer statements
- **CS1 · Priya** — Generate Northwind statement for the FY → opening + invoices − receipts − credit notes = closing; draft invoices excluded. *(Reconciles to documents.)*
- **CS2 · Priya** — Generate for a mid-year window → prior activity folded into opening; closing unchanged. *(Carry-forward correct.)*

### Compliance
- **CO1 · Manish** — Create a GSTR-3B record for C1 (due 20th) → appears in list with a risk score.
- **CO2 · Manish** — Walk Not Started → In Progress → Ready For Review → Ready To File → Filed → **filed_date stamped**, risk 0. *(Invalid jumps rejected.)*
- **CO3 · Priya** — Firm compliance summary → counts due-this-week / overdue / ready-to-file.

### Portal access
- **PA1 · Priya** — Invite a contact for C1 → status **invited**; e-mail sent. Re-invite same e-mail → idempotent (one contact).
- **PA2 · Priya** — Deactivate the contact → access revoked; resend now blocked (must re-invite).
- **PA3 · Client owner** — Log into the portal → sees ONLY C1 data; never staff/other-client data.

### Online payments
- **OP1 · Arjun** — Create a payment link for an issued invoice's outstanding → link for the exact amount.
- **OP2 · (system)** — Simulate a verified `captured` webhook → receipt auto-created via the engine; AR cleared; Bank debited; link marked **paid**; replay creates no second receipt. *(Real ledger reconciliation.)*

### Banking
- **B1 · Manish** — Create a bank account for C1; import a statement (one credit, one debit) → 2 transactions; re-import the same file → all skipped (dedup).
- **B2 · Manish** — Map a transaction to a GL account → status **matched**; post → balanced journal (money-in ⇒ Dr Bank; money-out ⇒ Cr Bank). *(See Known Issue K2 for the not-found error contract.)*

### Recurring invoices
- **R1 · Priya** — Create a monthly retainer template (start Apr 1) → preview shows Apr/May/Jun 1.
- **R2 · Priya** — Run "Generate now" as of mid-June → 3 **DRAFT** invoices (never auto-issued); re-run generates nothing (idempotent).
- **R3 · Priya** — Pause the template → run is blocked.

### Payment reminders
- **PR1 · Priya** — View AR aging → overdue invoices bucketed (0-30 … 90+).
- **PR2 · Priya** — Send a manual reminder on an overdue invoice → recorded in reminder history; sending on a not-overdue invoice is rejected.

---

## 4. Cross-cutting: tenant isolation & RBAC (critical)

These MUST all deny (the platform runs under service-role; app-layer scoping is
the control until `USE_USER_JWT` is on):

- **I1 · Priya (Firm-A)** attempts to open/issue/cancel/edit any Firm-B invoice,
  bill, customer, vendor, credit note, compliance record by id → **404 / 422**, no change.
- **I2 · Manish (Manager, assigned C1)** lists/opens C2 (assigned to Reena) →
  C2 data not visible (list filtered; by-id get 404). *(Assigned-book isolation.)*
- **I3 · Receipt/payment** cannot allocate to a foreign-firm invoice/bill → **422**.
- **I4 · Online payment** link cannot be created for a foreign-firm invoice → **404**.
- **I5 · Portal contact** for C1 cannot read C2/Firm-B or any staff endpoint.
- **I6 · RBAC** — Executive cannot perform Partner-only actions (e.g. cancel/approve); expect **403**.

Every isolation case above has an automated analogue in `tests/test_e2e_*.py`
and the Phase 5.1 security suites; UAT confirms them through the UI.

---

## 5. `USE_USER_JWT` staging validation (WS-3)

Run the **full catalogue** once with `USE_USER_JWT=true` in staging (see
`PHASE_5_2_E2E_UAT_PLAN.md` → WS-3 runbook). Acceptance: all positive scenarios
still pass, all isolation cases (§4) are denied **at the DB/RLS layer**, and
tokenless paths (scheduler, payment webhook) still function. Roll back via the
flag alone if any legitimate flow is RLS-denied.

---

## 6. Known issues to confirm during UAT (from WS-1)

- **K1 (data-integrity, non-blocking):** A recorded vendor payment posts AP/Bank
  correctly but does **not** change the purchase bill's status (stays
  "received") — `PurchasePaymentIn` has no `purchase_bill_id`. Confirm AP totals
  are right; flag bill-level status as a known limitation.
- **K2 (error contract, cosmetic):** Acting on a non-existent/foreign **bank
  transaction** id returns a 500-class error instead of a clean 404. Isolation
  still holds (no mutation).
- **K3 (minor):** Compliance records created via the API default to status
  `pending`, which is outside the domain state machine — always set an explicit
  status (`Not Started`) when creating.

---

## 7. Sign-off

| Field | Value |
|-------|-------|
| Scenario ID | (e.g. S2) |
| Tester / role | |
| Date | |
| Flag mode | `USE_USER_JWT` = false / true |
| Result | Pass / Fail |
| Evidence (screenshot / ledger figures) | |
| Notes / defect ref | |

**Entry criteria:** staging green on `main`; seed data loaded; all four Firm-A
personas + Firm-B Partner provisioned.
**Exit criteria:** every §3 scenario Pass under both flag modes; every §4
isolation case denied; K1–K3 acknowledged or fixed; no Critical/High defects open.

---

## 8. Per-role action / expected / acceptance matrix

| Role | Representative actions | Expected outcome | Acceptance criterion |
|------|------------------------|------------------|----------------------|
| **Partner (Priya)** | Anything firm-wide: view all clients; approve/post journals; cancel/delete invoices; finalize payroll; manage assignments & billing; run recurring; firm compliance summary | All permitted; sees every client in the firm | Every §3 scenario passes; Partner-only actions (post/approve, delete, billing, payroll-finalize) succeed; cross-firm (Firm-B) denied |
| **Manager (Manish)** | On **assigned** clients (C1): write invoices/bills, receive/pay, reconcile, approve compliance, send reminders, run recurring | Permitted on assigned clients; **cannot** post/approve journals (Partner-only), delete invoices, write billing/practice, or see unassigned C2 | S1–S5,P1–P3,B1–B2,CO1–CO2,R1–R3,PR1–PR2 pass for C1; C2 not visible (I2); accounting.approve / invoice.delete / billing.write → 403 |
| **Executive (Arjun)** | On assigned C1: create/issue invoices, create bills, record receipts, write compliance records | Permitted; **cannot** write accounting (journal), approve, or export reports | Invoice/bill/receipt flows pass; accounting.write / *.approve → 403 |
| **Reviewer (Reena)** | On assigned C2: read invoices/statements/compliance/reports; review | Read/review only; **no** write to accounting/invoice/compliance | Reads succeed; any write → 403; cannot read accounting (Executive+) |
| **Portal Client** | Log in; view own invoices, statement, compliance, reminders; pay online | Sees ONLY its own client's data; never staff data or other clients | PA3, OP*, portal cycle pass; another client's invoice → 404 (ownership gate); staff endpoints → denied |

These map 1:1 to `tests/test_e2e_permissions.py` (role matrix) and the per-cycle
isolation legs in `tests/test_e2e_*.py`.

## 9. Demo data package (executable + repeatable)

The demo dataset is provided as an **executable, deterministic fixture**:
`apps/api/tests/uat_fixtures.py` → `build_demo_dataset(db)` + `demo_callers()`,
verified by `apps/api/tests/test_uat_fixtures.py` (shape, determinism, usability,
isolation). It provisions: two firms; the four Firm-A personas + assignment
scope; clients C1/C2; customers; vendors; a standard COA per client; a fee
invoice; a received bill; a compliance obligation; and a Firm-B isolation foil.
It is the canonical contract a staging seed script mirrors (the same ids each
run make UAT repeatable).

## 10. Per-role sign-off checklist

| Role | Tester | Date | Scenarios executed | Result (Pass/Fail) | Defects | Signature |
|------|--------|------|--------------------|--------------------|---------|-----------|
| Partner sign-off | | | all §3 + Partner-only + N1 | | | |
| Manager sign-off | | | C1 cycles + I2 + 403 checks | | | |
| Executive sign-off | | | invoice/bill/receipt + 403 checks | | | |
| Reviewer sign-off | | | read/review + write-denied checks | | | |
| Portal-client sign-off | | | PA3 + portal cycle + ownership gate | | | |

Run under both `USE_USER_JWT` modes (see WS-3). UAT is complete when all five
roles sign off Pass with no Critical/High defect open.

## 11. Status
WS-2 deliverables: persona/role model, **executable repeatable demo fixtures**
(`tests/uat_fixtures.py`), full UAT scenario catalogue + **per-role
action/acceptance matrix**, cross-tenant/RBAC matrix, the `USE_USER_JWT` staging
tie-in (WS-3), known issues, and a **per-role sign-off checklist**. Ready to
execute once a staging environment is available.
