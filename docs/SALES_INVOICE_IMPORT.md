# Sales Invoice Bulk Import (CSV / XLSX)

Lets a CA firm onboard a client's existing sales invoices in bulk instead of
re-keying them one at a time. Built for the first-firm trial, where a client may
arrive with hundreds or thousands of historical invoices (often exported from
Tally / Excel).

## Where it lives

Client workspace → **Sales → Sales Invoices** tab → **Import** button
(next to **New Invoice**).

## How it works (and why it's safe)

The importer does **not** create invoices by a parallel code path. It maps the
uploaded rows onto the *exact same* `POST /api/sales-invoices/` payload the
manual "New Invoice" form uses, then calls that endpoint once per invoice. So all
existing server-side rules apply unchanged — GST computation, paise arithmetic,
invoice numbering, RLS / authorization, and draft status. Imported invoices land
as **drafts**; nothing is issued or submitted automatically.

Pipeline:

1. **Template** — user downloads a CSV or XLSX template (column headers + a hint row).
2. **Upload** — user uploads a filled `.csv`, `.xlsx`, or `.xls` file. XLSX is parsed
   client-side (first sheet) into CSV text, so both formats run through one pipeline.
3. **Validate** — required columns, `YYYY-MM-DD` dates, positive quantity, numeric
   rate / GST, and that each customer already exists for the client.
4. **Preview** — a table shows every row with a per-row status. Rows with errors are
   highlighted and **skipped**; only valid rows import. The user can re-upload a
   corrected file before committing.
5. **Import** — each invoice is created via the existing endpoint. A final report
   lists how many rows imported and the reason for every failure.

Pure mapping/validation lives in
[`apps/web/lib/invoices/importMapping.ts`](../apps/web/lib/invoices/importMapping.ts)
(`buildSalesInvoices`) and is unit-tested in `importMapping.test.ts`.
The generic upload/preview UI is
[`apps/web/components/CsvImportModal.tsx`](../apps/web/components/CsvImportModal.tsx).

## Template columns

| Column              | Required | Notes                                                                 |
|---------------------|----------|-----------------------------------------------------------------------|
| `customer`          | Yes      | Existing customer **name** (must already exist for this client).      |
| `invoice_date`      | Yes      | `YYYY-MM-DD`.                                                          |
| `due_date`          | No       | `YYYY-MM-DD`.                                                          |
| `supply_state_code` | No       | 2-digit GST state code, e.g. `27`.                                    |
| `invoice_ref`       | No       | Share one ref across rows to group them into a single multi-line invoice. |
| `description`       | Yes      | Line-item description.                                                 |
| `hsn_sac`           | No       | HSN or SAC code.                                                       |
| `quantity`          | Yes      | Positive number, e.g. `1`.                                            |
| `rate`              | Yes      | Per-unit rate in **rupees**, e.g. `1500.00`.                          |
| `gst_rate`          | Yes      | GST percent, e.g. `18` for 18%.                                       |

### Grouping rows into multi-line invoices

Each row is one invoice line. Rows that share the same `invoice_ref` are combined
into a single invoice with multiple lines (the row's `customer`, `invoice_date`,
`due_date`, and `supply_state_code` are taken from the first row of the group, and a
ref reused across two different customers is rejected). If `invoice_ref` is blank,
rows are grouped by `customer` + `invoice_date`.

### Units

The mapper converts to the backend's integer representation — never floats:

- `rate` (rupees) → `rate_paise` = `round(rate × 100)`
- `gst_rate` (percent) → `gst_rate_bps` = `round(percent × 100)` (basis points)

## Validation rules

A row is reported and **skipped** (not imported) when:

- the customer name doesn't match an existing active customer for the client;
- `invoice_date` (or a non-empty `due_date`) is not `YYYY-MM-DD`;
- `description` is blank;
- `quantity` is not a positive number;
- `rate` or `gst_rate` is not a non-negative number;
- an `invoice_ref` is used with more than one customer.

Valid rows still import even if other rows fail — the failures are listed by row
number / invoice in the final report.

## Scale

Designed for hundreds-to-thousands of rows. Parsing and grouping happen in the
browser in one pass; invoices are then created sequentially through the existing
API so server-side rules and rate limits are respected. Customers must be created
first (use the Customers tab or its own importer) since invoices reference them by
name.

## Tests

```bash
cd apps/web
node --experimental-strip-types --test lib/invoices/importMapping.test.ts
```

Covers paise/bps conversion, ref grouping, separate-invoice splitting, unknown-customer
skip, bad date/amount reporting, and ref-reused-across-customers rejection.
