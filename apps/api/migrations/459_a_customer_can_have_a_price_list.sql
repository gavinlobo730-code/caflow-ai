-- accounting-20 — named price lists, and a default list per customer.
--
-- WHAT WAS MISSING
--     `service_catalogue` carries ONE selling rate per item
--     (`default_rate_paise`), so a trading client who quotes a dealer, a
--     retailer and a wholesaler three different rates had to remember each one
--     and type it onto every invoice line. TallyPrime calls this a price level;
--     every product in this tier has it.
--
-- WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT
--     * `price_lists`        — a named list, owned by ONE client (a catalogue
--                              item is client-owned since migration 182, so a
--                              list that spanned clients would price an item
--                              that is not the client's own).
--     * `price_list_items`   — one rate per (list, catalogue item).
--     * `customers.price_list_id` — the customer's DEFAULT list, nullable.
--
--     IT CHANGES NO TAX AND NO POSTING. A price list is a PRE-FILL SOURCE for
--     the rate of an invoice line, exactly as `service_catalogue.default_rate_
--     paise` already is ("the stored rate/price are pre-fill hints, CGST Rule
--     46(g) — never used in tax/journal math"). The invoice keeps whatever rate
--     it was GIVEN; the create path never reads these tables. The rate is
--     resolved SERVER-SIDE (domain/sales/price_list.py) at the moment a line is
--     picked, so the browser holds no pricing rule.
--
-- RATES ARE STRICTLY POSITIVE
--     `rate_paise > 0`. The catalogue's own "0 means no default price" is the
--     precedent: a list rate of 0 would be indistinguishable from "this list
--     has no price for the item", and an item with no entry on a list simply
--     falls back to the catalogue rate. A genuinely free line is typed on the
--     invoice, where it is visible.
--
-- A LIST IS ARCHIVED, NOT DELETED
--     `is_active` — a customer pointing at an archived list falls back to the
--     catalogue rate and the answer SAYS so, rather than the pointer silently
--     breaking. `customers.price_list_id` is ON DELETE SET NULL only as a
--     backstop for a hard delete nobody should be doing.
--
-- CLIENT INTEGRITY
--     An item's `client_id` must be its list's: that is a composite foreign key
--     (price_list_id, client_id) -> price_lists(id, client_id), so the database
--     refuses an item filed under the wrong client rather than relying on every
--     writer to remember. The other two cross-table facts — the catalogue item
--     and the customer belong to the same client as the list — are checked in
--     `services/price_list_service.py`: a composite key onto `service_catalogue`
--     would need a new unique constraint on an existing production table, and
--     one onto `customers` cannot use ON DELETE SET NULL without nulling the
--     NOT NULL `client_id` beside it.
--
-- ADDITIVE AND IDEMPOTENT. No existing row is touched, nothing is back-filled
-- (no customer has a list until somebody gives them one), no policy is removed.

CREATE TABLE IF NOT EXISTS public.price_lists (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id    UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  name         TEXT        NOT NULL,
  description  TEXT,
  is_active    BOOLEAN     NOT NULL DEFAULT true,
  created_by   UUID        REFERENCES public.users(id) ON DELETE SET NULL,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT price_lists_name_present CHECK (btrim(name) <> ''),
  -- The target of price_list_items' composite key below.
  CONSTRAINT price_lists_id_client_key UNIQUE (id, client_id)
);

COMMENT ON TABLE public.price_lists IS
  'accounting-20. A named price list (Dealer, Retail, Wholesale) owned by one client. '
  'A PRE-FILL source for an invoice line''s rate, resolved server-side by '
  'domain/sales/price_list.py; it changes no tax and posts nothing, and the '
  'invoice keeps whatever rate it was given.';

CREATE UNIQUE INDEX IF NOT EXISTS uq_price_lists_client_name
  ON public.price_lists (client_id, lower(btrim(name)));

CREATE TABLE IF NOT EXISTS public.price_list_items (
  id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID        NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id             UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  price_list_id         UUID        NOT NULL,
  service_catalogue_id  UUID        NOT NULL REFERENCES public.service_catalogue(id) ON DELETE CASCADE,
  rate_paise            BIGINT      NOT NULL,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT price_list_items_rate_positive CHECK (rate_paise > 0),
  CONSTRAINT price_list_items_one_rate_per_item UNIQUE (price_list_id, service_catalogue_id),
  CONSTRAINT price_list_items_list_is_this_clients
    FOREIGN KEY (price_list_id, client_id)
    REFERENCES public.price_lists (id, client_id) ON DELETE CASCADE
);

COMMENT ON COLUMN public.price_list_items.rate_paise IS
  'Integer paise, strictly positive: the catalogue''s own "0 = no default '
  'price" is the precedent, so an item with no price on a list has NO ROW here '
  'and falls back to service_catalogue.default_rate_paise.';

CREATE INDEX IF NOT EXISTS idx_price_list_items_item
  ON public.price_list_items (service_catalogue_id);

ALTER TABLE public.customers
  ADD COLUMN IF NOT EXISTS price_list_id UUID REFERENCES public.price_lists(id) ON DELETE SET NULL;

COMMENT ON COLUMN public.customers.price_list_id IS
  'accounting-20. This customer''s DEFAULT price list. NULL means none: a line picked '
  'for them is pre-filled from the catalogue rate exactly as before. Only a '
  'pre-fill hint — the invoice keeps whatever rate it was given.';

-- ── Row-level security ───────────────────────────────────────────────────────
-- The firm policy every neighbour has, plus the RESTRICTIVE assignment scope a
-- client_id table needs (migration 084's loop has never run again, and
-- tests/test_a_table_the_browser_reads_is_assignment_scoped_pg.py is the rule).

ALTER TABLE public.price_lists ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.price_lists;
CREATE POLICY "firm_isolation" ON public.price_lists
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "price_lists_assignment_scope" ON public.price_lists;
CREATE POLICY "price_lists_assignment_scope" ON public.price_lists
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

ALTER TABLE public.price_list_items ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_isolation" ON public.price_list_items;
CREATE POLICY "firm_isolation" ON public.price_list_items
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "price_list_items_assignment_scope" ON public.price_list_items;
CREATE POLICY "price_list_items_assignment_scope" ON public.price_list_items
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Reads only for the signed-in role: every write goes through the API
-- (services/price_list_service.py), where rbac() runs and the client scope is
-- checked, on the service role. Nothing in the browser reads these tables.
GRANT SELECT ON public.price_lists      TO authenticated;
GRANT SELECT ON public.price_list_items TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.price_lists      TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.price_list_items TO service_role;
