-- Migration 438 — a renewal keeps the service type it was created with, and a
-- blank renewal date is stored as NULL rather than fabricated
--
-- BUG 1: service_type WAS ACCEPTED AND NEVER STORED
--
--   `public.renewals` (migration 059) has no `service_type` column at all.
--   `routers/lifecycle.py::create_renewal` accepted it on `RenewalIn`, put it
--   on the row it handed straight back in the create response (so the CA saw
--   the value they typed immediately, and the row in the table right after
--   creating it), and then EXCLUDED it from the actual INSERT with a comment
--   saying so ("service_type not stored in DB (no column) -- kept in mock for
--   display"). Any reload reads the row back from the database — the GET
--   /api/lifecycle/renewals endpoint's plain `select("*")`, and
--   apps/web/app/clients/[id]/lifecycle/page.tsx's own direct PostgREST read
--   of the same table — and the column was never there to read, so the field
--   came back blank on every renewal, permanently, the moment the create
--   response left memory.
--
--   The column is added nullable with no default: `RenewalIn.service_type` is
--   `Optional[str] = None` on the API side even though the Add Renewal form
--   marks it required with an asterisk, so the schema stays as permissive as
--   the model it is fed from.
--
-- BUG 2: A BLANK RENEWAL DATE WAS FABRICATED, NEVER LEFT NULL
--
--   `renewal_date` was `NOT NULL` (migration 059), and nothing on the create
--   path made a renewal date mandatory — the Add Renewal form's "Renewal
--   Date" field carries no asterisk and no required attribute, and the
--   frontend explicitly sends `renewal_date: null` when it is left blank.
--   `create_renewal` could not store that null, so it silently substituted
--   `ist_today() + 365 days` and wrote THAT as if the CA had typed it: a date
--   exactly a year out that nobody chose, indistinguishable on screen from a
--   genuine one, sitting in `renewal_date_idx` and read by the overdue-count
--   query (`GET /dashboard`, `.lt("renewal_date", today)`) as if it meant
--   something.
--
--   The column is made nullable rather than given a real default, because a
--   renewal genuinely may not have a date yet — the CA is tracking that a
--   service needs renewing this financial year and has not fixed a date for
--   it — and inventing one is exactly the defect being fixed here. Nothing
--   downstream needs to be taught about the null: the overdue-count filters
--   already guard it (`r.get("status") == "pending" and r.get("renewal_date")
--   and r["renewal_date"] < today` in mock mode; `.lt("renewal_date", today)`
--   in Postgres, where NULL < anything is UNKNOWN and the row is correctly
--   excluded rather than counted as overdue), and the two list/detail screens
--   already render a missing date as "--" (`formatDate`'s own `if (!d) return
--   "--"`). No other reader in this codebase assumes `renewal_date` is
--   present (checked: `grep -rn renewal_date apps/api apps/web`).
--
-- Both columns are widened, not narrowed, so this is safe against every row
-- already in the table: an existing `renewal_date` keeps the value it has,
-- and no row anywhere loses data.

ALTER TABLE public.renewals
  ADD COLUMN IF NOT EXISTS service_type TEXT;

ALTER TABLE public.renewals
  ALTER COLUMN renewal_date DROP NOT NULL;
