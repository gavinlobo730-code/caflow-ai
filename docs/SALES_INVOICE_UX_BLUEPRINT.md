# Sales Invoice UX — Batch 0 Design-Freeze Blueprint

**Date:** 2026-07-05 · **Status:** DESIGN FREEZE — implementation-ready · **Type:** specification only, **no code.**

This is the single foundation document for all future Sales-Invoice coding batches. It consolidates the two prior deliverables — `docs/audits/2026-07-05-sales-invoice-ux-workflow-review.md` (internal proposal review) and `docs/audits/2026-07-05-invoice-workspace-competitive-design.md` (competitive teardown + design) — into one buildable spec. Those two are the source of truth; this does not restart research or re-litigate the locked decisions.

**Locked decisions (from the prompt, honored verbatim):** immutable accounting kept; explicit posting kept; three actions (**Save Draft / Save & Issue / Save & Send**); reuse the posting kernel; dedicated **Create** and **Edit** pages; **View** is a right drawer; the issued invoice is the operational **Hub**; status split into **financial (authoritative) + derived delivery + derived compliance**; one unified HSN/SAC lookup over the official master; services-only Service Catalogue; compliance depth (multi-GSTIN / treatments / export / SEZ / LUT / IRN / QR / e-way bill) is future-phased; **never auto-submit to any government portal**.

