-- 398 — where the stock is, and which lot it came from (INV-03a).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING
-- ═══════════════════════════════════════════════════════════════════════════
-- `inventory_stock_ledger` records WHAT moved, WHEN, and for how much. It has
-- never recorded WHERE it moved or WHICH LOT it was, so a client with two
-- warehouses had one undifferentiated pile of stock, and a client whose goods
-- expire had no way to say which ones.
--
-- Owner decision of 14-09-2026, taken over the alternatives in the same
-- finding (item group, reorder level, alternate unit): batch, expiry and
-- godown together, because all three touch the stock ledger and doing them
-- separately is two migrations over the same table.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- A GODOWN IS NOT DECORATION — IT CAN CHANGE WHICH RETURN A SUPPLY IS IN
-- ═══════════════════════════════════════════════════════════════════════════
-- CGST s.25(1) requires registration in EVERY State or Union territory from
-- which a taxable supply is made, and migration 390 gave a client several
-- GSTINs for exactly that. A warehouse in another state is one of those
-- places. So a godown carries its own `state_code` and, optionally, the
-- REGISTRATION it operates under.
--
-- And the consequence the module names rather than decides: Schedule I
-- paragraph 2 makes a supply of goods between DISTINCT PERSONS a supply even
-- without consideration, and s.25(4) makes two registrations of one entity
-- distinct persons. So moving stock between godowns under DIFFERENT GSTINs is
-- a taxable supply needing a tax invoice, and moving it between two godowns
-- under the SAME registration is not. `domain/inventory/location.py` states
-- that and refuses to mint the invoice — the CA raises it, because the value
-- of such a supply is s.15 read with Rule 28 (open market value, or 90% of
-- the recipient's onward price, at the supplier's option) and nothing here
-- holds that election.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- BOTH COLUMNS ARE NULLABLE AND NOTHING IS BACKFILLED
-- ═══════════════════════════════════════════════════════════════════════════
-- Every movement already in the ledger happened at a location and in a lot
-- that nobody recorded. Backfilling a default godown onto them would assert
-- that they all happened THERE, which no one can know, and would make the
-- per-godown position confidently wrong on day one. NULL reads as
-- "unallocated", the detail report says so, and the total still ties to the
-- Inventory control account because it is the same deltas either way.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT A BATCH IS AND IS NOT
-- ═══════════════════════════════════════════════════════════════════════════
-- It is a TRACEABILITY and EXPIRY device: which lot is in stock, when it
-- expires, what to recall. It is NOT a cost formula. AS-2 paragraph 14 permits
-- FIFO or weighted average and migration 394 made that a client policy; the
-- Standard's paragraph 13 specific-identification basis is a THIRD formula and
-- adding it here by the back door — costing an issue at its batch's own cost —
-- would give a client a closing stock figure their own accounting policy note
-- does not describe. Named, not built.
--
-- EXPIRY IS A DATE, NOT A JOURNAL. Stock that has expired is written off
-- through the adjustment path that already exists (INV-06), which is also
-- where CGST s.17(5)(h) is asked — the credit on goods "lost, stolen,
-- destroyed, written off or disposed of by way of gift or free samples" must
-- be reversed. This migration adds the date; it posts nothing and reverses
-- nothing on its own.

BEGIN;

CREATE TABLE IF NOT EXISTS public.godowns (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id    UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,

  name         TEXT NOT NULL,
  code         TEXT,
  address      TEXT,

  -- The state the godown is IN. Two characters, the same vocabulary as a
  -- GSTIN's first two (migration 390's client_gst_registrations.state_code).
  state_code   TEXT CHECK (state_code IS NULL OR state_code ~ '^[0-9]{2}$'),
  -- The registration it operates under, where the client holds several. Plain
  -- TEXT rather than an FK: `clients.gstin` holds the PRIMARY and
  -- `client_gst_registrations` holds only the ADDITIONAL ones (migration 390),
  -- so there is no single table to point at and the domain module resolves it
  -- against the union the way every other reader does.
  gstin        TEXT,

  is_default   BOOLEAN NOT NULL DEFAULT FALSE,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  notes        TEXT,
  created_by   UUID REFERENCES public.users(id),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ,
  deleted_at   TIMESTAMPTZ,

  CONSTRAINT godowns_name_unique_per_client UNIQUE (client_id, name)
);

