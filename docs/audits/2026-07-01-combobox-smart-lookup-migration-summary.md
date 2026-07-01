# Platform-wide Searchable Combobox & Smart Lookup — Migration Summary

**Date:** 2026-07-01 · **Branch:** `claude/dazzling-curie-a55bpf` · **Type:** implementation of the approved
[combobox/smart-lookup audit](./2026-07-01-combobox-smart-lookup-audit.md).

Additive only. No accounting math, API contract, permission, or validation was changed. Every
phase left the app `tsc`-clean, `eslint`-clean and `next build`-green; the backend suite and the
frontend engine unit tests pass throughout.

---

## 1. Components created

### Reusable foundation (mirrors the shipped DataTable split)
| File | Role |
|---|---|
| `lib/combobox/match.ts` | Pure, unit-tested matcher/ranker (exact > prefix > word-prefix > includes > multi-token). |
| `lib/combobox/useCombobox.ts` | Headless hook: sync client-side filter **or** debounced async server search; loading/error; highlighted index; create-row flag. |
| `components/ui/combobox.tsx` | Presentational `<Combobox>` — button trigger + searchable popover; WAI-ARIA combobox/listbox, full keyboard nav, recent-first, rich rows, loading/empty/error states, optional "+ Create" row. |
| `lib/combobox/{types,index}.ts` | Types + barrel. |
| `lib/combobox/match.test.ts` | 10 unit tests (`node --test`). |

### id-string-controlled wrappers (near drop-in for the old `<select value={id}>`)
| Component | Backing | Search fields |
|---|---|---|
| `EntityLookup<T>` | shared adapter (id ⇄ object; sync or async; caches selection) | configurable |
| `CustomerLookup` | already-loaded customers (sync) | name, GSTIN, PAN, email, phone |
| `VendorLookup` | already-loaded vendors (sync) | name, GSTIN, PAN, email, phone |
| `AccountLookup` | already-loaded Chart of Accounts (sync) | account name, code (shows code · type) |
| `ClientLookup` | already-loaded CA clients (sync) | client name, PAN, GSTIN |
| `HsnLookup` | **async** `GET /api/hsn/search` | HSN/SAC code, description (master + firm history) |
| `StateLookup` | canonical GST state codes (`lib/constants/indianStates.ts`) | 2-digit code, state name |

**Rich rows:** Customer/Vendor show GSTIN (+ outstanding when available); Account shows code · type; HSN shows
description · GST rate · UQC.

---

## 2. Endpoints added

| Endpoint | Purpose |
|---|---|
| `GET /api/hsn/search?q=&type=&client_id=&limit=` | Smart HSN/SAC lookup over the canonical `hsn_master` (migration 036) **merged with** the firm's own usage history (`hsn_sac_preferences`, migration 101), de-duped by code, history first. Returns a pre-fill hint: description, GST rate (integer bps), UQC. `routers/hsn.py`, 6 unit tests. CGST Rule 46(g): the rate is a hint only — never used in any GST/journal computation without the existing CA-review path; every value stays CA-overridable. |

**Why only HSN got a server endpoint:** customers, vendors, accounts and clients are **client-scoped and
already fully loaded per screen** (bounded sets), so their lookups run client-side — matching the audit's own
scalability guidance ("client-side for small datasets"). `hsn_master` is thousands of rows and is *not* loaded
in the browser, so it is the one genuine server-search case. The `fetchOptions` prop on every wrapper is the
ready seam to switch any picker to debounced server search if a tenant's list ever outgrows client-side.

---

## 3. Screens updated

### Transaction smart lookups
- **Sales** (`clients/[id]/sales`): Customer picker on invoice / receipt / credit-note / recurring forms, the
  invoices-tab customer filter, and the statements tab (redundant manual search box removed). Invoice + credit-note
  line **HSN** → `HsnLookup` (pre-fills GST rate on select). Supply-state + customer state-code → `StateLookup`.
