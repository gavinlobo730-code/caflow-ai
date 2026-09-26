-- 421 — AN E-COMMERCE OPERATOR RECORDS WHAT ITS SELLERS SUPPLIED (GST-25, GSTR-8)
--
-- WHAT WAS WRONG
--   `domain/gst/registrations.py` has modelled TCS_COLLECTOR since migration
--   390 and already carries the refusal "a s.52 e-commerce operator files
--   GSTR-8" in OTHER_RETURN_FORMS — but nothing in this product could COMPUTE
--   that return, because the figures it needs do not live anywhere in this
--   schema at all.
--
-- WHY THIS IS NOT LIKE CMP-08 (the other half of GST-25)
--   CMP-08 reuses the client's OWN posted sales and purchases — a composition
--   dealer's books ARE the return. GSTR-8 Table 3 is the opposite kind of
--   fact: it is what THIRD-PARTY SELLERS supplied THROUGH the client's
--   platform (CGST Act s.52(1) — an "electronic commerce operator" collecting
--   tax on "the net value of taxable supplies made through it by other
--   suppliers"). Those suppliers' sales are never posted to this client's own
--   ledger — the operator is a marketplace, not the seller — so there is no
--   document here to read this off of. It is data the operator's own MIS or
--   the sellers' own reporting to the operator produces, and a CA records it
--   the same way `msme_43bh_service` names a vendor's Udyam status as a fact
--   no ledger holds.
--
-- THE SHAPE, FROM THE GSTN OFFLINE UTILITY'S OWN VBA
--   docs/compliance/sources/gst-offline-utilities/gstr8/ExportMod.bas.txt and
--   ValidateMod.bas.txt give the exact JSON Table 3 emits: `stin` (supplier
--   GSTIN), `supR`/`retsupR` (gross/returned value of supplies TO REGISTERED
--   persons), `supU`/`retsupU` (the same for UNREGISTERED persons), `pos`
--   (place of supply — the utility itself only emits this from FY 2025-26
--   onward), and `iamt`/`camt`/`samt` (TCS actually collected, entered
--   directly rather than derived — the offline utility does not compute a
--   split, it VALIDATES one the filer already typed). `net amount liable`
--   (`amt`) IS derived: supR + supU - retsupR - retsupU.
--
-- TWO TABLES, NOT ONE, FOR THE SAME REASON client_gst_registrations AND
-- customers ARE SEPARATE: Table 3 is keyed on a REGISTERED supplier's GSTIN
-- (s.52(1)); Table 3.1 is keyed on an unregistered supplier's Rule 12(1A)
-- ENROLMENT ID instead — a different identifier naming a different kind of
-- person, so folding them into one table with a nullable pair of identifier
-- columns would let a row claim neither or both.
--
-- WHAT IS DELIBERATELY NOT HERE YET
--   Table 4 / 4.1 (amendment of an EARLIER period's Table 3 / 3.1 row) are
--   named but not built — the same staging GSTR-1's own amendment tables
--   went through (the base builder first, amendments after). A correction
--   today is a fresh row for the current period; CLAUDE.md's append-only
--   discipline is not violated by that, because nothing here posts to the
--   GL or feeds another return that would double-count it.
--
--   The TCS RATE ITSELF is not stored anywhere in this schema and is not
--   asserted by this migration — domain/gst/gstr8.py carries it, [S]-graded,
--   the same posture domain/gst/composition.py takes for the s.10 rates.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ecommerce_operator_supplies (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                   UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                 UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The OPERATOR's own registration this row is filed under (GST-20's
  -- multi-registration shape — an operator may hold more than one GSTIN).
  -- Not FKed to client_gst_registrations: the primary is on clients.gstin
  -- and carries no row of its own there, the same reason gstr1_returns.gstin
  -- is a bare column rather than a foreign key.
  gstin                     TEXT NOT NULL
                            CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),

  -- GSTR-8 is filed MONTHLY (Rule 67(1)) — no QRMP for this return, so unlike
  -- gstr1_returns/gstr3b_returns there is no filing_frequency to key off.
  period                    TEXT NOT NULL,   -- MMYYYY

  -- The SELLER's GSTIN ("stin") — a registered supplier under s.52(1).
  supplier_gstin            TEXT NOT NULL
                            CHECK (supplier_gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),

  -- The offline utility's own "pos" field. NULLABLE and not asserted before
  -- FY 2025-26 — the utility's Table 3 schema itself did not carry this field
  -- before then (ExportMod.bas.txt: emitted only when the return's own FY is
  -- >= 2025), so a period before that has nothing to record here and NULL
  -- means exactly that, not an unrecorded fact for a period that needed one.
  place_of_supply           TEXT
                            CHECK (place_of_supply IS NULL OR place_of_supply ~ '^[0-9]{2}$'),

  gross_registered_paise    BIGINT NOT NULL DEFAULT 0,   -- "supR"
  returns_registered_paise  BIGINT NOT NULL DEFAULT 0,   -- "retsupR"
  gross_unregistered_paise  BIGINT NOT NULL DEFAULT 0,   -- "supU"
  returns_unregistered_paise BIGINT NOT NULL DEFAULT 0,  -- "retsupU"

  -- TCS actually collected, entered directly — the offline utility VALIDATES
  -- this against the net amount and the period's own rate rather than
  -- deriving it, and domain/gst/gstr8.py follows the same discipline.
  igst_paise                BIGINT NOT NULL DEFAULT 0,
  cgst_paise                BIGINT NOT NULL DEFAULT 0,
  sgst_paise                BIGINT NOT NULL DEFAULT 0,

  notes                     TEXT,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by                UUID REFERENCES public.users(id),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at                TIMESTAMPTZ
);

