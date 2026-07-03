-- 155 — Repair year-end workflow schema drift (fixes audit finding F9).
--
-- Migration 067 (Phase 6: Accounts Production Engine) created 8 tables for the
-- year-end close workflow, but every router built against that schema (routers/
-- year_end*.py, services/year_end_financial_service.py) targets columns 067
-- never created — and in three cases, a table name 067 never created at all.
-- Every one of those code paths 500s (NOT NULL violation or "column/relation
-- does not exist") the moment it runs against a real Postgres, not the FakeDB
-- double every existing test uses. This migration makes the schema match what
-- the already-built feature actually needs — additive only, via ADD COLUMN IF
-- NOT EXISTS / RENAME, so it is safe to apply on top of 067 in any order.
--
-- The 3 wrong table names (year_end_checklist_items, year_end_notes,
-- year_end_review_events) are NOT recreated here — the code itself is fixed
-- (this milestone) to reference 067's actual tables (year_end_checklists,
-- notes_to_accounts, year_end_reviews). Column drift on those 3 (plus every
-- correctly-named table) IS fixed here.

-- ── year_end_engagements ──────────────────────────────────────────────────────
-- routers/year_end.py (engagement_name) and routers/year_end_reviews.py (a
-- second, review-workflow-specific set of status-transition endpoints,
-- parallel to year_end.py's generic PATCH /status — see the audit doc for the
-- duplicate-implementation note) both write columns 067 never created.
ALTER TABLE public.year_end_engagements
  ADD COLUMN IF NOT EXISTS engagement_name         TEXT,
  ADD COLUMN IF NOT EXISTS submitted_by             UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS submitted_at             TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS revision_requested_by    UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS revision_comment         TEXT,
  ADD COLUMN IF NOT EXISTS final_approved_by        UUID REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS final_approved_at        TIMESTAMPTZ;

