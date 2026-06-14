# Batch 7 Design Review — Frontend & Workspace Experience

**Amendment v1.1 (Phase 10B) · Batch 7 (frontend-only) · Branch:** `claude/compassionate-darwin-nffpnb` · **Design only — awaiting approval.**

Backend for Amendment v1.1 is complete (Batches 1–6). Batch 7 wires UI to those
APIs. **Hard rule:** zero business logic in the frontend — UI consumes backend APIs
only; all money/aging/GST/visibility computation stays server-side.

## Grounding facts (current frontend)
- **Dual-rail nav:** `lib/workspace/workspaceConfig.ts` defines **9 Rail-1 workspaces**
  (Home, Clients, Deadlines, Work, Team, AI, Accounting, Relationships, Health);
  `ClientNavContext` drives the 16-section client workspace (`/clients/[id]/[section]`).
- **API client:** `lib/api/index.ts` — namespaced `api.*`, Bearer token from Supabase
  session, returns the backend `{success,data,error}` shape. Data fetchers in `lib/data/*`.
- **Permissions:** `lib/auth/permissions.ts` gates nav by role. **Frontend roles =
  `Partner | Manager | Article | Staff`** (drift from backend `Partner/Manager/
  Executive/Reviewer/Client`). No `Partner-only` concept yet.
- **Legacy `/billing`** page exists — it is the **legacy `fee_*` UI** (Engagement /
  fee_invoices; Draft/Sent/Paid/Overdue), under the Accounting workspace, visible to
  Partner+Manager. Per the bridge decision it **stays** (legacy, readable); new Revenue
  Operations is separate.
- **Existing frontend violations (flagged, NOT extended):** `lib/services/health-engine.ts`,
  `health-score-compute.ts`, `relationship-intelligence.ts`, `lib/repositories/*`, and
  large pages with inline CRUD/calculation. Batch 7 adds **no** new violations.

---

## 1. Navigation architecture

**New Rail-1 entries (2):**
- **Practice** (Partner/Owner-only) — the firm-as-internal-client + Revenue Operations
  home. Reuses the client-workspace shell for the internal client.
- **Knowledge** (all staff) — firm/department Knowledge Base.

Client Instructions are **not** a nav entry — they surface as pinned cards inside the
existing **Client → Overview**, plus a **Knowledge** section in the client workspace.

**Navigation tree (additions in bold):**
```
Rail 1 (firm)
├─ Home, Clients, Deadlines, Work, Team, AI, Accounting, Relationships, Health   (existing)
├─ **Practice**  (Partner-only)        → Rail 2: Revenue Dashboard | Billing | Collections/AR
│                                              | Accounting | GST | TDS | Documents | Reports
│                                              (internal client, reusing client shell)
└─ **Knowledge** (all staff)           → Rail 2: All Articles | Firm | Department | (search)

Client workspace (/clients/[id]/...)   (existing 16 sections)
├─ Overview            → + **pinned Client Instruction cards**
├─ **Knowledge**        → client-scoped articles (assignment-gated)
└─ **Instructions**     → manage client instructions (Executive+ if assigned)
```

**Role visibility (nav):**

| Rail-1 entry | Partner | Manager | Executive(=Article/Staff) | Reviewer | Client(portal) |
|---|---|---|---|---|---|
| Practice (Revenue/Billing/AR) | ✓ | ✗ | ✗ | ✗ | ✗ |
| Knowledge | ✓ | ✓ | ✓ | ✓ | ✗ |
| Client → Instruction cards | ✓ | ✓ | ✓ if assigned | ✓ if assigned | ✗ |

- **Partners** see everything incl. Practice/Revenue.
- **Managers** see Knowledge + client instructions firm-wide, but **not** Practice/Revenue
  (fee economics, G1). *(Note: legacy `/billing` stays Partner+Manager unless you choose
  to tighten it — see decisions.)*
- **Executives/Reviewers** see Knowledge (firm/dept) + assigned-client instructions/KB.
- **Clients (portal)** see none of this (separate audience).

**Role drift handling:** add a `PARTNER_ONLY` set to `permissions.ts` for Practice/Revenue;
map backend roles (`Executive→Article/Staff`, `Reviewer→Viewer`, `owner→Partner`). UI is
the *last* line — backend RBAC + RLS already enforce; even if a nav item leaked, the API
returns 403/empty.

---

## 2. Practice Workspace UX

- **Entry point:** "Practice" on Rail 1 (Partner-only). Clicking it **context-switches
  into the internal client** (reuses the client-workspace shell + `ClientNavContext`),
  visually marked as the firm itself (distinct monogram/colour). First load → **Revenue
  Dashboard**.
- **Provisioning gate:** if `GET /api/practice` returns no `internal_client_id`, show a
  one-click **"Set up Practice"** (calls `POST /api/practice/provision`) empty state.
