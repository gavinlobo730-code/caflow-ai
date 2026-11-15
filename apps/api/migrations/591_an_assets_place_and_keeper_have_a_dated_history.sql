-- Migration 591: an asset's place and keeper have a dated history (ledger POST-A-112, its first half).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═════════════════════════════════════════════════════════════════
-- `fixed_assets.location` is one free-text field. Moving a machine from the factory to the warehouse overwrote it, so where an asset was
-- in March, and who held the laptop before the employee who left, was nowhere; and nothing recorded who an asset is in the keeping of at
-- all. A CA verifying the register for an audit asks exactly those two things.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `fixed_assets.custodian`: who the asset is in the keeping of now (a person or a department, as the client names it), nullable.
--  * `fixed_asset_movements`: one row per movement of one asset, dated, with where it was and who held it before, and where it is and
--    who holds it after. Read by the members assigned to the client and written by the API only, the shape of migration 590: row
--    security on with the firm isolation, the assignment scope and the internal practice's Partner-only rule; every privilege revoked
--    from PUBLIC, anon and the signed-in role, READ given back to the signed-in role, writes the API's privileged client's; the two firm
--    checks of 565 and 566 installed.
--  * `record_fixed_asset_movement(...)`: the one way a movement is written. In ONE transaction it locks the asset, refuses what cannot be
--    a movement (an asset that is not this client's or is deleted, a disposed one, a date before the asset was bought, after India's
--    today or before the asset's latest movement, a movement that changes neither the place nor the keeper, and one sent from a form
--    opened before the asset last moved), stores the row with the asset's own place and keeper as "before", and moves the asset: a
--    movement and the register's place and keeper are written together. SECURITY INVOKER, and only the service role may execute it: a
--    signed-in session cannot write the table, so it cannot call this either, and the API asks who is calling before it does.
--  * Correcting a mistyped location or keeper stays an edit of the asset (the register's correction, which records no movement):
--    a typo is not a movement, so a correction changes the register alone and the latest movement keeps what was recorded then.
-- Nothing else changes and no row is written.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

ALTER TABLE public.fixed_assets ADD COLUMN IF NOT EXISTS custodian TEXT;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fixed_assets_custodian_is_a_line') THEN
        ALTER TABLE public.fixed_assets ADD CONSTRAINT fixed_assets_custodian_is_a_line
            CHECK (custodian IS NULL OR char_length(custodian) BETWEEN 1 AND 200) NOT VALID;
        ALTER TABLE public.fixed_assets VALIDATE CONSTRAINT fixed_assets_custodian_is_a_line;
    END IF;
END $$;

COMMENT ON COLUMN public.fixed_assets.custodian IS
  'POST-A-112, migration 591. Who the asset is in the keeping of now, as the client names them. Moved by record_fixed_asset_movement, '
  'which keeps the history in fixed_asset_movements; an edit of the asset corrects a typo and records no movement.';

CREATE TABLE IF NOT EXISTS public.fixed_asset_movements (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id)        ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id)      ON DELETE CASCADE,
  asset_id        UUID        NOT NULL REFERENCES public.fixed_assets(id) ON DELETE CASCADE,
  moved_on        DATE        NOT NULL,
  from_location   TEXT,
  to_location     TEXT,
  from_custodian  TEXT,
  to_custodian    TEXT,
  note            TEXT,
  created_by      UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT fixed_asset_movements_something_moved
    CHECK (to_location IS DISTINCT FROM from_location OR to_custodian IS DISTINCT FROM from_custodian),
  CONSTRAINT fixed_asset_movements_lines
    CHECK (char_length(coalesce(to_location, '')) <= 200 AND char_length(coalesce(to_custodian, '')) <= 200
           AND char_length(coalesce(note, '')) <= 500)
);

COMMENT ON TABLE public.fixed_asset_movements IS
  'POST-A-112, migration 591. One row per movement of an asset: dated, with its place and keeper before and after. Written only by '
  'record_fixed_asset_movement, which moves the asset in the same transaction. Read by the members assigned to the client.';

