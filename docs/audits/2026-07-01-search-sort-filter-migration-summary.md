# Platform-wide Search/Sort/Filter — Migration Summary

**Date:** 2026-07-01 · **Scope:** `apps/web` · Companion to the audit `2026-07-01-search-sort-filter-ux-audit.md`.

Implemented a single reusable table-interaction system and rolled it across every
logical list/table screen. Verified: **`next build` ✓ Compiled successfully**, `tsc`
clean, `eslint` clean, engine unit tests **8/8**. Delivered in 12 pushed commits.

## 1. Shared foundation (`lib/table/*` + `components/ui/data-table.tsx`)

Headless, client-side engine composed over existing primitives (`selectAll`,
`AsyncBoundary`, `TableSkeleton`, `formatting`) — no backend changes.

- `lib/table/process.ts` — pure search→filter→sort→paginate + CSV (unit-tested, `node --test`).
- `lib/table/useDataTable.ts` — headless hook: state, sort, filters, pagination, column visibility, row selection.
- `lib/table/useTablePreferences.ts` — `localStorage` persistence (search/sort/filters/pageSize/visible columns).
- `components/ui/data-table.tsx` — `<DataTable>`: debounced global search, `select`/`dateRange`/`amountRange`(₹→paise)/`boolean` filters, sortable sticky headers, 25/50/100/250 page sizes, column-visibility menu, bulk-select toolbar, CSV export of the filtered view, loading/empty/error states, responsive + a11y (`aria-sort`, labels). Slate design preserved.

Every migrated screen therefore gains, uniformly: **search · sort · filters · pagination · column visibility · sticky header · CSV export · preference persistence · consistent loading/empty/error**, plus bulk actions where they make sense.

## 2. Pages updated (17 files, ~25 tables)

| Module | Screen(s) | Notable filters / bulk / notes |
|---|---|---|
| Relationships | Entity Registry | entity-type filter; reference migration |
| Documents | Documents | client/type/FY/date filters; row download+delete |
| Platform | Firms admin | status filter; suspend/purge row actions |
| Notifications | Notifications | type filter; **bulk mark-read/archive**; kept server tabs |
| Health | Client Health (firm) | grade/band filters; row→overview |
| Engagements | Letters | status filter; fee (paise) sort; row lifecycle actions |
| Risks | Consolidated Risk Register | category+severity filters; days-overdue/amount sort |
| Payroll | Employees, Payslips | employee search; month filter; PF/ESI filters; View row action |
| Tasks | Task list | **global search (new)**; **bulk complete/delete**; removed silent 200-row cap |
| Deadlines | Compliance triage | status/type/date filters; **overdue-first sort**; honours URL `type` |
| Income-Tax | ITR Status | entity/AY/form/status filters; CA-confirm mark-filed preserved |
| GST | Filing tracker | status/form/period filters; mark-filed preserved |
| TDS | Deductions | section/quarter filters; money (paise); footer total kept |
| MCA | Companies, Filings, Directors | form-type filter; KYC-overdue-first; mark-filed preserved |
| Sales (client) | Invoices, Receipts, Credit Notes, Customers | status/date/amount + "unallocated only" + active/inactive; all row actions + detail drawer; FY/customer selectors in toolbar |
| Purchases (client) | Bills, Vendors, Payments | status/vendor/date/amount + AI-extracted + TDS-applicable; bill form + receive/pay preserved |
| Accounting (client) | Ledger, **Journal (new full list)**, Chart of Accounts | date/type filters; **fixed broken Dashboard "View all"**; fixed latent zero-amount bug in old journal preview |

## 3. Features added (every migrated table)
Global search · column sorting · multi-filter (select / date-range / amount-range in paise / boolean) · pagination with 25/50/100/250 rows-per-page · column visibility · sticky headers · CSV export of the *filtered* view · loading skeletons / empty / error states · responsive horizontal scroll · accessibility · persisted preferences. Bulk selection + actions added where a safe multi-row operation exists (Tasks, Notifications).

## 4. Pages intentionally excluded (and why)
- **Financial statements** — Trial Balance, P&L, Balance Sheet, Cash Flow, Schedule III, FX Reports: fixed statutory/report layouts, not generic tables. (They already reconcile with the GL; the useful add there is account-search + on-statement export — a targeted follow-up, not a DataTable.)
- **Dashboards** — Executive, Home, Client Overview, Practice: KPI/widget summaries.
- **Chat / feed UIs** — AI Assistant, Copilot, Memory, client AI-Insights: conversational, not tabular.
- **Pipeline** — kanban board; **Calendar** — temporal grid.
- **Settings** — forms; **Onboarding** — wizard.
- **Customer/Vendor Statements & Recurring invoices** — semi-structured statement / low-volume templates (left as-is; Statements tab keeps its selector + date range).
- **Knowledge** — accordion with existing search; low volume.
- **Banking month-end tabs** (Categorize / Post / Approvals / Reconciliation) — card/tab workflows; their bulk toolbars are a dedicated follow-up (below).
- **TDS Challans/Returns/Certificates, Payroll Monthly-Run/Statutory** — form/summary flows behind selectors.
- **Client-scoped embedded sub-lists** (client tasks/documents/knowledge/relationships/lifecycle) — small in-context lists; escalate to the main modules.

Guardrail honoured on all tax/compliance screens: **no bulk/row action submits to a government portal** — only export/print and the existing CA-confirmed mark-filed.

## 5. Behaviour changes to be aware of (intentional)
- **Sales → Customers** default view is now **All** (was active-only): the active/inactive segmented control became a client-side filter and `load()` now fetches all customers. Restoring active-only-by-default needs a small `initialFilters` prop on `DataTable` (follow-up).
- **Deadlines**: status/search now persist across URL `type` switches (localStorage) — a minor UX refinement; the load-bearing "no stale type filter under a URL type" is preserved.
- **Money in CSV/exports** emits rupee strings (e.g. `₹1,234.56`); some money cells now show 2 decimals consistently via `formatPaise`.
- **Risks register** rows have no DB id, so `getRowId` is composed from fields; a theoretical exact-duplicate row would only cause a React key warning (no selection on that table).
- **Accounting Journal** now lists posted **and** draft (non-deleted) entries with a Status badge (the old preview showed drafts too).

## 6. Follow-up recommendations
1. **Banking month-end bulk toolbars** — multi-select + bulk categorize / post / approve / reconcile (highest remaining workflow win).
2. **`DataTable` `initialFilters` prop** — so screens like Customers can default a filter (restore active-only).
3. **Server-side pagination for Ledger/Journal** at very high volume (today: client-side over the complete fetch — fine for SMB scale).
4. **Financial statements**: add account-search + on-statement CSV/PDF export (keep statutory layout).
5. **Remaining lists**: `/client-portal` admin, `/workflows`, `/time`, `/calendar` client filter, and the client-scoped embedded sub-lists.
6. **GSTR-2B**: variance-approval (CA sign-off) log, per the audit.
7. **Statements**: PDF/CSV export + email; **Payroll**: bulk payslip download once a per-row download handler exists.

## 7. Verification
`next build` → **✓ Compiled successfully**; `tsc --noEmit` clean; `eslint` clean on all changed files; `node --test lib/table/process.test.ts` → **8/8**. Each screen was migrated preserving its existing business logic (forms, modals, API calls, role gating, CA-review notices); only the list search/filter/table markup changed.