- **Layout (wireframe):**
```
[Rail1: Practice active]  [Client header: "★ <Firm> — Practice"  FY selector  Back to Firm]
Rail2: Revenue | Billing | Collections/AR | Accounting | GST | TDS | Documents | Reports
Content: <selected section>
```
- **Requirements met:** Partner-only (nav + route guard + backend); internal-client-aware
  (reuses internal client id); Revenue Operations is the home section.

## 3. Revenue Dashboard (Practice home)

- **KPI cards:** Total Receivable, Overdue (₹ + count), TDS Receivable, Collected (this
  period), Active Billing Schedules count.
- **AR aging summary:** mini 5-bar (Current/0–30/31–60/61–90/90+) → links to AR Dashboard.
- **Outstanding invoices:** top N unpaid internal-client `sales_invoices` (status + days
  overdue) → invoice detail.
- **Collections summary:** overdue count + "Send reminders" (Partner action).
- **Billing schedules:** count of active schedules + "due now" (preview-run).
- **Data sources:** `GET /api/billing/collections/dashboard`, `/ar-aging`, `/schedules`,
  `/preview-run`. **All money formatted from paise by a shared formatter (display only).**
- **Refresh:** on mount + manual refresh; after actions (generate/reminder) re-fetch.
- **Empty states:** "No receivables yet", "No billing schedules — create one".

## 4. AR Dashboard

- **Buckets:** Current/Not-due, 0–30, 31–60, 61–90, 90+ (from `/ar-aging`: paise + count).
- **Filters:** bucket, client, status. **Drill-down:** bucket → invoice list (filtered)
  → invoice detail; client column → client billing tab.
- **Collection actions (Partner):** per-invoice "Record receipt" (→ `/api/receipts` with
  optional `tds_paise`), "Send reminder"; bulk "Run sweep"/"Send reminders".
- Invoice links → `/api/sales-invoices/{id}`; client links → that client's billing tab.

## 5. Billing UI (under Practice)

- **Billing schedules:** list + create (`/api/billing/schedules`); "Preview run"
  (`/preview-run`) shows due schedules; "Generate" (`/schedules/{id}/generate`) → **draft**.
- **Invoice review (CA-confirm gate):** drafts list with a clear "Confirm & issue"
  (→ `/api/sales-invoices/{id}/issue`) — explicit gate; shows GST breakdown (from API).
- **Status visibility:** Draft → Issued → Partially Paid → Paid; **Overdue** shown as a
  derived **badge** (is_overdue/days_overdue/aging_bucket from API) **on top of** payment
  status (e.g. "Issued · 15d overdue") — never a separate mutated status.
- **Journey:** schedule → preview → generate draft → review (GST) → confirm/issue (posts
  JE) → collect (receipt, incl. TDS) → paid.

## 6. Knowledge Base UI

- **Listing:** `/knowledge` — articles with scope/department/tags/updated; **search** box
  (`?query=`), tag chips, scope filter. Firm list excludes client-scoped + internal.
- **Article view:** current content + **version history** (list of versions); **Manager+**
  sees "Edit" (new version) and **"Restore"** a prior version (rollback → new version).
- **Manager authoring flow:** New → scope/title/tags/content → save (v1) → edit (vN) →
  restore. **Executive/Reviewer consumption:** read + search only (no edit controls).

## 7. Client Instructions UI

- **Placement:** pinned **cards atop Client → Overview** (pinned first), plus a client
  **Instructions** manager. Cards show title/body + pin/edit/archive (if permitted).
- **Visibility cues:** absent entirely for unassigned Executive/Reviewer (API returns
  none); internal-client instructions visible only in Practice (Partner).
- **Assignment behavior:** Executive add/edit only on assigned clients (backend enforces;
  UI hides the add/edit control when the API indicates no write access / 403).

---

## 8. Permission visibility audit (per screen)

| Screen | Partner | Manager | Executive | Reviewer | Client |
|---|---|---|---|---|---|
| Practice workspace (entry + all sections) | Visible | **Hidden** | Hidden | Hidden | Hidden |
| Revenue Dashboard | Visible | Hidden | Hidden | Hidden | Hidden |
| AR Dashboard / Collections | Visible | Hidden | Hidden | Hidden | Hidden |
| Billing (schedules/invoices) | Visible | Hidden | Hidden | Hidden | Hidden |
| Staff cost rates / unbilled work | Visible | Hidden | Hidden | Hidden | Hidden |
| Knowledge (firm/dept) | Visible | Visible | Visible (read) | Visible (read) | Hidden |
| Client KB / instructions (external client) | Visible | Visible | if assigned | if assigned (read) | Hidden |
| Client KB / instructions (internal client) | Visible | Hidden | Hidden | Hidden | Hidden |

