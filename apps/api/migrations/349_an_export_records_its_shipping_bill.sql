-- 349: the shipping bill an export invoice is refunded against.
--
-- WHY
--   domain/gst/gstr1_builder._build_exp built GSTR-1 Table 6A with
--
--       "sbpcode": "", "sbnum": "", "sbdt": ""
--
--   as LITERALS, because client_sales_invoices had nowhere to record them —
--   grep over migrations/, models/ and services/ for shipping_bill or
--   port_code found nothing at all. So every export this software has ever
--   prepared declared an empty shipping bill, and no CA could have filled it
--   in, because there was no field.
--
--   For an export made ON PAYMENT of IGST that is not cosmetic. CGST Rule
--   96(1) makes the shipping bill itself the application for refund of the
--   tax, and the refund is granted by MATCHING the Table 6A entry against
--   what ICEGATE holds for that shipping bill. With no number and no date
--   there is nothing to match, and the refund does not arrive.
--
--   For an export under an LUT or bond (Rule 89) the refund is claimed by a
--   separate application, so the consequence is smaller — but the portal
--   fields are the same fields and the CA still has to be able to record what
--   the customs house issued.
--
-- WHAT THE COLUMNS ARE
--   shipping_bill_no    the number customs issued. TEXT, not a number: it is
--                       an identifier and leading zeroes are real.
--   shipping_bill_date  DATE. GSTN wants DD-MM-YYYY; the conversion belongs at
--                       the payload boundary, exactly as money is stored in
--                       paise and converted to rupees only for the statutory
--                       payload (CLAUDE.md).
--   port_code           the ICEGATE port code — six characters, "INMAA1"
--                       shape. GSTN calls it sbpcode.
--
-- WHY NO CHECK ON THE FORMAT
--   The port-code list is ICEGATE's and changes as ports are added; a regex
--   written from memory here would refuse a real port and there would be no
--   way round it. The shape is validated where a human TYPES it, the same
--   split this codebase already uses for GSTIN (domain/gst/gstin.py enforced
--   at the keyboard, models.client.validate_gstin deliberately not).
--
-- WHAT HAPPENS WITH NO VALUE
--   The invoice still builds and still files. An export WITH PAYMENT that has
--   no shipping bill recorded is reported as a payload GAP — named on the
--   screen beside the return — rather than filed with three empty strings and
--   no mention. That is the direction this codebase takes everywhere: refuse
--   to pretend, and say what is missing.
--
-- BLAST RADIUS
--   Three nullable columns, no default, no backfill. Nothing existing changes
--   shape. Production holds no export invoices today, so no live return moves.

BEGIN;

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS shipping_bill_no   TEXT,
  ADD COLUMN IF NOT EXISTS shipping_bill_date DATE,
  ADD COLUMN IF NOT EXISTS port_code          TEXT;

COMMENT ON COLUMN public.client_sales_invoices.shipping_bill_no IS
  'Shipping bill number issued by customs, for GSTR-1 Table 6A (GSTN sbnum). '
  'CGST Rule 96(1) makes the shipping bill the application for refund of IGST '
  'paid on an export, matched against ICEGATE — so an export with payment and '
  'no shipping bill recorded gets no refund. NULL means not yet recorded, '
  'which is reported as a payload gap rather than filed as an empty string.';

COMMENT ON COLUMN public.client_sales_invoices.shipping_bill_date IS
  'Date on the shipping bill (GSTN sbdt, sent as DD-MM-YYYY). Stored as a DATE '
  'and formatted only at the statutory payload boundary.';

COMMENT ON COLUMN public.client_sales_invoices.port_code IS
  'ICEGATE port code for the export, six characters (e.g. INMAA1) — GSTN '
  'sbpcode. Deliberately not CHECK-constrained: the list is ICEGATE''s and '
  'grows, and a pattern written from memory here would refuse a real port with '
  'no way round it.';

COMMIT;