-- ONE ROW PER SUPPLIER PER PERIOD PER OPERATOR REGISTRATION. A CA correcting
-- an earlier entry for the same period edits this row rather than the return
-- carrying two figures for one supplier — Table 4 (a correction to an
-- EARLIER period) is the separate, not-yet-built case.
CREATE UNIQUE INDEX IF NOT EXISTS uq_ecommerce_operator_supply
  ON public.ecommerce_operator_supplies (client_id, gstin, period, supplier_gstin)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_ecommerce_operator_supplies_period
  ON public.ecommerce_operator_supplies (client_id, gstin, period)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.ecommerce_operator_supplies IS
  'GSTR-8 Table 3 (CGST Act s.52) — supplies a REGISTERED seller made through '
  'this e-commerce operator client. A fact the operator''s own MIS records, '
  'not one derivable from this client''s books: the seller is not this '
  'client, so nothing here posts a journal. domain/gst/gstr8.py is the '
  'authority for what is computed from it. GST-25, migration 421.';

COMMENT ON COLUMN public.ecommerce_operator_supplies.place_of_supply IS
  'The GSTN offline utility''s own Table 3 schema only carries this field '
  'from FY 2025-26 onward (docs/compliance/sources/gst-offline-utilities/ '
  'gstr8/ExportMod.bas.txt). NULL for an earlier period is the utility''s own '
  'schema, not a gap; NULL for a later one IS a gap and domain/gst/gstr8.py '
  'names it as such.';

ALTER TABLE public.ecommerce_operator_supplies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_ecommerce_operator_supplies"
  ON public.ecommerce_operator_supplies;
CREATE POLICY "firm_staff_read_ecommerce_operator_supplies"
  ON public.ecommerce_operator_supplies
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "ecommerce_operator_supplies_assignment_scope"
  ON public.ecommerce_operator_supplies;
CREATE POLICY "ecommerce_operator_supplies_assignment_scope"
  ON public.ecommerce_operator_supplies AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Read-only from the browser: every write goes through the API so rbac() and
-- the reconciliation checks in domain/gst/gstr8.py both run.
GRANT SELECT ON public.ecommerce_operator_supplies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ecommerce_operator_supplies TO service_role;


-- ── Table 3.1 — the same fact for an UNREGISTERED seller ────────────────────
--
-- Rule 12(1A) gives a person supplying only through an e-commerce operator,
-- who would otherwise need no GST registration at all, an ENROLMENT ID
-- instead of a GSTIN. That is a different identifier naming a different kind
-- of person, which is why this is its own table rather than a nullable
-- second identifier column on the one above.

CREATE TABLE IF NOT EXISTS public.ecommerce_operator_unregistered_supplies (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin           TEXT NOT NULL
                  CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
  period          TEXT NOT NULL,   -- MMYYYY

  -- Rule 12(1A)'s Enrolment ID. No fixed statutory format is recorded here —
  -- unlike a GSTIN, this product holds no confirmed shape for one, so it is
  -- taken as the CA typed it rather than validated against an invented
  -- pattern.
  enrolment_id    TEXT NOT NULL,

  gross_value_paise BIGINT NOT NULL DEFAULT 0,   -- "grsval"
  returns_paise     BIGINT NOT NULL DEFAULT 0,   -- "supret"

  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by      UUID REFERENCES public.users(id),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at      TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_ecommerce_operator_unregistered_supply
  ON public.ecommerce_operator_unregistered_supplies (client_id, gstin, period, enrolment_id)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_ecommerce_operator_unreg_supplies_period
  ON public.ecommerce_operator_unregistered_supplies (client_id, gstin, period)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.ecommerce_operator_unregistered_supplies IS
  'GSTR-8 Table 3.1 — supplies made by a seller who holds only a Rule 12(1A) '
  'Enrolment ID, not a full GSTIN, through this e-commerce operator client. '
  'No TCS heads: an unregistered seller is not charged tax through this '
  'table (the offline utility''s "3.1 UNRD" sheet carries no iamt/camt/samt '
  'columns). GST-25, migration 421.';

ALTER TABLE public.ecommerce_operator_unregistered_supplies ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_ecommerce_operator_unreg_supplies"
  ON public.ecommerce_operator_unregistered_supplies;
CREATE POLICY "firm_staff_read_ecommerce_operator_unreg_supplies"
  ON public.ecommerce_operator_unregistered_supplies
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "ecommerce_operator_unreg_supplies_assignment_scope"
  ON public.ecommerce_operator_unregistered_supplies;
CREATE POLICY "ecommerce_operator_unreg_supplies_assignment_scope"
  ON public.ecommerce_operator_unregistered_supplies AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.ecommerce_operator_unregistered_supplies TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.ecommerce_operator_unregistered_supplies TO service_role;

COMMIT;