-- ── year_end_checklists ────────────────────────────────────────────────────────
-- Columns match routers/year_end_checklist.py column-for-column (fixed in
-- code: the WRONG table name the router used, and the router never
-- populating the NOT NULL firm_id column). The CHECK constraint's status
-- vocabulary does not, though: 067 allows 'not_started', but the router's
-- _STANDARD_ITEMS/_VALID_ITEM_STATUSES has always used 'pending' -- every
-- checklist auto-initialization (the first thing that happens when a new
-- engagement's checklist is opened) would violate this constraint. Widened
-- rather than narrowed, since 'pending' is the only value the code ever
-- writes and 'not_started' has no writers to preserve compatibility for.
ALTER TABLE public.year_end_checklists DROP CONSTRAINT IF EXISTS year_end_checklists_status_check;
ALTER TABLE public.year_end_checklists ADD CONSTRAINT year_end_checklists_status_check
  CHECK (status IN ('pending', 'in_progress', 'complete', 'not_applicable'));

-- ── year_end_adjustments ───────────────────────────────────────────────────────
-- The full submit -> approve/reject -> post workflow routers/
-- year_end_adjustments.py implements needs columns 067 never added.
ALTER TABLE public.year_end_adjustments
  ADD COLUMN IF NOT EXISTS debit_account_id  TEXT,
  ADD COLUMN IF NOT EXISTS credit_account_id TEXT,
  ADD COLUMN IF NOT EXISTS adjustment_date   DATE,
  ADD COLUMN IF NOT EXISTS reference_no      TEXT,
  ADD COLUMN IF NOT EXISTS submitted_by      UUID,
  ADD COLUMN IF NOT EXISTS submitted_at      TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS review_comment    TEXT,
  ADD COLUMN IF NOT EXISTS posted_by         UUID,
  ADD COLUMN IF NOT EXISTS posted_at         TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS rejected_by       UUID,
  ADD COLUMN IF NOT EXISTS rejected_at       TIMESTAMPTZ;

-- ── account_group_mappings ─────────────────────────────────────────────────────
-- routers/year_end_mappings.py and services/year_end_financial_service.py both
-- depend on normal_balance (debit/credit convention per Schedule III line) and
-- account_type, neither of which 067 created. 067 also has no updated_at at
-- all (only created_at), though the router updates/upserts a mapping's
-- updated_at on every write.
ALTER TABLE public.account_group_mappings
  ADD COLUMN IF NOT EXISTS normal_balance TEXT CHECK (normal_balance IN ('debit', 'credit')),
  ADD COLUMN IF NOT EXISTS account_type   TEXT,
  ADD COLUMN IF NOT EXISTS updated_at     TIMESTAMPTZ NOT NULL DEFAULT now();

-- account_name/statement_type are NOT NULL in 067 and the router never
-- populated them (would have 500'd on every insert). Relaxing NOT NULL here
-- rather than backfilling a value the router doesn't have at insert time
-- (account_name comes from the chart of accounts, not the mapping request
-- body; statement_type is derivable from schedule_line, both now done in code
-- for NEW rows going forward -- see routers/year_end_mappings.py).
ALTER TABLE public.account_group_mappings
  ALTER COLUMN account_name   DROP NOT NULL,
  ALTER COLUMN statement_type DROP NOT NULL;

-- ── financial_statement_versions ───────────────────────────────────────────────
-- routers/year_end_statements.py denormalizes client_id/financial_year onto
-- the snapshot row (avoids a join back through year_end_engagements for every
-- version list/read) and adds a free-text label/notes pair. The code's
-- "statements_data" was a typo for 067's actual "statement_data" column --
-- fixed in code (this milestone), not here.
ALTER TABLE public.financial_statement_versions
  ADD COLUMN IF NOT EXISTS client_id      UUID,
  ADD COLUMN IF NOT EXISTS financial_year VARCHAR(7),
  ADD COLUMN IF NOT EXISTS version_label  TEXT,
  ADD COLUMN IF NOT EXISTS notes          TEXT;

-- ── notes_to_accounts ───────────────────────────────────────────────────────────
-- routers/year_end_notes.py splits a note's body into a short human-readable
-- "content" string plus a structured "note_data" payload (line-item figures,
-- CA-review flags), rather than 067's single content_data JSONB blob --
-- content_data is left in place, unused, rather than migrating existing data
-- into a reshaped column. sequence_no orders notes for PDF/complete-pack
-- export; locked_by/locked_at record who locked a note (067 only tracked
-- is_locked, a boolean, with no actor/timestamp).
ALTER TABLE public.notes_to_accounts
  ADD COLUMN IF NOT EXISTS content     TEXT,
  ADD COLUMN IF NOT EXISTS note_data   JSONB,
  ADD COLUMN IF NOT EXISTS sequence_no INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS locked_by   UUID,
  ADD COLUMN IF NOT EXISTS locked_at   TIMESTAMPTZ;

-- ── year_end_reviews ────────────────────────────────────────────────────────────
-- routers/year_end_reviews.py's _record_review_event writes a free-form audit
-- trail (event_type + actor_id) that doesn't fit 067's review_type/action
-- CHECK-constrained vocabulary (prepared/reviewed/approved vs. the code's
-- actual submitted_for_review/approved/revision_requested/
-- final_approved_and_locked). Added as new columns rather than widening the
-- CHECK constraints to match, since review_type/action may still be useful
-- for a future structured review model -- they are simply unused (and, since
-- both were NOT NULL, would have blocked every insert) by today's code, not
-- removed. reviewed_by (also NOT NULL) IS populated by the code (= actor_id).
ALTER TABLE public.year_end_reviews
  ADD COLUMN IF NOT EXISTS event_type TEXT,
  ADD COLUMN IF NOT EXISTS actor_id   UUID,
  ALTER COLUMN review_type DROP NOT NULL,
  ALTER COLUMN action      DROP NOT NULL;

-- ── year_end_exports ────────────────────────────────────────────────────────────
-- routers/year_end_exports.py denormalizes client_id/financial_year onto the
-- export record (same rationale as financial_statement_versions) and adds a
-- free-text notes field. file_path -> storage_path is a straight rename: the
-- router uses "storage_path" consistently and exclusively, and this table has
-- no other consumers (confirmed: zero test coverage, grep-verified no other
-- file references year_end_exports.file_path).
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'year_end_exports'
               AND column_name = 'file_path')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'year_end_exports'
               AND column_name = 'storage_path') THEN
    ALTER TABLE public.year_end_exports RENAME COLUMN file_path TO storage_path;
  END IF;
END $$;

ALTER TABLE public.year_end_exports
  ADD COLUMN IF NOT EXISTS client_id      UUID,
  ADD COLUMN IF NOT EXISTS financial_year VARCHAR(7),
  ADD COLUMN IF NOT EXISTS notes          TEXT;
