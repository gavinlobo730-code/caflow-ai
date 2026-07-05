# PracticeSync — Manual Testing Roadmap

> A complete, phase-ordered manual test plan for the PracticeSync platform (AI-first
> practice-management for Indian Chartered Accountants). Built from a full audit of the
> Next.js frontend (`apps/web`, ~161 pages) and the FastAPI backend (`apps/api`, ~88
> routers, ~42 services, scheduler jobs). Execute phases top-to-bottom: later phases
> depend on data created in earlier ones.

---

## 1. Executive Summary

PracticeSync is a large multi-tenant SaaS for CA firms. It spans firm onboarding, RBAC
with per-client assignment scoping and optional MFA, a Lead → Engagement → Signature →
Client → Onboarding lifecycle, full double-entry accounting + banking, the Sales/AR and
Purchase/AP cycles with GST/TDS, Indian compliance & tax tracking (GST, TDS, ITR, MCA,
e-invoice, year-end), a client portal, AI/copilot surfaces (Groq), and a super-admin
platform console.

**Architecture facts that shape testing:**
- **Frontend is a Next.js static export** (`output: "export"`); there is no server-side
  middleware. Route protection is **client-side** (`AuthGuard`). Public pages are
  `/login`, `/signup`, `/onboarding`, `/join`, `/auth`, `/portal`, `/platform`, `/sign`.
- **All money is integer paise** (never float). Every amount on screen is paise/100.
- **Nothing auto-submits to a government portal.** Every GST/TDS/ITR/MCA/e-invoice filing
  path is gated by an explicit "CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT" step. These gates
  are the single highest-severity test target.
- **Two auth audiences:** firm staff (Partner/Manager/Executive/Reviewer) and portal
  clients (separate Supabase identity). Plus a separate **platform admin** allowlist.
- **Integrations:** Supabase (auth + Postgres + storage), Resend (email), Groq
  (`llama-3.3-70b-versatile`, with a mock fallback when no key), Razorpay (payments, with
  a mock provider). A daily in-process scheduler (`ENABLE_SCHEDULER`) drives recurring
  tasks, escalations, invoice/collections sweeps, and compliance generation.

**Testing priorities (in order):** (1) auth + roles + tenant isolation, (2) the
Lead→Sign→Client→Onboarding spine, (3) money correctness (accounting, GST/TDS, invoices),
(4) the no-auto-submit compliance gates, (5) public flows (signing page, payment webhook,
portal) for data-isolation, (6) AI surfaces (advisory-only, no auto-action).

---

## 2. Complete Feature Inventory

### Firm setup & identity
- Sign-up (firm + first Partner), email OTP, firm onboarding, team invitations (`/join`).
- Login with password; **MFA/TOTP** challenge (aal1→aal2); session revocation / force-logout.
- RBAC roles: **Partner > Manager > Executive > Reviewer > Client**; per-client assignment
  scoping (Executive/Reviewer see only assigned clients; Partner is firm-wide).
- **Platform admin** console (super-admin, separate allowlist): firm list/stats,
  suspend/unsuspend/soft-delete/purge (MFA-gated).

### Core CRM / lifecycle
- **Dashboard** (KPIs, next-steps, deadlines), global **Search**, **Notifications** inbox.
- **Clients**: list, create, CSV import, search/filter, archive/restore, delete-with-blockers.
- **Leads pipeline** (kanban): create/edit/delete leads, stage moves, MRR stats.
- **Engagement letters**: templates; Draft → Generated → Sent → Viewed → Signed/Rejected/
  Expired; email send; **resend / copy signing link / change recipient / regenerate link /
  download PDF / send-history**; staff Mark-as-Signed / Reject / Delete.
- **Public signing** (`/sign/?t=`): no-login review, e-sign (typed name + consent), decline,
  expired/invalid handling.
- **Convert Lead → Client**: requires a signed engagement; PAN optional; creates client +
  fee engagement + onboarding workflow.

### Client workspace (`/clients/[id]/…`)
Overview, Accounting (14 tabs), Compliance (GST/TDS/MCA), Tax (computation/filing/26AS),
Documents (versioned), Tasks, Health (7-dimension score + overrides), Relationships,
Knowledge, Instructions, Lifecycle (onboarding/renewals), Sales, Purchases, Payroll,
Fixed Assets, Reports (stub), CoA, Year-End engagement (checklist, adjustments, statements,
notes, review, exports, schedules, XBRL).

### Accounting & banking
Chart of accounts (+ import/export), account groups, journal (draft→posted, reversal),
ledger, trial balance (+ import, accrual/cash), P&L, Balance Sheet, Cash Flow, Schedule III
(+ mapping), **Lock Financial Year** (Partner, PIN), suppliers (TDS), MSME 43B(h), retainer,
budget, receivables aging, fixed assets (SL/WDV depreciation), loans & FD, recurring journals,
bank import/statements/feed, **bank reconciliation** (session tie-out).

### Sales / AR & Purchases / AP
Customers, vendors, **sales invoices** (GST CGST/SGST/IGST, issue/cancel, PDF, email,
resend, reminders), receipts + allocations (TDS), credit notes, customer statements,
**recurring invoices** (draft-only), purchase bills (GST + TDS), purchase payments,
collections/AR aging + reminders, **online payments** (Razorpay links + public hosted page
+ signature-verified webhook).

### Compliance & tax (no auto-submit)
GST tracker + **GSTR-1 / GSTR-3B builders + GSTR-2A reconciliation** (CA-approve →
download JSON → manual upload), TDS (deductions/challans/24Q-26Q/Form 16A), Income Tax
(ITR tracker, advance tax, AIS, notices), 26AS reconciliation, MCA (companies/directors/
annual filings), e-invoice (record IRN), e-way bill, deadlines hub, year-end engagement
(draft→in_review→approved→locked), XBRL.

