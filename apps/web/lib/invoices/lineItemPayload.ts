/**
 * Shared line-item → API-payload mapping for Sales Invoices and Credit Notes
 * (Beta-readiness Part 4). Both forms build lines from the same percentage-based
 * shape (qty/rate as strings, gst_rate as a plain percentage like 18) and send
 * them to endpoints whose lines are InvoiceLineIn (apps/api/models/invoices.py),
 * which declares gst_rate_percent — NOT gst_rate_bps. A previous gst_rate_bps
 * field on this payload was silently dropped by Pydantic, so every line fell
 * back to the model's 18% default regardless of the rate actually picked in
 * the UI. Centralizing the mapping here means the correct field name only has
 * to be right once.
 */

export interface InvoiceLineInput {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string; // rupees
  gst_rate: number; // percentage, e.g. 18
  unit?: string; // UQC, e.g. "NOS", "KGS"; blank -> server default "NOS"
}

export interface InvoiceLinePayload {
  description: string;
  hsn_sac: string | undefined;
  quantity: number;
  rate_paise: number;
  gst_rate_percent: number;
  unit: string | undefined;
}

export function toInvoiceLinePayload(line: InvoiceLineInput): InvoiceLinePayload {
  return {
    description: line.description.trim(),
    hsn_sac: line.hsn_sac.trim() || undefined,
    quantity: parseFloat(line.qty),
    rate_paise: Math.round(parseFloat(line.rate) * 100),
    gst_rate_percent: line.gst_rate,
    unit: line.unit?.trim() || undefined,
  };
}
