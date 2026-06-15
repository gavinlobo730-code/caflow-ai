-- PracticeSync AI — Migration 084: Assignment-scoped RLS (Module 9.0 / M5)
--
-- Goal: database-enforced assignment boundaries. Even if an API route, a
-- repository query, or a direct frontend (anon-key) query is implemented
-- incorrectly, Postgres RLS must not return clients a user is not assigned to.
--
-- Enforcement scope: RLS governs every NON-service-role connection (frontend
-- anon-key reads, PostgREST, direct DB). The backend connects with the
-- service_role key, which BYPASSES RLS — that path stays enforced at the
-- application layer (Module 9.0 M2 core.authz). Migrating the backend to a
-- per-user JWT (so RLS also covers it) is the documented next step and is NOT
-- done here, to avoid a production-breaking change.
--
-- Model (mirrors M3 Option B): Partner = full firm; Manager/Executive/Reviewer =
-- assigned clients only; rows with NULL client_id (firm-level) remain visible.
--
-- Mechanism: a RESTRICTIVE policy AND-s with the existing permissive
-- *_own_firm (firm isolation) and *_internal_partner_only (G1) policies — it can
-- only REMOVE access, never grant it. Partner short-circuits to TRUE, so the
-- only firm in production today (Partners only) is unaffected.
--
-- Idempotent. Reversible: 084_assignment_scoped_rls_rollback.sql.

-- ── Security helper ──────────────────────────────────────────────────────────
-- SECURITY DEFINER so it can read users + user_client_assignments regardless of
-- the caller's own RLS. search_path pinned (advisor 0011 + injection safety).
CREATE OR REPLACE FUNCTION public.can_access_client(p_client_id text)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public
AS $$
  SELECT
    p_client_id IS NULL
    OR public.get_my_role() = 'Partner'
    OR EXISTS (
      SELECT 1
      FROM public.user_client_assignments a
      JOIN public.users u ON u.id = a.user_id
      WHERE u.auth_user_id = auth.uid()
        AND a.client_id::text = p_client_id
    );
$$;

COMMENT ON FUNCTION public.can_access_client(text) IS
  'Module 9.0 M5: TRUE if the current user may access the given client (Partner = all; others = assigned via user_client_assignments; NULL = firm-level).';

-- ── clients table (keyed by its own id) ──────────────────────────────────────
ALTER TABLE public.clients ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "clients_assignment_scope" ON public.clients;
CREATE POLICY "clients_assignment_scope" ON public.clients
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(id::text))
  WITH CHECK (public.can_access_client(id::text));

-- ── notifications (recipient-scoped, not client-scoped) ──────────────────────
-- A notification is personal to its recipient; Partners may read all (oversight).
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "notifications_recipient_scope" ON public.notifications;
CREATE POLICY "notifications_recipient_scope" ON public.notifications
  AS RESTRICTIVE FOR ALL
  USING (public.get_my_role() = 'Partner' OR user_id = public.get_my_user_id())
  WITH CHECK (public.get_my_role() = 'Partner' OR user_id = public.get_my_user_id());

-- ── Every other base table with a client_id column ───────────────────────────
-- Skips: the assignment table itself, the already-assignment-gated KB tables,
-- notifications (handled above), and anything that is not a base table (views).
DO $$
DECLARE
  t text;
  skip text[] := ARRAY[
    'user_client_assignments',   -- the assignment source (helper reads it via SECURITY DEFINER)
    'knowledge_articles',        -- assignment-gated already (migration 079)
    'client_instructions',       -- assignment-gated already (migration 079)
    'notifications'              -- recipient-scoped above
  ];
BEGIN
  FOR t IN
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN information_schema.tables tb
      ON tb.table_schema = c.table_schema AND tb.table_name = c.table_name
    WHERE c.table_schema = 'public'
      AND c.column_name = 'client_id'
      AND tb.table_type = 'BASE TABLE'        -- exclude views (e.g. salary_slips)
      AND c.table_name <> ALL(skip)
  LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_assignment_scope', t);
    EXECUTE format(
      'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
      || 'USING (public.can_access_client(client_id::text)) '
      || 'WITH CHECK (public.can_access_client(client_id::text))',
      t || '_assignment_scope', t);
  END LOOP;
END $$;
