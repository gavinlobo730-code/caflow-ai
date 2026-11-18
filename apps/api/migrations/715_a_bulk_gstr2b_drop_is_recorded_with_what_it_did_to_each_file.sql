-- Migration 715: a bulk GSTR-2B drop is recorded with what it did to each file (POST-A-057).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- The firm-level GST page takes a drop of GSTR-2B files, routes each to the client whose GSTIN it names and reconciles it, one file per
-- request. The answer for each file (reconciled, matched no client, refused and why, what it replaced) lived only in the browser that sent
-- it: close the tab and nothing said what the drop did. `gstr2b_uploads` keeps each reconciled file, but not the drop it came in, and keeps
-- nothing for a file that was refused or matched no client.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- Two tables, written by the API's privileged client only:
--   * `gstr2b_bulk_drops`: one row per drop, the firm and the member who made it, and how many files of it reached the server and are
--     NOT in the file rows (`unrecorded_files`). The first request of a drop creates it and every later request of the same drop names it.
--   * `gstr2b_bulk_drop_files`: one row per file the server answered, with the status, the sentence, the GSTIN the file named, the month,
--     the client it was routed to (NULL where it was routed to none), whether it needs a look, the counts, the problems, the registration
--     caveat and what it replaced, exactly as the answer carried them. A client's name is not stored: it is read when the drop is read back.
--     The file's own content is not stored here (a reconciled file is kept in `gstr2b_uploads`, as before).
-- A file row names a drop OF ITS OWN FIRM (a composite foreign key), and a client of its own firm (`guard_client_firm`); a drop names a
-- member of its own firm (`guard_member_firm`).
--
-- SECURITY, the shape of migration 671 with 660's per-client policies on the file rows: row security on, the firm isolation, the RESTRICTIVE
-- assignment scope and the internal practice Partner-only on the file rows, and every privilege revoked from PUBLIC, anon and the signed-in
-- role. Nothing signed in reads or writes either table; the API reads them back for the member who made the drop, narrowed to the clients
-- that member may see now.
--
-- DEPLOY ORDER: the API ahead of this migration finds no table; the drop is reconciled exactly as before and its answer says it was not
-- recorded. Nothing reads the tables but the API.
--
-- Idempotent. Reversible: 715_..._rollback.sql drops both tables (the record of past drops is lost; the reconciliations themselves are not).

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.gstr2b_bulk_drops (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  created_by  UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Files of this drop that reached the server and whose answer is NOT in gstr2b_bulk_drop_files: the file rows' write failed, or the
  -- request failed after the drop was opened. The read-back says how many, so a drop is never shown as complete when it is not.
  unrecorded_files INTEGER NOT NULL DEFAULT 0,
  CONSTRAINT gstr2b_bulk_drops_id_firm UNIQUE (id, firm_id),
  CONSTRAINT gstr2b_bulk_drops_unrecorded_is_a_count CHECK (unrecorded_files >= 0)
);

COMMENT ON TABLE public.gstr2b_bulk_drops IS
  'POST-A-057, migration 715. One bulk GSTR-2B drop: the firm and the member (users.id) who made it. Written by the API only.';

CREATE INDEX IF NOT EXISTS idx_gstr2b_bulk_drops_firm_member
  ON public.gstr2b_bulk_drops (firm_id, created_by, created_at DESC);

