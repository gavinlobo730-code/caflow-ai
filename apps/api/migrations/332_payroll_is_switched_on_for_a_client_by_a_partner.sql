-- Migration 332: payroll is switched on for ONE CLIENT, by a PARTNER, and the
-- browser cannot switch it on at all.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THERE IS A SWITCH
-- ═══════════════════════════════════════════════════════════════════════════
-- Payroll is bundled into the subscription rather than priced per employee, and
-- docs/architecture/10-payroll.md calls the switch "the cost brake, in place of
-- a price". Three things it does, and only the first is about money:
--
--   * It keeps the marginal cost of a firm bounded by a decision somebody made,
--     rather than by how many clients happen to exist. A firm at 5,000
--     employee-months is a platform-tier conversation; today nothing would
--     surface that until the invoice.
--   * It stops payroll appearing for the clients that have none — which is most
--     of them. A CA firm with forty clients runs payroll for a handful, and a
--     screen offering to compute a payslip for a sole proprietor with no staff
--     is noise that makes the whole module look wrong.
--   * It makes "this client is a payroll client" a FACT rather than an
--     inference from whether an employee row happens to exist. The difference
--     matters at the end: a client whose payroll the firm has stopped running
--     still has Form 16s to issue and an ECR history to read, and "no longer
--     running payroll" is not the same as "never did".
--
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. WHERE IT LIVES, AND WHY NOT ITS OWN TABLE
-- ═══════════════════════════════════════════════════════════════════════════
-- On client_payroll_settings, which migration 326 created as one row per client
-- and whose own comment predicted this: "v1 item 12 adds per-client payroll
-- enablement, which belongs beside this and not in the core client record every
-- module reads."
--
-- That reasoning still holds. `clients` is read by every module in the product;
-- a payroll flag on it would be loaded by the GST return, the trial balance and
-- the client list alike, and would invite each of them to grow an opinion about
-- payroll.

BEGIN;

ALTER TABLE public.client_payroll_settings
  ADD COLUMN IF NOT EXISTS payroll_enabled    boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS payroll_enabled_by uuid REFERENCES public.users(id),
  ADD COLUMN IF NOT EXISTS payroll_enabled_on timestamptz;

COMMENT ON COLUMN public.client_payroll_settings.payroll_enabled IS
    'Whether this firm runs payroll for this client. FALSE, or no row at all, '
    'blocks every payroll WRITE for the client — creating an employee, a run, '
    'attendance, earnings, a salary revision. Reads are deliberately NOT '
    'blocked: a client whose payroll the firm has stopped running still has '
    'Form 16s to issue and an ECR history somebody may have to answer for. '
    'Only a Partner can change it, and only through the API — see section 3. '
    'Migration 332, payroll v1 item 12.';

COMMENT ON COLUMN public.client_payroll_settings.payroll_enabled_by IS
    'The internal users.id of the Partner who last switched payroll on or off '
    'for this client — NOT the Supabase auth id. NULL on a row backfilled by '
    'migration 332, because nobody made that decision explicitly.';

COMMENT ON COLUMN public.client_payroll_settings.payroll_enabled_on IS
    'When payroll was last switched on or off for this client, in UTC.';

-- ═══════════════════════════════════════════════════════════════════════════
-- 2. THE BACKFILL, AND WHY IT IS NOT "EVERYBODY" OR "NOBODY"
-- ═══════════════════════════════════════════════════════════════════════════
-- DEFAULT false is right for a client created tomorrow and WRONG for one whose
-- payroll this firm already runs. Shipping the default alone would switch
-- payroll off for every live client at once — the runs stay readable, but the
-- next month cannot be created, and nothing on screen would say why.
--
-- So: every client that already has a payroll EMPLOYEE or a payroll RUN is
-- enabled. That is not a guess. An employee row is the provisioning act this
-- switch exists to gate, and a run is proof somebody has already been paid; a
-- client with either is demonstrably one the firm runs payroll for, and the
-- decision was made — just not recorded, because there was nowhere to record it.
--
-- payroll_enabled_by stays NULL on these rows, deliberately, exactly as
-- migration 326 left attendance.entered_by NULL: the honest answer to "which
-- Partner decided this" is that nobody did, and stamping a user id would be
-- asserting an authorship that did not happen.
--
-- A row is INSERTED where the client has none, because client_payroll_settings
-- is sparse — migration 326 created it for the input cut-off, which most
-- clients have never set.

