# Bulk Import (CSV / XLSX) — Client Workspace

Lets a CA firm onboard a client's existing records in bulk instead of re-keying
them one at a time. Built for the first-firm trial, where a client typically
arrives with hundreds/thousands of historical records (often exported from Tally
or kept in Excel).

## What can be imported

| Entity | Where | Endpoint (reused) | References |
|--------|-------|-------------------|------------|
| **Sales Invoices** | Sales → Sales Invoices | `POST /api/sales-invoices/` | Customer (by name) |
| **Customers** | Sales → Customers | `POST /api/customers/` | — |
| **Receipts** | Sales → Receipts | `POST /api/receipts/` | Customer (by name) |
| **Vendors** | Purchases → Vendors | `POST /api/vendors/` | — |
| **Purchase Bills** | Purchases → Purchase Bills | `POST /api/purchase-bills/` | Vendor (by name) |
| **Employees** | Payroll → Employees | `POST /api/payroll/employees` | — |
| **Sales Credit Notes** | Sales → Credit Notes | `POST /api/credit-notes/` | Customer (by name), Sales Invoice (by number, optional) |
| **Sales Debit Notes** | Sales → Debit Notes | `POST /api/sales-debit-notes/` | Customer (by name), Sales Invoice (by number, optional) |
| **Purchase Debit Notes** | Purchases → Debit Notes | `POST /api/debit-notes/` | Vendor (by name), Purchase Bill (by number, optional) |
| **Purchase Credit Notes** | Purchases → Credit Notes | `POST /api/purchase-credit-notes/` | Vendor (by name), Purchase Bill (by number, optional) |

Each appears as an **Import** button next to the entity's "New / Add" button.

## How it works (and why it's safe)

Importers do **not** create records by a parallel code path. Each maps the
uploaded rows onto the *exact same* payload the manual form already posts, then
calls that existing endpoint once per record. So all server-side rules apply
unchanged — GST computation, integer-paise arithmetic, numbering, RLS /
authorization, TDS, draft status. Invoices and bills land as **drafts**; nothing
is issued or submitted automatically.

Pipeline (shared `CsvImportModal`):

1. **Template** — download a CSV or XLSX template (headers + a hint row).
2. **Upload** — `.csv`, `.xlsx`, or `.xls`. Excel is parsed client-side (first
   sheet) into CSV text, so both formats run through one pipeline.
3. **Validate** — required columns + per-entity rules (dates, amounts, formats,
   name → id lookups).
4. **Preview** — every row shown with a per-row status. Rows with errors are
   highlighted and **skipped**; the user can re-upload a corrected file.
5. **Import** — records created via the existing endpoint; a final report lists
   how many imported and the reason for every failure.

Pure mapping/validation lives in
[`apps/web/lib/imports/mappers.ts`](../apps/web/lib/imports/mappers.ts)
(`buildCustomers`, `buildVendors`, `buildPurchaseBills`, `buildReceipts`,
`buildEmployees`) — unit-tested in `imports.test.ts`. Sales invoices use the
earlier `lib/invoices/importMapping.ts`. The generic upload/preview UI is
[`apps/web/components/CsvImportModal.tsx`](../apps/web/components/CsvImportModal.tsx).

## Units (everywhere)

- Rupees → **integer paise** (`round(₹ × 100)`) — never float.
- Percent → **basis points** (`round(% × 100)`), e.g. GST `18` → `1800`, TDS `2` → `200`.
- Booleans accept `yes / y / true / 1` (case-insensitive).

## Order of import (because of references)

Some records reference others by **name**, so import the referenced entity first:

1. **Customers** and **Vendors** (no references) →
2. **Sales Invoices** / **Receipts** (need customers) and **Purchase Bills** (need vendors) →
3. **Credit & Debit Notes** (need customers/vendors; a linked Invoice No/Bill No is optional but recommended — see below).

Unknown names are reported per-row and skipped, never silently created.

---

## Column reference

### Customers
`name`* · `gstin` · `state_code` (auto-derived from GSTIN if blank) · `pan` ·
`email` · `phone` · `city` · `state` · `opening_balance` (₹) · `credit_days` (default 30).
GSTIN/PAN format-validated when present; duplicate names within the file are skipped.

### Vendors
`name`* · `gstin` · `pan` · `email` · `phone` · `tds_applicable` (yes/no) ·
`tds_section` (194C/194I/194J/194H/194A) · `tds_rate` (%) · `opening_balance` (₹).
When `tds_applicable` is yes, a valid section and a positive rate are required.