### Work management
Tasks (status machine, kanban), task templates, recurring tasks, workflows + workflow
builder (+ schedules, approvals, analytics, failures), time tracking, workload/capacity,
reminders, **approvals (maker-checker, MFA-gated)**, team + client assignments, escalations.

### Client portal (separate audience)
Invite contacts (magic link), client login, document requests + uploads, shared documents,
dues/invoices + PDF, statement, payment (stub), compliance status, two-way messages.

### AI features (advisory only, Groq)
Tax-law Q&A assistant, firm/client copilot (V1 + V2 with conversations/feedback),
AI insights (+ cross-client), deterministic intelligence (risk/health/recommendations/
workload/journal-suggestions), memory & triggers (Phase 13), document intelligence
(invoice + government-notice extraction → CA review), rule-based automation engine.

### Firm operations & settings
Practice (firm-as-internal-client provisioning, Partner), billing/revenue ops (Partner),
relationships intelligence, knowledge base (versioned), health, risks, analytics,
audit log (Partner), branding & invoice/email templates (Partner), timeline.

---

## 3. Testing Phases (ordered)

| # | Phase | Depends on | Severity if broken |
|---|-------|-----------|--------------------|
| 0 | Environment & smoke | — | Critical |
| 1 | Authentication & account creation | 0 | Critical |
| 2 | Permissions, roles & tenant isolation | 1 | Critical |
| 3 | Dashboard, navigation, search, notifications | 1 | Medium |
| 4 | Client management | 1,2 | Critical |
| 5 | Lead pipeline (+ edit/delete) | 4 | High |
| 6 | Engagement lifecycle | 5 | Critical |
| 7 | Public signing experience | 6 | Critical |
| 8 | Convert Lead → Client | 6,7 | Critical |
| 9 | Client profile & workspace | 4,8 | High |
| 10 | Documents | 4 | High |
| 11 | Work management | 4 | High |
| 12 | Accounting & financial year lock | 4 | Critical |
| 13 | Banking & reconciliation | 12 | High |
| 14 | Sales / AR cycle | 4,12 | Critical |
| 15 | Purchases / AP cycle | 4,12 | High |
| 16 | Online payments (public) | 14 | Critical |
| 17 | Compliance & tax (no auto-submit) | 4 | Critical |
| 18 | Year-end engagement | 12,17 | Medium |
| 19 | Client portal (public audience) | 4,14 | Critical |
| 20 | AI features | 4 | Medium |
| 21 | Practice & billing (Partner) | 1,2 | High |
| 22 | Notifications & email flows | 1 | High |
| 23 | Imports / exports | 4,12 | Medium |
| 24 | Settings & branding | 2 | Medium |
| 25 | Cross-cutting: errors, loading, empty, responsive | all | Medium |
| 26 | Platform admin (super-admin) | 1 | Critical |

---

## 4. Detailed Checklist per Phase

> Each phase lists **Goal**, **Features**, **Scenarios → Expected**, **Edge cases**,
> **Dependencies**, **Severity**.

### Phase 0 — Environment & Smoke
- **Goal:** Confirm the deployed stack is wired before functional testing.
- **Features:** Backend health, frontend load, integration keys, scheduler flag.
- **Scenarios → Expected:**
  - Open the app URL → login page renders; no console errors; `GET /health` returns
    `{success:true,...}`.
  - Confirm env configured: `SUPABASE_URL`/keys, `RESEND_API_KEY`, `EMAIL_FROM`,
    `FRONTEND_URL` (for signing links), `GROQ_API_KEY` (AI; mock if absent),
    Razorpay keys (payments; mock if absent), `ENABLE_SCHEDULER`.
  - `GET /api/scheduler/health` → reports enabled/last-run/stale state.
- **Edge cases:** Free-tier backend cold start (first call may take seconds — retry once);
  with no `GROQ_API_KEY`, AI returns clearly-labelled mock output (not an error).
- **Severity:** Critical (blocks everything).

### Phase 1 — Authentication & Account Creation
- **Goal:** A new firm can be created and users can authenticate (incl. MFA).
- **Features:** Sign-up, email OTP, firm onboarding, login, TOTP MFA, team invite (`/join`).
- **Scenarios → Expected:**
  1. Sign up (firm name, full name, email) → OTP email arrives → clicking the link lands on
     onboarding → submit firm details (name, email, optional PAN/GSTIN) → firm + first
     **Partner** created; CoA seeded; redirected to dashboard.
  2. Log out, log back in with password → dashboard.
  3. Enable TOTP MFA for the Partner → log out → log in → after password, a **6-digit
     challenge** is required; correct code → dashboard; wrong code → rejected, stays on login.
  4. Partner invites a teammate (email + role) from team admin → invitee uses `/join` link
     → accepts → can log in with the assigned role.
  5. Direct-navigate to a protected route (e.g. `/clients`) while logged out → redirected to
     `/login`. After login you return to the app.
- **Edge cases:** PAN format `AAAAA9999A` and GSTIN format validated at firm creation;
  duplicate firm PAN rejected; a brand-new authenticated user with **no firm** is routed to
  `/onboarding` (not an empty dashboard); an aal1 session with a verified factor must not be
  treated as fully authenticated (it must show the challenge); session revocation / force-logout
  invalidates older tokens.
- **Dependencies:** Phase 0. **Severity:** Critical.

