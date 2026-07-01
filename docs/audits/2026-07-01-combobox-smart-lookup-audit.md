# Platform-wide Searchable Combobox & Smart Lookup — UX Architecture Review

**Date:** 2026-07-01 · **Scope:** `apps/web` (+ backing masters in `apps/api`) · **Type:** audit & architecture only — **no code changed**.

Method: enumerated **all 80 files** that render a native `<select>` (via three parallel reviewers), classified every dropdown by dataset shape, and traced the backing data (hardcoded enum vs. fetched entity). Cross-checked backend masters and the existing HSN infrastructure.

---

## 1. Research — how modern accounting/ERP software handles this

Common patterns across **QuickBooks, Zoho Books, Xero, TallyPrime, NetSuite, SAP Business One, Odoo** (synthesised, not copied):

- **Entity pickers are type-ahead comboboxes, never long dropdowns.** Customer/vendor/item/account fields open a search box that matches on multiple fields and shows rich rows (name + secondary id + balance). Tally is keyboard-first (type-to-filter, arrow, Enter); Zoho/QuickBooks show avatars/sub-text; NetSuite/SAP use "list" popups with columns.
- **Create-on-the-fly ("+ Add new …").** Every product lets you create a customer/item inline when the search returns nothing — no context switch. (QuickBooks "+ Add", Zoho "New Customer", Odoo "Create …".)
- **Dependent auto-fill.** Selecting a customer fills billing/GST state, terms, currency; selecting an item fills HSN, rate, tax; selecting an account fills its type. This is the single biggest data-entry accelerator.
- **Recent / most-used first.** All rank recently- or frequently-used entries at the top of the list.
- **Server-side search at scale.** Above a few hundred rows, results come from a debounced server query (top-N), not a full client load. NetSuite/SAP paginate; Xero/Zoho debounce.
- **Small fixed enums stay plain dropdowns** (tax rate, status, terms) — comboboxes there add friction.
- **Tax-code / HSN is a dedicated smart lookup:** search by code *or* description, show rate + description, auto-apply rate, allow manual override.

**Design implication for PracticeSync:** introduce **one** shared combobox with a **smart-lookup** configuration for the critical transaction pickers; keep enums as-is.

---

## 2. Interaction taxonomy used in this report

| Symbol | Interaction | When |
|---|---|---|
| ✅ | **Keep dropdown** | Bounded, stable enum (≤ ~12 options) |
| 🔄 | **Searchable combobox** | Entity picker, moderate–large & growing; single searchable list |
| ⚡ | **Autocomplete** | Closed but larger code list (10–15) where type-to-filter + keyboard helps |
| 🧠 | **Smart lookup** | Critical-path entity picker: multi-field search **+ auto-fill dependent fields + quick-create + recent/frequent** |

---

## 3. Consolidated dropdown inventory (80 files audited)

### 🧠 Smart lookup (critical data-entry path) — **highest priority**
| Screen | Field | Search by | Auto-fill on select | Quick-create |
|---|---|---|---|---|
| Sales → Invoice | **Customer** | name, GSTIN, PAN, phone, email | GST/place-of-supply state, credit terms, opening balance | ✅ Customer |
| Sales → Receipt | **Customer** | name, GSTIN, phone | opening balance / outstanding | ✅ |
| Sales → Credit Note | **Customer** + **original invoice** | name/GSTIN; invoice_no | invoice GST rate/amounts | ✅ (customer) |
| Purchases → Bill | **Vendor** | name, GSTIN, PAN | TDS section+rate, payment terms, GST state | ✅ Vendor |
| Purchases → Payment | **Vendor** + **against bill** | name/GSTIN; bill_no/ref/amount | loads open bills | ✅ (vendor) |
| Purchases/Journal/Recon → **Line account** | account | account_code, account_name, type | account type/subtype | (via COA screen) |
| Invoice/Bill line → **HSN/SAC** | HSN code, description | **GST rate, description, unit (UQC)** | — (free-text allowed) |

### 🔄 Searchable combobox (entity pickers)
- **Client** picker — recurs in **≥8 places**: TaskFormModal, documents, notifications/whatsapp, client-portal, gst, income-tax/notices (+ filter), time (export + manual), payroll/statutory, settings/scheduled-reports, accounting/invoices, billing. *(Firm-scoped; grows with the practice.)*
- **Team member / assignee** — TaskFormModal, workflows/approvals, team/work-allocation.
- **Ledger/COA account** — journal-entry line, ledger viewer, bank-recon counter account (50–250+ accounts).
- **Linked entity** — clients/[id]/relationships (search entity name/PAN).
- **Open bill / unpaid invoice** — purchase payment "against bill", credit-note "original invoice".
- **Bank-recon session** — search by statement period/account/status.
- **State (place of supply / home state)** — 28–36 options: borderline; combobox (search by name or 2-digit code) reduces mis-selection risk.

