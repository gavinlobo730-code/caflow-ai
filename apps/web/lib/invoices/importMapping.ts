/**
 * Sales-invoice CSV/XLSX import — pure mapping & validation (PR-2).
 *
 * Groups flat line-rows into invoices and maps them onto the EXISTING
 * /api/sales-invoices/ create payload (no parallel invoice logic). All money is
 * converted to integer paise here; GST rate is sent as gst_rate_percent, the
 * field InvoiceLineIn (apps/api/models/invoices.py) actually declares — a
 * previous gst_rate_bps field here was silently dropped by Pydantic and every
 * imported line fell back to the model's 18% default (Beta-readiness Part 4).
 * Kept pure so it is unit-tested.
 */

export interface CustomerRef { id: string; name: string; }

export interface BuiltLine {
  description: string;
  hsn_sac?: string;
  quantity: number;
  rate_paise: number;        // integer paise (rupees × 100)
  gst_rate_percent: number;  // e.g. 18 for 18%
}

export interface BuiltInvoice {
  client_id: string;
  customer_id: string;
  invoice_date: string;
  due_date?: string;
  supply_state_code?: string;
  lines: BuiltLine[];
  ref: string;            // grouping key (invoice_ref or customer|date)
}

export interface BuildResult {
  invoices: BuiltInvoice[];
  errors: string[];       // human-readable, per-row failure reasons
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function num(v: string | undefined): number {
  return parseFloat((v ?? "").trim());
}

export interface ImportColumn { key: string; label: string; required: boolean; hint?: string; }

/** The import columns (also drives the downloadable template). */
export const SALES_INVOICE_IMPORT_COLUMNS: ImportColumn[] = [
  { key: "customer", label: "Customer", required: true, hint: "Existing customer name (must already exist for this client)" },
  { key: "invoice_date", label: "Invoice Date", required: true, hint: "YYYY-MM-DD" },
  { key: "due_date", label: "Due Date", required: false, hint: "YYYY-MM-DD (optional)" },
  { key: "supply_state_code", label: "Supply State Code", required: false, hint: "2-digit GST state code, e.g. 27 (optional)" },
  { key: "invoice_ref", label: "Invoice Ref", required: false, hint: "Group multiple line rows into one invoice by sharing a ref" },
  { key: "description", label: "Description", required: true, hint: "Line item description" },
  { key: "hsn_sac", label: "HSN/SAC", required: false, hint: "HSN or SAC code (optional)" },
  { key: "quantity", label: "Quantity", required: true, hint: "e.g. 1" },
  { key: "rate", label: "Rate (₹)", required: true, hint: "Per-unit rate in rupees, e.g. 1500.00" },
  { key: "gst_rate", label: "GST %", required: true, hint: "e.g. 18 (for 18%)" },
];

/**
 * Build invoice payloads from parsed CSV/XLSX rows.
 * - Rows sharing an invoice_ref (or, absent that, the same customer+invoice_date)
 *   become one invoice with multiple lines.
 * - Unknown customers / bad dates / bad numbers are reported and the row skipped.
 */
export function buildSalesInvoices(
  rows: Record<string, string>[],
  clientId: string,
  customers: CustomerRef[],
): BuildResult {
  const byName = new Map(customers.map((c) => [c.name.trim().toLowerCase(), c.id]));
  const groups = new Map<string, BuiltInvoice>();
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const customerName = (r.customer ?? "").trim();
    const invoiceDate = (r.invoice_date ?? "").trim();
    const dueDate = (r.due_date ?? "").trim();
    const description = (r.description ?? "").trim();
    const customerId = byName.get(customerName.toLowerCase());

    if (!customerId) { errors.push(`Row ${rowNo}: unknown customer "${customerName}" — create the customer first`); return; }
    if (!DATE_RE.test(invoiceDate)) { errors.push(`Row ${rowNo}: invoice_date must be YYYY-MM-DD`); return; }
    if (dueDate && !DATE_RE.test(dueDate)) { errors.push(`Row ${rowNo}: due_date must be YYYY-MM-DD`); return; }
    if (!description) { errors.push(`Row ${rowNo}: description is required`); return; }

    const qty = num(r.quantity);
    const rate = num(r.rate);
    const gst = num(r.gst_rate);
    if (!Number.isFinite(qty) || qty <= 0) { errors.push(`Row ${rowNo}: quantity must be a positive number`); return; }
    if (!Number.isFinite(rate) || rate < 0) { errors.push(`Row ${rowNo}: rate (₹) must be a non-negative number`); return; }
    if (!Number.isFinite(gst) || gst < 0) { errors.push(`Row ${rowNo}: GST % must be a non-negative number`); return; }

    const ref = (r.invoice_ref ?? "").trim() || `${customerName.toLowerCase()}|${invoiceDate}`;
    const line: BuiltLine = {
      description,
      hsn_sac: (r.hsn_sac ?? "").trim() || undefined,
      quantity: qty,
      rate_paise: Math.round(rate * 100),   // integer paise — never float
      gst_rate_percent: gst,
    };

    const existing = groups.get(ref);
    if (existing) {
      if (existing.customer_id !== customerId) {
        errors.push(`Row ${rowNo}: invoice_ref "${ref}" is used with a different customer`); return;
      }
      existing.lines.push(line);
    } else {
      groups.set(ref, {
        client_id: clientId,
        customer_id: customerId,
        invoice_date: invoiceDate,
        due_date: dueDate || undefined,
        supply_state_code: (r.supply_state_code ?? "").trim() || undefined,
        lines: [line],
        ref,
      });
    }
  });

  return { invoices: Array.from(groups.values()), errors };
}
