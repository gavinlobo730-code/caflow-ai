# Sales Invoice — UX & Workflow Architecture Review

**Date:** 2026-07-05 · **Scope:** `apps/web` Sales module + `apps/api` sales-invoice / posting / GST backend · **Type:** investigation & planning only — **no code changed.**

Reviewer role: Principal Product Architect / ERP UX / Senior Accounting Engineer.
Method: read the live implementation (frontend + backend + migrations + architecture docs), then evaluated each of the 15 proposals against it and against QuickBooks Online, Xero, Zoho Books, TallyPrime, NetSuite, and Dynamics 365 Business Central.

---

## 0. Executive summary — read this first

**The single most important finding: the "Current" state described in the review prompt is materially out of date. Most of the 15 "proposals" are already built and shipped.** Before planning any new work, the team must re-baseline against the code, or it will rebuild things that exist.

Ground truth (file-cited in §Reality check below):

- **Journal posting is already atomic and already gives actionable errors.** The `POST /api/sales-invoices/{id}/issue` endpoint posts the journal **first** and only then flips the invoice to `issued`; a failure leaves a **re-tryable draft**, never an "issued-but-unposted" ghost. The generic *"journal posting failed"* string the prompt quotes as "current" was already replaced with *"…seed the Chart of Accounts and retry."* (`apps/api/routers/sales_invoices.py:902-1002`).
- **HSN/SAC is already a smart, server-backed, searchable lookup** — not a "simple dropdown." It searches code **and** description over a canonical `hsn_master` merged with the firm's own usage history, auto-fills GST rate, and allows free-text (`apps/web/components/lookups/HsnLookup.tsx`, `apps/api/routers/hsn.py`, `apps/api/migrations/036_gst_engine.sql`).
- **Send-by-email (PDF attached), credit notes, recurring invoices, payment reminders, online pay-links, and a full `draft → issued → partially_paid → paid → cancelled` lifecycle all already exist and are merged to `main`** (see `docs/QUICKBOOKS_ACCOUNTING_ROADMAP.md`, which marks these ✅ Done).
- **Goods-vs-Services already exists in the data model** (`hsn_master.hsn_type ∈ {goods, services}`, `InvoiceLineIn.is_service`) — it is simply not surfaced as an explicit UI toggle.

So the genuine open work is **much smaller** than the prompt implies. The real gaps are: (a) the **create/edit form is still an inline embedded card**, not a focused surface; (b) **no "View Journal" drill-through**, **no Duplicate**, **no "Create Credit Note from this invoice"**, **no "Record Payment" on the invoice itself**; (c) **`hsn_master` is a curated ~35-row CA subset, not the official GST master**; (d) **no Service Catalogue / saved-line templates** (and note the roadmap has *permanently removed* an items master — a direct tension, see Topic 12); (e) the lifecycle does **not** model `Sent`/`Viewed` as first-class states; and (f) one **accounting-correctness rounding edge** on odd-basis-point GST rates.

A second structural caveat that colours several topics: **PracticeSync's whole engine is deliberately "draft-first, CA-confirmed, immutable once posted, never auto-submit"** (`docs/architecture/02-posting-kernel.md`, `CLAUDE.md`). Posted journal entries are immutable at the DB-trigger level and cannot post into a locked financial year. That governance model is the reason an explicit "Issue" step exists at all, and it must shape — not be steamrolled by — the "auto-post on Save" proposals in Topics 1–2.

---

## Reality check — proposal vs. what the code already does

