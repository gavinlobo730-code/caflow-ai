# Dead Code Audit — PracticeSync (apps/web)

**Date:** 2026-06-22
**Branch:** `claude/dazzling-curie-a55bpf`
**Scope:** Repository-wide, focused on `apps/web` (Next.js frontend). `apps/api` (Python), `supabase/`, and `docs/` reviewed for cross-references only.

## Method (evidence-based — no assumptions)

1. **Full inventory:** 268 `.ts`/`.tsx` files, 1 CSS file (`app/globals.css`), 51 public assets.
2. **Import-graph analysis:** For every non-entrypoint file, counted references via (a) exact `@/`-alias path with quote boundary, (b) any relative/absolute import ending in the file's basename, (c) directory-index form for `index.ts`.
3. **Entrypoint exclusion:** App Router special files (`page.tsx`, `layout.tsx`, `route.ts`, `not-found.tsx`) and config files (`next.config.mjs`, `tailwind.config.ts`, `postcss.config.mjs`, `sentry.*.config.ts`) are framework-reachable and never counted as dead by import count.
4. **Dynamic-import analysis:** All `await import(...)`, `next/dynamic`, `React.lazy` usages enumerated. **Result:** every dynamic import uses a *static string path* (e.g. `import("@/lib/data/tasks")`) — all captured by the import-graph scan. No computed/variable module paths exist.
5. **Cross-file-type sweep:** Re-searched each candidate's name across `.ts/.tsx/.js/.mjs/.json/.md` to catch references outside source (configs, docs).
6. **Cascade check:** Verified dependencies of deleted files retain other importers.

---

## Audit Summary

| Metric | Count |
|---|---|
| Source files scanned (.ts/.tsx) | 268 |
| Verified unused — **Safe To Delete** (16 direct + 3 cascade) | **19** |
| **Likely Safe To Delete** (human review) | 2 |
| **Requires Investigation** | 2 groups (logo pages + logo assets) |
| **Must Keep** (looks unused but required) | 12 |
| **Total deleted** | **19** (2,910 lines) |

---

## SAFE TO DELETE — verified unused, high confidence

Each below has **0** importers via absolute, relative, dynamic, and cross-file-type analysis. Deleting them causes **no cascade** (their own dependencies retain other importers).

### Components (8)

| File | What it does | Refs | Confidence |
|---|---|---|---|
| `components/ClientRail.tsx` | Old 52px client icon nav rail. **Orphaned by PR #133** which consolidated nav into `ClientContextPanel`. | 0 | 100% |
| `components/sidebar.tsx` | Old firm-level left nav. Replaced by `ActivityRail` + `ContextPanel` (the only nav `AppShell` imports). | 0 | 99% |
| `components/panels/CompliancePanel.tsx` | Workspace panel. `ContextPanel.tsx` wires in 11 sibling panels but **not** this one. | 0 | 99% |
| `components/PageHeader.tsx` | Generic page-header helper. | 0 | 99% |
| `components/ai-insight-banner.tsx` | AI insight banner. | 0 | 99% |
| `components/InvoiceFormModal.tsx` | Invoice create/edit modal (389 lines). Invoices page does not import it. | 0 | 97% |
| `components/IntelligencePanels.tsx` | Relationship intelligence panels (224 lines). | 0 | 98% |
| `components/DocumentUploader.tsx` | Document upload widget (164 lines). | 0 | 98% |

### Pages / legacy (1)

| File | What it does | Refs | Confidence |
|---|---|---|---|
| `app/clients/[id]/ClientWorkspacePage.tsx` | Legacy monolithic client-workspace component. Superseded by per-section pages (`overview/`, `accounting/`, …). Not a route (no `page.tsx` name) and imported by nobody. | 0 | 99% |

### Hooks (4) — superseded by direct `lib/data/*` calls

| File | What it does | Refs | Confidence |
|---|---|---|---|
| `lib/hooks/use-clients.ts` | `useClients()` data hook. App calls `lib/data/clients` directly. | 0 | 98% |
| `lib/hooks/use-tasks.ts` | `useTasks()` hook. | 0 | 98% |
| `lib/hooks/use-compliance.ts` | `useCompliance()` hook. | 0 | 98% |
| `lib/hooks/use-dashboard.ts` | `useDashboard()` hook. | 0 | 98% |

> After deletion `lib/hooks/` is empty → directory removed.

### Permissions duplicate (2) — superseded by `lib/auth/permissions.ts`

| File | What it does | Refs | Confidence |
|---|---|---|---|
| `lib/permissions/guards.ts` | `requirePermission()` guard. Imported by **nobody**. | 0 | 98% |
| `lib/permissions/roles.ts` | Role/permission matrix ("mirrors backend"). Imported **only** by the dead `guards.ts`. The live system is `lib/auth/permissions.ts` (used by `AppShell`, `RoleGuard`, etc.). | 0 (external) | 98% |

> After deletion `lib/permissions/` is empty → directory removed.

### Services (1)

| File | What it does | Refs | Confidence |
|---|---|---|---|
| `lib/services/compliance.ts` | `daysRemaining()` + status helpers. **0** importers of `@/lib/services/compliance` (the many `/compliance` hits all resolve to the live `@/lib/data/compliance`). | 0 | 96% |

### Cascade — transitively dead (3) — repository layer, only reachable through the deleted hooks

A post-deletion re-scan (and an independent full import-graph re-scan) found these became unreachable once the 4 hooks were removed. They only import `@/lib/api` (37 other users) and `@/lib/types` (39 other users), so removing them is terminal — no further cascade.

