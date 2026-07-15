/**
 * Pure Sales-Invoice domain primitives — types, the GST preview math, the Indian
 * state master, and status/delivery label maps. NO framework or browser imports, so
 * this module is unit-testable under `node --test` and safe to import anywhere.
 *
 * computeGst() is a rough CLIENT-SIDE PREVIEW only; the backend is authoritative for
 * stored amounts (it floors + splits each GST head and applies round-off in paise).
 */

/** GST rate slabs (%) offered in the invoice/credit-note line editors. */
export const GST_RATES = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28];

// ── Types ────────────────────────────────────────────────────────────────────
export type InvoiceStatus = "draft" | "issued" | "partially_paid" | "paid" | "cancelled";

export interface Customer {
  id: string;
  name: string;
  gstin: string | null;
  state_code: string | null;
  pan: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  state: string | null;
  opening_balance_paise: number;
  credit_days: number;
  is_active: boolean;
}

export interface SalesInvoice {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  customer_id: string;
  customer_name?: string;
  taxable_paise: number;
  gst_paise: number;
  total_paise: number;
  paid_paise?: number;
  status: InvoiceStatus;
  supply_state_code: string | null;
  is_interstate: boolean;
  // Collections metadata (server-maintained by the overdue sweep / reminders).
  is_overdue?: boolean;
  days_overdue?: number;
  reminder_count?: number;
  last_reminded_at?: string | null;
  // Multi-Currency (Phase 3 backend) — undefined/"INR" for a domestic invoice.
  txn_currency?: string | null;
  exchange_rate?: string | null;
  txn_total?: number | null;
  paid_txn?: number | null;
}

export interface InvoiceLine {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string; // in rupees
  gst_rate: number; // 0,5,12,18,28
  /** Unit of measure (UQC), e.g. "NOS", "KGS", "HRS". Blank = server default "NOS". */
  unit: string;
  /** service_catalogue pick for this line — mandatory on every line (migration 206). */
  serviceCatalogueId?: string | null;
}

/** Server line shape (from GET /api/sales-invoices/{id}). */
export interface ServerInvoiceLine {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_bps: number;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  line_total_paise: number;
  /** Which service_catalogue preset (if any) this line was picked from — see
   * lib/invoices/lineItemPayload.ts's InvoiceLineInput.serviceCatalogueId. */
  service_catalogue_id?: string | null;
}

/** Full invoice detail (header + lines + accounting + customer embed). */
export interface InvoiceDetail {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  credit_days?: number | null;
  customer_id: string;
  reference_no?: string | null;
  supply_state_code: string | null;
  is_interstate: boolean;
  notes: string | null;
  taxable_amount_paise: number;
  total_gst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  paid_paise: number;
  status: InvoiceStatus;
  journal_entry_id: string | null;
  issued_at: string | null;
  created_by_name: string | null;
  customers?: { id: string; name: string; email: string | null; gstin: string | null; phone: string | null } | null;
  lines: ServerInvoiceLine[];
  // Multi-Currency (Phase 3 backend) — optional; absent/undefined or "INR" means
  // an ordinary INR invoice. Set once at creation, never editable afterward.
  txn_currency?: string | null;
  exchange_rate?: string | null;
  txn_total?: number | null;
  rate_overridden?: boolean | null;
}

/** ISO 4217 currency master row (Multi-Currency Phase 1 — GET /api/currencies). */
export interface CurrencyOption {
  code: string;
  symbol: string | null;
  display_name: string | null;
  minor_unit: number;
}

export const STATUS_BADGE: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  issued: "bg-blue-100 text-blue-700",
  partially_paid: "bg-amber-100 text-amber-700",
  paid: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-600",
};

export interface InvoiceDelivery {
  id: string;
  invoice_id: string;
  sent_to: string;
  sent_by_email: string | null;
  status: "queued" | "sending" | "sent" | "failed" | "bounced";
  provider_message_id: string | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  kind?: "invoice" | "reminder";
}

/** Human labels for invoice_deliveries.status. */
export const DELIVERY_STATUS_LABEL: Record<string, string> = {
  queued: "Queued", sending: "Sending", sent: "Sent", failed: "Failed", bounced: "Bounced",
};

export function computeGst(
  lines: InvoiceLine[],
  isInterstate: boolean
): {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
} {
  let taxable_paise = 0;
  let cgst_paise = 0;
  let sgst_paise = 0;
  let igst_paise = 0;

  for (const line of lines) {
    const qty = parseFloat(line.qty) || 0;
    const rate = parseFloat(line.rate) || 0;
    // Use integer paise arithmetic — multiply rupees × 100 first
    const lineTaxablePaise = Math.round(qty * rate * 100);
    taxable_paise += lineTaxablePaise;

    if (isInterstate) {
      // IGST = full rate applied to taxable value (CGST Act §5)
      igst_paise += Math.round((lineTaxablePaise * line.gst_rate) / 100);
    } else {
      // CGST = SGST = half rate each (CGST Act §9 + SGST Act §9)
      const halfRateBps = line.gst_rate / 2;
      cgst_paise += Math.round((lineTaxablePaise * halfRateBps) / 100);
      sgst_paise += Math.round((lineTaxablePaise * halfRateBps) / 100);
    }
  }

  const gst_paise = igst_paise + cgst_paise + sgst_paise;
  const total_paise = taxable_paise + gst_paise;
  return { taxable_paise, cgst_paise, sgst_paise, igst_paise, total_paise };
}

