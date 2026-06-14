# Batch 6 Design Review — Knowledge Base + Client Instructions

**Amendment v1.1 (Phase 10B) · Branch:** `claude/compassionate-darwin-nffpnb` · **Status: design only, awaiting approval.**

Scope: KB articles + versions, search, client instructions, Timeline integration,
assignment-gated visibility, RLS, Partner/Staff controls. **Out:** AI memory/vector/RAG,
Revenue Intelligence, workflow automation, new document system, refactors.

**Foundation already in place (Batch 1, migration 073):** `knowledge_articles`,
`knowledge_article_versions`, `client_instructions` tables exist with **firm-scoped
RLS** + GIN FTS indexes (title, content) + tags GIN. Batch 6 adds the **service +
API + UI** and **refines RLS to assignment-gating**. No new tables required (one
small RLS/helper migration).

---

## 1. Knowledge Base architecture

- **A Knowledge Article** = a versioned, typed piece of operational firm knowledge:
  an SOP, compliance checklist, or internal policy. Scope is **firm**, **department**,
  or **client**.
- **Problem solved:** institutional knowledge today lives in individuals → staff
  turnover/leave is risk; a new joiner takes months. KB makes "how we do GST recon"
  durable, searchable, and surfaced at the client — the compounding-knowledge moat
  (PRD §11.3), kept *operational, not a wiki* (Amendment FR-KB-04).
- **Fit:** reuses existing storage (Postgres), RLS, search (Postgres FTS),
  `timeline_service`, role/assignment model, and the client workspace shell. No new
  subsystem.

**Data model (existing 073 tables):**
- `knowledge_articles(id, firm_id, scope[firm|department|client], department,
  client_id→clients (null unless scope=client), title, current_version int, tags[],
  is_archived, created_at, updated_at, created_by)`
- `knowledge_article_versions(id, firm_id, article_id→knowledge_articles, version,
  content, changed_by, changed_at, UNIQUE(article_id, version))`
- `client_instructions(id, firm_id, client_id→clients, title, body, is_pinned,
  created_by, created_at, updated_at)`

**Ownership:** firm-owned (`firm_id`); `created_by`/`changed_by` attribute authorship.
**Lifecycle:** Draft v1 → published (current_version) → edited (new version) →
(rollback = new version copying old content) → archived (`is_archived`, soft, never
deleted).

**Scope semantics:**
- **Firm-scoped** (`scope=firm`, `client_id` null): all firm staff.
- **Department-scoped** (`scope=department`, `department` set): all firm staff
  (department is an organisational tag; not a hard access boundary in v1).
- **Client-scoped** (`scope=client`, `client_id` set): assignment-gated; surfaced in
  that client's workspace. **Internal-client** client-scoped content → **Partner-only**
  (G1).
- **Shared content** = firm/department scope. **Internal-only** = client-scoped to the
  internal practice client (partner-only). Clients (portal users) **never** see KB.

---

## 2. Versioning strategy

- **Create:** inserting an article writes `knowledge_article_versions` v1 (content) and
  sets `current_version=1`.
- **Edit:** never mutates an existing version. A new row `version = current_version+1`
  with the new content is inserted; `knowledge_articles.current_version` is bumped.
  `UNIQUE(article_id, version)` makes this race-safe (concurrent edits → one wins,
  retry).
- **Current version:** `knowledge_articles.current_version` → the matching versions row.
- **History:** all versions remain (immutable; no UPDATE/DELETE of version rows).
- **Rollback:** "restore vN" = read vN's content and write it as a **new** version
  (vN+1) — non-destructive, fully auditable (who rolled back, when).

**Article lifecycle:** create → edit (×n) → rollback (→ new version) → archive.
**Version lifecycle:** appended once, never edited/deleted (immutable history).

---

## 3. Search strategy (Postgres FTS — no embeddings/vectors)

- **Indexed fields (already exist, 073):** GIN `to_tsvector('english', title)` on
  articles; GIN `to_tsvector('english', content)` on versions; GIN on `tags`.
- **Query:** `plainto_tsquery` against title + **current-version** content; plus tag
  containment (`tags @> ARRAY[q]`) and title `ILIKE` for prefix/substring.
