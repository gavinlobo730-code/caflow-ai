# QuickBooks-Style Accounting — Implementation Roadmap

**Status: Phase A & B shipped; Phase 4.1–4.4 + 4.5.1 shipped; Phase 4.5.2 next · Branch:** `claude/admiring-wozniak-0ajya3`

> **Scope changes (permanent, product-owner directive):**
> **Estimates / Quotations** and **Inventory / items master** are **removed from the
> roadmap permanently.** Do not build, scaffold, future-proof, or create any
> dependency toward either module. The forward plan is the **Phase 4.x** list below.

## Why this document

Goal: make the PracticeSync accounting module feel like **QuickBooks Online (QBO)** —
the "Match", "Add", and "Send invoice" experiences CAs love — while staying native to
Indian tax (GST/TDS) and our own rules (integer paise, no auto-submit, zero business
logic in the frontend).

**Market context:** Intuit withdrew QuickBooks Online from India in 2023. Every Indian
CA who relied on QBO is now looking for a replacement. "QuickBooks, but GST/TDS-native
and built for CA practices" is a strong positioning — this roadmap targets exactly that.

**Two product-owner callouts that triggered this plan:**
1. There is no **cash basis vs accrual basis** option anywhere.
2. We should support QuickBooks-style banking **"Match"** and **sending invoices
   directly to clients**.

---

## Grounding facts — what already exists today

The double-entry foundation is already built and tested. This is an *experience-layer*
expansion, not a rebuild.

| Capability | Status | Location |
| --- | --- | --- |
| Double-entry engine (post, reverse, immutability) | ✅ Built | `apps/api/domain/accounting_service.py` |
| Chart of Accounts (hierarchy, 5 account types) | ✅ Built | `apps/api/routers/accounting.py`, `services/coa_seed_service.py` |
| Trial Balance / P&L / Balance Sheet | ✅ Built | `apps/api/domain/accounting_service.py` |
| Sales invoices (GST, Rule 46) + PDF | ✅ Built | `apps/api/routers/sales_invoices.py`, `services/invoice_pdf_service.py` |
| Purchase bills (TDS), payments, receipts, credit notes | ✅ Built | `routers/purchase_bills.py`, `receipts.py`, `purchase_payments.py`, `credit_notes.py` |
| Customer & vendor masters | ✅ Built | migration `049_customer_vendor_master.sql` |
| Auto-journaling for sales/purchase/receipt/payment | ✅ Built | `apps/api/services/phase2_journal_service.py` |
| Bank statement import (CSV/PDF, dedup) | ✅ Built | `apps/api/routers/banking.py` → `POST /api/banking/statements/import` |
| Bank "Match" to existing journal | ✅ Built | `routers/banking.py` → `POST /api/banking/reconcile/match` |
| Bank match **suggestions** (amount ±₹1, date ±3d) | ✅ Built | `routers/banking.py` → `GET /api/banking/reconcile/suggestions` |
| Bank matching-rules table | ⚠️ Table only (not applied) | `routers/banking.py` → `/rules`, table `bank_matching_rules` |
| Fixed assets / depreciation, year-end adjustments | ✅ Built | `routers/fixed_assets.py`, `year_end_adjustments.py` |
| Email infra (Resend) | ✅ Built | `apps/api/services/email_service.py` |
| Invoice email | ⚠️ Overdue reminder only | `email_service.py` → `send_invoice_overdue()` |

**Key precise findings:**
- Accounting is **accrual-only**. The word "accrual" appears only as a *year-end
  adjustment type* (`routers/year_end_adjustments.py`), never as a reporting basis.
- `email_service._send()` does **not** support attachments yet, and there is **no**
  "send the invoice itself to the customer" — only an overdue reminder template.
- The banking **"Match"** half exists (link bank line → existing journal, plus a
  suggestion engine). The **"Add"** half (categorize a bank line into an account and
  auto-create the entry) does **not** exist. Bank rules are stored but never applied.
- Bank import is **manual only** (no live feed).

---

## Gap analysis — QuickBooks vs us

| QuickBooks capability | Us today | Effort |
| --- | --- | --- |
| **Cash/Accrual toggle on all reports** | ✅ Done | `domain/reporting` |
| **Send invoice by email (PDF attached)** | ✅ Done | `email_service.send_invoice_to_customer` |
| Customer statements | ✅ Done (Phase 4.1) | `services/customer_statement_service.py` |
| Automated payment reminders (scheduled) | ✅ Done (Phase 4.2) | `services/collections_service.py`, migration `106` |
| Cash Flow Statement | ✅ Done (AS-3) | `domain/reporting/builders.py` |
| Online "Pay Now" link on invoice | ⏭ Phase 4.6 (optional) | — |
| Bank "Add" (categorize → entry) | ✅ Done (Banking B.2/B.3) | `services/bank_posting_service.py` |
| Auto-apply bank rules | ⚠️ table only | `routers/banking.py` |
| Products/Services (items) master | ❌ **Removed permanently** | — |
| Recurring invoices | ✅ Done (Phase 4.3) | `services/recurring_invoice_service.py`, migration `107` |
| Estimates / quotes → invoice | ❌ **Removed permanently** | — |
| Live bank feed | ❌ manual import | L |
| Receipt capture / OCR | ❌ | L |
| Inventory | ❌ **Removed permanently** | — |
| Multi-currency | ❌ | L |