CREATE TABLE IF NOT EXISTS public.gstr2b_bulk_drop_files (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  drop_id             UUID        NOT NULL,
  -- The order the server answered the files in, across the drop's requests.
  seq                 BIGINT      GENERATED ALWAYS AS IDENTITY,
  client_id           UUID        REFERENCES public.clients(id) ON DELETE SET NULL,
  name                TEXT        NOT NULL DEFAULT '',
  -- `services/gst_2b_bulk_service.STATUSES`; a test holds the two lists identical.
  status              TEXT        NOT NULL,
  reason              TEXT,
  gstin               TEXT        NOT NULL DEFAULT '',
  period              TEXT,
  needs_attention     BOOLEAN     NOT NULL DEFAULT false,
  summary             JSONB,
  problems            JSONB       NOT NULL DEFAULT '[]'::jsonb,
  registration_caveat TEXT,
  replaced_earlier    JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT gstr2b_bulk_drop_files_drop_of_its_firm
    FOREIGN KEY (drop_id, firm_id) REFERENCES public.gstr2b_bulk_drops (id, firm_id) ON DELETE CASCADE,
  CONSTRAINT gstr2b_bulk_drop_files_status_is_known
    CHECK (status IN ('reconciled', 'unmatched_gstin', 'ambiguous_gstin', 'refused', 'unreadable', 'failed')),
  CONSTRAINT gstr2b_bulk_drop_files_period_is_mmyyyy
    CHECK (period IS NULL OR period ~ '^(0[1-9]|1[0-2])[0-9]{4}$'),
  CONSTRAINT gstr2b_bulk_drop_files_problems_is_a_list
    CHECK (jsonb_typeof(problems) = 'array'),
  -- Only a reconciled file has counts; a file that was not reconciled says why.
  CONSTRAINT gstr2b_bulk_drop_files_a_result_says_what_it_is
    CHECK ((status = 'reconciled' AND summary IS NOT NULL)
        OR (status <> 'reconciled' AND summary IS NULL AND reason IS NOT NULL AND btrim(reason) <> ''))
);

COMMENT ON TABLE public.gstr2b_bulk_drop_files IS
  'POST-A-057, migration 715. What a bulk GSTR-2B drop did to each file the server answered, as the answer carried it, so the drop can be '
  'read back after the screen is closed. client_id is NULL for a file routed to no client. Written by the API only.';

CREATE INDEX IF NOT EXISTS idx_gstr2b_bulk_drop_files_drop
  ON public.gstr2b_bulk_drop_files (drop_id, seq);
CREATE INDEX IF NOT EXISTS idx_gstr2b_bulk_drop_files_client
  ON public.gstr2b_bulk_drop_files (client_id) WHERE client_id IS NOT NULL;

ALTER TABLE public.gstr2b_bulk_drops ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.gstr2b_bulk_drop_files ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "gstr2b_bulk_drops_firm_isolation" ON public.gstr2b_bulk_drops;
CREATE POLICY "gstr2b_bulk_drops_firm_isolation" ON public.gstr2b_bulk_drops
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "gstr2b_bulk_drop_files_firm_isolation" ON public.gstr2b_bulk_drop_files;
CREATE POLICY "gstr2b_bulk_drop_files_firm_isolation" ON public.gstr2b_bulk_drop_files
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "gstr2b_bulk_drop_files_assignment_scope" ON public.gstr2b_bulk_drop_files;
CREATE POLICY "gstr2b_bulk_drop_files_assignment_scope" ON public.gstr2b_bulk_drop_files
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "gstr2b_bulk_drop_files_internal_partner_only" ON public.gstr2b_bulk_drop_files;
CREATE POLICY "gstr2b_bulk_drop_files_internal_partner_only" ON public.gstr2b_bulk_drop_files
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.gstr2b_bulk_drops FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.gstr2b_bulk_drop_files FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr2b_bulk_drops TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr2b_bulk_drop_files TO service_role;

DO $$
BEGIN
    PERFORM public.guard_member_firm('public.gstr2b_bulk_drops');
    PERFORM public.guard_client_firm('public.gstr2b_bulk_drop_files');
END $$;

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['public.gstr2b_bulk_drops', 'public.gstr2b_bulk_drop_files'] LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
                IF has_table_privilege(r, t, verb) THEN
                    RAISE EXCEPTION 'migration 715: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
        END LOOP;
        IF NOT has_table_privilege('service_role', t, 'INSERT') THEN
            RAISE EXCEPTION 'migration 715: the API (service_role) cannot write %', t;
        END IF;
    END LOOP;
END $$;

COMMIT;