- **Ranking:** `ts_rank` over title (weighted higher) + content; tie-break by
  `updated_at` desc.
- **Filtering:** `is_archived=false` default; by `scope`, `department`, `client_id`,
  `tags`. **Client-specific search** filters `client_id` and is assignment-gated.
- Search runs over the caller's **visible set only** (RLS + API filter), so results
  never leak unassigned-client or internal-client content.

---

## 4. Client instructions model

- **Qualifies as a client instruction:** a standing, client-specific operating note —
  e.g. "route approvals via the CFO", "GST filing only after partner sign-off". Not a
  task, not a one-off message — a **persistent instruction** surfaced whenever the
  client workspace opens (Amendment FR-KB-02).
- **Relationship to clients:** always client-scoped (`client_id` NOT NULL).
- **Relationship to assignments:** visible to assigned staff (+ Partner/Manager
  firm-wide). Internal-client instructions → Partner-only.
- **Relationship to timeline:** create/edit/pin/archive write a Timeline event on the
  client (traceable, auditable).
- **Lifecycle:** create → edit → pin/unpin → archive (soft). **Acknowledgement /
  completion is NOT in the Amendment schema** — see the open decision in §10/Deliverable.
- **Visibility:** surfaced as pinned cards atop the client Overview; assignment-gated.

---

## 5. Timeline integration

| Action | Event | Target | Category/severity |
|---|---|---|---|
| Client-scoped article created | `kb_article_created` | client timeline | `ai`/info |
| Client-scoped article version added (edit/rollback) | `kb_article_updated` | client timeline | `ai`/info |
| Client-scoped article archived | `kb_article_archived` | client timeline | `ai`/info |
| Firm/department article created/updated/archived | same types | **audit_log** (firm-level; no client) | — |
| Client instruction created | `client_instruction_created` | client timeline | `ai`/info |
| Client instruction updated/pinned/archived | `client_instruction_updated` | client timeline | `ai`/info |

- **Why split:** `client_timeline_events` is **per-client** (requires `client_id`).
  Firm/department article events have no client → recorded in the firm-level immutable
  `audit_log` instead. Client-scoped article + all instruction events → client Timeline.
- **Event structure:** reuse `timeline_service.log(...)` (title sentence, entity_type=
  `knowledge_article`/`client_instruction`, entity_id, actor, action link).
- **Ownership:** firm-scoped (`firm_id`), attributed to actor. **Retention:** append-only/
  soft-delete per the existing Timeline + audit policy.
- **Acknowledgement/completion events** appear only if that feature is approved (§10).

---

## 6. Assignment-gated visibility (critical)

**Mechanism:** `user_client_assignments(user_id, client_id, firm_id)`; a new
SECURITY-DEFINER helper `get_my_user_id()` (users.id for `auth.uid()`); assignment =
`EXISTS (SELECT 1 FROM user_client_assignments WHERE user_id=get_my_user_id() AND
client_id=<row>.client_id)`. **Partner/Manager** see all firm clients; **Executive/
Reviewer** are assignment-gated. Internal-client content → **Partner-only** (G1).

**Visibility matrix** (firm context; Client = portal user):

| Surface | Partner | Manager | Executive | Reviewer | Client |
|---|---|---|---|---|---|
| Firm/department articles (read) | ✓ | ✓ | ✓ | ✓ | ✗ |
| Article author/edit/version/archive | ✓ | ✓ | ✗ (proposed) | ✗ | ✗ |
| Client-scoped article (read) | ✓ all | ✓ all | ✓ if **assigned** | ✓ if **assigned** | ✗ |
| Client instruction (read) | ✓ all | ✓ all | ✓ if **assigned** | ✓ if **assigned** | ✗ |
| Client instruction (write) | ✓ | ✓ | ✓ if **assigned** (proposed) | ✗ | ✗ |
| Internal-client article/instruction | ✓ **only** | ✗ | ✗ | ✗ | ✗ |

**Edge cases:**
- *Internal practice client* content: Partner-only even for Managers (G1) — overrides
  the matrix.
