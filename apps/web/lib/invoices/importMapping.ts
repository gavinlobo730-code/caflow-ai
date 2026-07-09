/**
 * Sales-invoice CSV/XLSX import — pure mapping & validation (PR-2, refined
 * for fully-manual invoice numbering + Product/Service-driven lines).
 *
 * Groups flat line-rows into invoices and maps them onto the EXISTING
 * /api/sales-invoices/ create payload (no parallel invoice logic). All money is
 * converted to integer paise here; GST rate is sent as gst_rate_percent, the
 * field InvoiceLineIn (apps/api/models/invoices.py) actually declares — a
 * previous gst_rate_bps field here was silently dropped by Pydantic and every
 * imported line fell back to the model's 18% default (Beta-readiness Part 4).
 * Kept pure so it is unit-tested.
 *
 * invoice_no is now REQUIRED on every row and IS the grouping key — rows
 * sharing one invoice_no become one multi-line invoice (the old separate
 * invoice_ref column existed only to fake this; it's retired now that a real
 * invoice number is required anyway). The server validates its shape (CGST
 * Rule 46(b)) and rejects a duplicate for this client exactly as a manually
 * typed one would — same endpoint, same check, no separate import-only path.
 *
 * product_service is optional: when a row names an existing Product/Service,
 * description/hsn_sac/rate/gst_rate/unit become OPTIONAL OVERRIDES (blank =
 * use the catalogue item's own values) — mirroring how picking a preset
 * pre-fills a manually-created line. The values are copied onto the line,
 * never linked (service_catalogue has no FK from invoice lines), so nothing
 * server-side needs to change for this.
 */

export interface CustomerRef { id: string; name: string; }

/** The subset of ServiceCatalogueItem this mapper needs to pre-fill a line. */
export interface ServiceRef {
  id: string;
  name: string;
  description?: string | null;
  hsn_sac?: string | null;
  gst_rate_bps?: number | null;
  default_rate_paise?: number | null;
  unit?: string | null;
}

export interface BuiltLine {
  description: string;
  hsn_sac?: string;
  quantity: number;
  rate_paise: number;        // integer paise (rupees × 100)
  gst_rate_percent: number;  // e.g. 18 for 18%
  unit?: string;
}

export interface BuiltInvoice {
  client_id: string;
  customer_id: string;
  invoice_no: string;        // required — also the grouping key
  invoice_date: string;
  due_date?: string;
  supply_state_code?: string;
  lines: BuiltLine[];
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
  { key: "invoice_no", label: "Invoice Number", required: true, hint: "The real invoice number. Share it across rows to group them into one multi-line invoice." },
  { key: "customer", label: "Customer", required: true, hint: "Existing customer name (must already exist for this client)" },
  { key: "invoice_date", label: "Invoice Date", required: true, hint: "YYYY-MM-DD — must match across rows sharing an invoice number" },
  { key: "due_date", label: "Due Date", required: false, hint: "YYYY-MM-DD (optional) — must match across rows sharing an invoice number" },
  { key: "supply_state_code", label: "Supply State Code", required: false, hint: "2-digit GST state code, e.g. 27 (optional)" },
  { key: "product_service", label: "Product/Service", required: false, hint: "Existing catalogue item name (optional) — pre-fills description/HSN/rate/GST/unit" },
  { key: "description", label: "Description", required: false, hint: "Required unless Product/Service is given" },
  { key: "hsn_sac", label: "HSN/SAC", required: false, hint: "HSN or SAC code (optional; overrides the Product/Service's own)" },
  { key: "unit", label: "Unit", required: false, hint: "e.g. NOS, HRS, KG (optional; overrides the Product/Service's own)" },
  { key: "quantity", label: "Quantity", required: true, hint: "e.g. 1" },
  { key: "rate", label: "Rate (₹)", required: false, hint: "Per-unit rate in rupees, e.g. 1500.00 — required unless Product/Service is given" },
  { key: "gst_rate", label: "GST %", required: false, hint: "e.g. 18 (for 18%) — required unless Product/Service is given" },
];

/**
 * Build invoice payloads from parsed CSV/XLSX rows.
 * - Rows sharing an invoice_no become one invoice with multiple lines.
 * - Unknown customers/products, bad dates/numbers, and header fields that
 *   disagree with an invoice_no's already-established row are reported and
 *   the offending row is skipped (the rest of that invoice's rows still
 *   import) — the same "reject the row, keep the group" precedent this
 *   mapper already used for a mismatched customer.
 */
