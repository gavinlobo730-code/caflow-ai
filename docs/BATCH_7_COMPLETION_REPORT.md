# Batch 7 Completion Report — Frontend & Workspace Experience

**Amendment v1.1 (Phase 10B) · Batch 7 (frontend-only) · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14

Implemented to `docs/BATCH_7_DESIGN_REVIEW.md` + the locked decisions. Frontend-only:
**zero backend changes**, **no new business logic** — UI fetches the Batch 1–6 APIs and
displays; all aging/GST/overdue/totals/visibility computed server-side.

## Screens implemented
**Rail-1 "Practice" (Partner-only)** — `/practice` shell with sections:
- **Overview** (`/practice`) — KPI cards (receivable, overdue, TDS receivable, collected) + provisioning gate ("Set up Practice").
- **Revenue** (`/practice/revenue`) — KPIs + active-schedule count + quick links.
- **Billing** (`/practice/billing`) — schedules list + create + per-schedule "Generate draft"; CA-confirm note.
- **Collections** (`/practice/collections`) — overdue/receivable/collected + "Run sweep" / "Send reminders".
- **AR Aging** (`/practice/ar`) — Current/0–30/31–60/61–90/90+ buckets (paise + counts) + totals.
- **Knowledge Base** (`/practice/knowledge`) — routes to the Knowledge workspace.
- **Instructions** (`/practice/instructions`) — the internal client's standing instructions.

**Rail-1 "Knowledge" (all staff)** — `/knowledge`: firm/department article list, search, tags,
scope filter, **author** (Manager+), **version history + restore** (rollback).

**Client workspace additions** — `/clients/[id]/knowledge` (client-scoped articles, assignment-gated)
and `/clients/[id]/instructions` (CRUD); **pinned instruction cards on the client Overview**.

**Legacy `/billing` (fee_*) untouched** (Partner+Manager, unchanged).

## Components added
- `components/panels/PracticePanel.tsx`, `KnowledgePanel.tsx` (Rail-2 nav).
- `components/practice/PartnerGuard.tsx` (route-level G1 guard).
- `components/knowledge/ClientInstructions.tsx` (shared list/CRUD + `pinnedOnly` read mode).
- Wired into `components/ContextPanel.tsx`.

## APIs consumed (no logic, fetch+display)
`api.practice.{get,provision}`; `api.billing.{listSchedules,createSchedule,generate,
arAging,dashboard,sweep,sendReminders,listSchedules(active)}`; `api.knowledge.{listArticles,
createArticle,getArticle,listVersions,restoreVersion,clientArticles}`;
`api.instructions.{list,create,update,archive}`. (Plus `api.salesInvoices`/`receipts`
namespaces added for the CA-confirm/receipt flows.)

## Permission verification results
`lib/auth/permissions.test.ts` (6 tests, `node --experimental-strip-types --test`) — **all pass**:
- **Practice absent for non-partners** — `canAccessWorkspace("practice", Manager/Article/Staff)=false` (nav entry not rendered) + `PartnerGuard` blocks direct URL. ✓
- **Revenue Operations Partner-only** — `/practice` href hidden from Manager + staff; `isPartnerOnlyAllowed` only Partner. ✓
- **Knowledge visible to all staff** (Batch 6 rules; content assignment-gated server-side). ✓
- **Legacy billing unchanged** — `/billing` visible to Partner **and Manager** (no regression). ✓
- **Existing gating intact** — deadlines hidden from Article, etc. ✓
- **Internal client absent from client lists** — `getClients()` → `/api/clients` which excludes `is_internal` (Batch 2 backend, RLS + repo); frontend consumes that API.
- **Client instructions assignment-gated** — enforced by backend (Batch 6); UI renders only what the API returns.

## Test results
- **Build verification:** `pnpm build` → **Compiled successfully** (all 10 new routes present). ✓
- **Type-check:** passes (Next build runs full tsc; strict mode). ✓ (test files excluded via `tsconfig`.)
- **Frontend permission tests:** 6/6 pass. ✓
- **Lint:** warnings only (pre-existing `no-img-element`, app-wide `themeColor` metadata) — no new errors.
- **Regression:** backend suite **1025 passed** (unchanged — zero backend files touched); 23 pre-existing Supabase-503 env failures unchanged. ✓

## Remaining technical debt (documented)
1. **Frontend role drift** — FE roles are `Partner|Manager|Article|Staff` (no Executive/Reviewer/Client). `Staff/Article` map to backend `Executive`; assignment-gating for Executive/Reviewer is enforced by the **backend** (the FE can't compute assignment), so write controls are shown and the API authorises. A future pass can align FE roles to the 6-role model.
2. **₹→paise input conversion** in the billing-schedule form (parsing user rupee input to paise for submission) — input handling, not business logic; mirrors the existing billing page.
3. **AR drill-down depth** — AR shows buckets + totals; a per-invoice list with an inline **record-receipt (incl. `tds_paise`)** form is a follow-up (the receipts API + `salesInvoices.issue` namespaces are wired; the CA-confirm/receipt UI form is minimal in this batch).
4. **Pre-existing FE business-logic violations** (`lib/services/health-*`, `relationship-intelligence`, `lib/repositories/*`, large inline-CRUD pages) — **not extended**, flagged for a separate cleanup; Batch 7 added none.
5. **No FE component-test framework** — permission logic is unit-tested via `node:test`; UI interaction relies on the green production build as the safety net.

**Status: Batch 7 complete and passing. Amendment v1.1 (Batches 0–7) implemented.**
