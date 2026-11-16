-- Migration 617: a GSTR-8 amendment (Table 4 and Table 4.1) is recorded against the earlier month it amends (POST-A-056).
--
-- ====================================================================================================================================
-- WHAT WAS MISSING
-- ====================================================================================================================================
-- Migration 421 recorded what an e-commerce operator's sellers supplied through it for ONE month (GSTR-8 Table 3 for a registered seller,
-- Table 3.1 for an Enrolment-ID seller) and named the other two tables of the return as "not built yet": Table 4 and Table 4.1, which
-- amend a row an EARLIER month's statement declared. A correction therefore had nowhere to go but a fresh row in the current month,
-- which declares a second supply instead of correcting the first.
--
-- ====================================================================================================================================
-- WHAT THIS DOES
-- ====================================================================================================================================
-- Two tables, one per amendment table, shaped from the GSTN offline utility's own export (docs/compliance/sources/gst-offline-utilities/
-- gstr8/ExportMod.bas.txt: `tcsa` and `urda`) and its validation (ValidateMod.bas.txt: validateAmend and validateUNRDA):
--
--   public.ecommerce_operator_supply_amendments               Table 4  (`tcsa`): `ofp` original month, `ostin` original supplier, `opos` original
--                                                              place of supply (only from FY 2025-26), then the REVISED `stin`, `pos`, `supR`,
--                                                              `retsupR`, `supU`, `retsupU`, `iamt`, `camt`, `samt`, and the filer's `flag`.
--   public.ecommerce_operator_unregistered_supply_amendments  Table 4.1 (`urda`): `ofp`, `oeid` original Enrolment ID, the revised `eid`,
--                                                              `grsval`, `supret`, and `flag`.
--
-- `period` is the statement's month (the month the amendment is DECLARED in) and `original_period` the month whose row it amends, both
-- MMYYYY as everywhere else in this schema. The utility refuses an amendment whose original month is not earlier than the statement's
-- ("Month and Year in Amend Sheet should be lesser than in Home Sheet"), so a table CHECK says so: the API refuses it first, in words, and
-- this is the second lock. `action` is the utility's own two answers ("Add" -> `A`, "Delete" -> `D`), kept as the filer chose; nothing here
-- says what the portal does with each. Amounts are non-negative (the utility's "Invalid Amount").
--
-- ONE ROW PER AMENDED ROW PER STATEMENT: the unique index is the utility's own duplicate key ("Duplicate Combination of month, year and
-- GSTIN found"; from FY 2025-26 the original place of supply is part of it). `COALESCE(original_place_of_supply, '')` makes the NULL a
-- value, which is what the utility's key does before FY 2025-26 (the field does not exist there).
--
-- WHAT IS NOT DECIDED HERE, and is said beside the rows in the statement: the change an amendment makes to the tax payable (the figures the
-- original month filed live on the portal, not in this schema); how far back an amendment may go (the utility restricts the original year to
-- a list read from a worksheet range its VBA text does not carry, so no limit is asserted); and what "Add" and "Delete" do at the portal.
-- Nothing is transmitted to any portal and nothing posts to the ledger: like Table 3, this is a fact the operator's own records give and the
-- books do not hold.
--
-- ACCESS: written and read by the API's privileged client alone. No signed-in role holds any privilege on either table (the panel reads and
-- writes through the API, the browser never touches them), so neither joins the list of tables a signed-in session reaches outside the
-- role-by-table matrix. The row policies of the newest client tables (migration 592) are still declared, as the second lock, and each
-- table carries the two row guards every new client table carries (`guard_client_firm`, `guard_member_firm`).
--
-- Rollback: 617_..._rollback.sql drops both tables (and the amendments recorded in them).

BEGIN;