- *Unassigned Executive/Reviewer* on a client: no client-scoped article or instruction
  for that client; firm/department articles still visible.
- *Article scope change* (client→firm): becomes firm-visible; *firm→client*: becomes
  assignment-gated (re-evaluate on scope edit).
- *Client (portal) users*: never see any KB or instruction (separate audience).
- *Role drift*: DB role CHECK allows extra labels (`Admin`, `Staff`, `Viewer`, lower-case);
  app roles are Partner/Manager/Executive/Reviewer/Client. I'll map `Staff→Executive`,
  `Viewer→Reviewer`, `owner→Partner` consistently with prior batches.

---

## 7. Relationship to existing systems (clear separation)

| System | What it is | Why KB is separate |
|---|---|---|
| **Documents** | Uploaded/generated files (PDF/Excel) with extraction + storage path | KB is **authored, versioned text** (SOPs/policies), full-text searchable, surfaced in-workspace — not a file blob. No OCR/extraction. |
| **Timeline** | Append-only **event log** ("what happened, when") | KB is **durable reference knowledge** ("how we do X"); Timeline records *that* an article changed, but isn't the article. |
| **AI Memory** | Computed semantic profiles + anomaly triggers (nightly) | KB is **human-authored, deliberate** knowledge; not derived/probabilistic. (No vector/RAG — explicitly out of scope.) |
| **Client Notes / tasks** | Per-client ad-hoc notes / actionable work items | A client instruction is a **standing directive** surfaced on every workspace open — not a one-off note or a task with a due date. |

---

## 8. RLS & security model (service-role ⇒ API is primary; RLS is defense-in-depth)

- **Firm isolation:** existing `*_own_firm` policies (073) — `firm_id = get_my_firm_id()`.
- **Assignment isolation (new, migration 079):** RESTRICTIVE policies on
  `knowledge_articles` (client-scoped rows) + `client_instructions`:
  `get_my_role() IN ('Partner','Manager') OR client_id IS NULL OR EXISTS(assignment)`.
- **Client isolation:** rows carry `client_id`; assignment/role predicate gates access.
- **Internal-client handling:** RESTRICTIVE `client_id IS DISTINCT FROM
  my_internal_client_id() OR get_my_role()='Partner'` on `knowledge_articles` +
  `client_instructions` (the latter already in 074's list; add articles in 079).
- **Partner-only actions:** internal-client KB; (optionally) destructive archive.
- **Primary controls (Python, because service-role bypasses RLS):**
  - **Repository/API:** every read filters by `firm_id` + the assignment/role predicate
    + `is_internal` partner gate (reuse `internal_client_service`); writes gated by the
    `knowledge`/`client_instruction` RBAC resources.
  - **RLS (079):** the same predicates as defense-in-depth for any direct DB access.
- **Versions table:** inherits the parent article's visibility (join to article;
  enforce in API; firm RLS on versions).

---

## 9. UI surface review (no implementation)

| Surface | Change | Journey / permissions |
|---|---|---|
| **Practice / Firm — Knowledge tab** (Rail 1 or Settings) | NEW: list/search firm & department articles; view versions; author/edit (Manager+) | Staff search SOPs; Manager authors. Client-scoped + internal-client content excluded from this firm list. |
| **Client workspace — Knowledge section** | NEW: client-scoped articles for the open client | Assignment-gated; partner sees internal client's here (Practice workspace). |
| **Client Overview — Instruction cards** | NEW: pinned client-instruction cards atop Overview | Surfaced on open; assignment-gated; Manager+/assigned can add/edit. |
| **Article editor** | NEW: structured rich-text content + version history viewer + "restore version" | Manager+ (proposed). Rollback creates a new version. |
| **Global search** | OPTIONAL: include KB results | Scoped to caller's visible set. |

Navigation stays within the dual-rail model; no third nav level. Permission handling
mirrors prior batches (RBAC + assignment + internal-client guard; hide-if-empty).

---

## 10. Risk assessment