export function buildSalesInvoices(
  rows: Record<string, string>[],
  clientId: string,
  customers: CustomerRef[],
  services: ServiceRef[] = [],
): BuildResult {
  const customersByName = new Map(customers.map((c) => [c.name.trim().toLowerCase(), c.id]));
  const servicesByName = new Map(services.map((s) => [s.name.trim().toLowerCase(), s]));
  const groups = new Map<string, BuiltInvoice>();
  const errors: string[] = [];

  rows.forEach((r, i) => {
    const rowNo = i + 1;
    const invoiceNo = (r.invoice_no ?? "").trim();
    const customerName = (r.customer ?? "").trim();
    const invoiceDate = (r.invoice_date ?? "").trim();
    const dueDate = (r.due_date ?? "").trim();
    const supplyStateCode = (r.supply_state_code ?? "").trim();
    const productName = (r.product_service ?? "").trim();
    const customerId = customersByName.get(customerName.toLowerCase());
    const service = productName ? servicesByName.get(productName.toLowerCase()) : undefined;

    if (!invoiceNo) { errors.push(`Row ${rowNo}: invoice_no is required`); return; }
    if (!customerId) { errors.push(`Row ${rowNo}: unknown customer "${customerName}" — create the customer first`); return; }
    if (!DATE_RE.test(invoiceDate)) { errors.push(`Row ${rowNo}: invoice_date must be YYYY-MM-DD`); return; }
    if (dueDate && !DATE_RE.test(dueDate)) { errors.push(`Row ${rowNo}: due_date must be YYYY-MM-DD`); return; }
    if (productName && !service) { errors.push(`Row ${rowNo}: unknown product/service "${productName}" — create it first`); return; }

    const description = (r.description ?? "").trim() || (service ? (service.description?.trim() || service.name) : "");
    if (!description) { errors.push(`Row ${rowNo}: description is required (or give a Product/Service)`); return; }

    const qty = num(r.quantity);
    if (!Number.isFinite(qty) || qty <= 0) { errors.push(`Row ${rowNo}: quantity must be a positive number`); return; }

    const rateRaw = (r.rate ?? "").trim();
    const rate = rateRaw ? num(r.rate) : (service?.default_rate_paise != null ? service.default_rate_paise / 100 : NaN);
    if (!Number.isFinite(rate) || rate < 0) { errors.push(`Row ${rowNo}: rate (₹) must be a non-negative number (or give a Product/Service with a default price)`); return; }

    const gstRaw = (r.gst_rate ?? "").trim();
    const gst = gstRaw ? num(r.gst_rate) : (service?.gst_rate_bps != null ? service.gst_rate_bps / 100 : NaN);
    if (!Number.isFinite(gst) || gst < 0) { errors.push(`Row ${rowNo}: GST % must be a non-negative number (or give a Product/Service with a default rate)`); return; }

    const line: BuiltLine = {
      description,
      hsn_sac: (r.hsn_sac ?? "").trim() || service?.hsn_sac?.trim() || undefined,
      quantity: qty,
      rate_paise: Math.round(rate * 100),   // integer paise — never float
      gst_rate_percent: gst,
      unit: (r.unit ?? "").trim() || service?.unit?.trim() || undefined,
    };

    const existing = groups.get(invoiceNo);
    if (existing) {
      if (existing.customer_id !== customerId) {
        errors.push(`Row ${rowNo}: invoice_no "${invoiceNo}" is already used with a different customer`); return;
      }
      if (existing.invoice_date !== invoiceDate) {
        errors.push(`Row ${rowNo}: invoice_no "${invoiceNo}" is already used with a different invoice_date`); return;
      }
      if ((existing.due_date ?? "") !== dueDate) {
        errors.push(`Row ${rowNo}: invoice_no "${invoiceNo}" is already used with a different due_date`); return;
      }
      if ((existing.supply_state_code ?? "") !== supplyStateCode) {
        errors.push(`Row ${rowNo}: invoice_no "${invoiceNo}" is already used with a different supply_state_code`); return;
      }
      existing.lines.push(line);
    } else {
      groups.set(invoiceNo, {
        client_id: clientId,
        customer_id: customerId,
        invoice_no: invoiceNo,
        invoice_date: invoiceDate,
        due_date: dueDate || undefined,
        supply_state_code: supplyStateCode || undefined,
        lines: [line],
      });
    }
  });

  return { invoices: Array.from(groups.values()), errors };
}
