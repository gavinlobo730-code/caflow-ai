-- Migration 590: a client keeps narration templates for its manual journals (ledger POST-A-093).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═════════════════════════════════════════════════════════════════
-- A manual journal's narration is required and is the one place an entry says why it was made. A practice types the same few dozen
-- sentences every month for every client ("Being depreciation for the month", "Being salary payable for the month"), and Tally keeps
-- them for exactly that reason. Nothing here kept them: there was no narration template anywhere.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `journal_narration_templates`: one row per saved narration of one client. The words only: picking a template FILLS the journal's
--    narration box, and the entry stores the words, never the template, so archiving a template later changes no entry and no figure
--    reads one. `archived_at` takes a template out of the picker and keeps the row (nothing is hard-deleted from a signed-in path).
--  * A CHECK holds the words to 1..300 characters once trimmed, the length `domain/accounting/narration_templates.MAX_LENGTH` says; the
--    API refuses first, in words, and normalises the spacing. One live template per client per wording, ignoring case and spacing: a
--    partial unique index on `narration_key`, the key the API computes and compares by, so the picker never offers the same words twice
--    and the database and the API cannot disagree about what "the same" is.
--  * Read and written through the API only. Row security is on with the firm isolation, the assignment scope (a member reads only the
--    clients they are assigned; a Partner reads all) and the internal practice's Partner-only rule, in the set-based shape of
--    migrations 525 and 526. Every privilege is revoked from PUBLIC, anon and the signed-in role, and the signed-in role is given back
--    READ alone (the shape of 542); every write is the API's privileged client, which carries the acting person (547). anon holds
--    nothing.
--  * The two firm checks every new client table carries: a row's client belongs to its firm (565, `guard_client_firm`) and the member
--    it names belongs to its firm (566, `guard_member_firm`), installed by their own functions.
-- Nothing else changes and no row is written.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.journal_narration_templates (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id   UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  narration   TEXT        NOT NULL,
  -- What two templates are compared by: the words normalised and case-folded by the API (`domain/accounting/narration_templates.key`).
  -- Stored so the unique index below and the API's duplicate test are ONE rule: an index on lower(narration) folds a dotted capital I
  -- where Python's casefold() does not, and a save the API let through came back from the index as a bare error.
  narration_key TEXT      NOT NULL,
  created_by  UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  archived_at TIMESTAMPTZ,

  CONSTRAINT journal_narration_templates_words_are_a_line
    CHECK (char_length(btrim(narration)) BETWEEN 1 AND 300),
  CONSTRAINT journal_narration_templates_key_is_not_empty
    CHECK (char_length(narration_key) > 0)
);

COMMENT ON TABLE public.journal_narration_templates IS
  'POST-A-093, migration 590. Narrations a practice reuses on a client''s manual journals. Picking one fills the journal''s narration '
  'box; the entry stores the words, never the template, so archiving or rewording a template changes no entry. Written by the API only.';

CREATE INDEX IF NOT EXISTS idx_journal_narration_templates_client
  ON public.journal_narration_templates (firm_id, client_id)
  WHERE archived_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_narration_templates_live_words
  ON public.journal_narration_templates (client_id, narration_key)
  WHERE archived_at IS NULL;

ALTER TABLE public.journal_narration_templates ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "journal_narration_templates_firm_isolation" ON public.journal_narration_templates;
CREATE POLICY "journal_narration_templates_firm_isolation" ON public.journal_narration_templates
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "journal_narration_templates_assignment_scope" ON public.journal_narration_templates;
CREATE POLICY "journal_narration_templates_assignment_scope" ON public.journal_narration_templates
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "journal_narration_templates_internal_partner_only" ON public.journal_narration_templates;
CREATE POLICY "journal_narration_templates_internal_partner_only" ON public.journal_narration_templates
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.journal_narration_templates FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.journal_narration_templates TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.journal_narration_templates TO service_role;

DO $$
BEGIN
    PERFORM public.guard_client_firm('public.journal_narration_templates');
    PERFORM public.guard_member_firm('public.journal_narration_templates');
END $$;

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.journal_narration_templates', verb) THEN
                RAISE EXCEPTION 'migration 590: % still holds % on journal_narration_templates', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.journal_narration_templates', 'INSERT')
           OR has_any_column_privilege(r, 'public.journal_narration_templates', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 590: % still holds a column-level write privilege on journal_narration_templates', r;
        END IF;
    END LOOP;
    IF has_table_privilege('anon', 'public.journal_narration_templates', 'SELECT') THEN
        RAISE EXCEPTION 'migration 590: anon reads journal_narration_templates';
    END IF;
    IF NOT has_table_privilege('service_role', 'public.journal_narration_templates', 'INSERT') THEN
        RAISE EXCEPTION 'migration 590: the API (service_role) cannot write journal_narration_templates';
    END IF;
END $$;

COMMIT;
