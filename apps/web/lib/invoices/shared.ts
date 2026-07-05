/**
 * Shared Sales-Invoice primitives — types, money/GST preview helpers, the Indian
 * state master, and the REST client. Extracted from the Sales page (Batch 2) so the
 * new invoice workspace routes/components reuse ONE source instead of duplicating.
 *
 * Nothing here changes behaviour — code moved verbatim. computeGst() remains a
 * rough CLIENT-SIDE PREVIEW only; the backend is authoritative for stored amounts.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { formatPaise } from "@/lib/services/formatting";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
export { API };

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
}

/** Server line shape (from GET /api/sales-invoices/{id}). */
export interface ServerInvoiceLine {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  rate_paise: number;
  gst_rate_bps: number;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  line_total_paise: number;
}

/** Full invoice detail (header + lines + accounting + customer embed). */
export interface InvoiceDetail {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  credit_days?: number | null;
  customer_id: string;
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

// ── Money / GST preview helpers ──────────────────────────────────────────────
export function fmt(paise: number): string {
  return paise === 0 ? "—" : formatPaise(paise);
}

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

// ── Loading skeleton ───────────────────────────────────────────────────────

// ── REST client (Supabase-authed calls to the FastAPI backend) ───────────────

// ── API helpers ────────────────────────────────────────────────────────────

export async function apiCall(
  endpoint: string,
  method: "POST" | "PUT" | "PATCH" | "DELETE",
  body?: unknown,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const res = await fetch(`${API}${endpoint}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok && res.status !== 200) {
    // Try to parse as JSON first (FastAPI returns structured errors)
    const text = await res.text().catch(() => "Request failed");
    let errorMsg = text;
    try {
      const json = JSON.parse(text);
      // FastAPI validation error: { detail: [{msg, loc, type}] }
      if (json.detail && Array.isArray(json.detail)) {
        errorMsg = json.detail.map((e: { msg?: string }) => e.msg ?? String(e)).join("; ");
      } else if (typeof json.detail === "string") {
        errorMsg = json.detail;
      } else if (json.error) {
        errorMsg = json.error;
      }
    } catch {
      // text is not JSON — use as-is
    }
    return { success: false, data: null, error: errorMsg };
  }
  return res.json();
}

export async function getAuthToken(): Promise<string> {
  const supabase = getSupabaseClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? "";
}

export async function apiGet(
  endpoint: string,
  token?: string
): Promise<{ success: boolean; data: unknown; error: string | null }> {
  const res = await fetch(`${API}${endpoint}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "Request failed");
    return { success: false, data: null, error: text };
  }
  return res.json();
}