**Verified current-state anchors (cited throughout):** the backend already has atomic issue+posting, PDF, email, reminders, pay-links, credit notes, receipts, a smart HSN lookup, and — newly confirmed — **`/api/timeline`, `/api/einvoice/records`, `/api/eway-bill/records`** record scaffolding. The frontend already has `CustomerLookup`, `HsnLookup`, `AccountLookup`, `data-table`, `states`, `toast`, `async-state`, `combobox`, `badge`, `card`, `tabs`. The single biggest missing piece is the **dedicated Create/Edit page surface** (today it's an inline embedded card in `apps/web/app/clients/[id]/sales/page.tsx`).

---

# Part 1 — Complete UX Specification

## 1.1 Page layout & information architecture

Three surfaces, one shared render core:

| Surface | Route | Purpose | Chrome |
|---|---|---|---|
| **Create** | `/clients/[id]/sales/invoices/new` | Author a new invoice | Full page, focused |
| **Edit** | `/clients/[id]/sales/invoices/[invoiceId]/edit` | Amend a **draft** only | Full page, focused (identical to Create) |
| **View / Hub** | right-side **drawer** over the Sales list (deep-linkable `?invoice=[id]`) | Read an issued invoice + operate on it | Drawer, 640–760px |

The Sales list (`…/sales`, `SalesInvoices` component) remains the index. "New Invoice" and row "Edit" **navigate to the page**; row "View" opens the **drawer**. Create/Edit are pages (room for the line grid + live GST, deep-linkable, back-button-safe); View is a drawer (fast, non-destructive) per the locked decision.

**Create/Edit page — vertical information architecture (top → bottom):**
```
[ Page header: breadcrumb · title · status pill (Draft) · autosave hint ]
[ Toolbar: Cancel · Save Draft · Save & Send ▾ · Save & Issue (primary) ]
┌───────────────────────────── two-column body ─────────────────────────────┐
│  LEFT (flex, ~68%)                          │  RIGHT (sticky, ~32%)         │
│  • Party block: Customer (lookup) + auto-   │  • Summary panel (sticky):    │
│    filled billing/GST state, place of supply│    Taxable · CGST · SGST ·    │
│  • Invoice meta: number(preview) · date ·   │    IGST · Round-off · TOTAL    │
│    payment terms → due date · reference     │  • Amount in words             │
│  • Line-item grid (the core)                │  • Validation summary          │
│  • Notes / terms                            │  • (Edit mode) Activity mini   │
│  • Attachments                              │                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Component hierarchy (Create/Edit):**
```
<InvoiceEditorPage>                         (new; route wrapper, loads data, owns form state)
 ├─ <InvoiceEditorHeader>                   (new; title, status pill, dirty/autosave hint)
 ├─ <InvoiceToolbar>                         (new; the 3 actions + Cancel; disabled/loading states)
 ├─ <InvoicePartyBlock>                      (new; wraps existing <CustomerLookup> + autofill)
 ├─ <InvoiceMetaFields>                      (new; date, terms→due, reference, GST treatment [future])
 ├─ <InvoiceLineGrid>                        (new; keyboard grid)
 │   └─ <InvoiceLineRow> × n
 │       ├─ <ServiceCataloguePicker>         (new; Phase: catalogue)
 │       ├─ <HsnLookup>                       (exists)
 │       ├─ <GoodsServicesToggle>            (new; drives hsn_type filter + label)
 │       └─ qty · rate · gst% · amount (computed)
 ├─ <InvoiceNotes>                            (new/thin)
 ├─ <InvoiceAttachments>                      (new)
 └─ <InvoiceSummaryPanel>                     (new; sticky totals from server preview)
```

**Component hierarchy (View/Hub drawer):**
```
<InvoiceHubDrawer>                           (extract+extend existing InvoiceDetailDrawer)
 ├─ <InvoiceHubHeader>                        (rich header §1.5 — number, 3 status layers, amounts)
 ├─ <InvoiceHubActions>                       (the Hub verbs §1.11)
 ├─ <InvoiceReadonlyBody>                     (party, lines, totals — read-only)
 ├─ <InvoiceComplianceStrip>                  (derived IRN / e-way bill badges + 30-day clock [future])
 └─ <InvoiceActivityTimeline>                 (new; reads /api/timeline)
```

## 1.2 Responsive behavior
- **Desktop ≥1280px:** two-column editor (grid + sticky summary side-by-side). Drawer 720px.
- **Tablet 768–1279px:** editor single-column; summary panel becomes a **sticky bottom bar** (Total + primary action always visible). Line grid keeps columns but compresses description. Drawer = 88vw.
- **Mobile <768px:** editor single-column; line grid degrades from a table to **stacked line cards** (one card per line: description full-width, then qty/rate/gst/amount in a 2×2); toolbar collapses to a sticky bottom action bar with the primary action + a "⋯" for the rest; summary is a collapsible sheet. Drawer becomes a **full-screen sheet**.
- Never allow horizontal page scroll; the line grid scrolls inside its own `overflow-x:auto` container on small screens.

## 1.3 Header (editor)
Breadcrumb (`Client › Sales › New Invoice`), invoice title (`New Sales Invoice` / `Edit Draft SINV-2526-0042`), a **status pill** (Draft), and a subtle **dirty/autosave** hint ("Unsaved changes" / "Draft saved 12:04"). No monetary data here — that lives in the summary panel.

## 1.4 Toolbar (editor)
Right-aligned action cluster, left-aligned Cancel:
`[Cancel]                         [Save Draft]  [Save & Send ▾]  [ Save & Issue ]`
- **Save & Issue** = primary (filled). **Save Draft** = secondary. **Save & Send** = secondary with a caret (choose recipient/template; issues then emails).
- Buttons show per-action loading + disabled-until-valid; the primary is disabled while the **pre-flight gate** (§Part 6) has blocking errors.

## 1.5 Header (View/Hub) — the rich summary (satisfies "Invoice Summary" proposal)
```
SINV-2526-0042            ● Issued · Sent · Viewed        [IRN —] [EWB —]   (3 layers)
Acme Pvt Ltd  ·  27ABCDE1234F1Z5  ·  Place of supply 27-MH
Total ₹1,18,000     Paid ₹0     Outstanding ₹1,18,000     Due 20 Jul 2026 (aging)
```
Financial pill is authoritative; delivery + compliance are **derived badges**, visually distinct (outline, not filled) so they never read as accounting state.

## 1.6 Line-item grid
Columns: `# · Description · [Goods/Svc] · HSN/SAC · Qty · Unit · Rate · GST% · Amount · ⋯`.
- **Keyboard-first:** Tab/Shift-Tab across cells; **Enter on the last cell adds a new row**; ↑/↓ move rows; a row "⋯" menu (duplicate line, delete line). Add-row and delete-row buttons for pointer users.
- **Description** offers the Service-Catalogue picker (drops a full pre-priced line) and free text.
- **HSN/SAC** = existing `<HsnLookup>` (auto-fills GST rate; free-text allowed).
- **Goods/Services** per line filters the HSN lookup to `hsn_type` and sets the field label (HSN vs SAC) and PDF wording.
- **Amount** is computed read-only. GST% is the line rate (drives the preview).
- Empty grid shows one blank row + a hint ("Add your first line — start typing a service or HSN code").

## 1.7 Summary panel (sticky)
Server-authoritative preview (never a client recompute of record values): Taxable, CGST, SGST, IGST, **Round-off** (new invoice-level line), **Total**, plus amount-in-words. On desktop it's a sticky right rail; on tablet/mobile a sticky bottom bar with Total + primary action. Shows a subtle "computed on server" affordance while a debounce recompute is in flight.

## 1.8 Notes
Free-text notes/terms (maps to existing `notes`), with an optional saved-terms preset later. Character-count only if a PDF limit applies.

## 1.9 Attachments
Drag-drop file list on the editor (e.g. PO, work order). **New capability** — invoices have no attachment store today (only `journal_entries.attachments` exists). Model as `invoice_attachments` `[{name,url}]`; storage via the existing document store. Attachments are metadata only — **never** part of GST/journal math.

## 1.10 Activity (timeline)
Read-only chronological feed on the Hub: created, issued (with journal ref), sent/resent, viewed, payment recorded, reminder sent, credit note created, cancelled. Backed by the existing `/api/timeline` + `timeline_service` events already emitted on issue.

## 1.11 Invoice Hub (post-issue operational actions)
Surface **existing** capabilities — build entry points, not engines:
`View Journal · Record Payment · Duplicate · Create Credit Note · Send/Resend Email · Download PDF · Payment Link · (Activity)`. Visibility is status-gated (§Part 2 table).

## 1.12 States (empty / loading / validation / error)
- **Empty:** list empty → illustration + "Create your first invoice". Grid empty → one blank row + hint. Hub timeline empty → "No activity yet".
- **Loading:** page → `skeleton` for header + grid rows; summary → shimmer; async pickers → spinner-in-list (reuse `async-state` / `states`). Save actions → button spinner + disabled toolbar.
- **Validation (inline, non-blocking until submit):** per-field (customer required, ≥1 line, positive qty, rate ≥ 0, HSN present when required, place-of-supply present). Summary panel lists blocking issues; the primary action is disabled with a tooltip naming the first blocker.
- **Error (submit/posting):** structured, actionable, with a deep-linked fix (see §Part 6 error codes). Never a bare "journal posting failed". On any post failure the invoice **stays a re-tryable draft** (already guaranteed by `issue_invoice`).

---

# Part 2 — User journey (click-optimized)

End-to-end, with the **target click count** and every removed click called out.

| Step | Flow | Target clicks | Clicks removed vs today |
|---|---|---|---|
| **New Invoice** | List → "New Invoice" → Create page | 1 | Page instead of scrolling to an inline card |
| **Customer** | Type-ahead `CustomerLookup` → pick → **auto-fills GST state, place-of-supply, credit terms, due date** | 1 pick | −3 (state, terms, due date no longer manual) |
| **Line items** | Type description → catalogue/HSN auto-fills SAC+rate → Enter adds next row | ~1 pick + Enter per line | −2/line (HSN code + GST rate auto-filled; no mouse trip) |
| **Issue** | **Save & Issue** (pre-flight passes → atomic post) | 1 | −1 (Save-then-Issue collapsed to one) |
| **Send** | **Save & Send** issues **and** emails in one motion; or Hub → Send | 1 | −2 (no separate issue→open→send) |
| **Payment** | Hub → **Record Payment** (pre-filled amount/date) → confirm | 2 | Was a context switch to the Receipts tab entirely |
| **Credit Note** | Hub → **Create Credit Note** (pre-filled from invoice) → issue | 2 | Was re-keying in the Credit Notes tab |
| **Reports** | Issued invoice already flows to GSTR-1 / AR / P&L — **zero extra clicks** | 0 | Posting is the only commit; reports read posted GL |

**Unnecessary clicks eliminated (design intent):** (1) inline-card scroll → dedicated page; (2) manual state/terms/due-date → customer auto-fill; (3) manual HSN + rate → lookup auto-fill; (4) Save→Issue two-step → one primary; (5) issue→send two-step → Save & Send; (6) tab-hopping for payment/credit-note → Hub actions from the invoice itself. **Net: a 3-line issued+emailed invoice drops from ~18–22 interactions to ~8–10.**

**Journey guardrails:** every commit remains explicit (immutable ledger); Save & Send blocks on drafts sending nothing; Record Payment/Credit Note route through the existing engines only.

---

# Part 3 — Wireframes

## 3.1 Create (desktop)
```
Client › Sales › New Invoice                                   ● Draft   Draft saved 12:04
──────────────────────────────────────────────────────────────────────────────────────
[Cancel]                                   [Save Draft]  [Save & Send ▾]  [ Save & Issue ]
──────────────────────────────────────────────────────────────────────────────────────
 Customer  [ Acme Pvt Ltd                     ⌕ ]         ┌─ Summary ──────────────────┐
   GSTIN 27ABCDE1234F1Z5 · Place of supply 27-MH          │ Taxable        1,00,000.00 │
 Invoice date [05-07-2026]  Terms [Net 15 ▾]  Due [20-07] │ CGST 9%            9,000.00 │
 Reference    [ PO-8891         ]                          │ SGST 9%            9,000.00 │
──────────────────────────────────────────────────────────│ IGST                   0.00 │
 # Description        G/S  HSN/SAC  Qty Unit  Rate    GST% │ Round-off             0.00 │
 1 [Statutory audit▾] [S ] [998212⌕] 1  OTH 100000  18% ▾ │ ───────────────────────────│
   ⌕ auto: 998212 Financial auditing services  @18%       │ TOTAL        ₹1,18,000.00  │
 + Add line   (Enter on last cell adds a row)              │ One lakh eighteen thousand │
──────────────────────────────────────────────────────────│ ⚠ 0 issues — ready to issue│
 Notes [ Thank you for your business.            ]         └────────────────────────────┘
 Attachments  [ ⬆ drag files or browse ]
```

## 3.2 Edit (desktop) — identical layout, draft-only
```
Client › Sales › Edit SINV-2526-0042                           ● Draft   (only drafts editable)
──────────────────────────────────────────────────────────────────────────────────────
[Cancel]                                   [Save Draft]  [Save & Send ▾]  [ Save & Issue ]
 … identical body; fields pre-populated; issued/paid/cancelled → editor refuses & redirects to View …
```

## 3.3 View / Hub (drawer)
```
                                        ╎ SINV-2526-0042        ● Issued ·Sent·Viewed  ╎
                                        ╎ [IRN —] [EWB —]                      [ ✕ ]   ╎
                                        ╎ Acme Pvt Ltd · 27ABCDE1234F1Z5               ╎
                                        ╎ Total ₹1,18,000  Paid ₹0  Due ₹1,18,000      ╎
                                        ╎──────────────────────────────────────────────╎
                                        ╎ [View Journal] [Record Payment] [Duplicate]  ╎
                                        ╎ [Credit Note] [Send ▾] [PDF] [Pay Link]      ╎
                                        ╎──────────────────────────────────────────────╎
                                        ╎ Lines (read-only) …                          ╎
                                        ╎ Accounting: Journal JE-… ✓ Posted 05-07       ╎
                                        ╎──────────────────────────────────────────────╎
                                        ╎ Activity                                      ╎
                                        ╎ • 12:07 Issued (JE-2526-0311)                 ╎
                                        ╎ • 12:08 Emailed to ap@acme.com                ╎
                                        ╎ • 12:41 Viewed by recipient                   ╎
```

## 3.4 Tablet (editor)
```
Client › Sales › New Invoice                         ● Draft
────────────────────────────────────────────────────────────
 Customer [ Acme Pvt Ltd            ⌕ ]  27… · PoS 27-MH
 Date [05-07] Terms [Net 15▾] Due [20-07]  Ref [PO-8891]
 # Description       G/S HSN    Qty Rate    GST%
 1 [Statutory audit] [S][998212] 1 100000  18%
 + Add line
 Notes […]   Attachments [⬆]
────────────────────────────────────────────────────────────
▎ Total ₹1,18,000            [Save Draft] [ Save & Issue ]  ▎  ← sticky bottom bar
```

## 3.5 Mobile (editor)
```
‹ New Invoice            ● Draft
────────────────────────────────
 Customer [ Acme Pvt Ltd     ⌕ ]
 27ABCDE1234F1Z5 · PoS 27-MH
 Date 05-07  Terms Net15  Due 20-07
 ┌ Line 1 ───────────────── ⋯ ┐
 │ [Statutory audit        ]  │
 │ HSN [998212⌕]   [S/G]      │
 │ Qty 1     Rate 1,00,000    │
 │ GST 18%   Amt 1,00,000     │
 └────────────────────────────┘
 + Add line
 Notes […]      Attach [⬆]
────────────────────────────────
 Total ₹1,18,000          [⋯][Save & Issue]   ← sticky bottom bar; ⋯ = Draft/Send
```

---

# Part 4 — Component inventory

### Already exists (reuse as-is)
| Component / module | Path |
|---|---|
| `CustomerLookup`, `HsnLookup`, `AccountLookup`, `StateLookup`, `EntityLookup` | `apps/web/components/lookups/*` |
| `Combobox` + `useCombobox` | `apps/web/components/ui/combobox.tsx`, `lib/combobox/useCombobox.ts` |
| `DataTable` | `apps/web/components/ui/data-table.tsx` |
| Loading/empty/error primitives | `apps/web/components/ui/states.tsx`, `skeleton.tsx`, `async-state.ts` |
| Toast | `apps/web/components/ui/{toast,toaster}.tsx`, `use-toast.ts` |
| Badge / Button / Card / Tabs | `apps/web/components/ui/*` |
| CSV import modal + mapping | `apps/web/components/CsvImportModal.tsx`, `lib/invoices/importMapping.ts` |
| Line payload mapper | `apps/web/lib/invoices/lineItemPayload.ts` |
| Payment terms / due-date math | `apps/web/lib/sales/{paymentTerms,dateMath}.ts` |
| Typed API client (`salesInvoices`, `hsn`) | `apps/web/lib/api/index.ts` |

### Needs enhancement
| Component | Change |
|---|---|
| `InvoiceDetailDrawer` (in `sales/page.tsx`) | Extract to `InvoiceHubDrawer`; add Hub actions, compliance strip, activity timeline; make deep-linkable (`?invoice=`) |
| `SalesInvoices` list | Row "New/Edit" → navigate to pages; keep "View" → drawer; add Hub entry points |
| `HsnLookup` | Point at the **official** master ranking; ensure Goods/Services `type` filter is wired from the row toggle |
| Recurring template editor | Replace its plain HSN text input with `HsnLookup` |
| A reusable **Drawer/Sheet** primitive | None in `ui/` today — the sales drawer is bespoke; extract one for reuse |

### Needs creation
`InvoiceEditorPage`, `InvoiceEditorHeader`, `InvoiceToolbar`, `InvoicePartyBlock`, `InvoiceMetaFields`, `InvoiceLineGrid`, `InvoiceLineRow`, `GoodsServicesToggle`, `InvoiceSummaryPanel`, `InvoiceNotes`, `InvoiceAttachments`, `InvoiceActivityTimeline`, `InvoiceHubActions`, `ServiceCataloguePicker`, and the two route files (`invoices/new`, `invoices/[invoiceId]/edit`).

---

# Part 5 — Technical mapping (UI → backend, reuse-first)

| UI element / action | Existing endpoint | Existing service | Existing FE | New work |
|---|---|---|---|---|
| Load draft for Edit | `GET /api/sales-invoices/{id}` | — | drawer fetch | Route + editor state hydration |
| Live totals preview | (client preview; authoritative on save) | `_compute_line_gst` (server) | `computeGst` preview | Summary panel; **round-off line** (server) |
| Customer pick + autofill | `GET /api/customers/search` | — | `CustomerLookup` | Wire autofill → meta fields |
| HSN/SAC search | `GET /api/hsn/search` | `hsn.py` (`hsn_master`+prefs) | `HsnLookup` | Official master seed; ranking; `type` filter from toggle |
| HSN history suggest | `GET /api/sales-invoices/hsn-suggestions` | `_record_hsn_preferences` | — | Optional "recent codes" chips |
| **Save Draft** | `POST /api/sales-invoices/` · `PATCH /api/sales-invoices/{id}` | `numbering.insert_with_number` | `handleSave` | Toolbar wiring; page nav |
| **Save & Issue** | `POST /api/sales-invoices/{id}/issue` | `journal_for_sales_invoice` → `_create_journal` | `issueInvoice` | **Pre-flight gate**; structured error codes |
| **Save & Send** | `…/issue` then `POST /api/sales-invoices/{id}/send` | `email_service.send_invoice_to_customer`, `invoice_pdf_service` | `sendInvoice` | Compose "issue+send" as one toolbar action |
| Pre-flight (FY lock) | validated in `issue` | `period_validation_service.validate_posting_date` | — | Surface as a *pre*-check, not just on submit |
| **View Journal** | `GET /api/accounting/journal?client_id=…` (+ `journal_entry_id`) | `accounting_service.list_journal_entries` | — | Journal-detail drill-through view/modal |
| **Record Payment** | `POST /api/receipts/` | `receipt_service.create_receipt_core` | Receipts tab | Hub action pre-filled from invoice (one engine only) |
| **Create Credit Note** | `POST /api/credit-notes/` (+ `/issue`) | `journal_for_credit_note` | `CreditNoteForm` | Pre-fill from invoice; Hub entry point |
| **Duplicate** | `POST /api/sales-invoices/` (copy lines) | — | — | New draft, **new number + today's date** |
| Send / Resend / Deliveries | `…/send` · `…/resend` · `GET …/deliveries` | `email_service`, `invoice_deliveries` | Send/Delivery modals | Reuse in Hub |
| Payment Link | `POST /api/payments/links` · `…/send` | `payment_service`, `services/payments/*` | `PaymentLinkModal` | Reuse in Hub |
| Download PDF | `GET /api/sales-invoices/{id}/pdf` | `invoice_pdf_service` | `viewInvoicePdf` | — |
| **Activity timeline** | `GET /api/timeline` | `timeline_service` | — | `InvoiceActivityTimeline` (filter by entity) |
| Delivery badges (Sent/Viewed) | `GET …/deliveries` | `invoice_deliveries` | — | Derived badge render (no new status) |
| Compliance badges (IRN/EWB) | `GET /api/einvoice/records` · `GET /api/eway-bill/records` | `einvoice.py`, `eway_bill.py` | — | Derived badge render; **future** generation wiring |
| Attachments | — | — | — | `invoice_attachments` store + endpoints + UI |
| Service Catalogue | — | — | — | Table + `/api/service-catalogue` + picker (services-only) |
| Cancel / Repost maintenance | `POST …/cancel` · `POST …/repost-journal` · `GET …/maintenance/unposted` | reversal via `_create_journal` | — | Surface cancel in Hub (Partner-gated) |

**Reuse verdict:** every Hub verb maps to a shipped engine; **no backend accounting logic is rebuilt.** The genuinely new backend work is: an invoice-level **round-off** field, **attachments**, the **Service Catalogue**, the **official HSN master** seed, and (future) IRN/e-way-bill **generation** wiring on top of the existing record tables.

---

# Part 6 — Risks & mitigations

### Accounting risks (highest priority)
1. **Accidental irreversible post.** One-click Save & Issue posts an immutable entry. → **Mitigate:** pre-flight validation gate blocks the primary until clean; a lightweight confirm on first-issue-of-session; posting stays atomic (failure ⇒ re-tryable draft, already true).
2. **Round-off / odd-bps rounding.** Intra-state half-rate floor division can leave CGST+SGST 1 paise off; no invoice-level round-off today. → **Mitigate:** add a server round-off line + unit tests (repo rule) **before** the editor ships against it.
3. **Two invoice systems confusion** (`client_sales_invoices` vs `fee_invoices`). → **Mitigate:** this blueprint governs **only** `client_sales_invoices`; keep naming/nav distinct; no cross-wiring.
4. **Duplicate must not clone number/date.** → **Mitigate:** Duplicate always mints a new number via `insert_with_number` and defaults date=today, status=draft.

### Regression risks
- **Editor extraction from the 4,631-line `sales/page.tsx`.** → Extract incrementally; keep the list/drawer working each batch; feature-flag the new routes until parity.
- **Payment path forking.** Record Payment must call `receipt_service.create_receipt_core` — **never** a second path. → Code review gate + a test asserting AR = invoices+receipts+allocations.
- **FY-lock & immutability triggers.** → No change to the kernel; add integration tests against the real DB (FakeDB has no triggers, per `02-posting-kernel.md`).

### UX risks
- **Unsaved-changes loss** (drawer/page dismiss with dirty GST lines). → Hard discard-guard + autosave-draft on blur of the whole editor.
- **Status confusion** (delivery/compliance read as accounting). → Distinct visual language (outline badges vs filled financial pill); never in the DB status enum.
- **Mobile line entry friction.** → Stacked line cards; sticky Total + primary action.

### Performance risks
- **Large customer/HSN sets.** → Already debounced server search (top-N); do not full-load.
- **Live preview recompute on every keystroke.** → Debounce (250ms) + compute preview client-side for display only; authoritative totals on save.
- **Timeline/deliveries N+1 in the Hub.** → Single batched fetch per invoice open; cache within the drawer session.

---

# Part 7 — Final implementation breakdown (batches)

Small, independently shippable, review-safe. Each is gated by tests + a regression checklist. Complexity: **S** ≈ days · **M** ≈ 1–2 wk.

### Batch 1 — Money correctness prerequisite *(S)*
- **Objective:** invoice-level **round-off** + fix odd-bps CGST/SGST split; make `journal_for_sales_invoice` re-raise unexpected errors.
- **Scope:** `_compute_line_gst`, invoice payload (`round_off_paise`), `journal_for_sales_invoice`.
- **Files:** `apps/api/routers/sales_invoices.py`, `apps/api/services/phase2_journal_service.py`, migration for `round_off_paise`.
- **Dependencies:** none.
- **Test plan:** unit tests for 0.25%/odd-bps lines; round-off balances to total; posted JE Σdebit=Σcredit.
- **Regression checklist:** existing invoice totals unchanged for even-bps rates; GSTR-1 figures unchanged; all posting tests green.
- **Complexity:** S · **Risk:** Med (money).

### Batch 2 — Routing + editor shell *(M)*
- **Objective:** dedicated Create/Edit pages; extract View into a reusable `InvoiceHubDrawer`; deep-link `?invoice=`.
- **Scope:** new routes; move form out of `sales/page.tsx` behind a flag; list rows navigate.
- **Files:** `apps/web/app/clients/[id]/sales/invoices/new/page.tsx`, `…/[invoiceId]/edit/page.tsx`, refactor `sales/page.tsx`, new `components/ui/drawer.tsx`.
- **Dependencies:** none (parallel to B1).
- **Test plan:** create/edit/view render; back-button + refresh safe; draft-only edit guard redirects issued invoices to View.
- **Regression checklist:** list, filters, import, recurring, credit-note tabs still work; no change to create payload.
- **Complexity:** M · **Risk:** Med (extraction).

### Batch 3 — Line grid + smart pickers + summary *(M)*
- **Objective:** keyboard line grid, `CustomerLookup` autofill, `HsnLookup` per-line, Goods/Services toggle, sticky summary panel.
- **Scope:** `InvoiceLineGrid`/`Row`, `InvoicePartyBlock`, `InvoiceSummaryPanel`, `GoodsServicesToggle`.
- **Files:** new components under `apps/web/components/invoices/`; reuse `lib/invoices/lineItemPayload.ts`.
- **Dependencies:** Batch 2.
- **Test plan:** keyboard add/delete rows; customer autofill sets state/terms/due; totals preview matches server on save.
- **Regression checklist:** payload shape unchanged; GST preview parity; import path untouched.
- **Complexity:** M · **Risk:** Low–Med.

### Batch 4 — Three actions + pre-flight + structured errors *(M)*
- **Objective:** Save Draft / Save & Issue / Save & Send; pre-flight validation gate; error codes with deep-linked remediation.
- **Scope:** `InvoiceToolbar`; issue+send composition; error-code contract on `issue`.
- **Files:** `apps/web/components/invoices/InvoiceToolbar.tsx`, `apps/api/routers/sales_invoices.py` (error codes).
- **Dependencies:** Batches 2–3.
- **Test plan:** issue posts atomically; failure keeps draft; Save & Send issues then emails; each error code renders its CTA.
- **Regression checklist:** `/issue`, `/send` behavior preserved; FY-lock still blocks; mock+real DB.
- **Complexity:** M · **Risk:** Med (accounting).

### Batch 5 — Invoice Hub *(M)*
- **Objective:** View Journal, Record Payment, Duplicate, Create Credit Note, Send/Resend, PDF, Pay Link, Activity Timeline.
- **Scope:** `InvoiceHubActions`, `InvoiceActivityTimeline`, journal drill-through; pre-fill wiring.
- **Files:** Hub components; reuse receipts/credit-notes/payments/timeline endpoints.
- **Dependencies:** Batch 2 (drawer).
- **Test plan:** Record Payment routes through `create_receipt_core`; Credit Note pre-fills; Duplicate mints new number+today; timeline renders events.
- **Regression checklist:** AR = invoices+receipts+allocations; no second payment path; credit-note posting unchanged.
- **Complexity:** M · **Risk:** Med.

### Batch 6 — Status model rendering *(S)*
- **Objective:** financial pill + derived delivery (Sent/Viewed) + derived compliance (IRN/EWB) badges; rich Hub header.
- **Scope:** badge derivation from `invoice_deliveries` / `einvoice-records` / `eway-bill-records`.
- **Files:** `InvoiceHubHeader`, badge components.
- **Dependencies:** Batch 5.
- **Test plan:** badges reflect data; DB `status` enum **unchanged**; no accounting coupling.
- **Regression checklist:** status filters unchanged; reports read `status` only.
- **Complexity:** S · **Risk:** Low.

### Batch 7 — Official HSN master + Goods/Services depth *(M)*
- **Objective:** replace the ~35-row seed with a versioned official HSN/SAC master; ranking; wire recurring editor to `HsnLookup`.
- **Scope:** data seed/migration; `hsn.py` ranking; `type` filter.
- **Files:** new migration (versioned `hsn_master`), `apps/api/routers/hsn.py`, recurring editor.
- **Dependencies:** Batch 3 (toggle).
- **Test plan:** search by code/description returns master hits; rate is pre-fill-only (never in GST math); provenance recorded.
- **Regression checklist:** history-first ranking preserved; free-text still allowed; no invoice back-population.
- **Complexity:** M · **Risk:** Med (data/licensing).

### Batch 8 — Service Catalogue (services-only) *(M, gated)*
- **Objective:** reusable services-only billing presets (description + SAC + GST + default rate).
- **Scope:** `service_catalogue` table, `/api/service-catalogue` CRUD, `ServiceCataloguePicker`.
- **Files:** new migration, new router/service, picker.
- **Dependencies:** Batch 7 + **product-owner sign-off** (must not become an items/inventory master).
- **Test plan:** picker drops a full line; edits don't retro-change past invoices; no stock/valuation fields exist.
- **Regression checklist:** import/recurring unaffected; catalogue is presets only.
- **Complexity:** M · **Risk:** Med (scope-policy).

### Batch 9 — Attachments *(S)*
- **Objective:** invoice-level attachments (metadata only).
- **Scope:** `invoice_attachments`, endpoints, `InvoiceAttachments` UI.
- **Dependencies:** Batch 2.
- **Test plan:** upload/list/remove; attachments never touch GST/journal.
- **Regression checklist:** no coupling to posting; RLS/firm-scoped.
- **Complexity:** S · **Risk:** Low.

### Future program (separate blueprint) — Compliance depth
Multi-GSTIN place-of-business, GST treatments (SEZ/export/LUT/deemed-export), and **IRN/QR + e-way bill generation** via a GSP abstraction on top of the existing `einvoice`/`eway-bill` record tables, with the **30-day IRN clock** surfaced and **no auto-submit**. Deferred per the locked decisions; sequenced after Batches 1–9.

---

## Definition of done (Batch 0)
This blueprint is the frozen foundation. Coding begins at **Batch 1** and proceeds in order; each batch merges only when its test plan + regression checklist pass and the immutable-kernel invariants are untouched. No code has been written in this document — it is specification only.