### Purchase Bills (multi-line)
`vendor`* · `bill_no` · `bill_date`* (YYYY-MM-DD) · `due_date` · `description`* ·
`hsn_sac` · `quantity`* · `rate`* (₹) · `gst_rate`* (%).
Rows sharing a `bill_no` group into one multi-line bill (absent a `bill_no`,
rows group by `vendor` + `bill_date`). A `bill_no` reused across two vendors is rejected.

### Receipts
`customer`* · `receipt_date`* (YYYY-MM-DD) · `amount`* (₹) ·
`payment_mode`* (bank/cash/cheque/upi/neft/rtgs) · `reference_no`.
Imports **unallocated** receipts; matching a receipt to specific invoices stays a manual step.

### Employees
`name`* · `pan` · `aadhaar` · `designation` · `department` · `basic`* (₹/month) ·
`hra_percent` (default 40) · `pf_applicable` (default yes) · `esi_applicable`
(default yes) · `pt_applicable` (default no).

**Aadhaar — privacy by design:** the template accepts the full 12-digit Aadhaar,
but PracticeSync derives and stores **only the last 4 digits** (`aadhaar_last4`).
The full number is never sent to or persisted by the backend (UIDAI norms). The
backend rejects any `aadhaar_last4` that is not exactly 4 digits.

(\* = required) — Sales-invoice columns are documented in
[`SALES_INVOICE_IMPORT.md`](./SALES_INVOICE_IMPORT.md).

### Credit & Debit Notes (Sales Credit Notes, Sales Debit Notes, Purchase Debit Notes, Purchase Credit Notes)

`customer`*/`vendor`* · `invoice_no`/`bill_no` (optional, recommended) · `credit_note_date`*/`debit_note_date`*
(YYYY-MM-DD) · `reason` · `is_interstate` (yes/no) · `is_reverse_charge` (yes/no, purchase side only) ·
`note_ref` (optional grouping key) · `product_service`* · `description` · `hsn_sac` · `quantity`* · `rate` (₹) ·
`gst_rate` (%).

Unlike Sales Invoices/Purchase Bills, **`product_service` is REQUIRED on every line, not optional** — the
shared `InvoiceLineIn`/`PurchaseBillLineIn` backend model makes `service_catalogue_id` mandatory on every
line item, so a line with no matched Product/Service is rejected at import time (this also means a
description-only Sales Invoice/Purchase Bill import row is silently invalid today — a pre-existing gap this
importer does not repeat).

Rows group into one note by `note_ref` if given, else by `invoice_no`/`bill_no`, else by
`customer`/`vendor` + note date (same fallback `purchase_bills` uses for a blank `bill_no`).

**Linking an existing Invoice No/Bill No is the only reliable way to get correct GST treatment.** When
given, the linked document's own `is_interstate` is used (the `is_interstate` column is ignored in that
case); when blank, `is_interstate` falls back to the column. This matters because the four backend
endpoints handle it inconsistently: `POST /api/credit-notes/` **always** re-derives `is_interstate` from a
linked `sales_invoice_id` and forces `false` when none is linked (so a standalone Sales Credit Note can
never be interstate via the API today); `POST /api/debit-notes/`, `POST /api/sales-debit-notes/` and
`POST /api/purchase-credit-notes/` trust the client-sent value directly with no auto-derivation. Linking the
original document sidesteps all three behaviours correctly at once.

## Scale

Designed for hundreds-to-thousands of rows. Parsing and grouping happen in the
browser in one pass; records are then created sequentially through the existing
APIs so server-side rules and rate limits are respected.

## Tests

```bash
cd apps/web
node --experimental-strip-types --test lib/imports/imports.test.ts                  # customers, vendors, bills, receipts, employees
node --experimental-strip-types --test lib/imports/creditDebitNoteImports.test.ts   # credit & debit notes (all four)
node --experimental-strip-types --test lib/invoices/importMapping.test.ts           # sales invoices
```

## Not yet covered (deliberately)

These have create forms but were left out of this batch — add on demand:
chart of accounts, journal entries, fixed assets, loans/FDs,
purchase payments, firm-level accounting invoices, and **payroll monthly
variable inputs** (the current payroll run computes from the employee master +
statutory rules; there is no separate per-month input entity to import yet).
