-- Migration 241: optimistic-concurrency guard for the inventory stock ledger.
--
-- task #241 audit finding: domain/inventory_service.py's record_stock_in /
-- record_stock_out / record_stock_out_at_value / seed_opening_balance /
-- record_nrv_writedown all read the latest inventory_stock_ledger row,
-- compute the new running quantity/value/average cost in Python, then write
-- a new ledger row and update service_catalogue's cache -- with no locking
-- of any kind. Two concurrent movements on the SAME item (e.g. two
-- near-simultaneous sales) can both read the same stale running totals and
-- both write, silently dropping one movement's effect on the running
-- position (a classic lost update) instead of surfacing as a detectable
-- conflict.
--
-- stock_version is a plain INTEGER compare-and-set token, incremented by
-- exactly 1 on every successful stock movement for that item. It is
-- deliberately NOT service_catalogue.stock_qty_units itself: that column is
-- NUMERIC(10,3) and Postgres/PostgREST may return it in a different string
-- form on read than what the application wrote (e.g. scale-padded), which
-- would make a string-equality CAS guard on it unreliable. avg_cost_paise
-- (BIGINT) alone isn't a safe substitute either -- many consecutive
-- movements can share the same average cost even though quantity changed
-- between them (e.g. selling from a single-cost batch never moves the
-- average), so it can't detect every race on its own. A dedicated integer
-- counter has no such ambiguity.

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS stock_version INTEGER NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.service_catalogue.stock_version IS
    'Optimistic-concurrency token for inventory stock movements (task #241). Incremented by 1 on every successful record_stock_in/record_stock_out/seed_opening_balance/record_nrv_writedown write; a movement''s compare-and-set update is guarded on the version it read, so a concurrent movement on the same item that wins the race is detected and retried instead of silently overwriting the other''s effect.';