### ⚡ Autocomplete (closed code lists, keyboard-first)
- **TDS section** (192/194A/194C/194Q…) — purchases TDS, tds page, tds challan (search by number or label; already auto-fills rate).
- **IT notice type** (143(1)/143(2)/148…) — income-tax/notices.
- **Task template** (14 items) — TaskFormModal.

### ✅ Keep as plain dropdown (bounded enums — ~45 selects)
GST rate slabs, payment mode, payment terms presets, billing frequency/cycle, journal entry type, unit/UQC, document type, financial year, assessment year, quarter, month/period, return type, status/priority/workflow-state, entity type, GST filing frequency, DSC type/purpose/issuing-CA, user role, knowledge scope, lead source, MCA company/form/designation, bank name (9), currency filter, transaction category, bank-account pickers where only 2–10 exist.

**Tally:** ~45 keep · ~25–30 → 🔄 combobox · 7 → 🧠 smart lookup · 3 → ⚡ autocomplete.

---

## 4. HSN/SAC — recommended architecture (deep-dive)

**Today:** the invoice/bill line uses a **free-text `<input>`** for HSN/SAC, assisted by `GET /api/sales-invoices/hsn-suggestions` which reads the firm's **own history** (`hsn_sac_preferences`: description→code, `gst_rate_bps`, `use_count`, `last_used_at`) ranked recency-then-usage. Good for repeat entries; useless for a first-time or unknown code.

**Latent asset:** a canonical **`hsn_master`** table already exists (migration 036 — `hsn_code`, `description`, `gst_rate_pct`, `hsn_type` goods/services, `uqc` unit) **but no endpoint queries it**.