| # | Proposal | Actual current state in the repo | Verdict |
|---|---|---|---|
| 1 | Remove "Issue"; Save → post | Explicit `draft → issue` step; issue posts journal atomically | Partly valid — **reframe, don't delete** |
| 2 | Auto-post journal on Save | Journal posts on **Issue**, not Save (bulk import & recurring land as drafts by design) | **Challenge** — conflicts with draft-first governance |
| 3 | Actionable posting errors | **Already actionable** (`"…seed the Chart of Accounts and retry"`), atomic, re-tryable | **Already done** — minor polish only |
| 4 | Full-screen modal / drawer for create | Create/edit is an **inline embedded card**; *detail* is already a drawer | **Valid & unbuilt** — the one clear UX win |
| 5 | Status-aware detail actions | Rich actions exist; missing Duplicate, Create-Credit-Note, View-Journal, Record-Payment | Partly done — **fill the gaps** |
| 6 | Send invoice by email | **Already shipped** (`/send`, `/resend`, deliveries, PDF attach) | **Already done** |
| 7 | Intelligent searchable HSN lookup | **Already shipped** (`HsnLookup` + `/api/hsn/search`) | **Already done** |
| 8 | Bundle official GoI HSN/SAC master | Only a **curated ~35-row** `hsn_master` seed | **Valid & unbuilt** — real gap |
| 9 | Search by code + description | **Already shipped** (search matches both) | **Already done** |
| 10 | Auto-suggest SAC from description | **Already shipped** (history-based auto-fill; high-confidence only) | **Done (history)**; model fallback optional |
| 11 | Remember frequently-used codes | **Already shipped** (`hsn_sac_preferences`, recency+frequency) | **Already done** |
| 12 | Service Catalogue (reusable templates) | **Absent**; items master **permanently removed** from roadmap | **Valid but blocked by policy** — needs owner ruling |
| 13 | Explicit Goods (HSN) vs Services (SAC) | Exists in data (`hsn_type`, `is_service`), **not surfaced in UI** | Partly done — **thin UI layer** |
| 14 | `Draft→Open→Sent→Viewed→…Paid` | Have `draft/issued/partially_paid/paid/cancelled`; `sent`/`viewed` tracked as **deliveries**, not status | Partly done — **derive, don't duplicate** |
| 15 | Richer invoice header/summary | Drawer shows number/status/customer/total; "Outstanding" per-invoice is thin | **Valid & cheap** |

---

# Part 1 — Proposal-by-proposal review

For each: **Recommendation · Benefits · Drawbacks · Risks · Industry comparison.**

## 1. Remove the "Issue" button

**Recommendation: Do not delete the posting step — *reframe* it.** Keep exactly one authoritative moment where the invoice becomes an immutable, GST-reportable, ledger-posted document. Change the *UX* so that moment is the default one-click action, and make "Draft" an explicit opt-in — but keep an explicit **commit**, do not silently auto-post everything the instant a user tabs out of the last field.

Concretely: replace the two-step *Save (draft) → Issue* with a primary **"Save & Issue"** button and a secondary **"Save as Draft."** This is the proposal's real intent, and it is correct. What is *not* correct is framing it as "there is no commit step at all."

- **Benefits:** fewer clicks for the common case (most invoices are meant to be issued immediately); the word "Issue" is jargon customers don't recognise (QBO/Xero/Zoho say "Save and send" / "Approve"); a single button removes the "why is my invoice stuck in draft and missing from GSTR-1?" support class.
- **Drawbacks:** removing a deliberate confirmation from an **immutable, statutory** action raises the cost of a mistake — once posted, the entry can only be *reversed*, never edited (DB triggers `trg_journal_immutability*`, `docs/architecture/02-posting-kernel.md`). A stray Enter that instantly posts a wrong-dated invoice into the GL is worse than a stray Enter that saves a draft.
- **Risks:** GST timing — an auto-posted invoice immediately enters GSTR-1 for its month; posting into a nearly-closed period, or fat-fingering the date across an FY boundary, has filing consequences. The FY-lock guard (`period_validation_service.validate_posting_date`) protects locked years but not the "oops, wrong month, already filed" case.
- **Industry comparison:** QBO/Xero/Zoho **do** collapse this — "Save" on a finalised invoice effectively posts it; drafts are explicit. TallyPrime posts a voucher on Accept. **But** all of them make posted sales invoices comparatively easy to edit; PracticeSync's ledger is intentionally immutable, so the "cheap undo" those tools lean on doesn't exist here. That argues for keeping the commit *explicit and labelled* even while making it one click.

> **Net:** adopt "Save & Issue" (primary) + "Save as Draft" (secondary). Keep the atomic post. Do **not** auto-post on blur/close.

## 2. Automatic journal posting on Save