| Risk | Severity | Mitigation | Testing |
|---|---|---|---|
| Client-scoped article/instruction leaks to **unassigned** staff | High | Assignment predicate in API **and** RLS; Partner/Manager-only firm-wide | RLS negative tests (assigned vs unassigned Executive); API tests |
| **Internal-client** KB leaks to non-partners | High | `my_internal_client_id()` partner-gate in API + RLS (079) | Negative tests (staff/manager blocked, partner allowed) |
| **Client (portal) user** sees KB | High | KB endpoints are firm-audience only (no portal router exposure) | Test portal token cannot reach KB endpoints |
| Destructive edit / lost history | Med | Append-only versions; rollback = new version; no UPDATE/DELETE of versions | Version-immutability test; rollback test |
| Search returns out-of-scope rows | Med | Search restricted to visible set (filters applied before FTS) | Search isolation test (firm/assignment/internal) |
| Concurrent edits collide | Low | `UNIQUE(article_id, version)`; retry on conflict | Concurrency/idempotency test |
| Scope-change visibility surprise | Low | Re-evaluate visibility on scope edit; documented | Scope-change test |
| Role drift (DB vs app roles) | Low | Normalise via existing role mapping (`Staff→Executive`, etc.) | Role-mapping unit test |

---

# Deliverables

### 1. Design review — above.

### 2. Recommended implementation plan (batches of work)
1. **Migration 079** (assignment-gated RLS + helper) — small, additive.
2. **`knowledge_service.py`** — article CRUD + versioning (create/edit/rollback),
   search, archive; visibility helpers (reuse `internal_client_service`).
3. **`client_instructions` service** (same module) — CRUD + pin + surface-in-workspace query.
4. **RBAC resources** `knowledge` + `client_instruction` (read/write levels).
5. **Routers**: `routers/knowledge.py` (firm KB) + client-workspace endpoints
   (`/api/clients/{id}/knowledge`, `/api/clients/{id}/instructions`) under the Batch-2.1
   client guard.
6. **Timeline/audit wiring**.
7. **Tests** + **SQL harness**. 8. **Docs/report**.

### 3. Required migrations
- **079_knowledge_rls.sql** (+ rollback): `get_my_user_id()` helper; RESTRICTIVE
  assignment-gated policies on `knowledge_articles` (client-scoped) + `client_instructions`;
  internal-client partner-only RESTRICTIVE on `knowledge_articles`. *(No new tables.)*
- **Open decision:** if acknowledgement/completion is wanted, a tiny additive
  `client_instructions.acknowledged_by/acknowledged_at` (else omitted to stay lightweight).

### 4. Required API changes (all firm-audience, RBAC + assignment + internal-client gated)
- `knowledge`: `GET /api/knowledge/articles` (search/list), `POST` (create),
  `GET/PATCH /api/knowledge/articles/{id}`, `POST /{id}/versions` (edit),
  `GET /{id}/versions`, `POST /{id}/restore/{version}`, `POST /{id}/archive`.
- client workspace: `GET /api/clients/{id}/knowledge`, `GET/POST/PATCH
  /api/clients/{id}/instructions`, `POST /instructions/{id}/archive`.

### 5. Required UI changes — §9 (deferred to build; surfaces listed, not implemented).

### 6. Test strategy
- **Mock unit:** versioning (create→edit→rollback, current_version, immutability),
  search ranking/filter (pure), visibility helper matrix (Partner/Manager/Exec/Reviewer/
  Client × assigned/unassigned × internal), timeline event emission, partner-only internal,
  portal-audience blocked.
- **SQL harness (real PG):** migration 079 policies; assignment-gated RLS (assigned vs
  unassigned Executive); internal-client partner-only; version `UNIQUE`/immutability;
  FTS query; rollback.
- **Regression:** full suite green; 23 pre-existing env failures unchanged.

### 7. Rollout strategy
- Forward-only additive migration 079 (RLS + helper only; tables already exist from
  073). No data migration. Backward-compatible (firm-only policies are *tightened* to
  assignment-gating — verify no current feature reads these tables yet; KB is new, so
  no consumer regresses). Rollback drops 079 objects, reverting to firm-only RLS.
  Remote applied separately in the MCP-enabled session.

---

**Three decisions to validate before coding** (see chat).
