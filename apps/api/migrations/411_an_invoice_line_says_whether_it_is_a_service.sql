-- 411 — A SALES INVOICE LINE SAYS WHETHER IT IS A SERVICE, AND UNTIL NOW IT COULD NOT.
--
-- `models/invoices.InvoiceLineIn` and `SalesInvoiceLineIn` have both declared
-- `is_service: bool = False` since they were written, and
-- `client_sales_invoice_lines` has no such column — so a caller set it, Pydantic
-- validated it, and the create path dropped it on the floor. A field offered and
-- silently discarded is the shape this repository keeps finding (the team grid's
-- localStorage toggles, `invoice_templates`, `account_group_mappings`).
--
-- WHY IT MATTERS RATHER THAN BEING TIDINESS
--
--   The e-invoice portal's own item validations turn on it, and
--   `domain/gst/irp_validations.NOT_HELD` names TWO refusals that exist only
--   because this column does not:
--
--     "If Is Service is selected, then the HSN codes must belong to services."
--     "Quantity and Unit Quantity Code are mandatory for Goods and optional
--      for Services."
--
--   (Generate IRN API, "Validations on Items", committed under
--   docs/compliance/sources/e-invoice/.) Without the column, a service line
--   with no quantity and no UQC is indistinguishable from a goods line missing
--   both, so the rule cannot be asked at all — and CGST Rule 46(h) requires the
--   quantity and unit on a supply OF GOODS and not on a service.
--
--   The sibling tables already carry it: migration 392 gave quotations,
--   proforma invoices and sales orders `is_service NOT NULL DEFAULT false`, and
--   393 did the same on the purchase side. The tax invoice — the one document
--   of the six that the Act actually knows — was the one without it.
--
-- NULLABLE, NO DEFAULT, NO BACKFILL — AND THAT DIFFERS FROM 392 ON PURPOSE.
--
--   392's tables were NEW, so every row in them was written by a door that sets
--   the value and `false` is a real answer there. Every row already in
--   `client_sales_invoice_lines` predates the column, so `false` would not be a
--   recorded fact — it would be this migration asserting that every line ever
--   raised was a supply of goods. On a practice whose clients are mostly
--   professionals that is the wrong assertion on nearly every row, and the
--   first rule to read it would then report a UQC gap on all of them.
--
--   NULL is the third state and means nobody has said, the same shape as
--   `vendors.gst_registration_status` (388) and `fixed_assets.rule_43_use`
--   (372). `domain/gst/irp_validations` reports it as unrecorded rather than
--   guessing, because one guess demands a quantity the Act does not ask for and
--   the other waives one it does.
--
-- NOTHING IS COMPUTED FROM IT AND NO TAX MOVES. The GST on a line comes from
-- its own rate through `domain/sales/line_tax`, which does not and must not
-- read this; whether a supply is of goods or services changes the place-of-
-- supply RULES (IGST §§10-13) and this column is not wired to those, because
-- that is a statutory question about the transaction rather than a label on a
-- line. A test asserts `line_tax` never mentions it.

ALTER TABLE public.client_sales_invoice_lines
  ADD COLUMN IF NOT EXISTS is_service BOOLEAN;

COMMENT ON COLUMN public.client_sales_invoice_lines.is_service IS
  'Whether this line is a supply of SERVICES. NULLABLE with no default and no '
  'backfill: every row predating migration 411 was written with no such field, '
  'so false would assert it was goods rather than record what somebody said. '
  'NULL means unrecorded and is reported as a gap, never guessed — the e-invoice '
  'portal makes quantity and UQC mandatory for goods and optional for services '
  '(Generate IRN API, Validations on Items), and CGST Rule 46(h) asks for them '
  'on a supply of goods. The sibling columns on migration 392''s tables are NOT '
  'NULL DEFAULT false because those tables are new and every row in them was '
  'written by a door that sets it.';
