-- 462: job work comes back in LOTS, and FORM GST ITC-04 reports each return (GST-30).
--
-- WHY
--   `delivery_challans` (392) records ONE fact about the goods coming back:
--   `received_back_on`, a single date for the whole challan. Job work is
--   routinely returned in lots — half the castings in March, the rest in May —
--   and CGST Rule 45(3)'s FORM GST ITC-04 is built around exactly that: a row
--   per return, against the ORIGINAL challan, carrying the challan the job
--   worker issued on the way back and the nature of the work done. One column
--   could not hold "one challan sent, part returned", and it also meant the
--   s.143 clock could only be stopped for all of a challan or none of it.
--
--   Section 143(3) deems inputs "not received back" within one year to have been
--   supplied on the day they were sent out. Where part has come back, the clock
--   is still the challan's — the day the goods LEFT does not move — and what a
--   part return reduces is the amount left to be deemed supplied. So the return
--   is recorded against the challan LINE, which is also the grain the form asks
--   for (description, unit, quantity).
--
-- WHAT IS STORED, AND WHAT IS DELIBERATELY NOT
--   Stored: the quantity that came back, on what date, under which challan of the
--   job worker's, the nature of the work, and the quantity lost or wasted.
--   NOT stored: what is still outstanding. That is the line's quantity less the
--   sum of its returns, and a stored balance is wrong the moment a return is
--   corrected — migration 278's reasoning, applied to a quantity. It is derived
--   on every read by domain/gst/itc_04.py.
--
--   `quantity_lost_or_wasted` is recorded because the form has a column for it and
--   is NEVER subtracted from the outstanding balance: whether scrap counts as
--   "received back" for s.143 is a judgement this product does not take, and the
--   larger balance is the direction that cannot hide a deemed supply.
--
--   `job_worker_challan_no`, `job_worker_challan_date` and `nature_of_job_work` are
--   NULLABLE with no default, because a return recorded from a bare "the goods
--   are back" is a fact worth keeping before the job worker's paperwork is in
--   hand. The statement NAMES each one that is missing rather than printing a
--   blank into a column the form asks for.
--
-- WHAT THIS DOES NOT DO
--   It does not touch `received_back_on` or `delivery_challans.status`. The API,
--   which records the return, stamps `received_back_on` itself when the returns
--   have brought EVERY line back to nil, through the one existing write
--   (`record_goods_back`), so the legacy whole-challan path and this one stop the
--   clock the same way. No trigger does it: a quiet side effect on a statutory
--   clock is the kind of thing worth being able to read in Python.
--   It does not back-fill anything: a challan already marked received back keeps
--   its single date, and ITC-04 reports it as a whole-challan return and says the
--   particulars are not held.
--
-- ISOLATION, IN THE SHAPE 392 ESTABLISHED
--   firm-scoped SELECT for `authenticated`, writes only through the API (the
--   service role), and a RESTRICTIVE <table>_assignment_scope policy because the
--   table carries client_id and migration 084's one-shot loop has never run again
--   (see 370) — without it a Manager assigned to client A could read client B's
--   job-work movements over PostgREST. FOR ALL, with USING and WITH CHECK, and
--   can_access_client(client_id::text), held from the migration text by
--   tests/test_a_client_table_a_migration_creates_is_assignment_scoped.py and
--   from a real database by tests/test_job_work_returns_pg.py.
--
-- ADDITIVE AND IDEMPOTENT. One new table; no existing row, column, function or
-- policy is touched.

BEGIN;

CREATE TABLE IF NOT EXISTS public.delivery_challan_returns (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  challan_id               UUID NOT NULL REFERENCES public.delivery_challans(id)      ON DELETE CASCADE,
  challan_line_id          UUID NOT NULL REFERENCES public.delivery_challan_lines(id) ON DELETE CASCADE,

  returned_on              DATE NOT NULL,
  -- NUMERIC(10,3), the column every quantity in this schema is (050, 188, 210).
  quantity_returned        NUMERIC(10,3) NOT NULL DEFAULT 0
                             CHECK (quantity_returned >= 0),
  quantity_lost_or_wasted  NUMERIC(10,3) NOT NULL DEFAULT 0
                             CHECK (quantity_lost_or_wasted >= 0),

  -- ITC-04 Table 5A's own columns. NULL is "not recorded", never "none".
  job_worker_challan_no    TEXT,
  job_worker_challan_date  DATE,
  nature_of_job_work       TEXT,
  notes                    TEXT,

  created_by               UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- A return that returns nothing and wastes nothing records nothing.
  CONSTRAINT delivery_challan_returns_something_moved
    CHECK (quantity_returned > 0 OR quantity_lost_or_wasted > 0),
  CONSTRAINT delivery_challan_returns_job_worker_challan_no_not_blank
    CHECK (job_worker_challan_no IS NULL OR length(trim(job_worker_challan_no)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_delivery_challan_returns_challan
  ON public.delivery_challan_returns (challan_id);
CREATE INDEX IF NOT EXISTS idx_delivery_challan_returns_line
  ON public.delivery_challan_returns (challan_line_id);
-- The statement reads a window of returns for one client.
CREATE INDEX IF NOT EXISTS idx_delivery_challan_returns_client_date
  ON public.delivery_challan_returns (firm_id, client_id, returned_on);

COMMENT ON TABLE public.delivery_challan_returns IS
  'One row per return of goods sent for job work, against the challan line they '
  'were sent on (CGST Rule 45(3), FORM GST ITC-04 Table 5A). What is still '
  'outstanding is DERIVED (line quantity less returns) and never stored. Lost or '
  'wasted quantity is recorded and never subtracted from the balance. '
  'domain/gst/itc_04.py is the authority. Migration 462.';
COMMENT ON COLUMN public.delivery_challan_returns.quantity_lost_or_wasted IS
  'Losses and wastes as the form asks for them. NOT subtracted from what is '
  'outstanding: whether scrap counts as received back for CGST s.143 is not a '
  'judgement this product takes, and the larger balance cannot hide a deemed supply.';
COMMENT ON COLUMN public.delivery_challan_returns.job_worker_challan_no IS
  'The challan the JOB WORKER issued when the goods came back. NULL means not '
  'recorded; the ITC-04 statement names every return missing one.';

ALTER TABLE public.delivery_challan_returns ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_staff_read_delivery_challan_returns"
  ON public.delivery_challan_returns;
CREATE POLICY "firm_staff_read_delivery_challan_returns"
  ON public.delivery_challan_returns
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id());

DROP POLICY IF EXISTS "delivery_challan_returns_assignment_scope"
  ON public.delivery_challan_returns;
CREATE POLICY "delivery_challan_returns_assignment_scope"
  ON public.delivery_challan_returns
  AS RESTRICTIVE FOR ALL
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

GRANT SELECT ON public.delivery_challan_returns TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.delivery_challan_returns TO service_role;

COMMIT;
