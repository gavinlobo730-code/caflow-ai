-- 422 — A COMPOSITION DEALER'S ANNUAL RETURN RECORDS ITS OWN INWARD SUPPLIES
-- (GST-25, GSTR-4 Annual — the other half of the composition dealer's return
-- CMP-08 does not cover)
--
-- WHAT WAS WRONG
--   A composition registration (migration 420) already carries the refusal
--   "a composition dealer pays under s.10 and files CMP-08 quarterly with
--   GSTR-4 annually" (domain/gst/registrations.OTHER_RETURN_FORMS) — CMP-08
--   itself was built (GST-25 part 1), and nothing built GSTR-4 Annual, the
--   annual return under CGST Act s.44 / Rule 80(3) that consolidates the
--   year and records the dealer's own INWARD supplies.
--
-- WHY THIS IS FOUR TABLES, NOT ONE, AND WHY IT IS NOT LIKE GSTR-8
--   Read from the GSTN offline utility's own VBA
--   (docs/compliance/sources/gst-offline-utilities/gstr4-annual/), which
--   exports exactly four JSON sections for the dealer's own year:
--     4A "b2bor" — inward supplies from a REGISTERED supplier, other than
--                  reverse charge. Informational: the supplier already
--                  charged and remitted the tax, so this table never feeds
--                  the return's own liability.
--     4B "b2br"  — the SAME shape as 4A, but reverse-charge: the dealer must
--                  self-assess this tax, and it DOES feed the liability.
--     4C "b2bur" — inward supplies from an UNREGISTERED person, keyed on a
--                  PAN (nullable — an unregistered supplier may hold none)
--                  rather than a GSTIN, with reverse-charge itself a
--                  per-row fact (`rchrg`) rather than assumed.
--     4D "imps"  — import of services. IGST Act §7(4) deems this always
--                  inter-State, so — confirmed from the VBA's own column
--                  list — there is no CGST/SGST column for this table at
--                  all, only IGST and CESS.
--   Four identifier/column shapes, matching migration 421's own reasoning
--   for splitting GSTR-8's Table 3 (GSTIN) from Table 3.1 (Enrolment ID):
--   a shared table with nullable columns for whichever shape does not apply
--   would let a row claim a shape it is not.
--
--   UNLIKE GSTR-8, THIS IS GRAIN-BY-YEAR, NOT BY MONTH. Confirmed from the
--   VBA: none of 4A-4D carries a period/quarter dimension — HomeMod's own
--   `fp` key is a single annual value ("03" + the FY's ending year). So
--   these tables key on `financial_year` (canonical "YYYY-YY"), never on a
--   monthly `period`.
--
--   THE ACTION VOCABULARY IS "Add"/"Delete" ONLY, NEVER "Amend" — confirmed
--   from `CommonUtil.IsInActionType` (`Array("Add", "Delete")`), because
--   there is no earlier PERIOD within one annual filing to amend against.
--   "Delete" maps onto this codebase's own soft-delete convention
--   (`deleted_at`), the same as every other CA-recorded document here.
--
-- WHAT IS DELIBERATELY NOT HERE
--   Table 5 (the CMP-08 quarterly summary) and Table 7 (TDS/TCS credit
--   received) are BOTH populated by the government portal itself from data
--   it already has (the filed CMP-08s, and GSTR-7/8 filed by others against
--   this GSTIN) — confirmed from the VBA, where `CMP08Mod`/`TDSTCSMod` are
--   read on JSON *import* only and neither is part of `exportToJSON`'s own
--   payload. Table 5 is DERIVED at read time by summing four already-built
--   `cmp08_statement()` calls (domain/gst/gstr4_annual.py); Table 7 has no
--   table here at all — nothing in this product could write it, and
--   reading a fact from a portal this product does not integrate with
--   would be worse than an honest gap.
--
--   The "outward supply by rate" summary (rows 7-12 of the offline
--   utility's "6. Inward outward supplies" sheet, JSON key "outsupply") is
--   NOT modelled as a table either. Confirmed from the VBA: nothing
--   computes it from anything else in the sheet — it is typed directly by
--   the CA — and its own statutory meaning could not be confirmed even
--   from the VBA's full text (no "Table 6" label anywhere, and its six
--   rate buckets, 0/1/2/5/6/40%, do not cleanly match either GST's ordinary
--   rate schedule or s.10's own composition rates). Named as a gap in
--   domain/gst/gstr4_annual.py rather than guessed into a table.

BEGIN;

-- ── Table 4A — inward supplies from a registered supplier, non-RCM ─────────

CREATE TABLE IF NOT EXISTS public.gstr4_annual_b2b_supplies (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The composition dealer's OWN registration (GST-20's multi-registration
  -- shape). Not FKed to client_gst_registrations — the primary lives on
  -- clients.gstin with no row of its own there, the same reason
  -- ecommerce_operator_supplies.gstin (migration 421) is a bare column.
  gstin                  TEXT NOT NULL
                         CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),

  financial_year         TEXT NOT NULL,   -- canonical "YYYY-YY"

  -- The SUPPLIER's GSTIN ("ctin" in the VBA).
  supplier_gstin         TEXT NOT NULL
                         CHECK (supplier_gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),

  place_of_supply        TEXT NOT NULL CHECK (place_of_supply ~ '^[0-9]{2}$'),

  -- Rate in basis points (500 = 5%), matching this codebase's convention
  -- elsewhere (domain/gst/gstr8.py's TCS rate, section_rates.py's TDS
  -- rates) rather than a float percentage.
  rate_bps               INTEGER NOT NULL DEFAULT 0,

  taxable_value_paise    BIGINT NOT NULL DEFAULT 0,   -- "txval"
  igst_paise             BIGINT NOT NULL DEFAULT 0,
  cgst_paise             BIGINT NOT NULL DEFAULT 0,
  sgst_paise             BIGINT NOT NULL DEFAULT 0,
  cess_paise             BIGINT NOT NULL DEFAULT 0,

  notes                  TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr4_annual_b2b_supply
  ON public.gstr4_annual_b2b_supplies (client_id, gstin, financial_year, supplier_gstin, place_of_supply, rate_bps)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_gstr4_annual_b2b_supplies_fy
  ON public.gstr4_annual_b2b_supplies (client_id, gstin, financial_year)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr4_annual_b2b_supplies IS
  'GSTR-4 Annual Table 4A (CGST Act s.44) — a composition dealer''s inward '
  'supplies from a REGISTERED supplier, other than reverse charge. '
  'Informational only: the supplier already charged and remitted this tax, '
  'so this table never feeds this return''s own self-assessed liability '
  '(that is Table 4B). domain/gst/gstr4_annual.py is the authority. '
  'GST-25, migration 422.';

ALTER TABLE public.gstr4_annual_b2b_supplies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr4_annual_b2b_supplies"
  ON public.gstr4_annual_b2b_supplies;
CREATE POLICY "firm_staff_read_gstr4_annual_b2b_supplies"
  ON public.gstr4_annual_b2b_supplies
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr4_annual_b2b_supplies_assignment_scope"
  ON public.gstr4_annual_b2b_supplies;
CREATE POLICY "gstr4_annual_b2b_supplies_assignment_scope"
  ON public.gstr4_annual_b2b_supplies AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr4_annual_b2b_supplies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr4_annual_b2b_supplies TO service_role;


-- ── Table 4B — the SAME shape, but reverse charge ───────────────────────────

CREATE TABLE IF NOT EXISTS public.gstr4_annual_b2b_rc_supplies (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin                  TEXT NOT NULL
                         CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  financial_year         TEXT NOT NULL,
  supplier_gstin         TEXT NOT NULL
                         CHECK (supplier_gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  place_of_supply        TEXT NOT NULL CHECK (place_of_supply ~ '^[0-9]{2}$'),
  rate_bps               INTEGER NOT NULL DEFAULT 0,
  taxable_value_paise    BIGINT NOT NULL DEFAULT 0,
  igst_paise             BIGINT NOT NULL DEFAULT 0,
  cgst_paise             BIGINT NOT NULL DEFAULT 0,
  sgst_paise             BIGINT NOT NULL DEFAULT 0,
  cess_paise             BIGINT NOT NULL DEFAULT 0,
  notes                  TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr4_annual_b2b_rc_supply
  ON public.gstr4_annual_b2b_rc_supplies (client_id, gstin, financial_year, supplier_gstin, place_of_supply, rate_bps)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_gstr4_annual_b2b_rc_supplies_fy
  ON public.gstr4_annual_b2b_rc_supplies (client_id, gstin, financial_year)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr4_annual_b2b_rc_supplies IS
  'GSTR-4 Annual Table 4B — inward supplies from a registered supplier '
  'ATTRACTING REVERSE CHARGE. The dealer self-assesses this tax, and it '
  'feeds this return''s own liability, unlike Table 4A''s identical column '
  'shape. GST-25, migration 422.';

ALTER TABLE public.gstr4_annual_b2b_rc_supplies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr4_annual_b2b_rc_supplies"
  ON public.gstr4_annual_b2b_rc_supplies;
CREATE POLICY "firm_staff_read_gstr4_annual_b2b_rc_supplies"
  ON public.gstr4_annual_b2b_rc_supplies
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr4_annual_b2b_rc_supplies_assignment_scope"
  ON public.gstr4_annual_b2b_rc_supplies;
CREATE POLICY "gstr4_annual_b2b_rc_supplies_assignment_scope"
  ON public.gstr4_annual_b2b_rc_supplies AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr4_annual_b2b_rc_supplies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr4_annual_b2b_rc_supplies TO service_role;


-- ── Table 4C — inward supplies from an UNREGISTERED person ──────────────────

CREATE TABLE IF NOT EXISTS public.gstr4_annual_urp_supplies (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin                  TEXT NOT NULL
                         CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  financial_year         TEXT NOT NULL,

  -- The counterparty's PAN ("cpan") — NULLABLE. An unregistered supplier
  -- with no GSTIN may hold no recorded PAN either; the VBA's own export
  -- drops the "cpan" key from a group entirely when this segment is blank,
  -- confirming absence is itself a valid, expected state here.
  counterparty_pan       TEXT CHECK (counterparty_pan IS NULL OR counterparty_pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),

  -- "rchrg" — a PER-ROW fact, unlike 4A/4B where it is the table itself
  -- that says so. An unregistered supplier's inward supply may or may not
  -- attract reverse charge depending on what was supplied.
  reverse_charge         BOOLEAN NOT NULL DEFAULT false,

  place_of_supply        TEXT NOT NULL CHECK (place_of_supply ~ '^[0-9]{2}$'),

  -- "sply_ty" — confirmed from the VBA to be present ONLY where
  -- reverse_charge is true; refused otherwise by the CHECK below.
  supply_type            TEXT CHECK (supply_type IN ('Intra-State', 'Inter-State')),

  -- Nullable for the same reason: rate applies only where reverse_charge
  -- makes this row the dealer's own self-assessed liability at all.
  rate_bps               INTEGER,

  taxable_value_paise    BIGINT NOT NULL DEFAULT 0,
  igst_paise             BIGINT NOT NULL DEFAULT 0,
  cgst_paise             BIGINT NOT NULL DEFAULT 0,
  sgst_paise             BIGINT NOT NULL DEFAULT 0,
  cess_paise             BIGINT NOT NULL DEFAULT 0,

  notes                  TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ,

  CONSTRAINT gstr4_annual_urp_supply_type_needs_reverse_charge
    CHECK (supply_type IS NULL OR reverse_charge),
  CONSTRAINT gstr4_annual_urp_rate_needs_reverse_charge
    CHECK (rate_bps IS NULL OR reverse_charge)
);

-- `coalesce` on both nullable key columns, the same discipline migration
-- 390 applies to gstr1_returns/gstr3b_returns' nullable gstin: NULL is
-- DISTINCT from NULL in a unique index, so a bare UNIQUE would enforce
-- nothing on the very rows (no PAN, or no reverse-charge rate) this table
-- exists to hold honestly.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr4_annual_urp_supply
  ON public.gstr4_annual_urp_supplies (
    client_id, gstin, financial_year,
    COALESCE(counterparty_pan, ''), place_of_supply, COALESCE(rate_bps, -1)
  )
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_gstr4_annual_urp_supplies_fy
  ON public.gstr4_annual_urp_supplies (client_id, gstin, financial_year)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr4_annual_urp_supplies IS
  'GSTR-4 Annual Table 4C — inward supplies from an UNREGISTERED person, '
  'keyed on a PAN (nullable) rather than a GSTIN, with reverse charge a '
  'per-row fact. GST-25, migration 422.';

ALTER TABLE public.gstr4_annual_urp_supplies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr4_annual_urp_supplies"
  ON public.gstr4_annual_urp_supplies;
CREATE POLICY "firm_staff_read_gstr4_annual_urp_supplies"
  ON public.gstr4_annual_urp_supplies
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr4_annual_urp_supplies_assignment_scope"
  ON public.gstr4_annual_urp_supplies;
CREATE POLICY "gstr4_annual_urp_supplies_assignment_scope"
  ON public.gstr4_annual_urp_supplies AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr4_annual_urp_supplies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr4_annual_urp_supplies TO service_role;


-- ── Table 4D — import of services ────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.gstr4_annual_import_of_services (
  id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id              UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin                  TEXT NOT NULL
                         CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  financial_year         TEXT NOT NULL,
  place_of_supply        TEXT NOT NULL CHECK (place_of_supply ~ '^[0-9]{2}$'),
  rate_bps               INTEGER NOT NULL DEFAULT 0,
  taxable_value_paise    BIGINT NOT NULL DEFAULT 0,

  -- NO cgst_paise / sgst_paise COLUMN AT ALL — confirmed from the VBA's own
  -- column list for the "4D. IMPS" sheet (cols 2-7: pos, txval, rt, iamt,
  -- csamt, flag; no camt/samt anywhere). IGST Act s.7(4) deems an import of
  -- service always inter-State, so there is nothing for those two columns
  -- to hold, and adding them would invite a value the statute forbids.
  igst_paise             BIGINT NOT NULL DEFAULT 0,
  cess_paise             BIGINT NOT NULL DEFAULT 0,

  notes                  TEXT,
  created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by             UUID REFERENCES public.users(id),
  updated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at             TIMESTAMPTZ
);

-- Keyed on RATE ALONE, matching the sheet's own uniqueness check — the VBA
-- assumes one POS per filer throughout this sheet (see the module docstring
-- above), so there is nothing else to key on.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr4_annual_import_of_service
  ON public.gstr4_annual_import_of_services (client_id, gstin, financial_year, rate_bps)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_gstr4_annual_import_of_services_fy
  ON public.gstr4_annual_import_of_services (client_id, gstin, financial_year)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.gstr4_annual_import_of_services IS
  'GSTR-4 Annual Table 4D — import of services. IGST Act s.7(4) makes this '
  'always inter-State, hence no CGST/SGST columns. GST-25, migration 422.';

ALTER TABLE public.gstr4_annual_import_of_services ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_gstr4_annual_import_of_services"
  ON public.gstr4_annual_import_of_services;
CREATE POLICY "firm_staff_read_gstr4_annual_import_of_services"
  ON public.gstr4_annual_import_of_services
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "gstr4_annual_import_of_services_assignment_scope"
  ON public.gstr4_annual_import_of_services;
CREATE POLICY "gstr4_annual_import_of_services_assignment_scope"
  ON public.gstr4_annual_import_of_services AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.gstr4_annual_import_of_services TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr4_annual_import_of_services TO service_role;

COMMIT;