-- ── Table 4 — an amendment of a REGISTERED seller's row ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ecommerce_operator_supply_amendments (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                     UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id                   UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The OPERATOR's own registration, and the statement's month (MMYYYY): the month this amendment is declared in.
  gstin                       TEXT NOT NULL
                              CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  period                      TEXT NOT NULL
                              CHECK (period ~ '^(0[1-9]|1[0-2])[0-9]{4}$'),

  -- The row being amended: `ofp`, `ostin`, `opos`. `opos` exists in the utility's schema only from FY 2025-26, so NULL is the schema's
  -- own answer for an earlier month; a missing one for a later month is named by domain/gst/gstr8.py, not refused here.
  original_period             TEXT NOT NULL
                              CHECK (original_period ~ '^(0[1-9]|1[0-2])[0-9]{4}$'),
  original_supplier_gstin     TEXT NOT NULL
                              CHECK (original_supplier_gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  original_place_of_supply    TEXT
                              CHECK (original_place_of_supply IS NULL OR original_place_of_supply ~ '^[0-9]{2}$'),

  -- What the row is revised to, in Table 3's own shape: `stin`, `pos`, `supR`, `retsupR`, `supU`, `retsupU`, `iamt`, `camt`, `samt`.
  supplier_gstin              TEXT NOT NULL
                              CHECK (supplier_gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  place_of_supply             TEXT
                              CHECK (place_of_supply IS NULL OR place_of_supply ~ '^[0-9]{2}$'),
  gross_registered_paise      BIGINT NOT NULL DEFAULT 0 CHECK (gross_registered_paise    >= 0),   -- "supR"
  returns_registered_paise    BIGINT NOT NULL DEFAULT 0 CHECK (returns_registered_paise  >= 0),   -- "retsupR"
  gross_unregistered_paise    BIGINT NOT NULL DEFAULT 0 CHECK (gross_unregistered_paise  >= 0),   -- "supU"
  returns_unregistered_paise  BIGINT NOT NULL DEFAULT 0 CHECK (returns_unregistered_paise >= 0),  -- "retsupU"
  igst_paise                  BIGINT NOT NULL DEFAULT 0 CHECK (igst_paise >= 0),                   -- "iamt"
  cgst_paise                  BIGINT NOT NULL DEFAULT 0 CHECK (cgst_paise >= 0),                   -- "camt"
  sgst_paise                  BIGINT NOT NULL DEFAULT 0 CHECK (sgst_paise >= 0),                   -- "samt"

  -- The utility's "Add" / "Delete" dropdown, `flag` A / D in the file.
  action                      TEXT NOT NULL CHECK (action IN ('add', 'delete')),

  notes                       TEXT,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by                  UUID REFERENCES public.users(id),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at                  TIMESTAMPTZ,

  CONSTRAINT eo_amend_original_is_earlier CHECK (
    (substr(original_period, 3, 4) || substr(original_period, 1, 2)) < (substr(period, 3, 4) || substr(period, 1, 2)))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ecommerce_operator_supply_amendment
  ON public.ecommerce_operator_supply_amendments
     (client_id, gstin, period, original_period, original_supplier_gstin, COALESCE(original_place_of_supply, ''))
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_ecommerce_operator_supply_amendments_period
  ON public.ecommerce_operator_supply_amendments (client_id, gstin, period)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.ecommerce_operator_supply_amendments IS
  'GSTR-8 Table 4 (CGST Act s.52) — a revision of a REGISTERED seller''s row an EARLIER month''s statement declared, as the GSTN offline '
  'utility''s `tcsa` array lays it out. `period` is the statement the amendment is declared in, `original_period` the month it amends. '
  'Recorded and checked, never netted against the row it amends: that row''s filed figures are on the portal. POST-A-056, migration 617.';
COMMENT ON COLUMN public.ecommerce_operator_supply_amendments.action IS
  'The utility''s Add / Delete dropdown (`flag` A / D). Kept as the filer chose; what the portal does with each is not recorded here.';

-- ── Table 4.1 — an amendment of an ENROLMENT-ID seller's row ────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.ecommerce_operator_unregistered_supply_amendments (
  id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                     UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id                   UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin                       TEXT NOT NULL
                              CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  period                      TEXT NOT NULL
                              CHECK (period ~ '^(0[1-9]|1[0-2])[0-9]{4}$'),

  -- The row being amended (`ofp`, `oeid`) and what it is revised to (`eid`, `grsval`, `supret`). An Enrolment ID is kept as typed, as in
  -- Table 3.1: this schema holds no confirmed shape for one.
  original_period             TEXT NOT NULL
                              CHECK (original_period ~ '^(0[1-9]|1[0-2])[0-9]{4}$'),
  original_enrolment_id       TEXT NOT NULL,
  enrolment_id                TEXT NOT NULL,
  gross_value_paise           BIGINT NOT NULL DEFAULT 0 CHECK (gross_value_paise >= 0),   -- "grsval"
  returns_paise               BIGINT NOT NULL DEFAULT 0 CHECK (returns_paise     >= 0),   -- "supret"

  action                      TEXT NOT NULL CHECK (action IN ('add', 'delete')),

  notes                       TEXT,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by                  UUID REFERENCES public.users(id),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at                  TIMESTAMPTZ,

  CONSTRAINT eo_unreg_amend_original_is_earlier CHECK (
    (substr(original_period, 3, 4) || substr(original_period, 1, 2)) < (substr(period, 3, 4) || substr(period, 1, 2)))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ecommerce_operator_unregistered_supply_amendment
  ON public.ecommerce_operator_unregistered_supply_amendments
     (client_id, gstin, period, original_period, original_enrolment_id)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_ecommerce_operator_unreg_supply_amendments_period
  ON public.ecommerce_operator_unregistered_supply_amendments (client_id, gstin, period)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.ecommerce_operator_unregistered_supply_amendments IS
  'GSTR-8 Table 4.1 — a revision of an Enrolment-ID seller''s row (Table 3.1) an EARLIER month''s statement declared, as the GSTN offline '
  'utility''s `urda` array lays it out. No TCS heads, as in Table 3.1. POST-A-056, migration 617.';

-- ── Access: the API's privileged client alone ───────────────────────────────────────────────────────────────────────────────────────
-- The policy names are built from a SHORT name of the table: the second table's own name is 49 characters, and `<name>_assignment_scope`
-- would run past the 63 an identifier may have, which Postgres cuts without a word (and which would leave the name no longer ending in
-- `_assignment_scope`, the ending the catalog tests look for).
DO $$
DECLARE
    t     text;
    short text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ecommerce_operator_supply_amendments', 'ecommerce_operator_unregistered_supply_amendments'] LOOP
        short := CASE t WHEN 'ecommerce_operator_supply_amendments' THEN 'eo_amendments' ELSE 'eo_unreg_amendments' END;
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', short || '_firm_isolation', t);
        EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
                       'USING (firm_id = (SELECT public.get_my_firm_id())) '
                       'WITH CHECK (firm_id = (SELECT public.get_my_firm_id()))', short || '_firm_isolation', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', short || '_assignment_scope', t);
        EXECUTE format('CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
                       'USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false)) '
                       'WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))',
                       short || '_assignment_scope', t);

        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', short || '_internal_partner_only', t);
        EXECUTE format('CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
                       'USING ((SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text) '
                       'WITH CHECK ((SELECT public.get_my_role()) = ''Partner''::text '
                       '       OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)',
                       short || '_internal_partner_only', t);

        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC, anon, authenticated', t);
        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role', t);

        PERFORM public.guard_client_firm('public.' || t);
        PERFORM public.guard_member_firm('public.' || t);
    END LOOP;
END $$;

COMMIT;