S = ~days · M = ~1–2 weeks · L = larger.

---

## Priority 1 — Cash basis vs accrual basis toggle

**Recommended first build.** Smallest, safest, highest visibility, and it directly
answers callout #1.

**Approach (mirrors how QuickBooks does it):** keep accrual as the single source of
truth (invoices/bills already post A/R and A/P). Derive the **cash-basis** view at
*report time* — no new tables, no risk to existing entries:

- **Cash-basis P&L:** start from accrual figures, then remove revenue not yet collected
  and expenses not yet paid. Collection/payment status is already tracked via
  `receipt_allocations` (invoices) and `purchase_payments` (bills).
- **Cash-basis Balance Sheet:** drop the open Trade Receivables / Trade Payables that
  represent uncollected/unpaid accrual amounts.

**Implementation sketch:**
- Add `basis: "accrual" | "cash"` query param (default `accrual`) to:
  - `GET` P&L, Balance Sheet, and Trial Balance endpoints in `routers/accounting.py`.
- Push the logic into `domain/accounting_service.py` (frontend stays presentation-only).
- Frontend: a simple Accrual/Cash segmented toggle on the report pages
  (`apps/web/app/accounting/trial-balance`, P&L, balance-sheet, cash-flow).

**India guardrails (cite in code comments):**
- Cash basis is permissible for professionals/individuals under the IT Act
  (e.g. method of accounting under §145 / record-keeping §44AA). Companies must use the
  mercantile (accrual) system per Companies Act §128. Surface a per-client default but
  warn when cash basis is selected for a company/tax-audit client.
- GST is always invoice/accrual-driven for return filing — the cash/accrual toggle is a
  **management-reporting** view only and must **not** change GSTR figures.

**Tests (mandatory per repo rule):** for a part-paid invoice, accrual P&L shows full
revenue while cash P&L shows only the collected portion; all in integer paise.

---

## Priority 2 — Send invoice directly to the client

Directly answers callout #2. The PDF generator already exists; this wires delivery.

**Backend:**
- Extend `email_service._send()` to accept optional **attachments** (Resend supports a
  base64 `attachments` array).
- Add `send_invoice(to, customer_name, invoice_no, amount_str, due_date, pdf_bytes,
  pay_link?)` template.
- New endpoint `POST /api/sales-invoices/{id}/send` — renders PDF via
  `invoice_pdf_service`, emails the customer, and records delivery.
- Add invoice delivery status: `sent_at`, and (later) `viewed_at` via a tracking pixel
  or pay-link open. Status progresses Draft → Issued → **Sent** → (Viewed) → Paid.

**Frontend:** a "Send to client" button on the invoice in
`apps/web/app/accounting/invoices` and the client sales view.

**Prerequisite:** confirm `RESEND_API_KEY` is set in production (today the helper
silently no-ops without it).

**Stretch (Priority 4):** a Razorpay **"Pay Now"** link embedded in the email so the
client can pay by UPI/card/netbanking; webhook auto-creates a *draft* receipt for CA
review (never auto-posted).

---

## Priority 3 — QuickBooks-style banking ("Match" + "Add")

We have "Match"; QuickBooks' magic is the **"Add"** flow and **auto-rules**.

- **"Add" flow:** from an unreconciled bank line, the CA picks a category (CoA account)
  and a payee; we create a **draft** journal (Dr/Cr) and link it to the bank line in one
  action. Reuses the `phase2_journal_service` patterns. **Draft only — a human posts it.**
- **Auto-apply rules:** build a small engine that runs `bank_matching_rules`
  (description pattern + amount range → account) against unreconciled lines to
  pre-fill the suggested category. Still requires CA confirmation.
- **Confidence tuning:** the existing `/reconcile/suggestions` (amount ±₹1, date ±3d)
  can grow payee/description heuristics.

**Hard rule retained:** `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT`. Nothing the bank
flow produces is ever auto-posted.

---

## Phased roadmap