**Recommendation: Keep posting bound to the explicit issue action, not to "Save".** The desired *outcome* — one action creates the invoice, assigns the number, posts A/R + revenue + GST liability atomically — **already exists** and is well-built (`journal_for_sales_invoice` → `_create_journal`, `apps/api/services/phase2_journal_service.py:41-132`). Moving that trigger from "Issue" to "every Save" breaks three deliberate flows that depend on invoices existing **without** a posted journal:

1. **Bulk import** lands hundreds of historical invoices as **drafts** on purpose (`docs/SALES_INVOICE_IMPORT.md`).
2. **Recurring invoices** generate **drafts** for CA review, never auto-issued (`services/recurring_invoice_service.py`).
3. **Draft editing** — only drafts are editable; posting is the point of no return.

The posting itself is already correct double-entry:

```
Dr Trade Receivables   total_paise
   Cr Sales Revenue          taxable_amount_paise
   Cr GST Output CGST/SGST/IGST   per head (system_account_key: gst_cgst/sgst/igst)
```

- **Benefits (of the existing design):** idempotent (dedup on `client_id, reference_no, entry_date`), balance-asserted before insert, single posting kernel, integer paise throughout, atomic via the `post_journal_atomic` RPC (migration 152).
- **Drawbacks / what to add:** **failure handling** is the only real ask here, and it is largely solved — see Topic 3. The one addition worth making: a lightweight **pre-flight check on the draft** ("Chart of Accounts ready? customer state present? line HSN present?") surfaced *before* the user clicks Issue, so failures are prevented rather than reported.
- **Risks:** if the team *does* move posting to Save, the import and recurring pipelines must keep an explicit "create unposted" path, or they'll start posting hundreds of historical entries into current/again-locked periods.
- **Industry comparison:** the recommended failure model (post-first, atomic, retryable) matches NetSuite/Business Central, where sub-ledger→GL posting is transactional and a GL failure blocks the document rather than half-committing it.

## 3. Journal-posting failure UX

**Recommendation: Already 80% done; finish it with error *codes* + a one-click remediation link.** The current backend already returns specific, user-facing guidance and keeps the invoice a re-tryable draft:

- Missing CoA → *"Cannot issue — Required account not found: … Please set up Chart of Accounts before posting. Invoice remains a draft; seed the Chart of Accounts and retry."*
- There is even a remediation surface: `GET /maintenance/unposted` + `POST /{id}/repost-journal` for issued-but-unposted stragglers.

What to add:
- **Structured error codes** (`COA_MISSING`, `FY_LOCKED`, `IMBALANCE`, `CUSTOMER_STATE_MISSING`) so the frontend can render a **specific CTA** ("Set up Chart of Accounts →", "This year is locked — post to a later date?") instead of a raw sentence.
- **Deep-link the fix**: "Seed Chart of Accounts" should be a button that opens the CoA seeder, not an instruction.
- **Benefits:** turns a dead-end into a guided recovery; reduces "it just says failed" support tickets.
- **Drawbacks / Risks:** minimal — this is additive; keep the human-readable string as a fallback so nothing regresses.
- **Industry comparison:** Xero/QBO surface exactly this pattern — a blocking banner naming the missing account with a link to create it. PracticeSync is one abstraction (error codes) away from parity.

> **Correctness note to fix while here:** `journal_for_sales_invoice` **swallows non-ValueError exceptions and returns `None`**, whereas the receipt/payment builders deliberately re-raise. A transient DB error during posting could therefore read to the user as a generic "journal posting failed" with no cause. Align it to re-raise like the others so the endpoint can classify it.

## 4. Invoice creation UX — embedded form vs modal / drawer / page

**Recommendation: This is the one clear, unbuilt UX win. Move create/edit into a focused near-full-screen surface — a right-side slide-over drawer for quick single invoices, escalating to a dedicated route for complex ones.** Today create/edit is an **inline embedded card** in the tabbed page (`apps/web/app/clients/[id]/sales/page.tsx`, `InvoiceForm` ~lines 1877-2437) — cramped for a multi-line GST invoice, and it pushes the list around.

