# Sales Invoice Bulk Import (CSV / XLSX)

Lets a CA firm onboard a client's existing sales invoices in bulk instead of
re-keying them one at a time. Built for the first-firm trial, where a client may
arrive with hundreds or thousands of historical invoices (often exported from
Tally / Excel / QuickBooks).

## Where it lives

Client workspace → **Sales → Sales Invoices** tab → **Import** button
(next to **New Invoice**).

## How it works (and why it's safe)

The importer does **not** create invoices by a parallel code path. It maps the
uploaded rows onto the *exact same* `POST /api/sales-invoices/` payload the
manual "New Invoice" form uses, then calls that endpoint once per invoice. So all
existing server-side rules apply unchanged — GST computation, paise arithmetic,
invoice-number validation + duplicate rejection, RLS / authorization, and draft
status. Imported invoices land as **drafts**; nothing is issued or submitted
automatically.

Pipeline:

1. **Template** — user downloads a CSV or XLSX template (column headers + a hint row).
2. **Upload** — user uploads a filled `.csv`, `.xlsx`, or `.xls` file. XLSX is parsed
   client-side (first sheet) into CSV text, so both formats run through one pipeline.
3. **Resolve** — if the file references a customer or Product/Service that doesn't
   exist yet for this client, a staging step lists each one with a **"+ Add"**
   action that opens the same creation dialog used everywhere else in the app
   (`CustomerFormModal`, `ProductServiceFormModal`) right inside the import
   modal. Nothing is imported during this step. It's a courtesy, not a hard
   gate — the CA can skip ahead with names still unresolved; those rows are
   simply skipped and reported, same as any other row error. Skipped
   automatically when nothing is missing.
4. **Validate** — required columns, `YYYY-MM-DD` dates, positive quantity, numeric
   rate / GST, that each customer already exists for the client, and that a
   given `product_service` matches an existing catalogue item.
5. **Preview** — a table shows every row with a per-row status. Rows with errors are
   highlighted and **skipped**; only valid rows import. The user can re-upload a
   corrected file before committing.
6. **Import** — each invoice is created via the existing endpoint. A final report
   lists how many rows imported and the reason for every failure — including a
   duplicate `invoice_no` for this client, which the server rejects exactly as
   it would a manually typed duplicate (same check, same endpoint).

Pure mapping/validation lives in
[`apps/web/lib/invoices/importMapping.ts`](../apps/web/lib/invoices/importMapping.ts)
(`buildSalesInvoices`) and is unit-tested in `importMapping.test.ts`.
The generic upload/resolve/preview UI is
[`apps/web/components/CsvImportModal.tsx`](../apps/web/components/CsvImportModal.tsx)
(the "resolve missing references" step is an opt-in `resolvers` prop other
importers on this page don't use).

## Template columns

| Column              | Required     | Notes                                                                 |
|---------------------|--------------|-------------------------------------------------------------------------|
| `invoice_no`        | Yes          | The real invoice number (fully manual — see below). Share it across rows to group them into one multi-line invoice. |
| `customer`          | Yes          | Existing customer **name** for this client, or resolved via the "+ Add" step. |
| `invoice_date`      | Yes          | `YYYY-MM-DD`. Must match across every row sharing an `invoice_no`.       |
| `due_date`          | No           | `YYYY-MM-DD`. Must match across every row sharing an `invoice_no` (if given). |
| `supply_state_code` | No           | 2-digit GST state code, e.g. `27`. Must match across every row sharing an `invoice_no` (if given). |
| `product_service`   | No           | Existing Product/Service catalogue item name for this client, or resolved via the "+ Add" step. Pre-fills `description`/`hsn_sac`/`rate`/`gst_rate`/`unit` from the catalogue item — the row's own values still win if given. |
| `description`       | If no `product_service` | Line-item description.                                       |
| `hsn_sac`           | No           | HSN or SAC code. Overrides the `product_service`'s own if both are given. |
| `unit`              | No           | e.g. `NOS`, `HRS`, `KG`. Overrides the `product_service`'s own if both are given. |
| `quantity`          | Yes          | Positive number, e.g. `1`.                                            |
| `rate`              | If no `product_service` (or its catalogue price is unset) | Per-unit rate in **rupees**, e.g. `1500.00`. |
| `gst_rate`          | If no `product_service` (or its catalogue rate is unset) | GST percent, e.g. `18` for 18%. |

### Invoice numbering is fully manual — no Caflow-generated scheme

Sales invoice numbers are never auto-generated (Decision: the CA decides the
scheme, Caflow only validates shape — CGST Rule 46(b): ≤16 characters, letters/
digits/`-`/`/` only — and rejects a duplicate for this client). This is exactly
why `invoice_no` is now required on import: it's the CA's real invoice number
from their previous system (Tally / QuickBooks / Excel), preserved as-is —
*not* re-numbered into a new Caflow series. A blank `invoice_no` is a row
error, not a fallback to auto-numbering.

### Grouping rows into multi-line invoices

Each row is one invoice line. Rows that share the same `invoice_no` are
combined into a single invoice with multiple lines. `customer`, `invoice_date`,
`due_date`, and `supply_state_code` must be identical across every row sharing
an `invoice_no` — the first row establishes them, and a later row that
disagrees on any of them is reported and skipped (the rest of that invoice's
rows still import; this mirrors the existing "reused with a different
customer" rejection, extended to the other header fields).

### Units

The mapper converts to the backend's integer representation — never floats:

- `rate` (rupees) → `rate_paise` = `round(rate × 100)`
- `gst_rate` (percent) → `gst_rate_bps` = `round(percent × 100)` (basis points)

## Validation rules

A row is reported and **skipped** (not imported) when:

- `invoice_no` is blank;
- the customer name doesn't match an existing active customer for the client;
- a given `product_service` doesn't match an existing catalogue item for the client;
- `invoice_date` (or a non-empty `due_date`) is not `YYYY-MM-DD`;
- `description` is blank and no `product_service` supplies one;
- `quantity` is not a positive number;
- `rate` or `gst_rate` is not a non-negative number and no `product_service`
  supplies a default for it;
- an `invoice_no` is reused with a different `customer`, `invoice_date`,
  `due_date`, or `supply_state_code` than the row that first established it.

Valid rows still import even if other rows fail — the failures are listed by row
number / invoice in the final report, including any server-side rejection (e.g.
a duplicate `invoice_no` for this client).

## Scale

Designed for hundreds-to-thousands of rows. Parsing and grouping happen in the
browser in one pass; invoices are then created sequentially through the existing
API so server-side rules and rate limits are respected. Customers and Products/
Services can be created inline via the Resolve step, or ahead of time via their
own tabs/importers.

## Tests

```bash
cd apps/web
node --experimental-strip-types --test lib/invoices/importMapping.test.ts
```

Covers paise/bps conversion, invoice_no grouping, separate-invoice splitting,
unknown-customer/unknown-product skip, bad date/amount reporting,
product_service pre-fill + override, and invoice_no reused with a mismatched
customer/date/due_date/supply_state_code.