- **Purchases** (`clients/[id]/purchases`): Vendor picker (bill + payment forms; TDS banner preserved), bill-line
  **HSN** → `HsnLookup`, bill-line **expense account** → `AccountLookup`, payment "Against Bill" → searchable
  open-bill picker, **TDS section** → searchable Combobox (rate auto-fill preserved).

### Accounting
- **Chart-of-Accounts pickers** → `AccountLookup`: journal-entry line, ledger viewer (loadLedger preserved),
  bank-reconcile counter-account.
- **Suppliers**: TDS section → searchable Combobox (rate auto-fill preserved).

### CA-client pickers → `ClientLookup` (searchable by name / PAN / GSTIN)
GST (gstr1, gstr3b, gst, reconciliation) · income-tax (advance-tax, capital-gains, deductions, notices, tax-audit) ·
accounting (invoices ×2, receivables, schedule-iii, suppliers, fixed-assets, loans ×2, msme-tracker) · documents ×2 ·
billing · practice/billing · mca · tds/returns · payroll (×4) + statutory · reports + cash-flow ·
notifications/whatsapp · client-portal · settings/scheduled-reports.
"All Clients" filters that use an `"all"` sentinel map `all ⇄ ""` with a clearable reset so the All view stays
reachable.

### Tasks / enums
- **TaskFormModal**: client → `ClientLookup`, assignee → searchable team-member `EntityLookup` (clearable
  "Unassigned"), task-type → searchable Combobox.
- **income-tax/notices**: notice-type → searchable Combobox.

---

## 4. Search fields supported (recap)
- **Customer / Vendor:** name, GSTIN, PAN, email, phone.
- **Account:** account name, account code (type shown).
- **Client:** client name, PAN, GSTIN.
- **HSN/SAC:** code (prefix) OR description (substring), across master + firm history.
- **State:** 2-digit GST code OR state name.
- **TDS section / notice type / task type:** code and label.

---

## 5. Intentionally left as native dropdowns
- **Bounded enums** (per the audit): GST rate slabs, payment mode/terms, status/priority/workflow-state,
  financial/assessment year, quarter/month, entity/return type, currency filter, unit/UQC, bank name, DSC type,
  user role, etc.
- **Bank-account pickers** (2–10 items per client).
- **Name-based "state" fields** — firm-profile state (settings, onboarding) and the *manual*-invoice
  `place_of_supply` (accounting/invoices) store a state **name**, not a GST code. `StateLookup` is code-based, so
  converting them would change the persisted data contract; they were kept native. (The GST *code* place-of-supply
  on the client sales invoice **is** converted.)

---

## 6. Remaining recommendations (Low priority; seams ready)
- Additional **assignee/team** pickers (tasks list filter, work-allocation, approvals) → team-member `EntityLookup`.
- **tds/page** TDS-section and **task-templates** page task-type → searchable Combobox.
- **Relationships** linked-entity picker (`clients/[id]/relationships`) → `EntityLookup` (search name/PAN).
- **Products/Services** master + `…/search` endpoint — deferred until inventory exists (no master today).
- Optional **recent/favourite** affordances and context-aware defaults (the `recent` prop already exists).

---

## 7. Verification
- **Frontend:** `tsc --noEmit` clean · `eslint` clean · `next build` ✓ (165/165 static pages) · combobox matcher
  **10/10** + DataTable engine **9/9** (`node --test`).
- **Backend:** full suite **2132 passed** / 43 skipped; the 23 failures are the pre-existing
  DB-connectivity cases in `test_phase3_{gst,mca,tds}` (unchanged baseline) — no new failures.
- **Behaviour preserved:** every dependent auto-fill (invoice credit terms / due date / supply state / interstate;
  vendor TDS; HSN → GST rate; account selection; loadLedger; loadOpenBills; selectClient) and every form
  validation, filter sentinel and disabled state was carried across unchanged.