// ── Indian state master (GST state codes) ────────────────────────────────────
export const INDIAN_STATES = [
  { code: "01", name: "Jammu & Kashmir" }, { code: "02", name: "Himachal Pradesh" },
  { code: "03", name: "Punjab" }, { code: "04", name: "Chandigarh" },
  { code: "05", name: "Uttarakhand" }, { code: "06", name: "Haryana" },
  { code: "07", name: "Delhi" }, { code: "08", name: "Rajasthan" },
  { code: "09", name: "Uttar Pradesh" }, { code: "10", name: "Bihar" },
  { code: "11", name: "Sikkim" }, { code: "12", name: "Arunachal Pradesh" },
  { code: "13", name: "Nagaland" }, { code: "14", name: "Manipur" },
  { code: "15", name: "Mizoram" }, { code: "16", name: "Tripura" },
  { code: "17", name: "Meghalaya" }, { code: "18", name: "Assam" },
  { code: "19", name: "West Bengal" }, { code: "20", name: "Jharkhand" },
  { code: "21", name: "Odisha" }, { code: "22", name: "Chhattisgarh" },
  { code: "23", name: "Madhya Pradesh" }, { code: "24", name: "Gujarat" },
  { code: "27", name: "Maharashtra" }, { code: "29", name: "Karnataka" },
  { code: "32", name: "Kerala" }, { code: "33", name: "Tamil Nadu" },
  { code: "36", name: "Telangana" }, { code: "37", name: "Andhra Pradesh" },
];


// ── Totals preview (Batch 3) ─────────────────────────────────────────────────
// Live totals for the editor summary. Preview only — the backend is authoritative.
// The round-off mirror matches the Batch 1 rule (nearest ₹1, half-up) so the grand
// total previews on a whole rupee, exactly as the posted invoice will.
export function previewRoundOffPaise(amountPaise: number): number {
  const remainder = ((amountPaise % 100) + 100) % 100; // safe for negatives
  if (remainder === 0) return 0;
  return remainder < 50 ? -remainder : 100 - remainder;
}

export interface PreviewTotals {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  gst_paise: number;
  round_off_paise: number;
  grand_total_paise: number;
}

/**
 * Compute previewed totals for the summary panel. `applyRoundOff` is true for INR
 * invoices (whole-rupee round-off) and false for foreign-currency invoices, which
 * the backend does not rupee-round.
 */
export function previewTotals(
  lines: InvoiceLine[],
  isInterstate: boolean,
  applyRoundOff: boolean = true,
): PreviewTotals {
  const g = computeGst(lines, isInterstate);
  const gst = g.cgst_paise + g.sgst_paise + g.igst_paise;
  const round_off = applyRoundOff ? previewRoundOffPaise(g.total_paise) : 0;
  return {
    taxable_paise: g.taxable_paise,
    cgst_paise: g.cgst_paise,
    sgst_paise: g.sgst_paise,
    igst_paise: g.igst_paise,
    gst_paise: gst,
    round_off_paise: round_off,
    grand_total_paise: g.total_paise + round_off,
  };
}


// ── Editor validation (Batch 3) ──────────────────────────────────────────────
// Mirrors the minimums the backend enforces so the UI can block + explain BEFORE
// calling the API. The server remains authoritative.
export interface EditorValidationInput {
  customerId: string;
  invoiceNo: string;
  invoiceDate: string;
  lines: InvoiceLine[];
  isForeign: boolean;
  exchangeRate: string;
}

export interface EditorValidation {
  errors: {
    customer?: string;
    invoiceNo?: string;
    invoiceDate?: string;
    lines?: string;
    exchangeRate?: string;
  };
  /** Number of lines that carry a description + positive qty + positive rate. */
  validLineCount: number;
  ok: boolean;
}

/** CGST Rule 46(b): a tax invoice's serial number must be a consecutive serial
 * number not exceeding sixteen characters, using only alphabets, numerals,
 * and the special characters '-' and '/'. Numbering itself is fully manual
 * (the CA types it) — this only enforces the structural shape the law
 * requires; per-client uniqueness is checked server-side (the client can't
 * see every other draft/issued number to check itself). */
const INVOICE_NO_RE = /^[A-Za-z0-9\-/]{1,16}$/;

export function validateInvoiceNo(invoiceNo: string): string | undefined {
  const v = invoiceNo.trim();
  if (!v) return "Invoice number is required.";
  if (!INVOICE_NO_RE.test(v)) {
    return "Only letters, digits, '-' and '/' are allowed, up to 16 characters (CGST Rule 46(b)).";
  }
  return undefined;
}

/** A line is "valid" (postable) when it has a description, positive qty & rate,
 * and a linked Product/Service (mandatory on every line — migration 206). */
export function isValidLine(l: InvoiceLine): boolean {
  return (
    l.description.trim().length > 0 &&
    (parseFloat(l.qty) || 0) > 0 &&
    (parseFloat(l.rate) || 0) > 0 &&
    !!l.serviceCatalogueId
  );
}

export function validateInvoiceEditor(input: EditorValidationInput): EditorValidation {
  const errors: EditorValidation["errors"] = {};
  if (!input.customerId) errors.customer = "Select a customer.";
  errors.invoiceNo = validateInvoiceNo(input.invoiceNo);
  if (!errors.invoiceNo) delete errors.invoiceNo;
  if (!input.invoiceDate) errors.invoiceDate = "Invoice date is required.";

  const validLineCount = input.lines.filter(isValidLine).length;
  if (validLineCount === 0) {
    errors.lines = "Add at least one line with a description, quantity, rate and Product/Service.";
  }

  if (input.isForeign && (!input.exchangeRate.trim() || !(parseFloat(input.exchangeRate) > 0))) {
    errors.exchangeRate = "Enter a valid exchange rate.";
  }

  return { errors, validLineCount, ok: Object.keys(errors).length === 0 };
}