Guarantees: **no revenue surface renders for non-partners** (absent, not greyed); **no
internal-client data** in any client list/search (G2 + backend); **no fee economics**
(cost rates, AR, billing) outside Practice. Frontend hiding is cosmetic — backend
RBAC/RLS is authoritative.

---

## 9. Frontend architecture review

**Reuse:**
- Client-workspace shell (`ClientNavContext`, client header, Rail 2) for **Practice**.
- `api` client (`lib/api`) + a shared **paise→₹ formatter** (`lib/services/formatting.ts`
  exists) for display only.
- UI primitives (`components/ui`, cards, tables, panels), Timeline event components,
  AuthGuard/permission helpers.

**Extend:**
- `workspaceConfig.ts` (+Practice, +Knowledge entries), `permissions.ts` (+PARTNER_ONLY),
  `lib/api/index.ts` (+`practice`, `billing`, `knowledge`, `instructions` namespaces),
  Client Overview page (+instruction cards).

**New pages/components:** `/practice` (+ revenue/billing/collections sections),
`/knowledge` (+ article view/editor), client `knowledge` + `instructions` sections,
KPI-card / aging-bar / invoice-table / instruction-card components.

**New hooks:** `use-revenue-dashboard`, `use-ar-aging`, `use-billing-schedules`,
`use-knowledge`, `use-client-instructions` — **thin fetch wrappers only** (no logic).

**No business logic / no duplicated calculation:** all aging, GST, totals, overdue, and
visibility come from the API. **Flagged existing violations** (not fixed here, tracked
separately): `lib/services/health-*`, `relationship-intelligence`, `lib/repositories/*`,
inline CRUD in large pages.

---

## 10. Mobile & responsive review

- **Desktop:** information-dense, table-forward (per UI/UX brief); Practice reuses the
  desktop client shell.
- **Tablet:** KPI cards wrap 2-up; AR table → horizontal scroll with sticky first column;
  Rail 2 collapsible.
- **Mobile:** KPI cards stack 1-up; AR aging as a stacked list (bucket → expandable
  invoices); Billing/KB as cards; the firm side stays desktop-optimised (per brief, the
  firm layer is desktop-first — mobile is best-effort, the **portal** is the mobile-first
  surface and is untouched here).

---

## 11. Risk review

| Risk | Severity | Mitigation | Test |
|---|---|---|---|
| Revenue/Practice surface leaks to non-partner | High | PARTNER_ONLY nav gate + route guard; backend RBAC/RLS authoritative | Render tests per role; API 403 on direct nav |
| Internal-client data appears in a client list/search | High | Lists use `clients_external`/API (G2); Practice is the only internal surface | Verify internal client absent from Clients list/search |
| Fee economics (cost rates/AR) exposed | High | All under Practice (Partner-only); no Manager access to new surfaces | Permission-matrix test |
| Business logic creeps into frontend | Med | Hooks are fetch-only; review gate; formatter is display-only | Code review; grep for arithmetic in new files |
| Role drift (FE 4 roles vs BE 6) mis-gates | Med | Central role map; backend enforcement as backstop | Mapping unit test |
| State staleness after actions (issue/receipt) | Med | Re-fetch on action success; optimistic only for non-financial | Interaction tests |
| API dependency / error states | Med | Defined empty/loading/error states; surface backend error messages | Error-state tests |
| Legacy `/billing` confusion vs new Revenue | Low | Keep legacy as-is (or deprecate label); new lives under Practice | Navigation test |

---

# Deliverables

1. **Design review** — above.
2. **Navigation map** — §1 (Practice + Knowledge Rail-1; instructions in client Overview).
3. **Screen inventory:** `/practice` (Revenue Dashboard, Billing, Collections/AR + reused
   internal-client sections), `/knowledge` (+ article view/editor), client `knowledge` +
   `instructions` sections, Client Overview instruction cards.
4. **Permission matrix** — §8.
5. **Component reuse strategy** — §9 (client shell, api client, UI primitives, formatter).
6. **API integration plan:** `api.practice.{get,provision}`, `api.billing.{listSchedules,
   createSchedule,previewRun,generate,run,arAging,dashboard,sweep,sendReminders,
   unbilledWork,costRates}`, `api.knowledge.{list,get,create,editVersion,versions,restore,
   archive}`, `api.instructions.{list,create,update,archive}`, reuse `api.salesInvoices.
   {get,issue}` + `api.receipts.create`.
7. **Test plan:** per-role render/permission tests (Practice hidden for non-partner;
   internal client absent from lists); hook fetch tests (mocked API); empty/error states;
   CA-confirm gate present on draft issue; no-arithmetic lint on new files; full FE build
   (`pnpm build`) green.
8. **Rollout plan:** additive nav + new routes; legacy `/billing` untouched; no backend
   changes; feature-gated by role; ship behind the Partner role (no flag needed since
   backend already enforces). Reversible (remove nav entries + routes).

**Open decisions to validate (chat).**