### Phase 2 — Permissions, Roles & Tenant Isolation
- **Goal:** RBAC, per-client assignment scoping, and cross-firm isolation hold.
- **Features:** Role gates, `user_client_assignments` scoping, 404-not-403 on unauthorized.
- **Scenarios → Expected:**
  - Create one user per role. Verify gated actions:
    - **Partner-only:** practice, billing, firm/team/settings writes, client **delete**,
      journal **post/approve**, GST/TDS/ITR **approve**, FY lock, branding writes,
      audit-log read, platform actions.
    - **Manager+:** client create/edit, knowledge write, task delete, accounting write,
      approval approve/reject.
    - **Executive+:** task write, document write (assigned clients), compliance compute,
      workflow instantiate.
    - **Reviewer:** read-only.
  - **Assignment scope:** assign Client A (not B) to an Executive. As that Executive,
    Client B must **not** appear in clients list, global search, or task lists; navigating
    to Client B's URL returns "not found" (404, not a 403 that discloses existence).
  - **Cross-firm:** data from another firm is never visible (every query is firm-scoped).
- **Edge cases:** In mock/dev mode (no Supabase) scoping is permissive — test against a real
  DB; legacy role names (owner/admin/article/staff/viewer) normalize to canonical roles;
  Partners are exempt from assignment scoping (firm-wide).
- **Dependencies:** Phase 1. **Severity:** Critical.

### Phase 3 — Dashboard, Navigation, Search, Notifications
- **Goal:** Home surfaces, navigation rails, search and notifications work and respect scope.
- **Scenarios → Expected:**
  - Dashboard shows client count, pending tasks, filings due, overdue; for a brand-new firm
    it shows an empty/next-steps state (add client, invite team, import, review compliance).
  - Global search (≥2 chars) returns clients/accounts/journals/leads/engagements/tasks/
    documents/DSC with working deep-links; **unassigned clients never appear** for scoped users;
    the internal practice client is excluded.
  - Notifications: list, unread count, mark-one-read, mark-all-read, archive; a user only
    sees their **own** notifications.
- **Edge cases:** Empty states for each KPI; search below 2 chars returns nothing; cold-start
  spinners resolve.
- **Dependencies:** Phase 1. **Severity:** Medium.

### Phase 4 — Client Management
- **Goal:** Full client CRUD, archive/restore, safe delete, CSV import.
- **Scenarios → Expected:**
  - Create a client (name, entity_type, optional PAN/GSTIN, contact, GST filing freq) →
    appears in active list.
  - CSV import → valid rows imported; invalid PAN/GSTIN/entity_type rows reported/skipped.
  - Search by name/PAN/GSTIN/city; filter Active/Archived/All.
  - Archive (Partner/Manager) → leaves active list, appears under Archived; restore → back.
  - **Delete blockers (Partner):** attempt to delete a client that has open compliance tasks /
    documents / engagement letters / invoices / DSC records → blocked with a **human-readable
    list of blockers** and an "Archive instead" path. Delete a client with no linked records →
    soft-deleted.
- **Edge cases:** GSTIN/PAN CHECK constraints (format) enforced at DB; archived client can't be
  re-archived; non-Partner delete → 403; health score may load lazily/fail silently.
- **Dependencies:** Phases 1–2. **Severity:** Critical.

### Phase 5 — Lead Pipeline (+ edit/delete)
- **Goal:** Manage prospects through pipeline stages.
- **Scenarios → Expected:**
  - Create a lead (name, business, email, phone, entity type, expected value) → appears in
    the first stage; "Est. MRR (if all convert)" stat updates.
  - Edit a lead → changes persist; move a lead across stages → position persists on reload.
  - Delete a lead → removed from the board.
  - Engagement actions visible per lead ("Convert to Client" appears).
- **Edge cases:** Stage list is the simplified pipeline set; converted leads are excluded from
  the active board (`is_converted` true / null treated as not-converted); a lead created in the
  browser before save still converts via request-body fallback.
- **Dependencies:** Phase 4. **Severity:** High.

### Phase 6 — Engagement Lifecycle
- **Goal:** Author, send, and manage engagement letters end-to-end (no client login).
- **Features:** Templates; statuses Draft→Generated→Sent→Viewed→Signed/Rejected/Expired;
  email send; resend / copy link / change recipient / regenerate link / download PDF;
  send-history; staff Mark-as-Signed / Reject / Delete.
