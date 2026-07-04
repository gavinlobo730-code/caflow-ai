# Navigation & Routing Investigation — 2026-07-04

Investigation-only audit of four reported issues. **No fixes have been
implemented.** Every root cause below was verified empirically, not just by
code reading: the actual static export was built (`next build`,
`output: "export"`) and served locally through a faithful interpreter of
`public/_redirects` (first-match-wins, `:param` = one segment — Cloudflare
Pages semantics), then driven with headless Chromium using a stubbed
session. All four issues reproduced.

## Architecture primer (context for all four issues)

Two navigation systems plus one deployment mechanism interact here:

1. **Global shell** — `components/AppShell.tsx` wraps every non-auth page
   and renders `ActivityRail` (the 52px icon rail: workspace buttons +
   Settings gear + avatar) and `ContextPanel` (the 220px panel that shows
   one of 12 workspace panels). State comes from
   `lib/workspace/WorkspaceContext.tsx`: `activeWorkspace` plus a
   `lastRoute` map (one remembered route per workspace), persisted to
   localStorage under `practicesync_workspace_v1` and re-hydrated on every
   mount. Pathname→workspace mapping lives in
   `lib/workspace/workspaceConfig.ts:getWorkspaceForPathname()`. The shell
   hides the rail/panel inside the client workspace via
   `CLIENT_UUID_RE.test(pathname)` (`AppShell.tsx:23-24,34,101`).
2. **Client workspace shell** — `app/clients/[id]/layout.tsx` →
   `components/ClientWorkspaceShell.tsx` →
   `components/ClientContextPanel.tsx` (the client sidebar) +
   `ClientHeader`. The 19 sections are defined in
   `lib/workspace/ClientNavContext.tsx:CLIENT_SECTIONS` (all hrefs end with
   a trailing slash). The sidebar computes its own active state:
   `active = pathname.startsWith(target)` (`ClientContextPanel.tsx:74`).
3. **Deployment** — static export (`next.config.js`: `output: "export"`,
   `trailingSlash: true`) hosted on Cloudflare Pages. Dynamic `[id]` routes
   prerender only a `_placeholder` param
   (`app/clients/[id]/layout.tsx:generateStaticParams`), and
   `public/_redirects` hand-enumerates a 200-rewrite per client section so
   real UUIDs serve the placeholder HTML.

---

## Issue 1 — Client workspace sidebar does not highlight Sales

**Root cause:** trailing-slash mismatch between the sidebar's hrefs and the
pathname the Next.js client router reports after a client-side navigation.
Every section href ends with `/` (`ClientNavContext.tsx:40-58`); the active
test is a raw string-prefix check, `pathname.startsWith(target)`
(`ClientContextPanel.tsx:74`).

