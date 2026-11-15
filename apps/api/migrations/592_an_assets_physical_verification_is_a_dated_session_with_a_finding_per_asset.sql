-- Migration 592: an asset's physical verification is a dated session with a finding per asset (ledger POST-A-112, its second half).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═════════════════════════════════════════════════════════════════
-- A CA auditing a client's books asks whether the fixed assets were physically verified, when, by whom, and what was found against the
-- register. The product held the register and (since 591) where each asset is and who keeps it, and nothing of the count itself: the
-- working paper was a spreadsheet kept outside it.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `fixed_asset_verifications`: one row per count of one client's assets: the day it was counted, who counted (as the client names
--    them), a note, and whether it is open or closed (and when and by whom it was closed). A client has at most one open count.
--  * `fixed_asset_verification_findings`: one row per asset per count: found, found elsewhere (with the place it was seen), not found,
--    or damaged; with the place and keeper the register held on the day counted, a note and who recorded it.
--  * Both tables are read by the members assigned to the client and written by the API only, the shape of 590 and 591: row security on
--    with the firm isolation, the assignment scope and the internal practice's Partner-only rule; every privilege revoked from PUBLIC,
--    anon and the signed-in role, READ given back to the signed-in role, writes the API's privileged client's; the two firm checks of
--    565 and 566 installed.
--  * `record_fixed_asset_finding(...)`: the one way a finding is written. It holds the count (FOR SHARE, so a close waits for it), refuses
--    a count that is not this client's or is closed, an asset that is not this client's, is deleted, or was not held on the day counted
--    (bought after it, or disposed of on or before it), a finding that is not one of the four, a "found elsewhere" with no place, and
--    text over its length; reads the place and keeper the register held ON THE DAY COUNTED (the "before" of the first movement dated
--    after it, 591, or the asset's own where it has not moved since, so a movement recorded after the count does not rewrite what the
--    paper says the register held); and stores the finding, replacing the asset's earlier finding in the same count.
--  * `close_fixed_asset_verification(...)`: closes a count (FOR UPDATE), and refuses while any asset held on the day counted has no
--    finding, naming how many. A closed count is the working paper and nothing changes it: a finding on it is refused, and it is never
--    reopened. A finding moves nothing: an asset found elsewhere is moved in the register by a movement (591), which the person records.
--  * Both functions are SECURITY INVOKER and only the service role may execute them; the API asks who is calling before it calls.
-- Nothing else changes and no row is written.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

CREATE TABLE IF NOT EXISTS public.fixed_asset_verifications (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id    UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  verified_on  DATE        NOT NULL,
  counted_by   TEXT        NOT NULL,
  note         TEXT,
  status       TEXT        NOT NULL DEFAULT 'open',
  closed_at    TIMESTAMPTZ,
  closed_by    UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_by   UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fixed_asset_verifications_status CHECK (status IN ('open', 'closed')),
  CONSTRAINT fixed_asset_verifications_closed_has_its_time CHECK ((status = 'closed') = (closed_at IS NOT NULL)),
  CONSTRAINT fixed_asset_verifications_lines
    CHECK (char_length(counted_by) BETWEEN 1 AND 200 AND char_length(coalesce(note, '')) <= 500)
);