**Recommendation — a Smart HSN Lookup:**
1. Add `GET /api/hsn/search?q=&type=` over **`hsn_master`** (debounced server search; matches code **or** description; returns rate + description + UQC + type). `hsn_master` can be thousands of rows → server-side, top-N.
2. The lookup merges two sources, **recent/frequent first**: `hsn_sac_preferences` (the firm's history, already rate-bearing) then `hsn_master` (canonical). De-dupe by code.
3. On select → **auto-fill GST rate, description, and unit (UQC)**; leave all three editable (HSN is CA-overridable — CGST Rule 46(g)).
4. Keep **manual free-text** allowed (creatable) so an unlisted/edge code never blocks invoicing. Continue writing chosen code+rate back to `hsn_sac_preferences` (already happens) so history keeps learning.
5. Never use the looked-up rate in any tax/journal computation without the existing CA-review path — it only pre-fills the field.

This turns HSN from "know-the-code" into "search-by-what-you-sell", the pattern every ERP uses.

---

## 5. Large-dataset strategy (10k customers / 8k vendors / 20k products)

Do **not** load large entity sets into the browser. Strategy per dataset:

| Dataset | Realistic size | Strategy |
|---|---|---|
| **Customers, Vendors** | up to 10k / 8k | **Debounced server search** (`/api/customers/search?q=&limit=20`, `.ilike` on name/GSTIN/PAN/phone) + client-cached **recent/favourite** shown before typing. Never full-load. |
| **HSN/SAC** | thousands | **Debounced server search** over `hsn_master` (§4) + history. |
| **Chart of Accounts** | 50–250 | Already fully fetched per screen → **client-side filter** over the in-memory list; **virtualize** the rendered list if > ~200. No new endpoint needed. |
| **Clients** | tens–hundreds | Usually already loaded → client-side filter; add a search endpoint only if a firm exceeds a few hundred. |
| **Team members** | < 50 | Client-side filter over loaded list. |
| **Open bills / invoices per party** | 1–hundreds | Loaded per-party already → client-side filter; paginate/search if a party exceeds ~200 open items. |
| **Products / Services** | (no master table yet) | **Future** — when inventory is added, build the master + a server-search endpoint from day one (SKU/barcode/HSN). |

Rule of thumb baked into the component: **provide an `options` array → client-side; provide a `fetch(query)` → debounced async.** Same UI either way.

---

## 6. Reusable component architecture — `<Combobox>` + `useCombobox`

One headless hook + one presentational component; smart-lookups are thin configured wrappers (mirrors how the `DataTable` was built).

```
lib/combobox/useCombobox.ts     // headless: query, open, highlighted index, selection, async state
components/ui/combobox.tsx       // presentational: input, listbox, rows, create row, states
```

**Props (single source):**
```ts
type ComboboxProps<T> = {
  value: T | null | T[];                 // single or multi
  onChange: (v: T | null | T[]) => void;
  multiple?: boolean;
  // data — EITHER sync options OR an async fetcher (debounced):
  options?: T[];
  fetchOptions?: (query: string) => Promise<T[]>;  // server-side search
  getOptionId: (o: T) => string;
  getLabel: (o: T) => string;            // primary line
  getSecondary?: (o: T) => string;       // GSTIN / code / balance (rich rows)
  searchKeys?: (keyof T)[] | ((o: T) => string[]); // sync search fields
  // creatable:
  onCreate?: (label: string) => Promise<T> | void;  // "+ Create '…'"
  createLabel?: (q: string) => string;
  // affordances:
  recent?: T[]; favourites?: T[];        // shown before typing, top of list
  placeholder?: string; disabled?: boolean;
  loading?: boolean;                     // external loading (async)
  renderOption?: (o: T) => React.ReactNode;
  onSelectAutofill?: (o: T) => void;     // dependent-field auto-fill hook
};
```

**Behaviour:** debounced query (250 ms) for async; **auto-highlight first result**; **keyboard** ↑/↓ move, **Enter** select (or create if highlighted on the create row), **Esc** close, **Tab** commit-and-move, type-to-search, Home/End; click-away closes; sticky "+ Create" row when `onCreate` and no exact match.

**Accessibility:** WAI-ARIA combobox pattern — `role="combobox"` + `aria-expanded`/`aria-controls`/`aria-activedescendant`; listbox `role="listbox"`, rows `role="option"` `aria-selected`; label association; announced loading/empty; visible focus ring; sufficient contrast (reuse slate tokens).

**States:** loading (spinner in list), empty ("No matches" + create row), error (async failure → retry), disabled. Reuse `AsyncBoundary`/`Spinner` primitives.

**Smart-lookup wrappers** (config only): `<CustomerLookup>`, `<VendorLookup>`, `<AccountLookup>`, `<ClientLookup>`, `<HsnLookup>` — each sets fetch/search keys, rich rows, `onCreate`, and `onSelectAutofill`.

---

## 7. Additional UX improvements (beyond the swap)
- **Recent & frequent** entries surfaced before typing (customers/vendors/accounts/HSN — HSN history already exists).
- **Context-aware defaults:** invoice → default customer = last used for this client; bill line account = most-used for this vendor; GST rate default from HSN.
- **Dependent auto-fill** everywhere a selection implies other fields (§4, §3).
- **Intelligent sort:** exact-prefix > recent > frequent > alpha.
- **AI-assisted (only where genuinely useful):** HSN suggestion from line description (already history-based; could add a model fallback) — never auto-applied without CA review.

---

## 8. Roadmap & priority

| Phase | Work | Priority |
|---|---|---|
| **0 — Foundation** | Build `useCombobox` + `<Combobox>` (sync + async, creatable, recent, a11y, keyboard) with unit tests, mirroring the DataTable approach. | **Critical** |
| **1 — Transaction smart lookups** | `<CustomerLookup>` (invoice/receipt/credit-note), `<VendorLookup>` (bill/payment) with quick-create + auto-fill; add `/api/customers/search` & `/api/vendors/search`. | **Critical** |
| **2 — HSN smart lookup** | `<HsnLookup>` + `/api/hsn/search` over `hsn_master`, merged with history, auto-fill rate/description/UQC. | **High** |
| **3 — Account & client comboboxes** | `<AccountLookup>` (journal/bill/recon — client-side over loaded COA, virtualized) and `<ClientLookup>` across the ~8 client pickers. | **High** |
| **4 — Autocomplete enums & states** | TDS section / IT notice type / task template → autocomplete; state pickers → combobox. | **Medium** |
| **5 — Affordances** | recent/favourite, context-aware defaults, intelligent sort. | **Medium** |
| **Keep** | ~45 bounded enums unchanged. | — |

## 9. Notes / scope
- **No implementation performed** (per the task). This is architecture + roadmap only.
- Backend readiness: customers/vendors/clients/accounts/`hsn_master` tables all exist; only lightweight `…/search` endpoints (debounced `.ilike` + limit) are new work. **Products/Services masters do not exist yet** — those lookups are future once inventory is added.
- Consistency: this combobox complements the shipped `DataTable` — same headless-hook philosophy, same slate design, same a11y bar — so lists and pickers feel like one application.