CREATE INDEX IF NOT EXISTS idx_fixed_asset_movements_asset
  ON public.fixed_asset_movements (asset_id, moved_on DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fixed_asset_movements_client
  ON public.fixed_asset_movements (firm_id, client_id);

ALTER TABLE public.fixed_asset_movements ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "fixed_asset_movements_firm_isolation" ON public.fixed_asset_movements;
CREATE POLICY "fixed_asset_movements_firm_isolation" ON public.fixed_asset_movements
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

DROP POLICY IF EXISTS "fixed_asset_movements_assignment_scope" ON public.fixed_asset_movements;
CREATE POLICY "fixed_asset_movements_assignment_scope" ON public.fixed_asset_movements
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "fixed_asset_movements_internal_partner_only" ON public.fixed_asset_movements;
CREATE POLICY "fixed_asset_movements_internal_partner_only" ON public.fixed_asset_movements
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

REVOKE ALL ON public.fixed_asset_movements FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.fixed_asset_movements TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fixed_asset_movements TO service_role;

DO $$
BEGIN
    PERFORM public.guard_client_firm('public.fixed_asset_movements');
    PERFORM public.guard_member_firm('public.fixed_asset_movements');
END $$;

CREATE OR REPLACE FUNCTION public.record_fixed_asset_movement(
    p_firm_id         uuid,
    p_client_id       uuid,
    p_asset_id        uuid,
    p_moved_on        date,
    p_seen_location   text,
    p_seen_custodian  text,
    p_to_location     text,
    p_to_custodian    text,
    p_note            text,
    p_created_by      uuid
) RETURNS public.fixed_asset_movements
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
DECLARE
    -- A place, a keeper or a note is tidied the one way the API's models tidy it: runs of ASCII white space are one space, and the
    -- ends are trimmed (an explicit class, never \s, whose reach over a non-breaking space differs from Python's). A blank is none.
    v_asset           public.fixed_assets;
    v_latest          date;
    v_row             public.fixed_asset_movements;
    v_today           date := (now() AT TIME ZONE 'Asia/Kolkata')::date;
    v_location        text := NULLIF(btrim(regexp_replace(coalesce(p_to_location, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    v_custodian       text := NULLIF(btrim(regexp_replace(coalesce(p_to_custodian, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    v_seen_location   text := NULLIF(btrim(regexp_replace(coalesce(p_seen_location, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    v_seen_custodian  text := NULLIF(btrim(regexp_replace(coalesce(p_seen_custodian, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    v_note            text := NULLIF(regexp_replace(coalesce(p_note, ''), '^[ \t\n\r\f\v]+|[ \t\n\r\f\v]+$', '', 'g'), '');
    v_was_location    text;
    v_was_custodian   text;
BEGIN
    SELECT * INTO v_asset FROM public.fixed_assets
     WHERE id = p_asset_id AND firm_id = p_firm_id AND client_id = p_client_id AND deleted_at IS NULL
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Asset not found' USING ERRCODE = 'P0002';
    END IF;
    IF coalesce(v_asset.is_disposed, false) THEN
        RAISE EXCEPTION 'This asset has been disposed of, so it is no longer held and cannot be moved.' USING ERRCODE = '23514';
    END IF;
    -- Where the register has the asset and who it says keeps it, tidied as the new ones are: a place written with a stray space
    -- before 591 (or by a door that does not tidy) is the same place, so it neither makes a movement out of nothing nor hides one.
    v_was_location  := NULLIF(btrim(regexp_replace(coalesce(v_asset.location, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    v_was_custodian := NULLIF(btrim(regexp_replace(coalesce(v_asset.custodian, ''), '[ \t\n\r\f\v]+', ' ', 'g')), '');
    -- The place and keeper the person's form opened on must still be the register's, or a form opened before somebody else recorded a
    -- movement would put the asset back where it was, silently. 55000, as an issue of an invoice that is no longer a draft (577).
    IF v_seen_location IS DISTINCT FROM v_was_location OR v_seen_custodian IS DISTINCT FROM v_was_custodian THEN
        RAISE EXCEPTION 'The asset has moved since this was opened: the register now has it at %, kept by %. Nothing was recorded. '
            'Open the movement again, which starts from where the asset is now.',
            coalesce(v_was_location, 'no place recorded'), coalesce(v_was_custodian, 'nobody named') USING ERRCODE = '55000';
    END IF;
    IF p_moved_on IS NULL THEN
        RAISE EXCEPTION 'Moved on: enter the date the asset moved.' USING ERRCODE = '23514';
    END IF;
    IF p_moved_on > v_today THEN
        RAISE EXCEPTION 'Moved on: % has not come yet. A movement is recorded once it has happened.', to_char(p_moved_on, 'DD Mon YYYY')
            USING ERRCODE = '23514';
    END IF;
    IF v_asset.purchase_date IS NOT NULL AND p_moved_on < v_asset.purchase_date THEN
        RAISE EXCEPTION 'Moved on: % is before the asset was bought on %.', to_char(p_moved_on, 'DD Mon YYYY'),
            to_char(v_asset.purchase_date, 'DD Mon YYYY') USING ERRCODE = '23514';
    END IF;
    SELECT max(moved_on) INTO v_latest FROM public.fixed_asset_movements WHERE asset_id = p_asset_id;
    IF v_latest IS NOT NULL AND p_moved_on < v_latest THEN
        RAISE EXCEPTION 'Moved on: the asset''s latest movement is dated %, and one recorded before it would leave the register showing '
            'the wrong place. Record movements in the order they happened.', to_char(v_latest, 'DD Mon YYYY') USING ERRCODE = '23514';
    END IF;
    IF v_location IS NOT DISTINCT FROM v_was_location AND v_custodian IS NOT DISTINCT FROM v_was_custodian THEN
        RAISE EXCEPTION 'Nothing moved: the place and the keeper are the ones the register already holds.' USING ERRCODE = '23514';
    END IF;
    IF char_length(coalesce(v_location, '')) > 200 OR char_length(coalesce(v_custodian, '')) > 200 THEN
        RAISE EXCEPTION 'A place or a keeper is at most 200 characters.' USING ERRCODE = '23514';
    END IF;
    IF char_length(coalesce(v_note, '')) > 500 THEN
        RAISE EXCEPTION 'A note is at most 500 characters.' USING ERRCODE = '23514';
    END IF;

    INSERT INTO public.fixed_asset_movements (firm_id, client_id, asset_id, moved_on, from_location, to_location,
                                              from_custodian, to_custodian, note, created_by)
    VALUES (p_firm_id, p_client_id, p_asset_id, p_moved_on, v_was_location, v_location,
            v_was_custodian, v_custodian, v_note, p_created_by)
    RETURNING * INTO v_row;

    UPDATE public.fixed_assets SET location = v_location, custodian = v_custodian, updated_at = now() WHERE id = p_asset_id;
    RETURN v_row;
END;
$$;

COMMENT ON FUNCTION public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid) IS
  'POST-A-112, migration 591. Records one movement of an asset and moves the asset, in one transaction. The API''s privileged client '
  'calls it after asking who is calling; no signed-in session may execute it.';

REVOKE ALL ON FUNCTION public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid) TO service_role;

DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.fixed_asset_movements', verb) THEN
                RAISE EXCEPTION 'migration 591: % still holds % on fixed_asset_movements', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.fixed_asset_movements', 'INSERT')
           OR has_any_column_privilege(r, 'public.fixed_asset_movements', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 591: % still holds a column-level write privilege on fixed_asset_movements', r;
        END IF;
        IF has_function_privilege(r, 'public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid)', 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 591: % may execute record_fixed_asset_movement', r;
        END IF;
    END LOOP;
    IF has_table_privilege('anon', 'public.fixed_asset_movements', 'SELECT') THEN
        RAISE EXCEPTION 'migration 591: anon reads fixed_asset_movements';
    END IF;
    IF NOT has_function_privilege('service_role', 'public.record_fixed_asset_movement(uuid, uuid, uuid, date, text, text, text, text, text, uuid)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 591: the API (service_role) cannot record a movement';
    END IF;
END $$;

COMMIT;
