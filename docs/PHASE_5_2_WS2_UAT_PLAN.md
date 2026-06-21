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

## 8. Status
WS-2 deliverables (this document): persona/role model, demo-firm seed-data
specification, full UAT scenario catalogue grounded in the WS-1-validated
workflows, cross-tenant/RBAC matrix, the `USE_USER_JWT` staging tie-in, known
issues, and a sign-off sheet. Ready to execute once a staging environment is
available. The optional `scripts/seed_uat.py` provisioner is a small follow-up.