- **Recommended pattern (hybrid, industry-standard):**
  - **Slide-over drawer** (the app *already* uses a drawer for invoice *detail*, so the pattern and components exist) for the fast path.
  - **Dedicated route** `…/sales/invoices/new` and `…/[invoiceId]/edit` for deep links, refresh-safety, browser back/forward, and long multi-line invoices — and so an invoice is a **shareable URL**, which the current state-only page cannot do.
- **Benefits:** more horizontal room for the line-item grid + live GST panel; focus (dimmed background) reduces mis-entry; deep-linkable; back-button-safe.
- **Drawbacks:** a modal/drawer that holds unsaved GST lines needs solid **dirty-state / accidental-dismiss** guarding; very large invoices feel better on a full page than in a drawer.
- **Risks:** losing entered lines on an accidental click-away — mandatory "discard changes?" guard.
- **Industry comparison:** Zoho Books & QBO use **dedicated full-page** invoice editors; Xero uses a full page; **Stripe/Ramp-style** modern tools use large slide-overs for quick entry and pages for complex docs. The right answer for an ERP-grade GST invoice is **page for the editor, drawer for quick actions** — i.e. *don't* keep it an inline card, and *don't* trap a full invoice editor in a small modal.

## 5. Invoice detail actions & lifecycle

**Recommendation: The action set is already rich and status-gated; add the four missing verbs.** Present today (row + drawer): View, Edit (draft), Issue (draft), Delete (draft), Send/Resend email, Remind (overdue), Delivery history, Pay-link, View PDF. **Missing and worth adding:**

| Action | Status | Why | Effort |
|---|---|---|---|
| **View Journal** (drill-through to the GL entry) | issued+ | The drawer shows `journal_entry_id` as dead text; CAs expect to click into the entry | S |
| **Record Payment** on the invoice | issued/partly-paid | Payment exists only via the Receipts tab / pay-link; the natural place is the invoice itself | M |
| **Create Credit Note from this invoice** | issued/paid | Credit notes exist but only from their own tab; pre-filling from the invoice is the QBO/Zoho norm | M |
| **Duplicate** | any | Standard accelerator for repeat billing | S |

- **Benefits:** each closes a "the feature exists but I can't get to it from here" gap; View-Journal materially raises CA trust (transparency of posting).
- **Drawbacks / Risks:** **Record Payment** must route through the *existing* receipt engine (`receipt_service.create_receipt_core`) — do **not** create a second payment path (the codebase deliberately has one). **Duplicate** must always produce a **draft** with a **new number and today's date**, never copy the number/date.
- **Industry comparison:** QBO/Xero/Zoho all expose Record-Payment, Copy/Duplicate, Credit-Note, and a journal/"audit" view directly from the invoice. This is table-stakes; PracticeSync has the engines and just needs the entry points.

## 6. Send invoice by email — **already shipped**

**Recommendation: No new build; small polish only.** `POST /{id}/send` + `/resend` render the PDF (`invoice_pdf_service`), email via Resend, and log an `invoice_deliveries` row (`sending → sent/failed`, with `provider_message_id`). Guarded to `issued+` invoices only.

- **Essential?** Yes, and it's done. **Draft vs Posted:** correctly **blocked on drafts** — you shouldn't email a non-invoice; keep that.
- **Polish:** confirm `RESEND_API_KEY` is live in prod (the helper silently no-ops without it — `docs/QUICKBOOKS_ACCOUNTING_ROADMAP.md`); add a "Send" affordance in the *editor's* Save menu ("Save & Send") to match QBO's marquee flow.
- **Risks:** silent no-op if the key is unset reads as "sent" to the user — add an explicit config check.
- **Industry comparison:** at parity with QBO/Xero/Zoho once "Save & Send" is one motion.

## 7. Intelligent searchable HSN/SAC lookup — **already shipped**

**Recommendation: No new build.** `HsnLookup.tsx` is a debounced, keyboard-navigable combobox over `GET /api/hsn/search`, which merges `hsn_master` (canonical) + `hsn_sac_preferences` (firm history), de-duped, and auto-fills the GST rate on select, with free-text always allowed. This is exactly the proposed design and it already meets the ERP bar (see `docs/audits/2026-07-01-combobox-smart-lookup-audit.md` §4).

