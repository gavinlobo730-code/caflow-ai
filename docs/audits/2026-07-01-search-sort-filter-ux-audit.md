# Platform-Wide Audit — Search, Sort, Filter & List UX

**Date:** 2026-07-01 · **Scope:** `apps/web` (Next.js 14 frontend) · **Type:** audit & roadmap only (no code changed).

Methodology: enumerated all **161 `page.tsx`** routes + ~20 client-workspace sections, measured baseline usage, then audited every list/table/index screen across 6 module clusters against an 11-point checklist (search, sort, filter, pagination, export, refresh, loading, empty, bulk, sticky header, persisted prefs).

---

## 1. Executive summary

The app is **compliance-strong but list-UX-weak**. Data is fetched *complete* client-side (`lib/supabase/selectAll.ts` pages past PostgREST's 1000-row cap), so most interaction can be done in-browser — yet the interaction layer is missing and **each of 75 tables is hand-rolled**.

Baseline (measured):

| Signal | Count | Note |
|---|---|---|
| Pages rendering `<table>` | **75** | all bespoke |
| Pages with a search input | ~14 | concentrated in a few modules |
| Pages with client-side sort | ~17 | rarely surfaced as clickable headers |
| Pages using `localStorage` | 8 | persistence is the exception |
| **Pages with a "rows per page" control** | **0** | pagination UI is absent app-wide |
| Reusable `DataTable` component | **0** | root cause of the inconsistency |

**Top themes**
1. **No pagination UI anywhere** — lists load the whole FY into the DOM (and several silently cap at `limit: 100`/`200`, hiding overflow).
2. **Search is sparse and shallow** — present on Sales invoices, Clients, Documents, Relationships, Knowledge, E-invoice; absent on Purchases, Receipts, Ledger, Journal, COA, Payroll, Risks, Health, Platform, most tax screens.
3. **Sort is rarely exposed** — logic exists in a few files; almost no clickable sortable headers; the Ledger even sorts oldest-first.
4. **Bulk actions almost non-existent** — the month-end banking workflows (Categorize / Post / Approvals) are one-row-at-a-time.
5. **No preference persistence** (except Sales invoices, which persist to the URL — the model to copy).
6. **Shared primitives are adopted inconsistently** — Tasks/Calendar/Workflows use `AsyncBoundary`/`EmptyState`; Sales/Purchases/Clients/Accounting roll their own 3-state ladders.

**Highest-impact fix:** build **one reusable `DataTable` + `useTablePreferences` hook** (Section 3) and roll it out highest-volume-first (Ledger/Journal, Sales/Purchases, banking workflows, compliance triage).

---

## 2. Priority roadmap (module level)

| Priority | Screens |
|---|---|
| **Critical** | Accounting **Ledger**; **Journal** (no full-list view exists); Banking **Categorize / Post / Reconciliation**; Accounting **Approvals**; Compliance **/deadlines**; GST **/gst/reconciliation**; MCA **/mca** |
| **High** | Clients list; Sales **Invoices**; Purchases **Bills**; Tasks **/tasks**; Governance **/approvals** & **/workflows/approvals**; **Payroll** (employees/payslips/runs); **Risks**; firm **Health**; **Platform** admin; **Relationships** registry; **Engagements**; **Pipeline** (lead search); financial-statement **account search + export** (TB/P&L/BS/CF); Fixed Assets; IT **/income-tax/notices** |
| **Medium** | Sales Customers/Receipts/Credit Notes/Statements; Purchases Vendors/Payments; Billing invoices/outstanding; Documents; Notifications; Knowledge; COA; Year-end lists; GST tracker/TDS/ITR-planning; Calendar; Time; Client-portal admin; FX Reports; Suppliers/Receivables/Loans/Budget/Schedule-III (firm) |
| **Low** | Recurring invoices; Task templates; My Work; embedded Client Tasks; E-invoice; Team; Client documents/knowledge; AI Insights; Memory |
| **N/A (not a list)** | Executive/Home/Client dashboards; AI Assistant/Copilot chat; Settings forms; onboarding wizard |

---

## 3. Reusable architecture review — **build a `DataTable` (YES)**

**Verdict: yes, build one shared component.** 75 hand-rolled tables re-implement the same concerns divergently; a single component removes the drift and unlocks pagination/sort/bulk everywhere at once. Crucially, the foundation already exists — the new component is mostly *composition*:

- `lib/supabase/selectAll.ts` → complete dataset in memory ⇒ **client-side** search/sort/filter/paginate is correct for SMB scale (no backend work for most screens).
- `components/ui/states.tsx` (`AsyncBoundary`/`EmptyState`/`ErrorState`) → drop-in state handling.
- `components/ui/skeleton.tsx` (`TableSkeleton`, `ListSkeleton`, `CardGridSkeleton`) → loading.
- `components/ui/{badge,button,card,tabs}.tsx` + `lib/services/formatting.ts` → cells & chrome.

### Proposed API

```tsx
// components/ui/data-table.tsx
type Column<T> = {
  key: string;
  header: string;
  accessor: (row: T) => unknown;          // value for sort/search/export
  render?: (row: T) => React.ReactNode;   // custom cell (badges, links, money)
  sortable?: boolean;
  hideable?: boolean;                      // column-visibility menu
  align?: "left" | "right";
  width?: string;
  sticky?: boolean;                        // pin first column
};

type FilterDef =
  | { key: string; label: string; type: "select"; options: {value:string;label:string}[] }
  | { key: string; label: string; type: "dateRange" }
  | { key: string; label: string; type: "amountRange" };  // integer paise

type BulkAction<T> = { id: string; label: string; icon?: React.ReactNode;
                       run: (selected: T[]) => void | Promise<void>; confirm?: boolean };

<DataTable
  data={rows} loading={loading} error={error} onRetry={reload}
  columns={columns}
  getRowId={(r) => r.id}
  searchKeys={["invoice_no","customer_name","gstin"]}
  filters={filterDefs}
  pageSizes={[25, 50, 100, 250]}          // "rows per page"
  bulkActions={bulkActions}                // enables checkbox column
  exportFilename="invoices"                // CSV of the FILTERED set
  stickyHeader
  persistKey="sales.invoices"              // → localStorage + URL
  emptyState={<EmptyState title="No invoices yet" />}
/>
```

Companion hook (persistence): `useTablePreferences(persistKey)` stores `{ search, filters, sort, visibleColumns, pageSize }` in `localStorage` and mirrors sort/filter to the URL (generalising the pattern Sales invoices already uses).

**Built-in features:** debounced search · clickable sortable headers (↑/↓) · filter bar (select / date-range / amount-range in paise) · page-size + prev/next · column-visibility menu · checkbox multi-select + bulk-action toolbar · CSV export of the filtered rows · sticky header + optional sticky first column · loading/empty/error via `AsyncBoundary` · responsive horizontal scroll · preference persistence.

**Headless variant for card lists:** expose a `useDataTable()` hook returning the processed rows + controls so **card-rendered** screens (Clients, Client documents) get the same search/sort/filter/paginate/persist logic without a `<table>`.

### What should NOT use DataTable
Structured **financial statements** (Trial Balance, P&L, Balance Sheet, Cash Flow, Schedule III) — fixed statutory layouts; they need *account search + on-statement export*, not a generic grid. Also **kanban** (Pipeline), **calendar** (Calendar), **dashboards** (Executive/Home/Client/Practice), **chat** (Assistant/Copilot), and **settings forms**. FX Reports and Reconciliation buckets are **partial** (tables that benefit from search/sort/pagination but keep bespoke summary chrome).

---

## 4. Per-screen matrix

Legend for **Current**: S=Search, So=Sort, F=Filter, P=Pagination, E=Export, R=Refresh, L=Loading, Em=Empty, B=Bulk, St=Sticky, Pr=Persisted. ✓=present, ·=absent.

### 4.1 Accounting & Banking  *(client workspace: `app/clients/[id]/accounting`, tabbed)*

| Screen | Current (S So F P E R L Em B St Pr) | Missing / Recommendation | Priority | DataTable |
|---|---|---|---|---|
| **Ledger** (tab) | · · F(basis-no) · · ✓ ✓ ✓ · ✓ · | thousands of rows/account: **add pagination + search (narration/ref) + CSV export + sort toggle (default date DESC)**; make account picker a searchable combobox | **Critical** | Partial→Yes |
| **Journal** (tab) | · · · · · · ✓ ✓ · · · | only a "recent 5" preview exists — **build a full Journal list** (search voucher/narration, date-range filter, pagination, export); fixes broken Dashboard "View all" | **Critical** | Yes |
| **Categorize** (bank, tab) | · · F(status) · · ✓ ✓ ✓ · · · | **bulk categorize/match**, date-range + amount filter, search by description, pagination | **Critical** | Partial (card) |
| **Post** (bank, tab) | · · F(status) · · ✓ ✓ ✓ · · · | **bulk post**, pagination, search, sort by date/amount | **Critical** | Partial→Yes |
| **Reconciliation** (bank, tab) | · · F(status) · ✓ ✓ ✓ ✓ ✓(sel) · · | pagination + search within buckets; bulk-by-rule; PDF workpaper export (CSV exists) | **Critical** | Partial |
| **Approvals** (tab) | · · F(status) · · ✓ ✓ ✓ ·(sel-no) · · | **bulk approve/reject**, pagination, search narration/ref, sort | **Critical** | Partial→Yes |
| **Trial Balance** (tab) | · · F(basis) · ·(→Reports) ✓ ✓ ✓ · · · | **account search + type filter + on-tab export**; keep statutory layout | High | No (report) |
| **P&L / Balance Sheet / Cash Flow** (tabs) | · · F(basis;CF none) · ·(→Reports) ✓ ✓ ✓ · · · | account search within statement; **export on the statement itself** (currently only in Reports tab); optional multi-year compare | High | No (report) |
| **Chart of Accounts** (tab) | · · F(type) · · ✓ ✓ ✓ · · · | search by code/name; active/inactive filter; sort | Medium | Partial→Yes |
| **Reports** (tab) | · · · · ✓ · ✓ ✓ · · · | basis toggle on this tab; Shared-Reports metadata (by/to/date) + filter | High | Partial |
| **Banks** (tab) | · · · · · ✓ ✓ ✓ · ✓(txns) · | search bank/account; sort; pagination on statements & txns; txn status filter | Medium | Partial |
| **FX Reports** (tab) | · · F(currency) · · ✓ ✓ ✓ · · · | export; date/amount filter; pagination for many FX lines | Medium | Partial |
| **Accounting Dashboard** (tab) | — | fix "View all" → full Journal list | Medium | N/A |
| Firm: **Invoices**, **Fixed Assets**, **Suppliers**, **Receivables**, **Loans/FD**, **Recurring**, **Budget**, **Schedule III**, **Lock FY** (`app/accounting/*`) | mostly · · ·/F · · ✓/· ✓ ✓ · · · | invoices & fixed-assets **High** (search/sort/pagination/bulk); others Medium/Low | High–Low | Yes / report |

### 4.2 Sales / Purchases / Billing  *(`app/clients/[id]/{sales,purchases}`, `app/billing`, `app/einvoice`)*

| Screen | Current (S So F P E R L Em B St Pr) | Missing / Recommendation | Priority | DataTable |
|---|---|---|---|---|
| **Sales Invoices** | ✓ ✓ ✓ · · ✓ ✓ ✓ · · ✓(URL) | **best-in-app** — add pagination, bulk (email/print/export), amount/GST/state filters, sticky header | High | Yes |
| **Purchase Bills** | · · · · · ✓ ✓ ✓ · · · | search (bill/vendor/ref), status+vendor+date+AI filters, sort, pagination, amount/TDS filter | High | Yes |
| **Customers** | · · F(active) · · ✓ ✓ ✓ ✓(menu) · · | search (name/GSTIN/email/phone), sort, pagination | Medium | Yes |
| **Vendors** | · · · · · ✓ ✓ ✓ · · · | search, TDS-applicable filter, sort, pagination | Medium | Yes |
| **Receipts** | · · · · · ✓ ✓ ✓ · · · | search, "unallocated only" filter, sort, pagination | Medium | Yes |
| **Payments** | · · · · · ✓ ✓ ✓ · · · | search, vendor/mode/reconciled filter, sort, pagination | Medium | Yes |
| **Credit Notes** | · · · · · ✓ ✓ ✓ · · · | search, status filter, sort, pagination | Medium | Yes |
| **Customer Statements** | ✓(cust) · F(date) · ·(email) ✓ ✓ ✓ · · · | export PDF/CSV; sort statement lines | Medium | Partial |
| **Recurring Invoices** | · · · · · ✓ ✓ ✓ · · · | template search; run-history pagination | Low | No |
| **Billing (firm) invoices** | · · · · ✓(pdf) ✓ ✓ ✓ · · · | search/sort/filter; client filter; bulk email | Medium | Partial |
| **Billing Outstanding (aged)** | · · · · · ✓ ✓ ✓ ·(wa) · · | search/sort; export; keep aged-bucket layout | Medium | No (summary) |
| **E-Invoice** | ✓(load) · · · · ✓ ✓ ✓ · · · | auto-load client; in-list search; status filter | Low | No |

### 4.3 Tax & Compliance  *(`app/{gst,tds,income-tax,mca,compliance,deadlines}`, `app/clients/[id]/{tax,compliance}`)*  — **never add portal auto-submit; export/print only**

| Screen | Current (S So F P E R L Em B St Pr) | Missing / Recommendation | Priority | DataTable |
|---|---|---|---|---|
| **/deadlines** (triage hub) | ·(client-txt) · F(status,type) · · ✓ ✓ ✓ · ✓ · | **sort (overdue first), pagination, GSTIN search, bulk export, saved filter presets** | **Critical** | Yes |
| **/gst/reconciliation** (GSTR-2B) | ·(no in-table) F(status) grouped-sort · ✓(xlsx) · · ✓ · · · | in-table search (GSTIN/inv), variance-**approval log** (CA sign-off), notes | **Critical** | Yes |
| **/mca** (Companies/Filings/Directors/Deadlines) | · · · · · · ✓ ✓ · · · | search CIN/DIN/company/form, sort by due, filter by form type, KYC-overdue styling, export | **Critical** | Partial→Yes |
| **/gst** (filing tracker) | · · F(period) · · · ✓ ✓ · · · | search client/GSTIN, sort due/filed/status, status+form filters, export, pagination | Medium | Yes |
| **/gst/gstr1** (review) | · · · ·(big tables) ✓(json) · ✓ ✓ · · · | search/sort/**pagination** in B2B/B2CS invoice tables (can be >1000 rows) | High | Partial |
| **/gst/gstr3b** (review) | · · · · ✓(json) · ✓ ✓ · · · | drill-down from summary; Rule 36(4) explainer | Medium | No (summary) |
| **/tds** (deductions/challans/returns/certs) | · · · · · · ✓ ✓ · · · | search party/PAN, section+quarter filter, sort, export, deposited/pending toggle | Medium | Partial→Yes |
| **/tds/returns** (builder) | · · · · ✓(json) · ✓ ✓ · · · | search/sort deductees within return | High | Partial |
| **/income-tax** (ITR + advance tax) | · So(due) · · · · ✓ ✓ · · · | search client/PAN, filter entity/AY/form, audit-case highlight, export | Medium | Partial→Yes |
| **/income-tax/notices** | (table; assumed basic) | search, deadline counter, response tracking | High | Yes |
| **/clients/[id]/compliance** (calendar) | · So(date-fixed) F(type-tab) · · · ✓ ✓ · · · | search, sort, CSV/iCal export, inline notes | High | Partial→Yes |
| **/clients/[id]/tax/{filing,computation,26as}** | form/workspace | inherit states; per-screen search where lists appear | High | Mixed |

### 4.4 Clients / Relationships / Lifecycle / Portal / Team

| Screen | Current (S So F P E R L Em B St Pr) | Missing / Recommendation | Priority | DataTable |
|---|---|---|---|---|
| **/clients** (list) | ✓ · F(active/arch) · · ✓ ✓ ✓ ✓(menu) · · | **sort (name/type/city/health), pagination, bulk export/archive/assign, persistence, sticky** | High | Partial (cards→headless) |
| **/relationships** (entity registry) | ✓ · F(type) · · · ✓ ✓ · · · | sort, pagination, export, bulk link-to-client | High | Yes |
| **/pipeline** (prospects) | · · F(stage) · · · ✓ ✓ ✓(card) · · | global lead search, sort within stage, bulk move, export, filter presets | High | No (kanban) |
| **/engagements** | · · F(status-tabs) · · · ✓ ✓ ✓(row) · · | search (client/recipient/no), sort, pagination, bulk send/export, persist tab | High | Yes |
| **/clients/[id]/relationships** | · · · · · · ✓ ✓ · · · | sort, role-type filter, search | Medium | Yes |
| **/clients/[id]/lifecycle** | · · · · · · ✓ ✓ · · · | renewals: sort/filter/export | Medium | Partial |
| **/clients/[id]/health** & **/health** (firm) | ·/· · F(tab) · · ✓ ✓ ✓ · · · | firm Health: **search client, sort by score, export** | High | Partial→Yes |
| **/client-portal** (admin) | · · F(client) · · · ✓ ✓ · · · | sort/search docs & requests; pagination; bulk clear fulfilled | Medium | Partial |
| **/team** | · · · · · · ✓ ✓ · · · | search, role filter, sort, bulk deactivate/role | Low | Partial |

### 4.5 Tasks / Calendar / Workflows / Time / Approvals

| Screen | Current (S So F P E R L Em B St Pr) | Missing / Recommendation | Priority | DataTable |
|---|---|---|---|---|
| **/tasks** | · ✓ ✓(status/pri/assignee/client) ·(200-cap) · ✓ ✓ ✓ ✓ ✓ · | **full-text search, real pagination (remove 200 cap), export, persist filters (URL)** | High | Partial→Yes |
| **/approvals** (governance) | · · F(tabs) · · ✓ ✓ ✓ · ✓ · | search (requester/type/client), sort by urgency, date-range, export | High | Partial |
| **/workflows/approvals** | · · F(status) · · ✓ ✓ ✓ ·(row) ✓ · | search, sort overdue-first, due-date filter, export | High | Partial |
| **/deadlines** | *(see 4.3 — Critical)* | | Critical | Yes |
| **/workflows** | ✓ · F(category) · · ✓ ✓ ✓ · · · | sort by runs/success; pagination; persist | Medium | No (cards) |
| **/time** | · · F(export-only) ·(100-cap) ✓ · ✓ ✓ · · · | in-table search/sort; raise limit; display filters | Medium | Partial |
| **/calendar** | · So(date) F(legend) · · · ✓ ✓ ·(toggle) ✓ · | client filter, deadline search, CSV/iCal export | Medium | No (calendar) |
| **/work** (my work) | · · F(implicit) ·(slice8) · · ✓ ✓ · ✓ · | refresh; reveal sliced tail | Low | No (dashboard) |
| **/tasks/templates** | · · · · · · ✓ ✓ · · · | search/sort (small set) | Low | No (cards) |
| **/clients/[id]/tasks** | · · · ·(100-cap) · · ✓ ✓ · · · | link to detail; escalate to /tasks | Low | No |

### 4.6 Documents / Knowledge / AI / Notifications / Payroll / Risks / Platform / Settings

| Screen | Current (S So F P E R L Em B St Pr) | Missing / Recommendation | Priority | DataTable |
|---|---|---|---|---|
| **Payroll** (employees/runs/payslips/statutory) | · · F(client/month) ·/· ✓(files) · ✓ ✓ · · · | **employee search (name/PAN), sort, bulk payslip download**, run history/sort | High | Partial→Yes |
| **/risks** | · · · · ✓(csv-register) ✓ ✓ ✓ · · · | cross-category search/sort/filter; unified register; per-selection export | High | Partial→Yes |
| **/platform** (admin firms) | · · · · · ✓ ✓ ✓ · · · | search firm, sort, status filter, bulk suspend | High | Partial→Yes |
| **/documents** (firm) | ✓ So(date-fixed) F(client/type/FY) · · · ✓ ✓ · · · | pagination, clickable sort, bulk download, export, sticky | Medium | Partial→Yes |
| **/notifications** | · · F(tab+type) ·(100-cap) · ✓ ✓ ✓ ✓(mark-all) · · | text search, multi-select archive, pagination | Medium | Partial |
| **/knowledge** & client knowledge | ✓(enter) · ·(url-scope) · · ✓ ✓ ✓ · · · | sort, in-UI scope/department filter, pagination | Medium/Low | No (accordion) |
| **/settings/audit-log** | *(not audited — verify separately)* | expect search/date-range/actor filter, pagination, export | High | Yes |
| **/clients/[id]/documents** | · · · · · · ✓ ✓ · · · | search/filter/sort; bulk download | Low | No (tiles) |
| **/clients/[id]/ai-insights**, **/memory**, **/copilot**, **/ai-assistant** | cards/feed/chat | N/A (not generic lists) | Low/N/A | No |
| **Dashboards** (executive/home/client/practice), **Settings** forms | widgets/forms | N/A | N/A | No |

---

## 5. Cross-cutting recommendations (in order)

1. **Build `DataTable` + `useTablePreferences`** (Section 3). One component; client-side by default.
2. **Ledger & Journal first** — highest volume + a missing full Journal list; consider server-side `.range()` paging for these two specifically.
3. **Banking month-end (Categorize/Post/Approvals/Reconciliation)** — add multi-select + bulk toolbar + date/amount filters; reuse the good Reconciliation checkbox pattern as the template.
4. **Compliance triage (/deadlines, /gst/reconciliation, /mca)** — sort-overdue-first, search, export, and a variance-approval log for GSTR-2B. **No portal auto-submit.**
5. **Roll DataTable across Sales/Purchases/Customers/Vendors/Receipts/Payments/Documents/Payroll/Risks/Platform/Relationships/Engagements.**
6. **Add account-search + on-statement export** to TB/P&L/BS/CF (keep statutory layout; not DataTable).
7. **Standardise states** — replace bespoke 3-state ladders with `AsyncBoundary`; adopt everywhere for consistency.
8. **Persist preferences** — generalise Sales-invoices' URL pattern via `useTablePreferences` (URL + localStorage).
9. **Kill silent caps** — remove hidden `limit: 100/200` and `slice()` truncations; surface counts + pagination.

## 6. Phased delivery

- **Phase 1 (Critical, ~2 wks):** `DataTable` + hook; apply to Ledger, Journal (new), Sales Invoices, Purchase Bills, /deadlines. Bulk toolbar for Categorize/Post/Approvals.
- **Phase 2 (High, ~3 wks):** search/filter/sort/pagination across Customers, Vendors, Receipts, Payments, Relationships, Engagements, Tasks, Payroll, Risks, Health, Platform; GSTR-2B variance log; statement account-search + export.
- **Phase 3 (Medium, ~2 wks):** column-visibility, CSV export, sticky headers, bulk email/print/download; Documents/Notifications/COA/GST tracker/TDS/ITR.
- **Phase 4 (Polish, ~1 wk):** `AsyncBoundary` everywhere; standard FY + custom date-range picker; sort indicators; `/settings/audit-log` verify + upgrade.

## 7. Notes & open items
- **Not audited in depth (verify next):** `/settings/audit-log`, `/clients/[id]/year-end/[id]/*` sub-tabs, `/reports` (global), `/clients/[id]/coa`, some `app/accounting/*` firm pages (Suppliers/Receivables/Loans/Budget/Schedule-III). Assumed table-based; likely High/Medium.
- **Domain guardrail:** tax/compliance bulk actions must remain export/print/download only — never portal submission (CA-review gate).
- **Primitive adoption is uneven** — Tasks/Calendar/Workflows already use `AsyncBoundary`/`EmptyState`; Sales/Purchases/Clients/Accounting do not. The DataTable rollout is the opportunity to unify.