**Empirically observed:** on a full-page load of `/clients/<id>/sales/`,
`usePathname()` = `/clients/<id>/sales/` → Sales highlights correctly. After
clicking any sidebar item (client-side navigation), the browser URL and
`usePathname()` become `/clients/<id>/purchases` — **Next strips the
trailing slash on client transitions despite `trailingSlash: true`**, even
though the DOM hrefs are normalized WITH the slash. The prefix check
`"/clients/x/purchases".startsWith("/clients/x/purchases/")` is false, so
**every item unhighlights**. Hard refresh restores the highlight; the next
in-workspace click loses it again. That matches the report exactly (Sales is
normally opened by clicking from Overview → no highlight; "appears the user
is still somewhere else" because nothing is lit at all).

- **Files:** `components/ClientContextPanel.tsx:74` (matcher),
  `lib/workspace/ClientNavContext.tsx:39-58` (trailing-slashed hrefs),
  `next.config.js` (`trailingSlash: true`).
- **Architectural or implementation-specific?** Implementation (a
  format-fragile matcher), sitting on an architectural wart: there are
  *three* active-state mechanisms in this shell — the sidebar's pathname
  matching, a `getSectionForPathname()` helper that the sidebar doesn't
  use, and a completely **dead** `activeSection`/`setSection` state in
  `ClientNavContext` (grep confirms zero consumers anywhere).
- **Recommended fix:** match on **section identity, not URL prefix**:
  `const active = getSectionForPathname(pathname) === id`.
  `getSectionForPathname` reads path segment 3, so it is immune to both the
  trailing-slash inconsistency and the `_placeholder` prerender. At the same
  time, delete the dead `activeSection` machinery (or make it derived) so
  exactly one mechanism remains. Nothing hardcoded.
- **Risks:** low. The only behavior change is for nested paths
  (`/compliance/gst` → still maps to "compliance", which is the desired
  highlight). Section ids equal their path segments by construction.
- **Other modules affected:** grep found no other trailing-slash-suffixed
  `startsWith` matchers; `ActivityRail`'s settings check uses a slash-less
  prefix and is safe. The general lesson (identity matching over URL-string
  matching) applies to any future nav code.

## Issue 2 — Settings highlights Home

**Root cause:** `activeWorkspace` has no "none" state, and `/settings` is
deliberately excluded from workspace syncing.

- `WorkspaceContext.tsx:108`: the pathname-sync effect early-returns for
  `/settings` ("settings is not a workspace — don't pollute lastRoute").
  Correct for `lastRoute`, but it also skips `SET_WORKSPACE`, so the rail
  keeps the **previous** workspace lit when navigating to Settings.
- On a direct load of `/settings`, `getInitialState` →
  `getWorkspaceForPathname("/settings")` → the function's final fallback
  `return "home"` (`workspaceConfig.ts:200`) → Home lit.
- The Settings **gear** itself lights correctly
  (`ActivityRail.tsx:22`), so the user sees two simultaneous "active"
  indicators: Home in the workspace list and the gear below.

**Empirically observed:** both after click-through from Home and on a
direct `/settings/` load, the Home workspace button stays lit while the
gear is also lit.

- **Files:** `lib/workspace/WorkspaceContext.tsx:107-112`,
  `lib/workspace/workspaceConfig.ts:138-201`,
  `components/ActivityRail.tsx:22,46`.
- **Architectural or implementation-specific?** Architectural: the state
  model asserts "exactly one workspace is always active," which is false on
  non-workspace routes.
- **Blast radius (same fallback-to-home class):** `/copilot`, `/einvoice`,
  `/executive-dashboard`, `/memory`, `/migration`, `/time`, `/search` (and
  `/platform`) all render with Home lit — several of these were linked into
  panels recently, so this is user-visible today. `/workflows` maps
  correctly only by accident (`"/workflows".startsWith("/work")`).
- **Recommended fix:** derive the rail highlight from the pathname rather
  than from stored `activeWorkspace`: let the mapping return
  `WorkspaceId | null` with an explicit `null` for settings (and unknown
  routes), and add the seven missing prefix mappings to their proper
  workspaces. Keep "home" as the **panel** fallback in `ContextPanel`
  (which already special-cases settings at `ContextPanel.tsx:30`) — the
  highlight and the panel choice are different concerns and should not
  share one fallback.
- **Risks:** low-medium: splitting highlight from panel-choice must not
  change which panel renders for unknown routes (keep HomePanel); check
  `canAccessWorkspace` interactions when adding prefix mappings.
- **Other modules affected:** `ContextPanel` (panel choice), any code
  reading `activeWorkspace` for non-highlight purposes.

## Issue 3 — `clients/{clientId}/instructions` 404s

**Root cause:** the route exists and is correctly built — the **production
rewrite table doesn't know about it**. `public/_redirects` hand-enumerates
every client section, and there are **no rules** for `instructions`,
`knowledge`, or `year-end/xbrl`. With no matching rule and no static file at
`/clients/<uuid>/instructions/`, Cloudflare serves 404.

**Empirically reproduced** against the real build output under faithful
`_redirects` semantics: `instructions/`, `knowledge/`, `year-end/xbrl/` →
**404**; `sales/`, `overview/` → 200.

Answering the prompt's specific question: the feature was **completed but
never wired into the deployment config** — `app/clients/[id]/instructions/page.tsx`
exists, follows the placeholder-safe `clientId` pattern (`useClientNav`),
and is linked in the sidebar (`CLIENT_SECTIONS:58`), so every client
workspace page shows "Instructions" (and "Knowledge") items that 404 in
production. Dev works (real dynamic routing) — which is why it shipped
unnoticed. Not middleware (none exists in `output: "export"`), not a layout
problem, not accidental deletion.

Also found: a **stale** rule `/clients/:id/coa` pointing at a page deleted
in R3.3b — harmless (that path should 404 now anyway) but proof that nothing
reconciles this file against the route tree in either direction.

- **Files:** `public/_redirects` (missing rules),
  `app/clients/[id]/instructions/page.tsx` (fine),
  `app/clients/[id]/knowledge/page.tsx` (fine),
  `app/clients/[id]/year-end/xbrl/page.tsx` (fine),
  `app/clients/[id]/layout.tsx` (the `_placeholder` export pattern).
- **Architectural or implementation-specific?** Architectural: the route
  tree is duplicated by hand into infrastructure config with zero drift
  protection.
- **Recommended fix:** short-term, add the three missing rule pairs.
  Long-term, **generate `_redirects` at build time** from the export output
  (walk `out/clients/_placeholder/**`, emit both slash variants, sort by
  segment count descending so specific rules precede catch-alls, then append
  the static non-client rules) plus a CI assertion that every
  `app/clients/[id]/*/page.tsx` has a rule.
- **Risks:** rule order is semantic (first-match-wins): `compliance/gst`
  must precede `compliance`; `year-end/:eid/*` must precede `year-end`. A
  generator must sort deterministically and assert Cloudflare's rule-count
  limits (100 static + 100 dynamic; currently ~70 lines).
- **Other modules affected:** `/clients/<id>/knowledge` and
  `/clients/<id>/year-end/xbrl` 404 today for the same reason; any future
  client-section page will silently 404 in production until the generator
  exists.

## Issue 4 — "Clients" reopens Client A instead of the list

**Root cause:** this is the **intentional workspace-resume design**, not a
stray redirect. Rail workspace buttons call `setWorkspace(id)` →
`router.push(lastRoute[id] ?? DEFAULT_WORKSPACE_ROUTES[id])`
(`WorkspaceContext.tsx:114-122`). Every visited pathname is recorded into
its workspace's `lastRoute` (`:107-112`) and the whole map persists in
localStorage (`practicesync_workspace_v1`, `:34,:97-104`), re-hydrated on
mount (`:73-95`). Visiting Client A stores
`lastRoute.clients = /clients/<id>/sales/`; clicking "Clients" resumes it —
across reloads and across sessions.

**Empirically confirmed end-to-end:** after visiting Client A's Sales page
and returning Home, localStorage held the client-A route and clicking the
Clients rail button landed back on Client A's Sales page, with the Clients
icon lit.

**Intentional or bug?** The *mechanism* is unambiguously deliberate
(reducer + persistence + hydration + an explicit settings-exclusion guard).
The *granularity* is the questionable part: a rail button labeled "Clients"
reads as "go to the client list," and the only list affordance is the small
back-arrow inside the client sidebar (`ClientContextPanel.tsx:144`).
Whether deep per-client resume is desired is a **product decision**.

- **Recommended fix (hybrid, pending product sign-off):** keep resume for
  cross-workspace switches; make clicking the **already-active** workspace's
  button navigate to its `defaultRoute` (second click = "go to workspace
  root"). Alternative (list-first semantics): record only `/clients` into
  `lastRoute.clients` when the pathname is a client-detail page — fully
  matches the reported expectation but abandons resume.
- **Adjacent real bug found here (fix regardless of the product call):**
  hydration does `{...DEFAULT_WORKSPACE_ROUTES, ...parsed.lastRoute}`
  (`:84-87`) — persisted routes win over defaults with **no validation**.
  Any user whose localStorage predates this mission's route deletions has
  `lastRoute.accounting = "/accounting/chart-of-accounts"` (deleted in
  R3.3b): clicking Accounting pushes a 404 forever until localStorage is
  cleared. Fix: version-bump the storage key (v1→v2) or validate stored
  routes against the known-route set on hydrate.
- **Files:** `lib/workspace/WorkspaceContext.tsx` (all of the above),
  `components/ActivityRail.tsx:50` (the only `setWorkspace` caller).
- **Architectural or implementation-specific?** The resume behavior is
  architecture working as designed; the unvalidated persistence is an
  implementation bug.

## Cross-cutting findings

1. **Three active-state mechanisms** exist for the client sidebar; one is
   dead code (`activeSection`/`setSection`/`initialSection` in
   `ClientNavContext` — zero consumers). Collapse to one derived source.
2. `getWorkspaceForPathname`'s unknown→`"home"` fallback mislabels at least
   7 real, linked routes (list under Issue 2).
3. The workspace localStorage schema has **no migration or validation**
   (Issue 4's adjacent bug).
4. `public/_redirects` has **no drift protection in either direction**
   (missing: `instructions`, `knowledge`, `year-end/xbrl`; stale: `coa`).
5. Client-side navigations strip the trailing slash while DOM hrefs carry
   it — any future URL-string comparison will hit the same trap; prefer
   segment/identity matching in all nav code.

## Suggested implementation order

1. **Issue 3, short-term** — add the 3 missing `_redirects` rule pairs.
   Production 404s behind always-visible sidebar links; zero-risk one-file
   change.
2. **Issue 1** — section-identity matching in `ClientContextPanel` +
   remove the dead `activeSection` machinery. Small, isolated, kills the
   most-reported symptom.
3. **Issue 2** — pathname-derived rail highlight with a null state + add
   the 7 missing prefix mappings. One context + one component.
4. **Issue 4, adjacent bug** — validate/version the persisted `lastRoute`
   map so deleted routes can't be pushed.
5. **Issue 4, product behavior** — needs a product decision; if the hybrid
   is approved, second-click-to-default is a small change in
   `WorkspaceContext.setWorkspace`.
6. **Issue 3, long-term** — build-time `_redirects` generation + CI drift
   check, closing the whole class permanently.