COMMENT ON TABLE public.fixed_asset_verifications IS
  'POST-A-112, migration 592. One physical count of one client''s fixed assets: the day, who counted, open or closed. A client has at '
  'most one open count; a closed count is the working paper and is never reopened. Written by the API only.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_fixed_asset_verifications_one_open
  ON public.fixed_asset_verifications (client_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_fixed_asset_verifications_client
  ON public.fixed_asset_verifications (firm_id, client_id, verified_on DESC);

CREATE TABLE IF NOT EXISTS public.fixed_asset_verification_findings (
  id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id           UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  verification_id     UUID        NOT NULL REFERENCES public.fixed_asset_verifications(id) ON DELETE CASCADE,
  asset_id            UUID        NOT NULL REFERENCES public.fixed_assets(id) ON DELETE CASCADE,
  finding             TEXT        NOT NULL,
  found_in             TEXT,
  register_location   TEXT,
  register_custodian  TEXT,
  note                TEXT,
  recorded_by         UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fixed_asset_verification_findings_one_per_asset UNIQUE (verification_id, asset_id),
  CONSTRAINT fixed_asset_verification_findings_finding
    CHECK (finding IN ('found', 'found_elsewhere', 'not_found', 'damaged')),
  CONSTRAINT fixed_asset_verification_findings_elsewhere_says_where
    CHECK (finding <> 'found_elsewhere' OR found_in IS NOT NULL),
  CONSTRAINT fixed_asset_verification_findings_lines
    CHECK (char_length(coalesce(found_in, '')) <= 200 AND char_length(coalesce(note, '')) <= 500)
);

COMMENT ON TABLE public.fixed_asset_verification_findings IS
  'POST-A-112, migration 592. What a physical count found of one asset, beside what the register said when it was recorded. Written '
  'only by record_fixed_asset_finding, never on a closed count. A finding moves nothing in the register.';

CREATE INDEX IF NOT EXISTS idx_fixed_asset_verification_findings_asset
  ON public.fixed_asset_verification_findings (asset_id);
CREATE INDEX IF NOT EXISTS idx_fixed_asset_verification_findings_client
  ON public.fixed_asset_verification_findings (firm_id, client_id);

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['fixed_asset_verifications', 'fixed_asset_verification_findings'] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_isolation', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
                       'USING (firm_id = (SELECT public.get_my_firm_id())) '
                       'WITH CHECK (firm_id = (SELECT public.get_my_firm_id()))', t || '_firm_isolation', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_assignment_scope', t);
        EXECUTE format('CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
                       'USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false)) '
                       'WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))',
                       t || '_assignment_scope', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_internal_partner_only', t);
        EXECUTE format('CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
                       'USING ((SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text) '
                       'WITH CHECK ((SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)',
                       t || '_internal_partner_only', t);

        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC, anon, authenticated', t);
        EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', t);

        PERFORM public.guard_client_firm('public.' || t);
        PERFORM public.guard_member_firm('public.' || t);
    END LOOP;
END $$;

-- Whether an asset was held on a day: bought on or before it, and not disposed of on or before it. One place says it, for both
-- functions; the API's mock-mode twin is `domain/fixed_assets/verification.held_on`, pinned to this by the real-database test.
CREATE OR REPLACE FUNCTION public.fixed_asset_held_on(p_asset public.fixed_assets, p_day date)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
    SELECT p_asset.deleted_at IS NULL
       AND (p_asset.purchase_date IS NULL OR p_asset.purchase_date <= p_day)
       AND NOT (coalesce(p_asset.is_disposed, false) AND (p_asset.disposal_date IS NULL OR p_asset.disposal_date <= p_day));
$$;

COMMENT ON FUNCTION public.fixed_asset_held_on(public.fixed_assets, date) IS
  'POST-A-112, migration 592. Whether an asset was held on a day (bought on or before it, not deleted, not disposed of on or before '
  'it): the assets a physical count on that day must account for.';

CREATE OR REPLACE FUNCTION public.record_fixed_asset_finding(
    p_firm_id          uuid,
    p_client_id        uuid,
    p_verification_id  uuid,
    p_asset_id         uuid,
    p_finding          text,
    p_found_in          text,
    p_note             text,
    p_recorded_by      uuid
) RETURNS public.fixed_asset_verification_findings
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    -- Text is tidied as 591 tidies a place: every run of ASCII white space is one space and the ends are trimmed; a blank is none.
    v_count    public.fixed_asset_verifications;
    v_asset    public.fixed_assets;
    v_row      public.fixed_asset_verification_findings;
    v_found_in  text := NULLIF(btrim(regexp_replace(coalesce(p_found_in, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    v_note     text := NULLIF(regexp_replace(coalesce(p_note, ''), '^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$', '', 'g'), '');
    v_reg_location   text;
    v_reg_custodian  text;
BEGIN
    SELECT * INTO v_count FROM public.fixed_asset_verifications
     WHERE id = p_verification_id AND firm_id = p_firm_id AND client_id = p_client_id
       FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Verification not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_count.status <> 'open' THEN
        RAISE EXCEPTION 'This verification was closed on %, so its findings are the working paper and cannot change.',
            to_char((v_count.closed_at AT TIME ZONE 'Asia/Kolkata')::date, 'DD Mon YYYY') USING ERRCODE = '55000';
    END IF;
    SELECT * INTO v_asset FROM public.fixed_assets
     WHERE id = p_asset_id AND firm_id = p_firm_id AND client_id = p_client_id AND deleted_at IS NULL;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Asset not found' USING ERRCODE = 'P0002';
    END IF;
    IF NOT public.fixed_asset_held_on(v_asset, v_count.verified_on) THEN
        RAISE EXCEPTION 'This asset was not held on %, the day counted (it was bought after it or disposed of by then), so the count '
            'has nothing to find of it.', to_char(v_count.verified_on, 'DD Mon YYYY') USING ERRCODE = '23514';
    END IF;
    IF p_finding IS NULL OR p_finding NOT IN ('found', 'found_elsewhere', 'not_found', 'damaged') THEN
        RAISE EXCEPTION 'Finding: one of found, found elsewhere, not found or damaged.' USING ERRCODE = '23514';
    END IF;
    IF p_finding = 'found_elsewhere' AND v_found_in IS NULL THEN
        RAISE EXCEPTION 'Found in: say where the asset was found, since it was not where the register has it.' USING ERRCODE = '23514';
    END IF;
    IF char_length(coalesce(v_found_in, '')) > 200 THEN
        RAISE EXCEPTION 'A place is at most 200 characters.' USING ERRCODE = '23514';
    END IF;
    IF char_length(coalesce(v_note, '')) > 500 THEN
        RAISE EXCEPTION 'A note is at most 500 characters.' USING ERRCODE = '23514';
    END IF;

    -- The place and keeper the register held on the day counted. Movements are recorded in the order of their dates (591), so the first
    -- one dated after the day carries, as its "before", what the register held from the day until it moved; with none, the asset has
    -- not moved since the day and its own place is the one. Never the place as it is when the finding happens to be written.
    SELECT m.from_location, m.from_custodian INTO v_reg_location, v_reg_custodian
      FROM public.fixed_asset_movements m
     WHERE m.asset_id = p_asset_id AND m.firm_id = p_firm_id AND m.client_id = p_client_id AND m.moved_on > v_count.verified_on
     ORDER BY m.moved_on, m.created_at, m.id
     LIMIT 1;
    IF NOT FOUND THEN
        v_reg_location := v_asset.location;
        v_reg_custodian := v_asset.custodian;
    END IF;

    INSERT INTO public.fixed_asset_verification_findings (firm_id, client_id, verification_id, asset_id, finding, found_in,
                                                          register_location, register_custodian, note, recorded_by)
    VALUES (p_firm_id, p_client_id, p_verification_id, p_asset_id, p_finding,
            CASE WHEN p_finding = 'found_elsewhere' THEN v_found_in END,
            NULLIF(btrim(regexp_replace(coalesce(v_reg_location, ''), '[ \t\n\r\f\v]+', ' ', 'g')), ''),
            NULLIF(btrim(regexp_replace(coalesce(v_reg_custodian, ''), '[ \t\n\r\f\v]+', ' ', 'g')), ''),
            v_note, p_recorded_by)
    ON CONFLICT (verification_id, asset_id) DO UPDATE
       SET finding = EXCLUDED.finding, found_in = EXCLUDED.found_in, register_location = EXCLUDED.register_location,
           register_custodian = EXCLUDED.register_custodian, note = EXCLUDED.note, recorded_by = EXCLUDED.recorded_by,
           recorded_at = now()
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

COMMENT ON FUNCTION public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid) IS
  'POST-A-112, migration 592. Records (or replaces) what an open count found of one asset held on the day counted, beside the '
  'register''s place and keeper. The API''s privileged client calls it after asking who is calling; no signed-in session may.';

CREATE OR REPLACE FUNCTION public.close_fixed_asset_verification(
    p_firm_id          uuid,
    p_client_id        uuid,
    p_verification_id  uuid,
    p_closed_by        uuid
) RETURNS public.fixed_asset_verifications
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_count    public.fixed_asset_verifications;
    v_missing  integer;
BEGIN
    SELECT * INTO v_count FROM public.fixed_asset_verifications
     WHERE id = p_verification_id AND firm_id = p_firm_id AND client_id = p_client_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Verification not found' USING ERRCODE = 'P0002';
    END IF;
    IF v_count.status <> 'open' THEN
        RAISE EXCEPTION 'This verification was closed on % and stays closed.',
            to_char((v_count.closed_at AT TIME ZONE 'Asia/Kolkata')::date, 'DD Mon YYYY') USING ERRCODE = '55000';
    END IF;
    SELECT count(*) INTO v_missing
      FROM public.fixed_assets a
     WHERE a.firm_id = p_firm_id AND a.client_id = p_client_id
       AND public.fixed_asset_held_on(a, v_count.verified_on)
       AND NOT EXISTS (SELECT 1 FROM public.fixed_asset_verification_findings f
                        WHERE f.verification_id = p_verification_id AND f.asset_id = a.id);
    IF v_missing > 0 THEN
        RAISE EXCEPTION '% % held on % % no finding yet. Record what the count found of each before closing it.',
            v_missing, CASE WHEN v_missing = 1 THEN 'asset' ELSE 'assets' END, to_char(v_count.verified_on, 'DD Mon YYYY'),
            CASE WHEN v_missing = 1 THEN 'has' ELSE 'have' END USING ERRCODE = '23514';
    END IF;
    UPDATE public.fixed_asset_verifications SET status = 'closed', closed_at = now(), closed_by = p_closed_by
     WHERE id = p_verification_id
    RETURNING * INTO v_count;
    RETURN v_count;
END;
$$;

COMMENT ON FUNCTION public.close_fixed_asset_verification(uuid, uuid, uuid, uuid) IS
  'POST-A-112, migration 592. Closes a count once every asset held on the day counted has a finding; a closed count never reopens. '
  'The API''s privileged client calls it after asking who is calling; no signed-in session may.';

REVOKE ALL ON FUNCTION public.fixed_asset_held_on(public.fixed_assets, date) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.close_fixed_asset_verification(uuid, uuid, uuid, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.fixed_asset_held_on(public.fixed_assets, date) TO service_role;
GRANT EXECUTE ON FUNCTION public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.close_fixed_asset_verification(uuid, uuid, uuid, uuid) TO service_role;

DO $$
DECLARE
    r text;
    t text;
    verb text;
    fn text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH t IN ARRAY ARRAY['public.fixed_asset_verifications', 'public.fixed_asset_verification_findings'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
                IF has_table_privilege(r, t, verb) THEN
                    RAISE EXCEPTION 'migration 592: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, t, 'INSERT') OR has_any_column_privilege(r, t, 'UPDATE') THEN
                RAISE EXCEPTION 'migration 592: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        FOREACH fn IN ARRAY ARRAY['public.fixed_asset_held_on(public.fixed_assets, date)',
                                  'public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid)',
                                  'public.close_fixed_asset_verification(uuid, uuid, uuid, uuid)'] LOOP
            IF has_function_privilege(r, fn, 'EXECUTE') THEN
                RAISE EXCEPTION 'migration 592: % may execute %', r, fn;
            END IF;
        END LOOP;
    END LOOP;
    IF has_table_privilege('anon', 'public.fixed_asset_verifications', 'SELECT')
       OR has_table_privilege('anon', 'public.fixed_asset_verification_findings', 'SELECT') THEN
        RAISE EXCEPTION 'migration 592: anon reads a verification table';
    END IF;
    IF NOT has_function_privilege('service_role', 'public.record_fixed_asset_finding(uuid, uuid, uuid, uuid, text, text, text, uuid)', 'EXECUTE')
       OR NOT has_function_privilege('service_role', 'public.close_fixed_asset_verification(uuid, uuid, uuid, uuid)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 592: the API (service_role) cannot record a finding or close a count';
    END IF;
END $$;

COMMIT;
