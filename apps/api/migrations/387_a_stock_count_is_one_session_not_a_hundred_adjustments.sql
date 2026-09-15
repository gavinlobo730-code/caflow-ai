-- 387 — a physical stock count is ONE session, not a hundred adjustments
-- (INV-08).
--
-- WHAT WAS WRONG
--     `POST /api/inventory/items/{id}/adjust` takes one item per call, and the
--     screen opens its modal only from inside one item's ledger drill-down.
--     Stock-taking at 31 March produces a sheet with a hundred variances, so
--     the CA opened each item's ledger, clicked Adjust, retyped the quantity,
--     chose a reason and confirmed the s.17(5)(h) checkbox — a hundred times —
--     and the hundred journals that came out had no common reference tying
--     them to the count. Tally records the whole count in ONE Physical Stock
--     voucher and derives the variances.
--
-- WHAT IS NOT HERE, BECAUSE IT ALREADY IS
--     The count SHEET. The stock register is already exportable to CSV from
--     the Inventory tab, and `StockAdjustmentIn.reference_no` already exists
--     with the placeholder "e.g. count sheet #". The residual gap the finding
--     names is the ROUND TRIP — accepting the counted quantities back, showing
--     the variance list, and posting one batch — and that is all this adds.
--
-- TWO TABLES AND WHY THE SYSTEM QUANTITY IS ON BOTH SIDES OF TIME
--     `stock_count_lines.system_qty_units` is the figure SNAPSHOTTED when the
--     sheet was opened — what the CA was counting against. The variance that
--     is POSTED is recomputed at post time against the position as at the
--     COUNT DATE, because stock genuinely moves between opening a sheet and
--     keying it in: a 30 March purchase bill entered on 2 April changes what
--     the books say for 31 March, and the count is a fact about 31 March.
--     Posting the snapshot's variance would then re-introduce the very
--     difference the bill corrected. Where the two disagree the session SAYS
--     so rather than silently preferring one.
--
-- NOTHING IS POSTED FROM HERE
--     The session is a worksheet. Posting goes through
--     `domain/inventory_service.apply_stock_adjustment` once per varying item,
--     the same function the single-item path uses — one write path, and every
--     line carries the session's own reference so the hundred journals are
--     one count. A session that has posted is closed to editing; posting
--     again is refused rather than doubling the adjustment.
--
-- `reverse_itc` IS NULLABLE WITH NO DEFAULT, and that is the whole of
-- s.17(5)(h) in this table. Whether a shortage is credit that must be
-- reversed is a judgement only the CA can make — damaged stock might still be
-- sold at a discount — so a SHORTAGE line with no decision cannot post, and
-- says so. A surplus needs no decision: stock found is not stock lost, and
-- the single-item path has refused `reverse_itc` on an increase since it was
-- written.

CREATE TABLE IF NOT EXISTS public.stock_count_sessions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id     UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  -- The date the stock was COUNTED. Every adjustment this session posts is
  -- dated here, and the variance is measured against the position as at it.
  count_date    DATE NOT NULL,
  reference_no  TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'open'
                  CHECK (status IN ('open', 'posted', 'abandoned')),
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by    UUID REFERENCES public.users(id),
  posted_at     TIMESTAMPTZ,
  posted_by     UUID REFERENCES public.users(id),
  -- One live count per client per date. A second sheet for the same date is
  -- either a mistake or a re-count, and a re-count means abandoning the first
  -- — two open sheets would post two sets of variances for one stock-take.
  -- Narrowed to the OPEN ones so an abandoned sheet does not block a redo and
  -- a posted one stays on the record.
  CONSTRAINT stock_count_sessions_reference_not_blank CHECK (length(trim(reference_no)) > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_count_open_per_client_date
  ON public.stock_count_sessions (client_id, count_date)
  WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_stock_count_sessions_client
  ON public.stock_count_sessions (firm_id, client_id, count_date DESC);

CREATE TABLE IF NOT EXISTS public.stock_count_lines (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id     UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  session_id    UUID NOT NULL REFERENCES public.stock_count_sessions(id) ON DELETE CASCADE,
  service_catalogue_id UUID NOT NULL REFERENCES public.service_catalogue(id) ON DELETE CASCADE,

  -- What the books said when the sheet was opened. Kept so the CA can see
  -- that the books moved under them; NOT what the posted variance is measured
  -- against — see the header.
  system_qty_units  NUMERIC(10,3) NOT NULL DEFAULT 0,
  -- What was counted. NULL means NOT YET COUNTED, which is not zero: a zero
  -- count writes the whole of an item's stock off.
  counted_qty_units NUMERIC(10,3),

  -- CGST Act s.17(5)(h), per line and per the CA. NULL means not decided, and
  -- a SHORTAGE line with no decision cannot post.
  reverse_itc                 BOOLEAN,
  itc_reversal_is_interstate  BOOLEAN NOT NULL DEFAULT false,
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, service_catalogue_id)
);

CREATE INDEX IF NOT EXISTS idx_stock_count_lines_session
  ON public.stock_count_lines (session_id);

COMMENT ON COLUMN public.stock_count_lines.counted_qty_units IS
  'What the CA counted. NULL means NOT YET COUNTED and is deliberately not '
  'zero — a zero count writes the whole of an item''s stock off, which is a '
  'real answer somebody has to give.';
COMMENT ON COLUMN public.stock_count_lines.reverse_itc IS
  'CGST Act s.17(5)(h), decided by the CA per line. NULL means not decided; a '
  'shortage line with no decision is refused rather than defaulted, because '
  'damaged stock might still be sold at a discount. A surplus needs no '
  'decision — stock found is not stock lost.';

ALTER TABLE public.stock_count_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stock_count_lines    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_stock_count_sessions" ON public.stock_count_sessions;
CREATE POLICY "firm_staff_read_stock_count_sessions" ON public.stock_count_sessions
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "firm_staff_read_stock_count_lines" ON public.stock_count_lines;
CREATE POLICY "firm_staff_read_stock_count_lines" ON public.stock_count_lines
  FOR SELECT TO authenticated USING (firm_id = public.get_my_firm_id());

-- Migration 084's loop has never run again (see 370), so a table created now
-- carries only its firm-wide policy unless it says otherwise here.
DROP POLICY IF EXISTS "stock_count_sessions_assignment_scope" ON public.stock_count_sessions;
CREATE POLICY "stock_count_sessions_assignment_scope"
  ON public.stock_count_sessions AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "stock_count_lines_assignment_scope" ON public.stock_count_lines;
CREATE POLICY "stock_count_lines_assignment_scope"
  ON public.stock_count_lines AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

-- Read-only from the browser: the variance is derived and the posting runs
-- through the one adjustment path, so there is no legitimate frontend write.
GRANT SELECT ON public.stock_count_sessions TO authenticated;
GRANT SELECT ON public.stock_count_lines    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.stock_count_sessions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.stock_count_lines    TO service_role;