- **Scenarios → Expected:**
  1. Create a template; create an engagement from it → Draft.
  2. Generate → merge fields render; status Generated.
  3. Send to client (enter/confirm email) → status **Sent**, `sent_at` + `last_sent_at` set,
     a PDF is attached, and the email contains a "Review & Sign Online" link. Lead advances
     to "Engagement Sent".
  4. **Resend** (Send Again) → same subject/PDF/engagement number/**same token**; `resend_count`
     increments; **Last Sent** updates; status unchanged; a "resent" event appears in history.
  5. **Copy Signing Link** → toast "Signing link copied."; the copied URL equals the emailed URL.
  6. **Change Recipient** → save (and optionally Save & Resend) → recipient updated on the same
     engagement; **no new token**.
  7. **Download PDF** → the PDF downloads (matches the emailed copy).
  8. **Generate New Signing Link** → confirm "invalidate previously shared links" → a new token
     is minted (old links die); optionally email the new link.
  9. **Send History** shows Created / First Sent / Last Sent / Sent Count.
  10. Staff **Mark as Signed** / **Reject** / **Delete** behave per status rules (signed letters
      cannot be deleted).
- **Edge cases:** Email-delivery failure → letter stays in current status with a **friendly**
  message (never `RESEND_API_KEY`/provider internals); resending an **expired** letter requires
  a confirm; deleted/signed letters block resend/regenerate; very long letter HTML still renders
  in the PDF (₹ becomes "Rs." in the PDF only).
- **Dependencies:** Phase 5. **Severity:** Critical.

### Phase 7 — Public Signing Experience (no login)
- **Goal:** A prospect can review and e-sign without an account; security holds.
- **Scenarios → Expected:**
  - Click the email's "Review & Sign Online" (or the copied link) → the **public `/sign` page
    opens without redirecting to login**; the letter renders (sandboxed), firm name shown.
  - First open transitions Sent→**Viewed** (recorded with IP).
  - Enter full name + tick consent → **Accept & Sign** → success confirmation; status becomes
    **Signed**; the linked lead advances to "Engagement Signed".
  - **Decline** with optional reason → status Rejected; the lead is handed back to the pipeline.
  - Invalid/garbage token or a regenerated-away (old) token → "link is invalid or has expired".
  - An **expired** letter shows an expired banner and cannot be signed.
- **Edge cases:** Token is the only credential (unguessable, exact-match, URL-safe, not
  truncated/hashed); a genuine backend failure must surface as a distinct "temporarily
  unavailable" (503) message, **not** a misleading "invalid link"; idempotent re-sign returns the
  confirmed state; the page must NOT show the firm's nav/sidebar.
- **Dependencies:** Phase 6. **Severity:** Critical.

### Phase 8 — Convert Lead → Client
- **Goal:** A signed lead becomes a client with onboarding, without losing data.
- **Scenarios → Expected:**
  - Try to convert a lead with **no signed engagement** → blocked (409, "A signed engagement
    letter is required…").
  - Convert a lead **with** a signed engagement, **leaving PAN blank** → succeeds; client
    created; fee engagement created from the signed letter's fee/service type; onboarding
    workflow + tasks created; lead marked converted and removed from the board; success screen
    links to onboarding.
  - Convert **with** a valid PAN → stored uppercased; with an **invalid** PAN → friendly
    "PAN format is invalid…" (no DB error leaks); with/without GSTIN both work.
- **Edge cases:** Multiple signed letters → the most-recently-signed is used (with a warning);
  a DB error during creation returns a friendly generic message (no SQL/constraint text);
  duplicate PAN across clients is allowed (no unique constraint).
- **Dependencies:** Phases 6–7. **Severity:** Critical.

### Phase 9 — Client Profile & Workspace
- **Goal:** The per-client workspace surfaces and sub-tabs load and scope correctly.
- **Scenarios → Expected:**
  - Open a client → Overview shows health score, open/overdue tasks, upcoming deadlines,
    pinned instructions, activity timeline.
  - Navigate every sub-tab (Accounting, Compliance, Tax, Documents, Tasks, Health,
    Relationships, Knowledge, Instructions, Lifecycle, Sales, Purchases, Payroll, Fixed Assets,
    CoA, Year-End) → each loads, shows data or an empty state, no crashes.
  - **Health** tab: 7 weighted dimensions, grade band, history, alerts; Partner can override a
    dimension with an expiry.
  - **Relationships** tab: add a role (director/shareholder/etc.); cross-client matches (same
    PAN across clients) are flagged for confirm/reject.
  - **Lifecycle** tab: onboarding workflow/tasks and service renewals.
- **Edge cases:** Health is computed monthly (recomputes on demand); compliance calendar seeds
  on first open; `/clients/[id]/reports` and `…/year-end/xbrl` are **stubs** ("Coming…")—verify
  they don't error; relationships intelligence is largely mock data.
- **Dependencies:** Phases 4, 8. **Severity:** High.

### Phase 10 — Documents
- **Goal:** Document storage, versioning, expiry alerts (firm vault + per-client).
- **Scenarios → Expected:**
  - Upload a document to a client (label, category, optional expiry) → appears in the list;
    download works; delete works.
  - Upload a new file with an **existing label** → prompted "New version of X?" → version
    increments; history preserved.
  - Set an expiry within 60 days → an expiry alert/badge shows.
- **Edge cases:** >50 MB rejected; filenames sanitized; storage path isolated by UUID;
  category enum enforced.
- **Dependencies:** Phase 4. **Severity:** High.

### Phase 11 — Work Management
- **Goal:** Tasks, templates, recurring tasks, workflows, time, workload, approvals.
- **Scenarios → Expected:**
  - **Tasks:** create/assign; move through `todo → in_progress → waiting_client/review_required
    → completed`; cannot revert from completed; overdue shown red; reassignment notifies old +
    new assignee; kanban groups render.
  - **Templates:** create a template; instantiate to a task (tags applied; timeline logged).
  - **Recurring tasks:** create a config (frequency, next due, assignment rules); run generation
    (manual `/generate` or scheduler) → one task created; **running twice the same day creates no
    duplicate** (idempotent).
  - **Workflows:** instantiate a standard workflow (e.g., GST Monthly) → linked step-tasks
    created; workflow steps that say "CA REVIEW REQUIRED" must not auto-file; schedule a workflow
    (cron) and verify the runner fires it; analytics/failures populate.
  - **Time tracking:** start timer (auto-stops the previous), stop, manual entry, export CSV/XLSX.
  - **Workload:** capacity (40h/10 tasks defaults), utilisation %, overloaded/underutilised flags;
    Manager+ edits capacity.
  - **Approvals (maker-checker):** Executive raises a request (e.g., user_create / role_change /
    assignment / CoA change); Manager+ approves/rejects; **approve/reject require MFA**; requester
    can cancel.
- **Edge cases:** circular task dependencies are **not** auto-detected (verify UI guards);
  self-approval is not blocked in code for approve (only for cancel) — verify policy expectation;
  reminders are a **stub** (no real email/SMS dispatch yet); scheduler is single-process only.
- **Dependencies:** Phase 4. **Severity:** High.

### Phase 12 — Accounting & Financial-Year Lock
- **Goal:** Double-entry correctness, reporting, and period locking.
- **Scenarios → Expected (per client workspace → Accounting):**
  - Post a balanced journal (Dr = Cr) → posted; an **unbalanced** entry is rejected (shows the
    difference) and cannot post.
  - Reverse a posted entry → a linked reversal is created; the original stays immutable.
  - Ledger shows opening/running/closing balances (computed server-side); Trial Balance balances
    and toggles accrual/cash; P&L and Balance Sheet render and tie out.
  - **Lock FY (Partner, PIN):** lock a year → posting into that year is rejected with a clear
    message; unlock requires the correct PIN.
  - CoA import (Tally/Busy/Zoho/QB/Excel CSV): validates type enum, dedupes by code; CoA export
    downloads CSV. Trial-Balance import is **intentionally gated off** — no migration adds the
    `chart_of_accounts.opening_balance_dr_paise`/`opening_balance_cr_paise` columns it needs, and
    the reporting engine doesn't consume them either, so the wizard checks availability on load and
    shows a clear "not available yet" message with a link to Chart of Accounts instead of running a
    wizard that would fail every row (verify the disabled-state message renders, not the wizard).
- **Edge cases:** posting needs Partner approval (no auto-post); locked-period and unbalanced
  attempts must fail with friendly messages; very large amounts (crores → paise) must not lose
  precision; some firm-level `/accounting/*` pages **redirect into the client workspace** (verify
  the redirect, not a 404); retainer/budget/recurring-journals persist in **localStorage**
  (clearing the browser loses them — verify expectation).
- **Dependencies:** Phase 4. **Severity:** Critical.

### Phase 13 — Banking & Reconciliation
- **Goal:** Import statements, match, and reconcile to a tie-out.
- **Scenarios → Expected:**
  - Import a bank statement (CSV/XLSX, ≤10 MB) → transactions load; re-importing the same file
    does **not** duplicate (dedupe).
  - Open a reconciliation session (opening/closing balances) → mark items reconciled → complete
    only when opening + deposits − withdrawals ± adjustments = closing; an out-of-balance session
    cannot complete; export the reconciliation CSV.
  - Posting a bank transaction creates a journal entry (human-initiated, never auto).
- **Edge cases:** completed sessions are immutable; transactions already reconciled elsewhere show
  as exceptions; matching-rules/suggestions endpoints exist but may be **not wired** to the UI.
- **Dependencies:** Phase 12. **Severity:** High.

### Phase 14 — Sales / AR Cycle
- **Goal:** Invoice → issue → pay, with correct GST and AR.
- **Scenarios → Expected:**
  - Create a customer (GSTIN validated); create a sales invoice with HSN/SAC lines → GST computes
    **intra-state CGST+SGST** vs **inter-state IGST** correctly (integer paise); number is
    `SINV-{FY}-{seq}`.
  - **Issue** (draft→issued) posts the journal atomically; only **drafts** are deletable.
  - Record a **receipt** with allocations (and TDS) → invoice `paid_paise` updates; status →
    partially_paid → paid; re-allocation does not inflate paid amounts.
  - Issue a **credit note** (GST reversal), linked to an invoice or standalone.
  - Email an invoice PDF; **resend** appends a new delivery record (history kept); send a
    **statement** PDF; send overdue **reminders** (≥7-day cadence).
  - **Recurring invoices** generate **drafts only** (never auto-issue/email); pause/resume.
- **Edge cases:** over-allocation beyond invoice total → 422; allocating to a **foreign** client's
  invoice → 422; duplicate invoice number not auto-prevented (review); email failure → delivery
  "failed" + friendly message; issued-but-unposted invoices are detectable via a maintenance
  endpoint and repostable.
- **Dependencies:** Phases 4, 12. **Severity:** Critical.

### Phase 15 — Purchases / AP Cycle
- **Goal:** Vendor bills with GST + TDS, and payments.
- **Scenarios → Expected:**
  - Create a vendor (TDS section/rate); create a purchase bill → GST computed; **TDS deducted on
    the taxable value** per §194C/194I/194J; `net_payable = total − tds`; journal posts (Dr
    Expense / Cr Payables + Cr TDS Payable).
  - Record a purchase payment (`VPMT-{FY}-{seq}`) → vendor outstanding decreases.
- **Edge cases:** TDS cannot exceed taxable; vendor bill numbers are user-supplied (duplicates not
  blocked); overpayment to a vendor is allowed (no cap).
- **Dependencies:** Phases 4, 12. **Severity:** High.

### Phase 16 — Online Payments (public)
- **Goal:** Hosted payment link + webhook capture without parallel accounting.
- **Scenarios → Expected:**
  - Create a payment link for an outstanding invoice (amount = exact balance); creating again for
    the same invoice returns the existing open link (idempotent); email the link.
  - Simulate a Razorpay `payment.captured` webhook with a **valid signature** → a receipt is
    created via the receipt engine (no duplicate journal); invoice moves toward paid.
  - **Invalid signature** → 400 "Webhook rejected" (no internal details); **replay** the same
    event → idempotent (no second receipt).
- **Edge cases:** webhook is **public** (signature-verified, no auth); partial capture is not a
  scenario (exact-outstanding model); paying then cancelling the invoice needs manual reversal;
  `POST /portal/self/invoices/{id}/pay` is currently a **stub (501)** — verify.
- **Dependencies:** Phase 14. **Severity:** Critical.

### Phase 17 — Compliance & Tax (NO AUTO-SUBMIT)
- **Goal:** Verify every filing path computes correctly and **never** auto-submits; the CA-review
  gate is mandatory before any JSON/portal action.
- **Scenarios → Expected:**
  - **GSTR-1:** build from invoices → classify B2B/B2CS/B2CL (₹2.5L threshold) → validate →
    **CA Approve** → only then can JSON download; "Mark as Filed" requires a manually-entered ARN.
  - **GSTR-3B:** compute outward tax + ITC (Rule 36(4) 105% cap flagged) + IGST cross-utilization →
    CA Approve → JSON; mark filed with ARN.
  - **GSTR-2A reconciliation:** upload purchase register + 2A CSVs → matched / mismatch / missing /
    extra with ±3-paise tolerance; export Excel; footer reiterates "does not auto-submit".
  - **TDS:** add deductions (auto-rate by section), challans, returns (24Q/26Q), Form 16A; warnings
    state filing is done manually on TRACES.
  - **Income Tax:** ITR tracker (audit vs non-audit due dates auto-filled by entity type), advance
    tax installments (15%/45%/75%/100%), AIS ingest, notices; "Mark Filed" modal warns "does NOT
    auto-submit".
  - **26AS reconciliation:** upload, parse, reconcile vs books; variance triggers an AI insight.
  - **MCA:** companies (CIN format), directors (DIN/KYC), annual filings (AOC-4/MGT-7); no
    auto-submit to MCA21.
  - **E-invoice:** record an IRN **after** generating it on the IRP portal (64-char IRN + ack);
    nothing is generated by PracticeSync.
  - **Deadlines hub:** triage across all clients; mark-filed inline with ARN; demo/simulate filing
    is non-binding.
- **Edge cases:** confirm **every** download/file action is blocked until CA approval; due dates
  match the rules (GSTR-1 11th, GSTR-3B 20th, GSTR-9 31 Dec, advance-tax dates, TDS quarter-end+1m);
  PAN/GSTIN format validated; some sub-pages use mock/seed data — verify real vs placeholder.
- **Dependencies:** Phase 4. **Severity:** Critical (regulatory).

### Phase 18 — Year-End Engagement
- **Goal:** Year-end workflow from draft to locked.
- **Scenarios → Expected:** create an engagement for an FY; walk checklist, adjustments,
  financial statements, notes, schedules; transition **draft → in_review → approved → locked**
  with role gates (Manager approves, **Partner locks**); exports available; locked is terminal.
- **Edge cases:** several sub-pages are partially implemented — verify load + role gates rather
  than deep output; XBRL likely stub.
- **Dependencies:** Phases 12, 17. **Severity:** Medium.

### Phase 19 — Client Portal (public audience)
- **Goal:** A client can self-serve; isolation is absolute.
- **Scenarios → Expected:**
  - CA invites a contact email for one client → magic-link email → client logs in → portal loads
    (requests, shared docs, reports, dues, messages).
  - Client fulfils a document request (upload) → CA sees "fulfilled".
  - Client sees only **their** dues/invoices (canonical AR in paise) and can download their own
    invoice PDF; two-way messages work.
  - **Isolation:** a client supplying another client's id (header) → 403; another firm's data is
    never reachable.
- **Edge cases:** multi-client contact → must choose a client (409 until chosen); re-invite
  reactivates a deactivated contact; dues tab UI may be a placeholder though the API returns data;
  payment from portal is a **stub (501)**; invite magic links have no explicit TTL.
- **Dependencies:** Phases 4, 14. **Severity:** Critical (data isolation).

### Phase 20 — AI Features
- **Goal:** AI is **advisory only** and correctly scoped; nothing auto-acts.
- **Scenarios → Expected:**
  - **Assistant** (`/ai-assistant`): ask a GST/ITR/TDS question → answer with act/section source;
    chat history persists for 24h in the browser and auto-clears; "New chat" clears it; no vendor
    branding shown.
  - **Copilot** (firm + client): answers use live firm/client context; "suggested actions" are
    links only (no execution); client-scoped copilot must not leak other clients' data.
  - **AI insights / intelligence:** risk/health/recommendation/workload scores are **computed
    deterministically** (no hallucination); acknowledge/dismiss clears them; journal-suggestion
    "approve" creates a **draft** (Partner still posts).
  - **Document intelligence:** upload an invoice → extracted fields with `requires_review=true`
    (creates nothing); upload a government notice → creates a notice + task in **ca_approved=false**
    until a CA approves.
  - With **no `GROQ_API_KEY`** → mock output clearly labelled "review manually".
- **Edge cases:** copilot V2 intelligence endpoints and recommendation-action execution are
  **stubs**; Groq is text-only (no real OCR/vision); suggested-actions use brittle keyword matching.
- **Dependencies:** Phase 4. **Severity:** Medium.

### Phase 21 — Practice & Billing (Partner)
- **Goal:** Firm-as-internal-client provisioning and revenue operations.
- **Scenarios → Expected:**
  - **Practice:** `GET /api/practice` shows can_provision; provision (idempotent) → an internal
    client id is created and is **excluded** from normal client lists; Partner can maintain
    PAN/GSTIN/state.
  - **Billing:** create a billing schedule (retainer/one-time/package × cadence, amount, GST) →
    preview-run (dry) → run → **draft** invoices generated; idempotent (one invoice per
    schedule/period); AR aging + collections dashboard + reminder cadence (7/14/21, capped);
    unbilled-work view; staff cost-rate capture.
- **Edge cases:** Partner-only throughout (others 403); internal client excluded from payroll;
  cost-rate "profitability" is display-only (no margin analysis yet).
- **Dependencies:** Phases 1–2. **Severity:** High.

### Phase 22 — Notifications & Email Flows
- **Goal:** Every transactional email sends and fails gracefully.
- **Scenarios → Expected:** trigger each email — engagement letter, invoice issued/overdue,
  statement, payment link, collections reminder, portal invite, task assignment/overdue,
  document request, compliance notice — and verify it arrives with the right content/attachment;
  delivery history is recorded.
- **Edge cases:** with a missing/invalid `RESEND_API_KEY`, the user sees a **friendly** message
  while the **full** provider error (status/code/body) is logged **server-side only** — no env var,
  provider name, or stack trace ever reaches the UI; invalid recipient → validation error.
- **Dependencies:** Phase 1. **Severity:** High.

### Phase 23 — Imports / Exports
- **Goal:** All CSV/Excel import and export paths.
- **Scenarios → Expected:** clients CSV, CoA import/export, trial-balance import, sales/customers/
  receipts import (client Sales tab), vendors/purchase import, Tally migration, GST/2A CSVs,
  Schedule III / statements Excel export, time export, year-end exports → each validates, reports
  bad rows, and round-trips amounts as integer paise.
- **Edge cases:** malformed CSV (embedded quotes/newlines), header variants, duplicate rows
  (upsert/skip), unbalanced TB import (allowed with a visible warning).
- **Dependencies:** Phases 4, 12. **Severity:** Medium.

### Phase 24 — Settings & Branding
- **Goal:** Firm branding and templates apply across documents/emails.
- **Scenarios → Expected:** upload a logo (PNG/JPG/SVG/WebP ≤5 MB); set brand colors (hex); set
  invoice prefix/sequence/start number; choose an invoice template; edit email templates →
  verify they reflect on generated invoices/emails.
- **Edge cases:** Partner-only writes; invoice sequence seeding is atomic; defaults apply when
  unset; team "module permissions" matrix is **localStorage-only** (not server-enforced) —
  verify expectation.
- **Dependencies:** Phase 2. **Severity:** Medium.

### Phase 25 — Cross-cutting: Errors, Loading, Empty, Responsive
- **Goal:** Consistent UX states everywhere.
- **Scenarios → Expected:** every list has a loading skeleton, a meaningful empty state, and a
  readable error banner (never a raw stack/JSON/SQL); forms validate before submit; destructive
  actions confirm; the app is usable on a phone (mobile nav drawer, tables scroll/stack).
- **Edge cases:** backend cold-start spinners resolve; a 500 still returns CORS-safe JSON (not an
  opaque "Failed to fetch"); no PostgreSQL/constraint text ever appears to users.
- **Dependencies:** all. **Severity:** Medium.

### Phase 26 — Platform Admin (super-admin)
- **Goal:** Cross-tenant console is correct and tightly gated.
- **Scenarios → Expected:** as a non-admin, `/platform` self-gates and redirects to `/`; as an
  allowlisted admin, view firm list/stats/detail/users; **suspend** a firm (reason) → its users'
  sessions are revoked and they cannot use the app; unsuspend restores; soft-delete and permanent
  purge work; **suspend/delete/purge require MFA (aal2)**; all actions are audited.
- **Edge cases:** platform powers are orthogonal to firm RBAC; unauthorized access returns 404
  (no existence disclosure).
- **Dependencies:** Phase 1. **Severity:** Critical.

---

## 5. End-to-End Business Journeys

> Run these as continuous, multi-phase scripts — they are the real product narratives.

1. **Prospect → paying client (the spine).**
   Sign up firm → create lead → create engagement from template → generate → **send email** →
   open the email's link in a **private/incognito window** (no login) → review → **e-sign** →
   confirm status Signed and pipeline "Engagement Signed" → as staff, **Convert to Client**
   (leave PAN blank) → onboarding workflow created → complete onboarding tasks → raise a fee
   invoice → email it → record a receipt → client appears with health score and timeline.

2. **Resend / re-share without breaking links.**
   Send an engagement → copy the link and "send via WhatsApp" (paste in a second incognito tab) →
   **Resend** the email → confirm the **old tab's link still works** → **Change Recipient** to a
   second email and resend → finally **Generate New Signing Link** → confirm the **old links now
   fail** and the new one works.

3. **Monthly GST close (no auto-submit).**
   Import sales/purchases for a client → build GSTR-1 → CA approve → download JSON → reconcile
   GSTR-2A → compute GSTR-3B (verify ITC 105% cap) → CA approve → mark filed with ARN →
   confirm **at no point** did the app submit to a portal.

4. **Accounting period close.**
   Post journals across a year → run Trial Balance / P&L / Balance Sheet → reconcile the bank →
   **Lock the FY (PIN)** → attempt a back-dated posting → confirm it is rejected.

5. **Client self-service.**
   Invite a client to the portal → client logs in via magic link → uploads a requested document →
   views dues → downloads their invoice PDF → messages the CA → CA sees the reply; confirm the
   client cannot see any other client/firm.

6. **Online collection.**
   Issue a fee invoice → create a payment link → email it → simulate a captured webhook → confirm
   a receipt is recorded once (replay-safe) and the invoice moves to paid.

7. **Team governance (maker-checker + MFA).**
   Executive raises a role-change request → Manager approves (MFA challenge) → verify the change
   applied and audited; Partner force-logs-out a user → that user is signed out everywhere.

---

## 6. High-Risk Areas (test hardest)

- **No-auto-submit compliance gates (Critical/regulatory).** Any path that downloads filing JSON
  or marks a return filed must require explicit CA approval first. A regression here has legal
  consequences.
- **Public endpoints & isolation (Critical).** `/sign` page, the payment **webhook** (signature +
  replay), and the **client portal** (per-client/firm scoping). The signing flow specifically had
  prior bugs: auth-redirect to login and a missing service-role grant that masked as "invalid link".
- **Money math (Critical).** Integer-paise everywhere; GST intra/inter-state split; TDS on taxable
  value; receipt allocations not inflating `paid_paise`; double-entry balance; FY lock.
- **RBAC + assignment scoping (Critical).** Unassigned clients must be invisible (404, not 403) to
  scoped users; Partner-only gates (delete, post/approve, practice, billing, platform).
- **MFA enforcement (High).** aal1 vs aal2; approvals and platform destructive actions require aal2;
  session revocation invalidates old tokens.
- **Error-message hygiene (High).** No PostgreSQL/constraint/stack/JSON or provider/env-var text
  ever reaches users (engagement email, convert-to-client, and all email flows were hardened here).
- **Scheduler idempotency (High).** Recurring tasks/invoices/compliance generation must not
  duplicate on re-run; single-process only.
- **localStorage-backed features (Medium).** Retainer, budget, recurring journals, AI chat history,
  team module-permissions — data loss on browser clear; permissions not server-enforced.

---

## 7. Nice-to-have UX Improvements (noticed in code)

- **Regenerate-link UX:** uses browser `confirm()`/inline panel; a single modal showing the old vs
  new link state would be clearer.
- **Portal "Dues" tab:** backend returns data but the UI shows a placeholder — wire it through.
- **Copilot "suggested actions":** keyword-matched from the response (brittle); make them real
  deep-links/actions.
- **Duplicate invoice/bill numbers:** allowed silently — a soft warning would prevent data-quality
  issues.
- **Unallocated receipts** accumulate with no surfacing — add a "cash on account" view.
- **Expired payment links / engagement letters** are never cleaned up — a status sweep + filter
  would help.
- **Reminders module** is a stub (no real dispatch) yet appears actionable — hide or label until wired.
- **Team module-permission matrix** is localStorage-only and not enforced — either enforce
  server-side or clearly mark as cosmetic.
- **Friendlier empty states** with first-action CTAs on the many list pages that currently show
  bare "No data".

---

## 8. Features that appear Incomplete or Hidden

> Verify each: does it error, no-op, or show "coming soon"? Decide ship/hide per release.

- **Stubs / placeholders:** `/clients/[id]/reports` ("Coming in Phase 1"), client **Reports** and
  **Fixed-Assets Reports** tabs, `…/year-end/xbrl`, several **year-end** sub-pages (checklist/
  schedules/notes/review partial), `/assistant` redirecting to `/ai-assistant`.
- **Backend stubs:** portal `POST /invoices/{id}/pay` → **501**; copilot V2 intelligence endpoints
  and recommendation-action execution return placeholders; `GET /portal/self/documents` returns empty.
- **Mock/in-memory (not DB-backed):** relationships intelligence (loans/properties/related-party),
  health "hard-override" detection, some dashboard activity logs, parts of compliance sub-tabs.
- **Not wired:** bank matching-rules / categorization suggestions endpoints exist but aren't in the UI.
- **Dev-only:** `/logo-concepts/*` pages; the dev header-based auth fallback (only when Supabase
  is unset and `APP_ENV=development`).
- **Staged behind flags (OFF by default):** `USE_USER_JWT`, `REQUIRE_MFA` (+ `MFA_REQUIRED_ROLES`).
  Test both states before relying on them.
- **Reminders** (work module) — infrastructure only; no real email/SMS send yet.

---

## 9. Recommended Order for Future Regression Testing

When time is limited, run this **smoke-to-deep** order; stop-the-line on any Critical failure.

1. **Smoke (every deploy):** login (+MFA), dashboard loads, create client, create lead,
   create+send engagement, open `/sign` in incognito and sign, convert to client. *(Critical spine.)*
2. **Isolation pass:** scoped-user cannot see unassigned clients; portal client sees only own data;
   payment webhook rejects bad signatures. *(Critical.)*
3. **Money pass:** post a balanced + an unbalanced journal; create+issue an invoice (intra & inter
   state); record a receipt; FY lock blocks back-posting. *(Critical.)*
4. **Compliance gate pass:** GSTR-1/3B require CA approval before JSON; e-invoice records IRN only;
   "mark filed" never submits. *(Critical, regulatory.)*
5. **Engagement management pass:** resend keeps old links valid; regenerate invalidates them;
   change recipient; download PDF; send-history counts. *(High.)*
6. **Email hygiene pass:** force an email failure → friendly message, no internals leaked. *(High.)*
7. **Work & approvals pass:** task lifecycle; recurring generation idempotent; approval needs MFA.
   *(High.)*
8. **Scheduler pass:** run daily jobs twice → no duplicates. *(High.)*
9. **Breadth pass:** click through all client-workspace sub-tabs, accounting reports, portal tabs,
   AI surfaces → loads, empty/error states, no raw errors. *(Medium.)*
10. **Platform pass:** suspend/unsuspend a test firm (MFA), confirm session revocation. *(Critical,
    run in a non-prod tenant.)*

**Automate first (highest ROI):** the Phase-1/2 auth+RBAC matrix, the money calculations
(GST/TDS/journal balance/paise), the no-auto-submit gates, and the public signing + webhook
isolation — these are both high-severity and stable enough to encode as regression suites.

---

*Generated from a full read-through of the PracticeSync codebase. Where a feature is marked
"stub/mock/not wired", treat the test as "verify it degrades safely" rather than "verify full
behavior". No application code was modified to produce this roadmap.*