### ✅ Completed to date
- **Cash/Accrual basis toggle** — P&L, Balance Sheet, Trial Balance, Cash Flow (`domain/reporting`).
- **Cash Flow Statement** (AS-3 indirect) + **single reporting engine** consolidation (incl. **Ledger**, Phase 3.4).
- **Send invoice to client** (PDF email via Resend + delivery tracking).
- **Practice-as-Client** foundation + reporting/screen consolidation (Phase 3 / 3.3A).
- **Banking B.0–B.4:** bank feed/import → matching & categorization → posting engine → reconciliation.
- **Draft Journal Workflow** (Phase 3.5): Draft → Approve → Post; banking aligned to draft-first.
- **Customer Statements** (Phase 4.1): read-only account statement + PDF + email + audit.
- **Payment Reminders** (Phase 4.2): overdue-invoice reminders to customers (7/14/21-day cadence, capped; manual single reminder; invoice PDF attached). Collections-only — no journal/statement/GST/cash-flow impact. `invoice_deliveries.kind` + `reminder_settings` (migration `106`); works with the scheduler enabled or disabled.
- **Recurring Invoices** (Phase 4.3): per-customer templates generate **draft** sales invoices via the existing invoice engine (weekly/monthly/quarterly/half-yearly/yearly; month-end clamped). Draft-only — never auto-issue/post/email; idempotent (one invoice per template/occurrence); daily scheduler job + manual run. `recurring_invoice_templates`/`_template_lines`/`_runs` + `client_sales_invoices.recurring_template_id`/`recurring_occurrence` (migration `107`). Separate from `billing_schedules`.
- **Compliance & Engagement Management** (Phase 4.4): operational layer over the canonical `compliance_records` (obligations) + extended `fee_engagements` (lifecycle Draft→…→Closed + preparer/reviewer/partner). Deterministic + idempotent obligation generation from engagements (reuses `compliance_engine` due dates), lifecycle workflow (+Completed), internal-only 7/3/1/overdue escalations (daily job + manual), Practice→Compliance dashboard + calendar projection, full audit+timeline. No filing/portal/OCR; touches no accounting/GST/banking. Migration `108` (additive: extend two tables + idempotency index). `compliance_calendar` is a projection.
- **Customer Portal — Foundation** (Phase 4.5.1): multi-contact + multi-client portal access. `client_portal_users` (invite→activate→deactivate lifecycle) + additive sibling RLS, backward compatible with the legacy `clients.portal_user_id` (migration `109`). `get_current_portal_client()` reuses Supabase auth (no parallel system), with explicit/deterministic active-client selection (`X-Portal-Client-Id`; no implicit switching). CA invite endpoints + client `/me`/`/memberships`/dashboard **shell** (no data yet). Strict client/firm isolation; every CA mutation audited.

### ⏭ Active roadmap — Phase 4 (business modules)
- **Phase 4.5.2 — Customer Portal Data Surfaces** *(next)* — read-only, client-safe views of invoices, statements, payment reminders, and compliance status (reuse existing engines; hybrid RLS-direct + client-authenticated backend endpoints; never expose internal fields).
- **Phase 4.6 — Online Payments** *(optional)* — Razorpay/UPI "Pay Now" + draft-receipt webhook (never auto-posted).

### ❌ Permanently removed (do not build / scaffold / depend on)
- **Estimates / Quotations.**
- **Inventory / Products-Services items master.**

### Deferred / unscheduled (not in Phase 4)
- **Draft Journal Workflow refinement** — incremental polish on the existing Draft → Approve → Post flow (Phase 3.5); not a major phase.
- Auto-apply bank-rules engine (table exists), live bank feeds (Account Aggregator), receipt OCR, cost centers, multi-currency.

---

## Guardrails (non-negotiable, from CLAUDE.md)

- Every rupee value stays **integer paise** — never floating point.
- Every new financial calculation gets a **unit test**.
- GST/ITR logic carries a comment citing the **CGST Act / IT Act** section.
- Bank-flow and any portal-adjacent action stays **draft + CA-confirmed**; never
  auto-submit, never auto-post.
- **Zero business logic in the frontend** — all money/GST/basis math is server-side.

---

## Needed from the product owner

- **Razorpay** (or alternative) account for pay-links — or confirm payments defer to Phase B.
- **Bank-feed** decision for Phase C: Account Aggregator integration vs. keep manual import.
- Confirm **`RESEND_API_KEY`** is live in production.
- A **sample invoice template / brand** to match the "send to client" PDF and email.

## Open decisions

- Cash/accrual default: per-firm, per-client, or per-report? (Recommend per-client
  default, overridable per report view.)
- Payment provider: Razorpay vs Cashfree vs PayU.
- Scope sign-off: this roadmap is **beyond** the "MVP Phase 1" note in `CLAUDE.md` —
  confirm the phase expansion before Phase A build begins.