-- ONE DEFAULT PER CLIENT, as a partial unique index rather than a trigger:
-- two defaults would make "where did this movement happen" ambiguous in the
-- one place the answer is not stated.
CREATE UNIQUE INDEX IF NOT EXISTS godowns_one_default_per_client
  ON public.godowns (client_id)
  WHERE is_default AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS public.inventory_batches (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id             UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  service_catalogue_id  UUID NOT NULL REFERENCES public.service_catalogue(id) ON DELETE CASCADE,

  -- The supplier's or the manufacturer's own lot number. Free text because it
  -- is somebody else's identifier, the same reason `purchase_bills.bill_no`
  -- is not validated against Rule 46(b).
  batch_no              TEXT NOT NULL,
  manufactured_on       DATE,
  -- NULLABLE WITH NO DEFAULT. Plenty of stock does not expire, and a default
  -- would either put everything permanently in the "no expiry" bucket (if
  -- far-future) or report sound stock as expired. An item with no date is
  -- NAMED as having none rather than assumed sound.
  expiry_date           DATE,

  notes                 TEXT,
  created_by            UUID REFERENCES public.users(id),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at            TIMESTAMPTZ,

  -- One lot number per item. Two items may share a lot number (different
  -- manufacturers number independently); one item may not have two.
  CONSTRAINT inventory_batches_one_lot_per_item
    UNIQUE (service_catalogue_id, batch_no),
  CONSTRAINT inventory_batches_expiry_after_manufacture
    CHECK (manufactured_on IS NULL OR expiry_date IS NULL
           OR expiry_date >= manufactured_on)
);