- **UX/Performance/Scalability:** server-side top-N search scales to a full master; history-first ranking makes repeat entry instant.
- **Only real weakness:** the underlying dataset is tiny (Topic 8), so "search by description" often returns nothing for goods. Fixing the data, not the UI, is the work.
- **Gap to close:** the **Recurring template editor** still uses a plain text input for HSN/SAC — route it through `HsnLookup` for consistency.

## 8. Official Government HSN/SAC master — **valid, real gap**

**Recommendation: Ship a bundled, versioned canonical master; this is the highest-value data investment on the list.** Today `hsn_master` is a **hand-curated ~35-row** seed skewed to CA/professional SACs (migration `036`). "Search by what you sell" only works if the dataset is real.

- **Is there a suitable official dataset?** Yes — CBIC publishes the HSN (goods, Customs Tariff-aligned) and SAC (services, Scheme of Classification of Services) lists, and the GST portal exposes an HSN/SAC search. There is **no single clean, licensed, redistributable file**, so plan to **compile** a master from the CBIC tariff + SAC scheme and **treat it as reference data you maintain**, not a one-time import.
- **Update strategy:** version the table (`hsn_master_version`, `effective_from`), ship it as a migration/seed, and refresh on **rate-notification** events (GST rates change by notification, sometimes mid-year). Crucially: **never** back-populate old invoices from a new rate — the invoice's stored rate is the source of truth; the master only pre-fills new lines.
- **Licensing:** government works/statutory data are generally freely usable, but codes+descriptions curated by third-party vendors are not — build from the official CBIC source, not a scraped commercial list, and keep provenance notes.
- **Offline support:** ~12k HSN + ~800 SAC rows is small; bundling it in Postgres (or a shipped seed) gives full offline/local search with zero external dependency — a genuine advantage over portals.
- **Risks:** a stale rate in the master could mislead a user — mitigated because the rate is a **pre-fill hint only**, never used in the GST/journal math (already true in code; keep it that way and cite CGST Rule 46(g)).

## 9. Search by code *and* description — **already shipped**

**Recommendation: No build; usability is already good.** `/api/hsn/search` matches both fields; typing "Accounting" surfaces `998211 Accounting and bookkeeping services` **today** (it's literally in the seed). Improve *ranking* only: exact-code > prefix > history-frequency > description-substring, and show `rate · type · UQC` on each row (the audit already specifies this).

## 10. Auto-suggest SAC from description — **already shipped (rule/history based)**

**Recommendation: Keep the current history-based auto-fill; make an AI fallback optional and always CA-reviewed.** Today a **high-confidence exact-normalised-description history match** silently fills the code and rate; weaker matches only suggest. That is the right conservatism.

- **Practical / AI vs rule-based:** rule/history is practical and safe now. An LLM/embedding fallback for *first-time* descriptions is reasonable **only** as a non-binding suggestion.
- **Risk of incorrect tax classification:** real and material — a wrong HSN can mean wrong GST rate and a compliance exposure. Therefore: never auto-**apply** an AI guess to the rate without explicit selection; label AI suggestions as such; keep free-text override; and keep the rate out of the tax math except via the user's confirmed pick (already the case). Cite CGST Rule 46(g) in code.

## 11. Frequently-used codes — **already shipped**

**Recommendation: No build.** `hsn_sac_preferences` records `(description_key, hsn_sac, gst_rate_bps, use_count, last_used_at)` per firm+client and ranks recency-then-frequency; it's written on every create/update and surfaced first in search and in `/hsn-suggestions`. This is the best-practice implementation. Only enhancement: expose a small "Recent HSN/SAC" chip row before the user types (the audit's "recent/frequent before typing").

## 12. Service Catalogue (reusable service templates) — **valid, but collides with a standing policy decision**

**Recommendation: Escalate a scope decision before building. A *services* catalogue is high-value for a CA practice, but the roadmap has *permanently removed* the "Products/Services items master."** (`docs/QUICKBOOKS_ACCOUNTING_ROADMAP.md`: "Inventory / Products-Services items master — **Removed permanently**.")

There is a clean way to reconcile this: a **billing/service template** (description + SAC + GST rate + default rate) is **not** an inventory items master — it carries no stock, no valuation, no COGS. It's the same idea as the existing **recurring-invoice templates** and **`hsn_sac_preferences`**, just promoted to a first-class, nameable, reusable line preset.

