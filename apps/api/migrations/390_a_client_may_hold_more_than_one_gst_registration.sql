-- 390 — A CLIENT MAY HOLD MORE THAN ONE GST REGISTRATION (GST-20)
--
-- WHAT WAS WRONG
--   `clients.gstin` (migration 001) held exactly one, and BOTH return tables
--   were `UNIQUE (client_id, period)` (migration 036, lines 60 and 116) — so a
--   second registration could not have its own GSTR-1 or GSTR-3B row whatever
--   the code did. CGST Act s.25(1) requires registration in EVERY State or
--   Union territory from which a taxable supply is made, and s.25(2)'s proviso
--   allows a separate registration per place of business inside one state. A
--   manufacturer with a depot, a services firm with two offices, an
--   e-commerce seller holding warehouse-state registrations: one legal person,
--   several GSTINs, several sets of returns.
--
--   The CA's only route was a second fake "client" per GSTIN — which splits ONE
--   entity's accounting across two ledgers and breaks every client-scoped
--   report, the trial balance and the ITR alike.
--
-- WHY `clients.gstin` SURVIVES, AND WHY THIS TABLE IS "ADDITIONAL" ONLY
--   It stays the PRIMARY registration and remains the only place the primary is
--   stored. About thirty callers read it — the invoice PDF, the purchase-bill
--   place of supply, the engagement letter, search, onboarding — and every one
--   of them wants the client's MAIN GSTIN, which is exactly what they still
--   get, unchanged.
--
--   The obvious alternative is to move every registration in here and leave
--   `clients.gstin` as a cache of the primary. A cache needs ONE write path and
--   that column already has several (onboarding, the client edit screen, the
--   seed in migration 073), so it would drift the first time somebody edited a
--   client — silently, surfacing later as a return filed under the wrong
--   registration. A denormalised copy nobody can keep honest is worse than no
--   copy. `domain/gst/registrations.py` presents the union so no caller has to
--   know the difference.
--
--   There is deliberately NO BACKFILL for the same reason: every client's
--   primary is already where it belongs.

BEGIN;

CREATE TABLE IF NOT EXISTS public.client_gst_registrations (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id           UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  -- The same shape CHECK `clients.gstin` carries (migration 001). The CHECK
  -- DIGIT is not testable in SQL and is not attempted here — `domain/gst/gstin`
  -- is the one implementation of that and the API refuses at the door, which is
  -- where a human types it.
  gstin               TEXT NOT NULL
                      CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),

  -- A REGISTRATION IS STATE-WISE (s.25(1)), so the state is the GSTIN's own
  -- first two characters and cannot disagree with it. Enforced rather than
  -- trusted: a state code typed wrong puts every supply under this
  -- registration in the wrong state.
  state_code          TEXT NOT NULL
                      CHECK (state_code = left(gstin, 2)),

  registration_type   TEXT NOT NULL DEFAULT 'regular'
                      CHECK (registration_type IN (
                        'regular', 'composition', 'casual_taxable_person',
                        'input_service_distributor', 'sez_unit',
                        'sez_developer', 'tds_deductor', 'tcs_collector',
                        'non_resident_taxable_person')),

  -- The QRMP scheme (s.39(1) proviso with Rule 61A). It decides which PERIODS
  -- are due, not which forms.
  filing_frequency    TEXT NOT NULL DEFAULT 'monthly'
                      CHECK (filing_frequency IN ('monthly', 'quarterly')),

  -- What a human recognises. A client with three registrations in ONE state is
  -- told apart only by this.
  trade_name          TEXT,
  address_line1       TEXT,
  address_line2       TEXT,
  city                TEXT,
  pincode             TEXT,

  effective_from      DATE,
  -- s.29 cancellation or surrender. A cancelled registration still owes the
  -- returns for the periods it was live, so it is never hidden — only closed.
  effective_to        DATE,

  notes               TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by          UUID REFERENCES public.users(id),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  deleted_at          TIMESTAMPTZ,

  CONSTRAINT client_gst_registrations_dates_run_forward
    CHECK (effective_to IS NULL OR effective_from IS NULL
           OR effective_to >= effective_from)
);

-- ONE ROW PER GSTIN PER CLIENT. Partial on deleted_at so a registration
-- recorded in error can be withdrawn and re-entered.
CREATE UNIQUE INDEX IF NOT EXISTS uq_client_gst_registration
  ON public.client_gst_registrations (client_id, gstin)
  WHERE deleted_at IS NULL;

-- A GSTIN identifies one taxable person, so the same number cannot belong to
-- two clients of one firm. Caught here rather than in the app because the app
-- would have to scan every client to notice.
CREATE UNIQUE INDEX IF NOT EXISTS uq_gst_registration_per_firm
  ON public.client_gst_registrations (firm_id, gstin)
  WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_client_gst_registrations_client
  ON public.client_gst_registrations (client_id)
  WHERE deleted_at IS NULL;