| File | What it does | Refs after hook deletion | Confidence |
|---|---|---|---|
| `lib/repositories/client.repository.ts` | Supabase client data-access. Was imported only by `use-clients.ts`. | 0 | 99% |
| `lib/repositories/task.repository.ts` | Task data-access. Was imported only by `use-tasks.ts`. | 0 | 99% |
| `lib/repositories/compliance.repository.ts` | Compliance data-access. Was imported only by `use-compliance.ts`. | 0 | 99% |

> After deletion `lib/repositories/` is empty → directory removed. The whole hooks+repositories layer was a superseded data-access pattern; live code uses `lib/data/*` directly.

---

## LIKELY SAFE TO DELETE — unused, but human review recommended

Verified 0 references, **but** these are substantial domain artifacts tied to existing routes; a human should confirm they are not pending-wiring before removal.

| File | What it does | Refs | Confidence unused | Why not auto-deleted |
|---|---|---|---|---|
| `lib/data/income-tax.ts` | 273 lines of income-tax computation (`S80CInput`, slab logic). | 0 | 95% | Maps directly to live `/income-tax/*` routes; may be intended for wiring. CLAUDE.md treats tax logic specially. |
| `lib/services/relationship-intelligence.ts` | "Phase 0 stub" — types/interfaces for `/relationships`. | 0 | 95% | Self-described scaffold for an in-progress feature. |

---

## REQUIRES INVESTIGATION

| Item | Note |
|---|---|
| `app/logo-concepts/`, `app/logo-concepts/final/`, `app/logo-concepts/v7/` (3 page routes) | **Not linked** from any nav/page — design-exploration scratch routes. Valid URLs in a static export, so not "dead" at build time. Deleting *pages* changes the route surface; needs owner sign-off. |
| `public/logos/**` (41 SVGs incl. `v7/`, `final/`, `v1`–`v10`) | Logo design variants referenced (if at all) by the logo-concepts pages via `<img src>`. Pruning requires design-owner confirmation; static export serves them regardless. Not deleted. |

> No "dynamic usage" risks were found in code — all dynamic imports use static string paths and are fully resolved by the import graph.

---

## MUST KEEP — looks unused but is required

| File(s) | Why it must stay |
|---|---|
| `app/clients/[id]/year-end/[engagementId]/{adjustments,checklist,dashboard,exports,financial-statements,notes,review,schedules}/_page.tsx` (8 files) | **Not backups.** Each sibling `page.tsx` (9-line route wrapper doing `generateStaticParams`) imports `./_page` as the real client implementation. Verified: `import XPageClient from "./_page"` in all 8 wrappers. |
| `lib/auth/permissions.test.ts`, `lib/filing/demoFiling.test.ts`, `lib/imports/imports.test.ts`, `lib/invoices/importMapping.test.ts` (4 files) | Excluded from tsconfig and no runner is wired, **but** required by CLAUDE.md ("every financial calculation must have a corresponding unit test"). They import **live, used** source (`./permissions.ts`, `./importMapping.ts`, etc.). |

> Note: `app/DashboardContent.tsx`, `app/health/[client_id]/HealthDetailClient.tsx`, `app/relationships/[entity_id]/EntityDetailClient.tsx` initially appeared unreferenced by `@/`-path but are **imported relatively** by their sibling `page.tsx` — confirmed used, not candidates.

---

## Deletion executed (Phase 3)

Deleted the 16 direct **Safe To Delete** files, then the 3 cascade repository files = **19 files, 2,910 lines**. Emptied directories removed: `lib/hooks/`, `lib/permissions/`, `lib/repositories/`. Likely-Safe, Requires-Investigation, and Must-Keep were left untouched.

---

## Validation Results (Phase 4)

Dependencies installed via `pnpm install --frozen-lockfile` (node_modules was absent). Baseline captured before deletion to attribute results.

| Check | Baseline | After deletion | Result |
|---|---|---|---|
| `tsc --noEmit` (typecheck) | exit 0, clean | exit 0, clean | ✅ PASS |
| `next lint` | exit 0 (only pre-existing `<img>` warnings in `logo-concepts/*`) | exit 0 (same) | ✅ PASS — no new issues |
| `next build` (static export) | n/a | exit 0 — **157 HTML files** exported | ✅ PASS |

> Note: `npm run typecheck` is not defined in `package.json` (scripts are `dev`/`build`/`start`/`lint`); typecheck was run via `npx tsc --noEmit`.

### Functional verification (static-export prerender = full React tree rendered without error)

| Area | Evidence |
|---|---|
| Authentication | `/login` exported; `lib/auth/*` untouched |
| Navigation | `AppShell` + `ActivityRail` + `ContextPanel` untouched (old `sidebar.tsx` was unused) |
| Client Workspace | `/clients/[id]/overview`, `…/accounting`, etc. exported; `ClientWorkspaceShell`/`ClientContextPanel`/`ClientHeader` intact |
| Dashboard | `/` exported; `DashboardContent.tsx` intact |
| Documents | `/documents` + `/clients/[id]/documents` exported; confirmed they never imported the deleted `DocumentUploader` |
| Reports | `/reports` exported |
| AI Insights | `/clients/[id]/ai-insights` exported; confirmed it never imported the deleted `ai-insight-banner` |
| Mobile navigation | `ClientContextPanel` drawer (PR #133) intact; build passed |