- **Build before or after HSN work?** **After** the HSN master (Topic 8) but it can reuse it. The catalogue *references* an SAC and a rate; a real HSN master makes the catalogue's defaults trustworthy.
- **Benefits:** for CA firms whose "products" are a dozen repeatable services (audit, ITR filing, GST return, ROC filing), a catalogue is a far bigger data-entry win than HSN search alone; it standardises descriptions and rates across the practice.
- **Drawbacks / Risks:** scope creep toward the banned inventory module; naming and governance must make clear this is **billing presets, not stock**. Needs product-owner sign-off to not violate the standing directive.
- **Industry comparison:** every peer (QBO/Xero/Zoho items, Tally stock/service items) has this; its permanent removal is PracticeSync's most notable functional gap versus the market — worth revisiting explicitly for **services only**.

## 13. Explicit Goods (HSN) vs Services (SAC) — **mostly done in data; thin UI layer left**

**Recommendation: Surface the distinction that already exists in the model; don't split the control into two.** The data already knows: `hsn_master.hsn_type ∈ {goods, services}` and `InvoiceLineIn.is_service`. The lookup can already filter by `type`.

- **Recommended UX:** keep **one** HSN/SAC field but add a per-line (or per-invoice) **Goods/Services** segment that (a) filters the lookup to HSN vs SAC, (b) drives correct labelling ("HSN" vs "SAC") on the field and the PDF, and (c) helps GSTR-1 HSN-summary classification. Do **not** build two separate controls — that adds friction for mixed invoices.
- **Benefits:** correct terminology on the statutory invoice (CGST Rule 46 distinguishes HSN/SAC); cleaner HSN-summary in GSTR-1; better search relevance.
- **Risks:** mixed goods+services invoices must allow per-line type, not a single invoice-level switch — model it per line.
- **Industry comparison:** Tally/Zoho treat item type as an attribute of the item, not a mode switch — surfacing `hsn_type` per line matches that.

## 14. Invoice lifecycle — `Draft → Open → Sent → Viewed → Partially Paid → Paid`

**Recommendation: Keep the *accounting* status set as-is; render `Sent`/`Viewed` as *derived* display states from data you already capture — do not add them to the DB status enum.** Two different concepts are being conflated:

- **Accounting status** (authoritative, drives the ledger/GST): `draft → issued → partially_paid → paid → cancelled` (DB CHECK, migration 050). This is correct and should not gain `sent`/`viewed`, which have **no accounting meaning** and would pollute a statutory field.
- **Delivery/engagement status** (informational): already captured in `invoice_deliveries` (sent, and — with a tracking pixel/pay-link open — viewable). Render these as **badges layered on top of** the accounting status ("Issued · Sent · Viewed"), the way QBO shows "Sent"/"Viewed" separately from "Open/Paid".

Map the proposal:
- **"Open"** = your `issued` with `paid_paise = 0` and not overdue. (Just a label — no new state.)
- **"Sent" / "Viewed"** = derived from `invoice_deliveries`.
- **"Overdue"** = already a **derived** flag (`is_overdue`, `days_overdue`), correctly *not* a status. Keep it derived.

- **Benefits:** richer at-a-glance state without corrupting the statutory status or complicating the immutable-ledger transitions.
- **Risks:** if `sent`/`viewed` become real statuses, every report/filter/guard that switches on status must handle them — needless blast radius. Derived badges avoid it.
- **Industry comparison:** QBO/Xero explicitly separate **financial** status (Open/Paid/Overdue) from **delivery** status (Sent/Viewed). Mirror that separation.

## 15. Invoice header / summary

**Recommendation: Build it — cheap and high-value.** Add a consistent header (in the drawer and the new editor) showing **Invoice #, Status (accounting + delivery badges), Customer, Total, Amount Paid, Outstanding, Due date/aging.** Most fields exist; the missing piece is a clean **per-invoice Outstanding** (`total_paise − paid_paise`) and aging surfaced prominently.