INSERT INTO public.client_payroll_settings (firm_id, client_id, payroll_enabled)
SELECT DISTINCT c.firm_id, c.id, true
FROM public.clients c
WHERE (EXISTS (SELECT 1 FROM public.payroll_employees e
               WHERE e.client_id = c.id AND e.firm_id = c.firm_id)
       OR EXISTS (SELECT 1 FROM public.payroll_runs r
                  WHERE r.client_id = c.id AND r.firm_id = c.firm_id))
  AND NOT EXISTS (SELECT 1 FROM public.client_payroll_settings s
                  WHERE s.client_id = c.id AND s.firm_id = c.firm_id);

UPDATE public.client_payroll_settings s
SET payroll_enabled = true
WHERE s.payroll_enabled = false
  AND (EXISTS (SELECT 1 FROM public.payroll_employees e
               WHERE e.client_id = s.client_id AND e.firm_id = s.firm_id)
       OR EXISTS (SELECT 1 FROM public.payroll_runs r
                  WHERE r.client_id = s.client_id AND r.firm_id = s.firm_id));

-- ═══════════════════════════════════════════════════════════════════════════
-- 3. THE BROWSER CANNOT WRITE THIS COLUMN. AT ALL.
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 326 gave client_payroll_settings Manager+ RESTRICTIVE policies,
-- because a Manager legitimately agrees an input cut-off with a client. But
-- enablement is a Partner decision — it is what the firm is charged for and what
-- decides whether a client is a payroll client at all — and RLS cannot say
-- "Manager may write these columns and not that one". A policy is per ROW.
--
-- Column privileges can. So the table-level grants are replaced by column-level
-- ones that simply omit the three enablement columns, and `authenticated` — the
-- role every PostgREST request runs as — can no longer name them in an INSERT or
-- an UPDATE. Not "is filtered out": the statement is REFUSED, with
-- `permission denied for column payroll_enabled`.
--
-- REVOKE FIRST, THEN GRANT THE REST. This order is not stylistic. PostgreSQL
-- holds table-level and column-level privileges separately, and a table-level
-- UPDATE grant already covers every column — so REVOKE UPDATE (payroll_enabled)
-- against a role holding the table-level grant does NOT take the column away.
-- The table-level privilege has to go first.
--
-- INSERT is granted on the other columns only, so a row inserted from the
-- browser takes payroll_enabled's DEFAULT false. That is the correct outcome:
-- a Manager setting a cut-off for a new client does not thereby switch payroll
-- on for them.
--
-- The API keeps writing it, because it runs as service_role, whose grants are
-- untouched. rbac("payroll", "enable") is Partner-only (core/permissions.py) and
-- is the single door.

REVOKE INSERT, UPDATE ON public.client_payroll_settings FROM authenticated;

GRANT INSERT (id, firm_id, client_id, inputs_due_day, note, updated_by,
              created_at, updated_at)
  ON public.client_payroll_settings TO authenticated;

GRANT UPDATE (inputs_due_day, note, updated_by, updated_at)
  ON public.client_payroll_settings TO authenticated;

-- SELECT and DELETE are unchanged: reading the flag is how a screen knows to
-- offer payroll at all, and DELETE was already Manager+ by policy. Deleting the
-- settings row switches payroll off by removing the record of it having been
-- switched on, which is the same answer as false and needs no separate rule.

COMMIT;
