# Batch 6 Completion Report — Knowledge Base + Client Instructions

**Amendment v1.1 (Phase 10B) · Batch 6 of 7 · Branch:** `claude/compassionate-darwin-nffpnb`
**Date:** 2026-06-14 · **Migration:** `079_knowledge_rls.sql` (+ rollback)

Built to the approved design review (`docs/BATCH_6_DESIGN_REVIEW.md`) and validated
decisions. Reuses the Batch-1 tables (073), Postgres FTS (no vectors), the
role/assignment model, `internal_client_service` (G1), `timeline_service`,
`audit_service`. Lightweight — not a wiki.

## Validated decisions implemented
- **No acknowledgement/completion** — client instructions are standing guidance
  (create/edit/pin/archive); Timeline created/updated/archived. No state columns.
- **Manager = firm-wide**, Partner firm-wide, Executive/Reviewer **assignment-gated**,
  internal-client **Partner-only (G1)**, portal clients never see KB.
- **Articles: Manager+ author/edit; Client instructions: Executive+ (Executive only
  for assigned clients); Reviewer read-only; Client none.**

## 1. Versioning
- Edit appends a new `knowledge_article_versions` row (`version = current+1`) and bumps
  `current_version`. **History is immutable** (`UNIQUE(article_id, version)`; no
  UPDATE/DELETE). **Rollback** = write the chosen version's content as a *new* version
  (non-destructive, auditable). Race-safe via the unique constraint.

## 2. Search
- Postgres FTS (GIN on title + content from 073) + tags + title `ILIKE`. Firm KB list
  excludes client-scoped + internal-client rows; client search filters `client_id` and
  is assignment-gated. Results restricted to the caller's visible set.

## 3. Client instructions
- Client-scoped standing guidance; pinned cards for the client workspace; CRUD +
  pin/archive (soft). Timeline event per action on the client.

## 4. Timeline / audit
- Client-scoped article + all instruction events → **client Timeline**
  (`timeline_service.log`). Firm/department article events → **`audit_log`**
  (firm-level), since `client_timeline_events` is per-client.

## 5. Security model (service-role ⇒ API primary; RLS defense-in-depth)
- **API primary:** `knowledge_service` visibility helpers (`can_view_client_content`,
  `can_write_instruction`) enforce role + assignment + internal-client (G1) on every
  read/write; RBAC resources `knowledge` (Manager+ write) and `client_instruction`
  (Executive+ write). Client-scoped endpoints sit under `/api/clients/{client_id}/...`
  so the Batch-2.1 `require_client_access` guard also gates the internal client.
- **RLS (079):** RESTRICTIVE assignment-gated policies on `knowledge_articles`
  (client-scoped) + `client_instructions`; internal-client partner-only on
  `knowledge_articles` (client_instructions already covered in 074); new
  `get_my_user_id()` helper.

## 6. Files
**New:** `migrations/079_knowledge_rls.sql` (+ rollback), `services/knowledge_service.py`,
`routers/knowledge.py`, `tests/test_batch6_knowledge.py`, `tests/test_batch6_migration.py`,
`tests/sql/batch6_knowledge_verify.sql`, `docs/BATCH_6_DESIGN_REVIEW.md`.
**Modified:** `core/permissions.py` (`knowledge` + `client_instruction` resources),
`main.py` (register knowledge router with the client-access guard).

**Endpoints:** `GET/POST /api/knowledge/articles`, `GET/PATCH /api/knowledge/articles/{id}`,
`GET/POST /api/knowledge/articles/{id}/versions`, `POST /{id}/restore/{version}`,
`POST /{id}/archive`; `GET /api/clients/{id}/knowledge`;
`GET/POST /api/clients/{id}/instructions`, `PATCH .../instructions/{iid}`,
`POST .../instructions/{iid}/archive`.

## 7. Test results
- **Application (`test_batch6_knowledge.py`, 8, mock):** visibility matrix (Partner/
  Manager/Executive/Reviewer/Client × internal × assigned), instruction-write matrix,
  `next_version`, RBAC (knowledge Manager+/all-read; client_instruction Executive+
  write/Reviewer read). PASS.
- **DB RLS (`test_batch6_migration.py` + SQL harness, real PG):** assigned Executive
  sees firm + assigned-client content (not internal); unassigned Executive gated
  (read + write denied); Manager firm-wide but not internal; Partner full access;
  **version immutability** (duplicate version rejected); clean 079 rollback. PASS.
- **Regression:** full suite **1025 passed**; the same **23 pre-existing Supabase-503
  environmental failures** — no regression.

## 8. Residual notes
- KB tables are DB-only (no mock store), so service CRUD is thin over Supabase and the
  security logic lives in pure helpers (unit-tested) + RLS harness.
- `knowledge_article_versions` carries firm RLS (073); article-level visibility on
  versions is enforced in the API (`_load_article_or_404`).
- Department scope is an organisational tag (all firm staff), not a hard access
  boundary in v1 (per the design review).
- UI surfaces (Practice/Client Knowledge tabs, instruction cards) are listed in the
  design review and implemented in the frontend batch (Batch 7).
- **Out of scope (untouched):** AI memory/vector/RAG, Revenue Intelligence, workflow
  automation, document system.

**Status: Batch 6 complete and passing. Holding before Batch 7 (frontend: Practice workspace + Revenue/KB UI).**
