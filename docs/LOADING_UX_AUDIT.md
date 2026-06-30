# Loading-UX Audit & Improvements

> Read-first audit of every PracticeSync route, plus a reusable loading-component
> library and a first wave of fixes. Goal: the app should never leave the user
> wondering whether something is happening.

---

## 1. Audit report (Phases 1–2)

**Method.** Four parallel read-only passes over `apps/web` catalogued every page
that fetches data and classified its current state (skeleton / spinner / none ·
empty state · error state). Baseline measured by grep: **161 pages — 119 track a
loading state, 49 use skeletons, 49 use spinners, and there was no shared
`Skeleton` primitive** (only ad-hoc `animate-pulse` in two components).

**Consolidated verdicts (active, data-fetching pages):**

| Category | ~count | Meaning |
|---|---|---|
| OK (skeleton + empty + error) | ~45 | Dashboard, Clients, Engagements, Deadlines, Billing, Risks, Executive Dashboard, Health, Payroll, MSME, Budget, Schedule III, Year-End, Account Groups, Notifications, client Overview/Accounting/Sales, portal, … |
| SPINNER-ONLY (text/spinner, no skeleton) | ~28 | Pipeline, Approvals, Settings, GSTR-1/3B, Income-tax mark-filed, Relationships (x2), Knowledge, Portal dashboard, Invoices, Suppliers, Fixed-assets, Lock-year, Retainer, COA export, AI-insights, … |
| BLANK / silent failure (no error UI) | ~12 | Calendar (client fetch), GST reconciliation upload, e-invoice Load, compliance notice-extraction, Copilot initial load, `clients/[id]/portal`, payroll employees import, … |
| SEQUENTIAL FETCH WATERFALL | 3 | `clients/[id]/overview` (compliance→seed→reload→health), `portal/dashboard` (memberships→dashboard), `clients/[id]/accounting` dashboard (P&L then cash-flow) |
| BUTTON without loading/disabled | ~20+ | GST Approve/Mark-filed/Download-JSON, compliance Extract-notice, e-invoice actions, Copilot accept/snooze/dismiss, Relationships "Detect", a few menu/secondary actions |
| FILE UPLOAD without progress | ~8 | GST/2A CSV, TDS import, payroll import, trial-balance import, portal uploads, e-invoice |
| REDIRECT (no fetch — not an offender) | 7 | `accounting/{chart-of-accounts,journal,ledger,trial-balance,cash-flow,bank-*}`, `reports/financial-statements` |
| STUB (placeholder, little/no fetch) | ~18 | income-tax sub-pages, health sub-pages, `assistant`→`ai-assistant`, year-end XBRL, `clients/[id]/reports` |

**Strengths found.** Most core pages already have error banners and optimistic
updates with rollback (pipeline move/delete, notifications archive). Auth and
modal forms generally disable submit during save.

**Systemic gaps.** (1) No shared skeleton — every page rolls its own, so many fall
back to a "Loading…" string. (2) A long tail of API buttons and file uploads
lacks loading/disabled feedback. (3) A few pages fail silently (no error state).
(4) Three fetch waterfalls hurt perceived speed.

---

## 2. Pages that previously lacked good loading UX (now improved this pass)

| Page | Before | After |
|---|---|---|
| `app/pipeline/page.tsx` | "Loading leads…" text over empty columns | **Kanban column skeleton** (header + 3 card placeholders per stage) |
| `app/approvals/page.tsx` | "Loading…" text | **ListSkeleton** rows |
| `app/settings/page.tsx` (Firm Profile) | "Loading…" text in card | **FormSkeleton** (6 fields) |
| `app/accounting/invoices/page.tsx` | full-page "Loading invoices..." text | **PageLoader** (centered spinner + label) |
| `app/accounting/suppliers/page.tsx` | "Loading…" text in table card | **TableSkeleton** (bare, embedded) |
| `app/accounting/fixed-assets/page.tsx` | "Loading…" text (whole page) | **TableSkeleton** (6×6) |
| `app/accounting/lock-year/page.tsx` | "Loading…" text in card | **TableSkeleton** (bare, embedded) |

These span four modules (CRM, settings, accounting) and demonstrate every new
primitive. The remaining SPINNER-ONLY pages can adopt the same one-line swap
(see backlog §8).

---

## 3. Files modified

- **New shared library:** `components/ui/skeleton.tsx`, `components/ui/states.tsx`,
  `components/ui/async-state.ts`, `components/ui/submit-button.tsx`.
- **New tests:** `components/ui/async-state.test.ts`.
- **Pages updated:** `app/pipeline/page.tsx`, `app/approvals/page.tsx`,
  `app/settings/page.tsx`, `app/accounting/invoices/page.tsx`,
  `app/accounting/suppliers/page.tsx`, `app/accounting/fixed-assets/page.tsx`,
  `app/accounting/lock-year/page.tsx`.

---

## 4. Shared loading components introduced (Phase 4)

Single source of truth, matching the app's slate palette and the
existing `cn()` util. No duplicate implementations.

