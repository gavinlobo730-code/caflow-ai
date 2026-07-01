# Final Pre-Merge Audit — Platform-wide Search/Sort/Filter (DataTable)

**Date:** 2026-07-01 · **Branch:** `claude/dazzling-curie-a55bpf` · **Gate:** final engineering/UX/regression review before merge.

Method: the shared engine was deep-reviewed by hand; all 17 migrated page files were
audited by four independent reviewers that **diffed each migration against its
pre-migration parent** and traced behaviour, then genuine issues were fixed centrally
and the whole tree re-verified.

## 1. Pages audited (17 files, ~25 tables) + shared foundation
- **Foundation:** `lib/table/{process,useDataTable,useTablePreferences,types}.ts`, `components/ui/data-table.tsx`.
- **Sales** (Invoices/Receipts/Credit-Notes/Customers), **Purchases** (Bills/Vendors/Payments).
- **Accounting** (Ledger, new Journal list, Chart of Accounts) — statements & banking tabs verified untouched.
- **Deadlines, GST, TDS, MCA, Income-Tax.**
- **Relationships, Documents, Platform, Notifications, Health, Engagements, Risks, Payroll, Tasks.**

## 2. Issues found, severity & fixes applied

| # | Area | Severity | Finding | Resolution |
|---|---|---|---|---|
| 1 | Engine `applySort` | **Low** | Descending sort placed blank/null values **first** (nullish was multiplied by the sort direction). | **Fixed** — nulls now always sort last in both directions; added a regression test (engine 9/9). |
| 2 | Sales → Customers | **Medium** (regression) | Default view silently changed from **active-only** to "All" after migration. | **Fixed** — added an `initialFilters` prop to the DataTable and set the Customers table's default to `is_active=active` (loader fetches all, so Inactive/All still work). Parity restored + capability added. |
| 3 | Accounting → Ledger | **Medium** (UX) | The running-**Balance** column was `sortable`; sorting by it yields a non-progressive, misleading sequence (running balance is chronological-only). | **Fixed** — column set to `sortable: false`. Values were always correct; date/debit/credit sorting unaffected. |

No **Critical** or **High** issues survived verification.

### Reviewer findings triaged as non-issues (no change needed)
- **Sales "Customers loader still active-only" (reported HIGH):** false positive — the reviewer conflated the Receipts form's customer **dropdown** loader (correctly active-only) with the Customers **tab** loader, which fetches all. Verified by component boundaries; issue #2 above is the real, fixed regression.
- **Receipts "unallocated" filter recomputes inline (Medium):** produces correct results; minor duplication only — not a bug or regression.
- **Customers status filter uses `select` string-mapping vs `boolean` type (Low):** cosmetic; works correctly.

## 3. Verification performed
- **Functionality:** every original row action, modal, detail panel/drawer, create/edit form, MFA purge gate, cross-tab navigation and URL params confirmed preserved across all pages.
- **Search / Sort / Filters / Pagination / Column visibility / Bulk / Export / Persistence:** verified per screen; accessors return integer **paise** for money (right-aligned; CSV exports rupees) and raw **ISO** for dates (correct chronological sort); badge columns sort by rank (severity/grade/priority/KYC-days), not alphabetical; bulk actions reuse existing handlers with confirms; exports emit the **filtered** view with correct headers.
- **Domain safety (tax/compliance):** **no** government-portal auto-submit was introduced anywhere; every "DO NOT AUTO-SUBMIT"/CA-review notice and the CA-confirmed Mark-Filed flows are intact; `/deadlines` URL `?type=` scoping + filter-suppression preserved (no double-filtering).
- **Regression:** accounting statements (TB/P&L/BS/CF/Schedule III/FX) and all banking tabs have **zero** diff hunks; payroll computation + statutory downloads untouched; no accounting math, API, permission or validation changed.
- **Build/quality:** `tsc --noEmit` clean · `eslint` clean · engine unit tests **9/9** · `next build` → **✓ Compiled successfully**.

## 4. Remaining risks (Low / non-blocking)
- **Client-side model:** search/sort/filter/paginate run over the full fetched dataset (via `selectAll`). Correct and fast at SMB scale; for a client with tens of thousands of ledger/journal rows, a future server-side pagination mode is advisable (tracked in the migration summary follow-ups).
- **Risks register `getRowId`** is composed from row fields (no DB id); an exact-duplicate row would only cause a React key warning (no selection on that table) — cosmetic.
- **Behaviour refinements (intentional, documented):** money now shows 2 decimals consistently; `/deadlines` search/filters persist across `?type=` switches; accounting Journal lists drafts too (with a Status badge).
- **Column-visibility menu** uses a native `<details>` popover (no outside-click-to-close) — minor UX, not a defect.

## 5. Verdict

**The branch is production-ready and suitable for merge.** All discovered genuine issues (one Low engine bug, one Medium regression, one Medium UX) were fixed and re-verified; no Critical/High issues remain; existing accounting logic, APIs, permissions, validations, calculations and workflows are unchanged; and the full platform builds and lints clean with the shared DataTable delivering consistent search/sort/filter/pagination/export/persistence across every migrated screen.