CREATE INDEX IF NOT EXISTS idx_godowns_client
  ON public.godowns (firm_id, client_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_batches_item
  ON public.inventory_batches (service_catalogue_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_batches_expiring
  ON public.inventory_batches (firm_id, client_id, expiry_date)
  WHERE deleted_at IS NULL AND expiry_date IS NOT NULL;

ALTER TABLE public.inventory_stock_ledger
  ADD COLUMN IF NOT EXISTS godown_id UUID REFERENCES public.godowns(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS batch_id  UUID REFERENCES public.inventory_batches(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_ledger_godown
  ON public.inventory_stock_ledger (firm_id, client_id, godown_id, movement_date);
CREATE INDEX IF NOT EXISTS idx_ledger_batch
  ON public.inventory_stock_ledger (firm_id, client_id, batch_id, movement_date);

-- A TRANSFER IS A NEW MOVEMENT KIND AND THE COLUMN'S CHECK HAS TO ADMIT IT.
--
-- Without this the two rows a godown transfer writes are rejected by Postgres
-- outright — the feature works in mock mode, where no CHECK is enforced, and
-- fails on the first real transfer. `tests/test_status_vocabularies_pg.py` is
-- what caught it, and it exists for exactly this: a rejected write in an error
-- path or a background task is usually swallowed, and the feature silently
-- stops working.
--
-- The list is CARRIED FORWARD FROM MIGRATION 191, which last defined this
-- constraint, rather than written from memory — an ADD CONSTRAINT replaces the
-- whole definition, so omitting a value silently forbids it. `grep -ln
-- "movement_type" migrations/*.sql | sort | tail -1` is how that ancestor was
-- found, the same rule CLAUDE.md states for CREATE OR REPLACE FUNCTION.
--
-- Widening a CHECK is additive and cannot fail on existing data: every row
-- already satisfies the narrower list. 'transfer' is its own value rather than
-- an 'adjustment' for the reason 191 gave 'nrv_writedown' its own — an
-- adjustment is a quantity CHANGE (a count, damage, theft) and a transfer
-- changes nothing at the item level, only where the stock sits.
ALTER TABLE public.inventory_stock_ledger
  DROP CONSTRAINT IF EXISTS inventory_stock_ledger_movement_type_check;
ALTER TABLE public.inventory_stock_ledger
  ADD CONSTRAINT inventory_stock_ledger_movement_type_check
    CHECK (movement_type IN
      ('opening', 'purchase', 'sale', 'sale_reversal', 'purchase_reversal',
       'adjustment', 'sale_return', 'purchase_return', 'nrv_writedown',
       'transfer'));

ALTER TABLE public.godowns ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.inventory_batches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS godowns_own_firm ON public.godowns;
CREATE POLICY godowns_own_firm ON public.godowns
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS inventory_batches_own_firm ON public.inventory_batches;
CREATE POLICY inventory_batches_own_firm ON public.inventory_batches
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Migration 084's assignment scoping, declared here rather than left to its
-- one-shot DO loop, which has never re-run (CLAUDE.md).
DROP POLICY IF EXISTS godowns_assignment_scope ON public.godowns;
CREATE POLICY godowns_assignment_scope ON public.godowns
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS inventory_batches_assignment_scope ON public.inventory_batches;
CREATE POLICY inventory_batches_assignment_scope ON public.inventory_batches
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT, INSERT, UPDATE, DELETE ON public.godowns TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.inventory_batches TO authenticated;

-- ═══════════════════════════════════════════════════════════════════════════
-- THE DETAIL POSITION — A SECOND GRAIN, NOT A SECOND ANSWER
-- ═══════════════════════════════════════════════════════════════════════════
-- `stock_position_as_at` (migration 363) is the ITEM-level position and is not
-- touched: its signature is what `domain/reporting/stock_position.py` and its
-- parity test are written against, and it is the figure that ties to the
-- Inventory control account.
--
-- This one answers the same question one grain finer — per (item, godown,
-- batch) — from the SAME deltas, so its totals are that function's totals by
-- construction. A test asserts exactly that, because two aggregates over one
-- table that can disagree is how a register stops tying to its own ledger.
--
-- NULL godown and NULL batch are REAL GROUPS, not rows to drop: every movement
-- recorded before this migration has both, and dropping them would make the
-- detail sum to less than the total with nothing saying why.
CREATE OR REPLACE FUNCTION public.stock_position_detail_as_at(
    p_firm   uuid,
    p_client uuid,
    p_as_of  date,
    p_item   uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_my_firm  uuid;
    v_internal uuid;
    v_out      jsonb;
BEGIN
    -- Restates the RLS that SECURITY DEFINER bypasses. Transcribed from
    -- stock_position_as_at (migration 363), which took it from
    -- schedule_iii_ageing (303), cash_flow_report (279) and
    -- post_journal_atomic (271), so the five cannot drift in what they
    -- consider an authorised caller.
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'stock_position_detail_as_at: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'stock_position_detail_as_at: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'stock_position_detail_as_at: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'stock_position_detail_as_at: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT (
    WITH pos AS (
        SELECT l.service_catalogue_id  AS item_id,
               l.godown_id             AS godown_id,
               l.batch_id              AS batch_id,
               SUM(l.quantity_delta)   AS qty,
               SUM(l.value_delta_paise) AS value_paise,
               MAX(l.movement_date)    AS last_movement_date,
               COUNT(*)                AS movements
          FROM public.inventory_stock_ledger l
         WHERE l.firm_id = p_firm
           AND l.client_id = p_client
           AND l.movement_date <= p_as_of
           AND (p_item IS NULL OR l.service_catalogue_id = p_item)
         GROUP BY l.service_catalogue_id, l.godown_id, l.batch_id
    ),
    named AS (
        SELECT p.item_id, p.godown_id, p.batch_id,
               COALESCE(c.name, '(deleted item)') AS item_name,
               c.unit                             AS unit,
               g.name                             AS godown_name,
               g.state_code                       AS godown_state_code,
               g.gstin                            AS godown_gstin,
               b.batch_no                         AS batch_no,
               b.expiry_date                      AS expiry_date,
               p.qty, p.value_paise, p.last_movement_date, p.movements
          FROM pos p
          LEFT JOIN public.service_catalogue c
                 ON c.id = p.item_id AND c.firm_id = p_firm AND c.client_id = p_client
          LEFT JOIN public.godowns g
                 ON g.id = p.godown_id AND g.firm_id = p_firm
          LEFT JOIN public.inventory_batches b
                 ON b.id = p.batch_id AND b.firm_id = p_firm
    )
    SELECT jsonb_build_object(
        'as_of', p_as_of,
        'rows', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'service_catalogue_id', n.item_id,
                       'item_name',            n.item_name,
                       'unit',                 n.unit,
                       'godown_id',            n.godown_id,
                       'godown_name',          n.godown_name,
                       'godown_state_code',    n.godown_state_code,
                       'godown_gstin',         n.godown_gstin,
                       'batch_id',             n.batch_id,
                       'batch_no',             n.batch_no,
                       'expiry_date',          n.expiry_date,
                       'qty_units',            n.qty,
                       'value_paise',          n.value_paise,
                       'last_movement_date',   n.last_movement_date,
                       'movements',            n.movements)
                   ORDER BY n.item_name, n.item_id, n.godown_name NULLS FIRST,
                            n.expiry_date NULLS LAST, n.batch_no NULLS FIRST)
              FROM named n), '[]'::jsonb),
        -- THE SAME TOTAL stock_position_as_at RETURNS, by construction: one
        -- SUM over one set of deltas, grouped differently.
        'total_value_paise', COALESCE((SELECT SUM(n.value_paise) FROM named n), 0)
    )) INTO v_out;

    RETURN v_out;
END
$fn$;

REVOKE ALL ON FUNCTION public.stock_position_detail_as_at(uuid, uuid, date, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.stock_position_detail_as_at(uuid, uuid, date, uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.stock_position_detail_as_at(uuid, uuid, date, uuid) TO service_role;

COMMENT ON TABLE public.godowns IS
  'A place a client keeps stock. CGST s.25(1) requires registration in every '
  'State a taxable supply is made from, so a godown carries its own state code '
  'and, where the client holds several GSTINs (migration 390), the '
  'registration it operates under. Moving stock between godowns under '
  'DIFFERENT registrations is a supply between distinct persons (Schedule I '
  'paragraph 2 with s.25(4)) and needs a tax invoice; between two under the '
  'same registration it is not. domain/inventory/location.py states that and '
  'refuses to mint the invoice — its value is s.15 with Rule 28, whose option '
  'nothing here holds.';
COMMENT ON COLUMN public.inventory_stock_ledger.godown_id IS
  'Where the movement happened. NULLABLE and NOT BACKFILLED: every movement '
  'recorded before migration 398 happened somewhere nobody wrote down, and '
  'stamping a default godown on them would assert they all happened there. '
  'NULL is reported as unallocated, and the total still ties to the Inventory '
  'control account because it is the same deltas either way.';
COMMENT ON COLUMN public.inventory_stock_ledger.batch_id IS
  'Which lot moved. Nullable and not backfilled, for the same reason as '
  'godown_id. A batch is a TRACEABILITY and EXPIRY device and NOT a cost '
  'formula: AS-2 paragraph 13''s specific identification is a third formula '
  'beside the two migration 394 made a client policy, and costing an issue at '
  'its own batch''s cost would give a client a closing stock figure their own '
  'accounting policy note does not describe.';
COMMENT ON COLUMN public.inventory_batches.expiry_date IS
  'Nullable with no default — plenty of stock does not expire. A far-future '
  'default would put everything permanently in the "no expiry" bucket and a '
  'near one would report sound stock as expired, so a batch with no date is '
  'NAMED as having none rather than assumed sound. Expired stock is written '
  'off through the adjustment path that already exists, which is where CGST '
  's.17(5)(h) is asked (INV-06); nothing here posts or reverses on its own.';

COMMIT;