COMMENT ON TABLE public.client_gst_registrations IS
  'The ADDITIONAL GST registrations a client holds beyond the primary, which '
  'stays on clients.gstin (GST-20). CGST Act s.25(1) makes registration '
  'state-wise and s.25(2) allows one per place of business, so one legal '
  'person may hold several. domain/gst/registrations.py presents the union; '
  'nothing here duplicates the primary. Migration 390.';

COMMENT ON COLUMN public.client_gst_registrations.state_code IS
  'Always left(gstin, 2) and CHECKed to it — a registration is state-wise, so '
  'a state code that disagrees with the number means one of the two is wrong.';

COMMENT ON COLUMN public.client_gst_registrations.effective_to IS
  'CGST Act s.29 cancellation or surrender. A cancelled registration still '
  'owes the returns for the periods it was live, so it is closed, never '
  'hidden.';

ALTER TABLE public.client_gst_registrations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_client_gst_registrations"
  ON public.client_gst_registrations;
CREATE POLICY "firm_staff_read_client_gst_registrations"
  ON public.client_gst_registrations
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

-- Migration 084's loop has never run again (see 370), so a table created now is
-- firm-wide unless it says otherwise here.
DROP POLICY IF EXISTS "client_gst_registrations_assignment_scope"
  ON public.client_gst_registrations;
CREATE POLICY "client_gst_registrations_assignment_scope"
  ON public.client_gst_registrations AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Read-only from the browser: every write goes through the API so rbac() runs
-- and the check digit, the duplicate test and the state rule are all asked.
GRANT SELECT ON public.client_gst_registrations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_gst_registrations TO service_role;

-- ── The returns are keyed PER REGISTRATION ─────────────────────────────────
--
-- Narrowing the key is the whole structural change: every existing row keeps
-- its number and its identity, and the new key is satisfied by them unchanged.
--
-- ⚠️ THE TWO `gstin` COLUMNS ARE NOT THE SAME SHAPE, AND THE DIFFERENCE DECIDES
-- WHETHER THIS MIGRATION CONSTRAINS ANYTHING AT ALL. `gstr1_returns.gstin` has
-- been NOT NULL since migration 036. `gstr3b_returns.gstin` is NULLABLE: 036's
-- CREATE TABLE omitted it entirely and migration 234 added it as a bare
-- `TEXT`, with nothing to back-fill from at the time. Postgres treats NULLs as
-- DISTINCT in a unique index, so `(client_id, period, gstin)` would enforce
-- NOTHING on a row that left it blank — two GSTR-3Bs for one client and one
-- month, which is exactly the collision `UNIQUE (client_id, period)` used to
-- prevent. Narrowing the key would have REMOVED a guarantee rather than
-- refined it. Two things close that, in this order:
--
--   (1) The BACK-FILL below, run while the old constraint is still in force.
--       That constraint guarantees at most ONE row per (client_id, period), so
--       the update cannot collide with a row that already carries a GSTIN; and
--       before this migration a client held exactly one registration, so
--       `clients.gstin` IS the registration such a row was prepared under.
--       It is a repair of 234's omission, not a guess.
--
--   (2) The indexes key on `coalesce(gstin, '')`, so a row that still has none
--       — a client with no GSTIN recorded at all, which `clients.gstin` being
--       nullable allows — is constrained exactly as the old key constrained it.
--       On `gstr1_returns` the coalesce is a no-op today and is written anyway:
--       the nullability of these two columns has already drifted apart once,
--       and an index that does not depend on it cannot drift with it.
--
-- A `SET NOT NULL` is deliberately NOT used. Merging to main applies this to
-- production with no review step, and one unbackfillable row would abort the
-- deploy and block every later migration behind it.
--
-- The old constraint's name is the one Postgres generated from the table and
-- the columns; dropped IF EXISTS so a database that never had it (or has it
-- under another name from an earlier hand-fix) does not abort the migration,
-- with the new index doing the work either way.

UPDATE public.gstr3b_returns r
   SET gstin = c.gstin
  FROM public.clients c
 WHERE c.id = r.client_id
   AND r.gstin IS NULL
   AND c.gstin IS NOT NULL;

UPDATE public.gstr1_returns r
   SET gstin = c.gstin
  FROM public.clients c
 WHERE c.id = r.client_id
   AND r.gstin IS NULL
   AND c.gstin IS NOT NULL;

ALTER TABLE public.gstr1_returns
  DROP CONSTRAINT IF EXISTS gstr1_returns_client_id_period_key;
ALTER TABLE public.gstr3b_returns
  DROP CONSTRAINT IF EXISTS gstr3b_returns_client_id_period_key;

CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr1_return_per_registration
  ON public.gstr1_returns (client_id, period, coalesce(gstin, ''));
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr3b_return_per_registration
  ON public.gstr3b_returns (client_id, period, coalesce(gstin, ''));

COMMENT ON COLUMN public.gstr1_returns.gstin IS
  'The registration this return is filed under. Part of the uniqueness key '
  'since migration 390 — before it, (client_id, period) alone meant a client '
  'with two registrations could not hold both months'' returns (GST-20).';
COMMENT ON COLUMN public.gstr3b_returns.gstin IS
  'The registration this return is filed under. Part of the uniqueness key '
  'since migration 390 (GST-20).';

COMMIT;
