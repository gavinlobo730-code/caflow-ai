-- 437 — a timeline event's financial_year is the DOCUMENT's, not the day it
-- was written
--
-- WHAT IS WRONG
--
--   `client_timeline_events.financial_year` is read directly by
--   `apps/web/components/ClientTimeline.tsx` (a
--   `financial_year=eq.XXXX-YY` PostgREST filter, straight over the browser's
--   second data path — CLAUDE.md's "The frontend's second data path"), so the
--   Overview screen's Activity feed is only as correct as this column.
--
--   Before commit 972cb98 (24-09-2026), `routers/sales_invoices.py` and
--   `routers/purchase_bills.py` stamped the `invoice_posted`/`bill_posted`
--   timeline event with whatever `ist_fy_label()` answered AT THE MOMENT the
--   event was WRITTEN — the FY the invoice/bill was POSTED in, not the FY its
--   own `invoice_date`/`bill_date` actually falls in. A document dated in
--   FY 2025-26 but entered (posted) in July 2026 — a late entry, a Tally
--   migration, a backdated correction — was stamped "2026-27": filtering the
--   Activity feed to FY 2025-26 hides it, and filtering to FY 2026-27 shows a
--   document that FY never contained. The two routers now stamp
--   `ist_fy_label(invoice_date)` / `ist_fy_label(bill_date)` (the document's
--   own date), which is right; this migration is the one-off correction for
--   every row written before that changed.
--
-- WHAT THIS DOES
--
--   For every `client_timeline_events` row of event_type `invoice_posted`
--   (entity_type `sales_invoice`) or `bill_posted` (entity_type
--   `purchase_bill`), recompute the Indian financial-year label (1 April —
--   31 March, "YYYY-YY") from the underlying document's own
--   `invoice_date`/`bill_date` and update the row only where the stored
--   label DISAGREES with it (`IS DISTINCT FROM`). A row already correct —
--   every event written since 972cb98, and any event whose posting month and
--   document date happen to share an FY — is left untouched and this UPDATE
--   affects zero of them.
--
--   The label is computed in SQL with the identical rule
--   `core/ist_clock.ist_fy_label` uses (month >= 4 -> that calendar year
--   starts the FY; else the year before does), because no SQL helper for it
--   already exists in this migration history (checked: no `fy_label` or
--   FY-arithmetic function is defined anywhere under migrations/) — see
--   `core/ist_clock.py::ist_fy_label` for the Python original this mirrors.
--
--   `entity_id` is joined directly against each table's own `id`, both uuid
--   — CHECKED BY NUMBER rather than assumed from migration 045's original
--   design (which also declared it uuid): migration 187 later added it as
--   plain TEXT to match what was actually live, and migration 293 (Group C)
--   is the migration that LAST touched its type, converting it back to uuid
--   ("client_timeline_events.entity_id: text -> uuid ... every one of the
--   68,592 non-null values ... is a well-formed UUID"). 293 postdates 187 and
--   nothing after 293 touches it again, so uuid is what the column actually
--   is today and no text cast is needed on either side of the join.
--
-- WHAT THIS DELIBERATELY DOES NOT DO
--
--   It touches ONLY these two (event_type, entity_type) pairs. Every other
--   event_type this table carries (compliance escalations, document
--   uploads, payroll runs, and so on) is stamped from a different date
--   entirely — most have no underlying dated "document" this migration could
--   even ask about — and is out of scope for this specific defect.
--
--   It does not touch a soft-deleted row (`deleted_at`) specially: a
--   deleted event is not rendered by the Activity feed either way, and
--   correcting its `financial_year` for consistency (rather than leaving a
--   stale value on a row nobody reads) is harmless and simpler than carving
--   out an exception.
--
--   It never widens `client_sales_invoices`/`purchase_bills` to rows the
--   timeline event does not already reference — the join is driven by
--   `entity_id`, so a document with no timeline event (there is always
--   exactly one per issued invoice/received bill — see the two routers'
--   single `log_timeline_event` call sites) contributes nothing here.
--
-- IDEMPOTENT. The `IS DISTINCT FROM` guard means a second run touches zero
-- rows — recomputing the same label from the same immutable invoice_date/
-- bill_date always agrees with what the first run already wrote. It is also
-- SCOPED: any row the two routers write correctly from now on already
-- matches its own document's date and is never touched.
--
-- ⚠️ NOT APPLIED AGAINST A REAL DATABASE IN THIS CHANGE. HARNESS_PG needs a
-- live Postgres 16 + `psql`, neither of which this sandbox could safely
-- provide (see the commit message this migration ships with). The SQL below
-- was checked by hand against `core.ist_clock.ist_fy_label`'s own worked
-- examples (1 April boundary, a normal mid-year date, and the century-
-- rollover LPAD case) rather than run.

BEGIN;

-- Sales invoices: correct financial_year to the invoice's OWN invoice_date.
UPDATE client_timeline_events e
SET financial_year = doc.correct_fy
FROM (
  SELECT
    i.id,
    CASE
      WHEN EXTRACT(MONTH FROM i.invoice_date)::int >= 4
        THEN EXTRACT(YEAR FROM i.invoice_date)::int::text
             || '-' ||
             LPAD(((EXTRACT(YEAR FROM i.invoice_date)::int + 1) % 100)::text, 2, '0')
      ELSE (EXTRACT(YEAR FROM i.invoice_date)::int - 1)::text
             || '-' ||
             LPAD((EXTRACT(YEAR FROM i.invoice_date)::int % 100)::text, 2, '0')
    END AS correct_fy
  FROM client_sales_invoices i
) doc
WHERE e.event_type = 'invoice_posted'
  AND e.entity_type = 'sales_invoice'
  AND e.entity_id = doc.id
  AND e.financial_year IS DISTINCT FROM doc.correct_fy;

-- Purchase bills: correct financial_year to the bill's OWN bill_date.
UPDATE client_timeline_events e
SET financial_year = doc.correct_fy
FROM (
  SELECT
    b.id,
    CASE
      WHEN EXTRACT(MONTH FROM b.bill_date)::int >= 4
        THEN EXTRACT(YEAR FROM b.bill_date)::int::text
             || '-' ||
             LPAD(((EXTRACT(YEAR FROM b.bill_date)::int + 1) % 100)::text, 2, '0')
      ELSE (EXTRACT(YEAR FROM b.bill_date)::int - 1)::text
             || '-' ||
             LPAD((EXTRACT(YEAR FROM b.bill_date)::int % 100)::text, 2, '0')
    END AS correct_fy
  FROM purchase_bills b
) doc
WHERE e.event_type = 'bill_posted'
  AND e.entity_type = 'purchase_bill'
  AND e.entity_id = doc.id
  AND e.financial_year IS DISTINCT FROM doc.correct_fy;

COMMIT;
