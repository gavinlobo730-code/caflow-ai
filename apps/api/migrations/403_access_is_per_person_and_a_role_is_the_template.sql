-- Migration 403: access becomes PER PERSON, and a role becomes the template it
-- is pre-filled from.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- `rbac(resource, action)` decided every one of its 1037 call sites from the
-- caller's ROLE alone, and a role is five buckets. A practice does not staff
-- itself in five buckets: one Executive runs GST and TDS and never touches
-- payroll, another runs payroll and nothing else, and a senior Manager is
-- trusted with the firm's own billing while their peer is not. None of that is
-- expressible, so the firm either promotes somebody to reach one screen — which
-- hands them every other screen that tier opens — or does the work outside the
-- product.
--
-- The Team screen already showed a per-member grid, headed "Toggle access per
-- member per module. Changes are saved instantly. Overrides the role default
-- for that individual." Every clause was false: the toggles went into
-- `localStorage`, reaching no other user, device or server, and nothing in
-- `core/permissions.py` could have honoured them. It was made READ-ONLY rather
-- than deleted, because the need it described is real. This table is the need,
-- built.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE ROLE SURVIVES, AND THIS IS THE LOAD-BEARING PART
-- ═══════════════════════════════════════════════════════════════════════════
-- The obvious build is to delete roles and hold only per-person grants. It was
-- rejected on a measurement: `public.get_my_role()` is asked at 61 sites across
-- 32 migrations, and those policies are what protect the ~83 tables the browser
-- reads DIRECTLY over PostgREST, where `rbac()` never runs at all. Rewriting
-- them per-person is a migration touching ~50 tables whose failure mode is a
-- silent cross-client read — no error, no log, nothing that surfaces.
--
-- So the role keeps two jobs and loses one. It keeps answering the SQL policies
-- and `core.authz._FIRMWIDE_ROLES` (who sees every client rather than their own
-- assigned book — a different question from which screens open, and one this
-- grid deliberately does not answer). It keeps being the TEMPLATE a new hire's
-- grid is pre-filled from, so onboarding stays one choice instead of thirty
-- toggles, each of which is silent when wrong. What it stops being is the last
-- word: where a row exists here, it wins.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- ABSENCE IS THE ROLE DEFAULT, WHICH IS EXACTLY TODAY'S BEHAVIOUR
-- ═══════════════════════════════════════════════════════════════════════════
-- `granted` is NOT NULL and the ROW is what is optional — three states, not a
-- nullable boolean: no row means "whatever the role says", true means allowed
-- however junior the role, false means refused however senior. That is why
-- there is NO BACKFILL and no default row per user: an empty table reproduces
-- the current behaviour for every existing member exactly, so this migration
-- changes nobody's access on the day it lands. A backfill would freeze today's
-- role map into 30-odd rows per person and detach them from `PERMISSIONS` the
-- moment it is edited — the `account_group_mappings` mistake, where a cached
-- derivation outranked the derivation and no later change reached it.
--
-- The pair is stored as free TEXT with no CHECK. The vocabulary is
-- `core/permissions.PERMISSIONS`, a Python dict, and a CHECK constraint cannot
-- read one; a hand-copied list in SQL is the second authority this codebase
-- keeps having to delete. The API door validates against the dict instead and
-- the resolver ignores a pair it does not recognise, so a stale row is inert
-- rather than dangerous.
--
-- Additive. Idempotent. Reversible: 403_..._rollback.sql.
-- No application behaviour changes until `core/permissions.can_user` reads it.

CREATE TABLE IF NOT EXISTS public.user_permissions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     uuid NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    resource    text NOT NULL,
    action      text NOT NULL,
    -- NOT NULL deliberately: the third state is the ABSENCE of the row, not a
    -- NULL in it. A nullable boolean would give two spellings of "no opinion"
    -- and the resolver would have to treat them the same, which is how one of
    -- them silently becomes a deny.
    granted     boolean NOT NULL,
    -- Who decided, so the audit trail on a permission change names a person.
    granted_by  uuid REFERENCES public.users(id),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT user_permissions_one_answer_per_pair UNIQUE (user_id, resource, action)
);

COMMENT ON TABLE public.user_permissions IS
    'Per-person access overrides. A row OVERRIDES the role default for one '
    '(resource, action) pair; no row means the role decides. The vocabulary is '
    'core/permissions.PERMISSIONS and is validated at the API door, not by a '
    'CHECK — a hand-copied list in SQL would be a second authority. '
    'Migration 403.';
COMMENT ON COLUMN public.user_permissions.granted IS
    'true = allowed however junior the role; false = refused however senior. '
    'NOT NULL: the third state is the absence of the row.';

CREATE INDEX IF NOT EXISTS idx_user_permissions_user ON public.user_permissions(user_id);
CREATE INDEX IF NOT EXISTS idx_user_permissions_firm ON public.user_permissions(firm_id);

ALTER TABLE public.user_permissions ENABLE ROW LEVEL SECURITY;

-- Firm isolation plus role-guarded access, in the shape migrations 260/261
-- established and 376/377 last used. There is NO assignment-scope policy and
-- that is not an omission: the row carries no client_id — it is a fact about a
-- member of the firm, not about a client's books — so `can_access_client` has
-- nothing to ask.
--
-- The tiers match `PERMISSIONS["team"]` exactly (read Manager+, write
-- Partner-only), because the app-layer check is the primary control and RLS is
-- defence in depth; the two disagreeing would mean one of them is decorative.
-- Reading this table is reading who may do what across the whole firm, which is
-- the Team screen, which is already Manager+.
DO $$
BEGIN
  EXECUTE 'DROP POLICY IF EXISTS firm_user_permissions ON public.user_permissions';
  EXECUTE 'CREATE POLICY firm_user_permissions ON public.user_permissions '
          'FOR ALL TO authenticated '
          'USING (firm_id = public.get_my_firm_id()) '
          'WITH CHECK (firm_id = public.get_my_firm_id())';

  -- Kept contiguous in ONE string literal: tests/test_direct_write_tables_are_
  -- role_guarded.py reads the migration FILE, and a policy split across
  -- adjacent literals is valid SQL and invisible to that scan.
  EXECUTE 'DROP POLICY IF EXISTS user_permissions_role_select ON public.user_permissions';
  EXECUTE 'CREATE POLICY user_permissions_role_select '
          'ON public.user_permissions AS RESTRICTIVE '
          'FOR SELECT USING (public.my_role_at_least(''Manager''))';

  EXECUTE 'DROP POLICY IF EXISTS user_permissions_role_insert ON public.user_permissions';
  EXECUTE 'CREATE POLICY user_permissions_role_insert '
          'ON public.user_permissions AS RESTRICTIVE '
          'FOR INSERT WITH CHECK (public.my_role_at_least(''Partner''))';

  EXECUTE 'DROP POLICY IF EXISTS user_permissions_role_update ON public.user_permissions';
  EXECUTE 'CREATE POLICY user_permissions_role_update '
          'ON public.user_permissions AS RESTRICTIVE '
          'FOR UPDATE USING (public.my_role_at_least(''Partner'')) '
          'WITH CHECK (public.my_role_at_least(''Partner''))';

  EXECUTE 'DROP POLICY IF EXISTS user_permissions_role_delete ON public.user_permissions';
  EXECUTE 'CREATE POLICY user_permissions_role_delete '
          'ON public.user_permissions AS RESTRICTIVE '
          'FOR DELETE USING (public.my_role_at_least(''Partner''))';
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_permissions TO authenticated;