- **Benefits:** the header becomes the single source of "where does this invoice stand"; supports the collections workflow.
- **Risks:** none material; ensure Outstanding uses server values (`paid_paise`, `credited_paise`) not a client recompute (zero business logic in the frontend — `CLAUDE.md`).
- **Industry comparison:** standard across all peers; this is pure catch-up polish.

---

# Part 2 — What's missing (ERP architect's lens)

Things the 15 topics don't mention that a production Indian GST ERP needs:

1. **GST rounding correctness on odd basis points.** `_compute_line_gst` splits intra-state tax as `half_rate = gst_rate_bps // 2` then floor-divides each half. For **odd-bps** rates (e.g. 0.25% = 25 bps, 0.10% = 10 bps) `cgst + sgst` can be **1 paise short** of the IGST-equivalent, and the two halves may differ. Also, **line-wise vs invoice-total rounding** (Rule 46/round-off) isn't reconciled to a single invoice-level round-off line. Decide a documented rounding policy, add a `round_off_paise` line, and unit-test it (repo rule: every financial calc gets a test).
2. **E-invoice (IRN/QR) & e-way bill.** There's an `einvoice` page shell, but IRP registration (IRN, signed QR) is mandatory above the turnover threshold and is a first-class part of "issue" for many clients. Where does IRN generation sit relative to Issue? (Must stay CA-confirmed, never auto-submit.)
3. **Reverse charge, export/SEZ (zero-rated, LUT/with-payment), and nil/exempt supplies** on the sales side. RCM exists for purchases; the sales invoice needs export/SEZ handling for GSTR-1 correctness (the multi-currency doc already flags LUT).
4. **Editing a posted invoice.** The immutable-ledger model means "edit issued invoice" = reverse + reissue, or a credit/debit note. The UX must make this explicit rather than appearing to "lock" with no path forward.
5. **Numbering governance.** `SINV-{fy}-{seq:04d}` is race-safe, but statutory numbering must be **gapless and sequential** (CGST Rule 46(b)); cancellations create gaps. Document how cancelled numbers are handled for GSTR-1 (report as cancelled, don't reuse).
6. **Multi-currency export invoices** are built but flagged OFF; the GST-on-INR-equivalent path (CGST Rule 34) is designed but must be wired before enabling — a landmine if turned on carelessly.
7. **Discounts & additional charges** (pre/post-tax, freight, round-off) — not visible in the line model; common on real invoices and GST-relevant.
8. **Two invoice systems.** `client_sales_invoices` (GST) vs `fee_invoices` (practice billing) have **different numbering, status enums, and no double-entry on the fee side.** Users will conflate them. Clarify naming/navigation and decide whether fee invoices should also post to the GL.
9. **Bulk actions & list ergonomics** — bulk send/remind/export, saved filters, column choices on the invoice list (the DataTable exists; wire the batch verbs).
10. **Audit/trust surface** — "View Journal" (Topic 5) plus a visible audit trail on the invoice raises CA confidence; the audit log already exists (`trg_audit_capture`), just surface it.

---

# Part 3 — Dependency-aware implementation roadmap

Ordered so each phase unblocks the next. Complexity: **S** ≈ days, **M** ≈ 1–2 weeks, **L** ≈ larger.

### Phase 0 — Correctness & re-baseline (do first)
- **Objective:** fix the GST odd-bps rounding + add invoice-level round-off with tests; align `journal_for_sales_invoice` to re-raise (Topic 3 note); document numbering/cancellation gaps.
- **Why first:** correctness of money is non-negotiable (`CLAUDE.md`); everything else sits on the posting engine.
- **Dependencies:** none. **Complexity:** S. **Risk:** Medium (touches money math — mitigated by mandatory unit tests).

### Phase 1 — Editor surface + posting UX reframe
- **Objective:** move create/edit to a slide-over/dedicated route (Topic 4); replace Save→Issue with **"Save & Issue" / "Save as Draft"** (Topic 1); add pre-flight readiness check + structured error codes with deep-link remediation (Topics 2–3); build the invoice header/summary (Topic 15).
- **Why here:** the biggest UX wins; depends on Phase 0 posting being solid.
- **Dependencies:** Phase 0. **Complexity:** M. **Risk:** Medium (must guard immutable-post confirmation + dirty-state).

### Phase 2 — Detail-action completeness
- **Objective:** add **View Journal** drill-through, **Record Payment** (via existing receipt engine), **Create Credit Note from invoice** (pre-filled), **Duplicate** (Topic 5); render **Sent/Viewed** as derived delivery badges + "Open" label (Topic 14); "Save & Send" (Topic 6 polish).
- **Why here:** wires already-built engines to the invoice; low risk once the editor/header exist.
- **Dependencies:** Phase 1. **Complexity:** M. **Risk:** Low–Medium (reuse engines; never fork payment path).

### Phase 3 — HSN/SAC data depth
- **Objective:** ship the **bundled, versioned official HSN/SAC master** (Topic 8); improve search ranking + rich rows (Topic 9); surface **Goods/Services per line** from `hsn_type` (Topic 13); route the recurring editor through `HsnLookup` (Topic 7 gap); "recent codes" chips (Topic 11 polish).
- **Why here:** independent of the editor work; unlocks the catalogue.
- **Dependencies:** none hard (parallelizable with Phase 1–2), but *precedes* Phase 4. **Complexity:** M (data curation is the cost). **Risk:** Medium (data provenance/licensing; keep rate as hint-only).

### Phase 4 — Service Catalogue (gated on a product-owner decision)
- **Objective:** reusable **service** templates (description + SAC + GST + default rate), reusing the HSN master and the recurring-template pattern (Topic 12).
- **Why here:** depends on a trustworthy HSN master (Phase 3) and needs an explicit exception to the "no items master" directive.
- **Dependencies:** Phase 3 **+ product-owner sign-off.** **Complexity:** M. **Risk:** Medium (scope-policy conflict — resolve before building).

### Phase 5 — Statutory depth (as needed by real clients)
- **Objective:** e-invoice IRN/QR + e-way bill hooks (CA-confirmed), export/SEZ/RCM-on-sales, discounts/charges, AI HSN fallback (Topic 10), enabling multi-currency export invoices with the Rule-34 INR path.
- **Why last:** highest complexity/compliance risk; each is independently large.
- **Dependencies:** Phases 0–3. **Complexity:** L. **Risk:** High (statutory + external portals — strict no-auto-submit).

---

# Part 4 — Recommended end-state Sales Invoice experience

The optimal experience for PracticeSync — premium-modern for Indian businesses **without** compromising accounting correctness:

1. **One focused editor, deep-linkable.** Create/edit an invoice on a dedicated route (drawer for quick single invoices), with a live GST panel, per-line Goods/Services + smart HSN/SAC lookup backed by the **real** GST master and the firm's history, and a **Service Catalogue** to drop in a full pre-priced line in one pick.
2. **One deliberate, one-click commit.** Primary **"Save & Issue"** (atomically: number + immutable posted journal for A/R, revenue, and per-head GST) with **"Save as Draft"** and **"Save & Send"** alongside. A **pre-flight check** prevents the common failures; when one slips through, a **coded, deep-linked** error guides recovery — the invoice never lands in a broken state (this is *already* how the engine behaves; the work is UX).
3. **The invoice is the hub.** From the invoice you can View Journal, Record Payment, Send/Resend, Remind, create a pre-filled Credit Note, Duplicate, and download the GST PDF — all wired to the **single** existing engine for each, never a second path.
4. **Honest, layered status.** Authoritative accounting status (`draft/issued/partially_paid/paid/cancelled`) drives the ledger and GST; **Sent/Viewed/Overdue** ride on top as **derived** badges — richer signal, statutory field kept clean.
5. **Correctness as a feature, visible.** Integer-paise everywhere, documented rounding with a round-off line, gapless numbering, immutable posted entries with an explicit reverse/credit-note path, FY-lock respected, and **nothing auto-submitted to any government portal** — with the audit trail and journal one click away so CAs can *trust and verify*.

The through-line: **PracticeSync already has the hard part — a correct, immutable, single-kernel double-entry engine with GST at source. The remaining work is overwhelmingly experience-layer: surface what exists, focus the editor, deepen the HSN data, and reconcile the service-catalogue policy.** Re-baseline against the code before writing a single line of new feature work.

---

*No code was written or modified. Architecture and planning only, per the task.*