**`components/ui/skeleton.tsx`**
- `Skeleton` — base shimmer block (compose anything).
- `SkeletonText({lines})` — paragraph placeholder.
- `Spinner({label})` — accessible inline spinner.
- `PageLoader({label})` — centered page/region loader (for page transitions).
- `TableSkeleton({rows,cols,bare})` — table rows; `bare` embeds inside an
  existing card.
- `MetricCardSkeleton` / `DashboardSkeleton({cards})` — KPI cards.
- `ListSkeleton({rows})` — avatar + two-line rows.
- `CardGridSkeleton({count})` — card grids (templates, etc.).
- `FormSkeleton({fields})` — modal/drawer form placeholders.
- `ClientHeaderSkeleton` — client-workspace header.
- `TimelineSkeleton({rows})` — activity timelines.
- `ChartSkeleton({height})` — report/chart placeholder.

**`components/ui/states.tsx`**
- `EmptyState({icon,title,description,action})` — distinct "no data" state with CTA.
- `ErrorState({title,message,onRetry})` — error + retry button.
- `AsyncBoundary({loading,error,isEmpty,onRetry,skeleton,empty,children})` —
  renders exactly one of error → loading → empty → content.

**`components/ui/async-state.ts`**
- `resolveAsyncState({loading,error,isEmpty})` — the pure precedence used by
  `AsyncBoundary` (unit-tested).

**`components/ui/submit-button.tsx`**
- `SubmitButton({loading,loadingText})` — shows a spinner and disables to prevent
  double-submit. (Hand-styled buttons can get the same effect with
  `disabled={busy}` + the shared `<Spinner/>`.)

**Adoption pattern (one-liner per page):**
```tsx
{loading ? <TableSkeleton rows={6} cols={5} /> : <RealTable/>}
// or, end-to-end:
<AsyncBoundary loading={loading} error={error} isEmpty={rows.length===0}
  onRetry={reload} skeleton={<TableSkeleton/>} empty={<EmptyState title="No invoices yet"/>}>
  {table}
</AsyncBoundary>
```

---

## 5. Performance / perceived-performance

- **Perceived speed (done):** replacing blank/text loaders with content-shaped
  skeletons removes the "is it frozen?" gap and prevents layout jump on data
  arrival (skeletons mirror the real layout). Applied to the 7 pages above.
- **Fetch waterfalls (identified, not yet refactored):** three were found —
  `clients/[id]/overview` (compliance → seed → reload → health; partly inherently
  sequential), `portal/dashboard` (memberships → dashboard/dues), and
  `clients/[id]/accounting` dashboard (P&L then cash-flow in separate effects).
  These touch data-loading order, so they are listed for a focused follow-up
  rather than changed blindly here (the brief says *do not change business
  logic*). Recommended fix: `Promise.all` the genuinely independent calls.

---

## 6. Regression tests added (Phase 8)

- `components/ui/async-state.test.ts` — 5 tests covering the error → loading →
  empty → content precedence (incl. null/empty-string error handling). Run:
  `node --experimental-strip-types --test components/ui/async-state.test.ts`.
- **Build-level regression:** `npx tsc --noEmit` clean, `npx eslint` clean on all
  changed files, and a full `npx next build` succeeds (all routes prerender).
- **Manual visual checklist** for the changed pages: no blank screen on first
  paint, skeleton matches final layout (no jump), single loader (no double
  spinner), error banner + retry where data fails, distinct empty state.

---

## 7. Confirmation

Every page changed in this pass now shows a content-shaped loading state instead
of a blank screen or bare "Loading…" text, and the reusable library makes the
correct pattern a one-liner for the rest of the app. The build, type-check, lint
and unit tests are all green.

---

## 8. Prioritized backlog (remaining, with the exact fix)

Adopting the new library, in priority order:

1. **Silent-failure pages → add `ErrorState`/`AsyncBoundary`:** `app/calendar`
   (client fetch), `app/copilot` + `clients/[id]/ai-insights` (swallowed errors),
   `app/einvoice` (Load button: add `disabled={loading}` + error state).
2. **SPINNER-ONLY → skeleton (one-line swap):** `gst/gstr1`, `gst/gstr3b`,
   `relationships`, `clients/[id]/relationships`, `clients/[id]/knowledge`,
   `portal/dashboard` (use `DashboardSkeleton` + `TableSkeleton`),
   `accounting/retainer`, `accounting/coa-export`.
3. **API buttons without feedback → `disabled={busy}` + `<Spinner/>`:** GST
   Approve / Mark-filed / Download-JSON, compliance Extract-notice, e-invoice
   Create / Record-IRN, Copilot accept/snooze/dismiss, Relationships "Detect".
4. **AI "thinking" indicator:** show a typing placeholder in `copilot` /
   `ai-assistant` while a response is in flight.
5. **File-upload progress:** GST/2A, TDS, payroll, trial-balance imports, portal
   uploads — switch to `XMLHttpRequest.upload.onprogress` with a progress bar.
6. **Fetch waterfalls:** parallelize the three independent chains in §5.

---

*Audit performed read-first across all 161 pages. The first wave of fixes is
intentionally scoped to be safe and reviewable; the library + backlog make the
remaining adoption mechanical and low-risk. No business logic was changed.*
