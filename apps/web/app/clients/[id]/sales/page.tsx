"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import {
  Plus, RefreshCw, X, FileText, CheckCircle, Upload, Send, Clock,
  Pencil, Trash2, Search, Eye, Download, ArrowUp, ArrowDown, Loader2, AlertTriangle,
} from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { buildSalesInvoices, SALES_INVOICE_IMPORT_COLUMNS } from "@/lib/invoices/importMapping";
import { buildCustomers, CUSTOMER_IMPORT_COLUMNS, buildReceipts, RECEIPT_IMPORT_COLUMNS } from "@/lib/imports/mappers";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── API helpers ────────────────────────────────────────────────────────────

async function apiCall(
  endpoint: string,
  method: "POST" | "PATCH" | "DELETE",
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

async function getAuthToken(): Promise<string> {
  const supabase = getSupabaseClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? "";
}

async function apiGet(
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

// ── Types ──────────────────────────────────────────────────────────────────

type SalesTab = "invoices" | "customers" | "receipts" | "credit-notes";
const TABS: { id: SalesTab; label: string }[] = [
  { id: "invoices", label: "Sales Invoices" },
  { id: "customers", label: "Customers" },
  { id: "receipts", label: "Receipts" },
  { id: "credit-notes", label: "Credit Notes" },
];

type InvoiceStatus = "draft" | "issued" | "partially_paid" | "paid" | "cancelled";

interface Customer {
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

interface SalesInvoice {
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
}

interface InvoiceLine {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string; // in rupees
  gst_rate: number; // 0,5,12,18,28
}

/** Server line shape (from GET /api/sales-invoices/{id}). */
interface ServerInvoiceLine {
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
interface InvoiceDetail {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
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
}

/** HSN/SAC suggestion (from GET /api/sales-invoices/hsn-suggestions). */
interface HsnSuggestion {
  hsn_sac: string;
  gst_rate_bps: number | null;
  use_count: number;
  sample_description: string;
  reason: string;
}

type SortKey = "invoice_no" | "invoice_date" | "due_date" | "total_paise" | "status";
type SortDir = "asc" | "desc";
type DateMode = "current" | "previous" | "custom";

interface Receipt {
  id: string;
  receipt_no: string;
  receipt_date: string;
  customer_id: string;
  customer_name?: string;
  amount_paise: number;
  payment_mode: string;
  reference_no: string | null;
  allocated_paise: number;
}

interface CreditNote {
  id: string;
  cn_no: string;
  cn_date: string;
  customer_id: string;
  customer_name?: string;
  original_invoice_id: string | null;
  original_invoice_no?: string | null;
  reason: string;
  taxable_paise: number;
  gst_paise: number;
  total_paise: number;
  status: "draft" | "issued" | "cancelled";
}

interface InvoiceDelivery {
  id: string;
  invoice_id: string;
  sent_to: string;
  sent_by_email: string | null;
  status: "queued" | "sending" | "sent" | "failed" | "bounced";
  provider_message_id: string | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Money formatter — paise → ₹ string (CGST Act §15: all amounts in Indian rupees) */
function fmt(paise: number): string {
  if (paise === 0) return "—";
  return (
    "₹" +
    new Intl.NumberFormat("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Math.abs(paise) / 100)
  );
}

/** FY range (April 1 to March 31) — Income Tax Act §3 */
function fyRange(fy: string): { start: string; end: string } {
  const [y] = fy.split("-");
  const yr = parseInt(y, 10);
  return { start: `${yr}-04-01`, end: `${yr + 1}-03-31` };
}

/** Previous financial year string, e.g. "2025-26" → "2024-25". */
function previousFy(fy: string): string {
  const [y] = fy.split("-");
  const yr = parseInt(y, 10) - 1;
  return `${yr}-${String(yr + 1).slice(2)}`;
}

/** Format an ISO timestamp for display, or "—" when absent. */
function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? "—" : d.toLocaleString("en-IN");
}

/**
 * Open the GST tax-invoice PDF in a new tab. The endpoint requires a Bearer
 * token, so we fetch with auth and open a blob URL (a plain window.open would
 * drop the Authorization header). Backend-generated PDF — no logic here.
 */
async function viewInvoicePdf(invoiceId: string): Promise<void> {
  const token = await getAuthToken();
  const res = await fetch(`${API}/api/sales-invoices/${invoiceId}/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("PDF generation failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Validate GSTIN format: 2-digit state + PAN(10) + entity# + Z + check (CGST Act §25) */
function isValidGstin(gstin: string): boolean {
  return /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(gstin);
}

/** Validate PAN format: AAAAA9999A (IT Act §139A) */
function isValidPan(pan: string): boolean {
  return /^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test(pan);
}

/**
 * Compute GST on invoice lines (paise arithmetic only — never floating point).
 * CGST Act §9: CGST+SGST for intra-state, IGST for inter-state.
 */
function computeGst(
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

const STATUS_BADGE: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  issued: "bg-blue-100 text-blue-700",
  partially_paid: "bg-amber-100 text-amber-700",
  paid: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-600",
};

const GST_RATES = [0, 5, 12, 18, 28];
const PAYMENT_MODES = ["bank", "cash", "cheque", "upi", "neft", "rtgs"];
const INDIAN_STATES = [
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

function LoadingSkeleton() {
  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 px-6 pt-5 pb-0">
        <div className="h-8 w-96 bg-[#F8FAFC] rounded-lg animate-pulse" />
      </div>
      <div className="flex-1 px-6 pb-6 pt-4 space-y-3">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="h-12 rounded-lg bg-[#F8FAFC] animate-pulse" />
        ))}
      </div>
    </div>
  );
}

// ── Toast ──────────────────────────────────────────────────────────────────

function Toast({ msg, type }: { msg: string; type: "success" | "error" }) {
  if (!msg) return null;
  return (
    <div
      className={`rounded-lg px-4 py-3 text-sm font-medium mb-4 ${
        type === "success"
          ? "bg-green-50 border border-green-100 text-green-700"
          : "bg-red-50 border border-red-100 text-red-700"
      }`}
    >
      {msg}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function SalesPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<SalesTab>("invoices");

  if (!clientId || clientId === "_placeholder") return <LoadingSkeleton />;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Sub-tab bar */}
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id
                  ? "bg-white text-[#0F172A] shadow-sm"
                  : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "invoices" && (
          <SalesInvoices clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "customers" && (
          <Customers clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "receipts" && (
          <Receipts clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "credit-notes" && (
          <CreditNotes clientId={clientId} financialYear={financialYear} />
        )}
      </div>
    </div>
  );
}

// ── Sales Invoices Tab ─────────────────────────────────────────────────────

function SalesInvoices({
  clientId,
  financialYear,
}: {
  clientId: string;
  financialYear: string;
}) {
  const [invoices, setInvoices] = useState<SalesInvoice[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [sendModal, setSendModal] = useState<{ invoice: SalesInvoice; customerEmail: string | null } | null>(null);
  const [deliveryModal, setDeliveryModal] = useState<{ invoice: SalesInvoice; deliveries: InvoiceDelivery[] } | null>(null);

  // Edit / detail / delete
  const [editing, setEditing] = useState<InvoiceDetail | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SalesInvoice | null>(null);

  // Search / filter / sort (sort + filters persisted in the URL).
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [customerFilter, setCustomerFilter] = useState<string>("all");
  const [dateMode, setDateMode] = useState<DateMode>("current");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("invoice_date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  // Summary stats
  const [stats, setStats] = useState({ outstanding: 0, issued: 0, paid: 0 });

  // ── URL state: hydrate once on mount, then mirror changes back ────────────
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("sort")) setSortKey(p.get("sort") as SortKey);
    if (p.get("dir")) setSortDir(p.get("dir") as SortDir);
    if (p.get("status")) setStatusFilter(p.get("status")!);
    if (p.get("cust")) setCustomerFilter(p.get("cust")!);
    if (p.get("fy")) setDateMode(p.get("fy") as DateMode);
    if (p.get("from")) setCustomFrom(p.get("from")!);
    if (p.get("to")) setCustomTo(p.get("to")!);
    if (p.get("q")) { setSearch(p.get("q")!); setDebouncedSearch(p.get("q")!); }
  }, []);

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const set = (k: string, v: string, def: string) => (v && v !== def ? p.set(k, v) : p.delete(k));
    set("sort", sortKey, "invoice_date");
    set("dir", sortDir, "desc");
    set("status", statusFilter, "all");
    set("cust", customerFilter, "all");
    set("fy", dateMode, "current");
    set("from", dateMode === "custom" ? customFrom : "", "");
    set("to", dateMode === "custom" ? customTo : "", "");
    set("q", debouncedSearch, "");
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  }, [sortKey, sortDir, statusFilter, customerFilter, dateMode, customFrom, customTo, debouncedSearch]);

  // Debounce the search box (instant-feel, but not a filter pass per keystroke).
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(t);
  }, [search]);

  // The date window that scopes the server query (FY-aware).
  const range = useMemo(() => {
    if (dateMode === "custom" && (customFrom || customTo)) {
      return { start: customFrom || "1900-01-01", end: customTo || "2999-12-31" };
    }
    if (dateMode === "previous") return fyRange(previousFy(financialYear));
    return fyRange(financialYear);
  }, [dateMode, customFrom, customTo, financialYear]);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();

    const [{ data: invData }, { data: custData }] = await Promise.all([
      supabase
        .from("client_sales_invoices")
        .select(
          "id, invoice_no, invoice_date, due_date, customer_id, taxable_amount_paise, total_gst_paise, total_paise, paid_paise, status, supply_state_code, is_interstate, customers(name)"
        )
        .eq("client_id", clientId)
        .is("deleted_at", null)
        .gte("invoice_date", range.start)
        .lte("invoice_date", range.end)
        .order("invoice_date", { ascending: false }),
      supabase
        .from("customers")
        .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name"),
    ]);

    const mapped: SalesInvoice[] = ((invData ?? []) as unknown as Array<
      { id: string; invoice_no: string; invoice_date: string; due_date: string | null;
        customer_id: string; taxable_amount_paise: number; total_gst_paise: number;
        total_paise: number; paid_paise: number; status: string; supply_state_code: string | null;
        is_interstate: boolean; customers: { name: string } | null }
    >).map((r) => ({
      id: r.id,
      invoice_no: r.invoice_no,
      invoice_date: r.invoice_date,
      due_date: r.due_date,
      customer_id: r.customer_id,
      customer_name: r.customers?.name ?? "—",
      taxable_paise: r.taxable_amount_paise,
      gst_paise: r.total_gst_paise,
      total_paise: r.total_paise,
      paid_paise: r.paid_paise,
      status: r.status as InvoiceStatus,
      supply_state_code: r.supply_state_code,
      is_interstate: r.is_interstate,
    }));

    setInvoices(mapped);
    setCustomers((custData as Customer[]) ?? []);

    // Summary: outstanding = issued + partially_paid (total_paise), paid FY, issued FY
    let outstanding = 0, issued = 0, paid = 0;
    for (const inv of mapped) {
      if (inv.status === "issued" || inv.status === "partially_paid") outstanding += inv.total_paise;
      if (inv.status === "issued" || inv.status === "partially_paid" || inv.status === "paid") issued += inv.total_paise;
      if (inv.status === "paid") paid += inv.total_paise;
    }
    setStats({ outstanding, issued, paid });
    setLoading(false);
  }, [clientId, range]);

  useEffect(() => { load(); }, [load]);

  // ── Search + filter + sort, all client-side over the loaded window ────────
  const visible = useMemo(() => {
    const q = debouncedSearch.trim().toLowerCase();
    let r = invoices.filter((inv) => {
      if (statusFilter !== "all" && inv.status !== statusFilter) return false;
      if (customerFilter !== "all" && inv.customer_id !== customerFilter) return false;
      if (q) {
        const hay = `${inv.invoice_no} ${inv.customer_name ?? ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    r = [...r].sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "invoice_no": cmp = a.invoice_no.localeCompare(b.invoice_no); break;
        case "invoice_date": cmp = a.invoice_date.localeCompare(b.invoice_date); break;
        case "due_date": cmp = (a.due_date ?? "").localeCompare(b.due_date ?? ""); break;
        case "total_paise": cmp = a.total_paise - b.total_paise; break;
        case "status": cmp = a.status.localeCompare(b.status); break;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return r;
  }, [invoices, debouncedSearch, statusFilter, customerFilter, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "total_paise" || key.includes("date") ? "desc" : "asc");
    }
  }

  async function issueInvoice(id: string) {
    try {
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const token = await getAuthToken();
      const result = await apiCall(`/api/sales-invoices/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue invoice");
      showToast("Invoice issued successfully", "success");
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Error issuing invoice", "error");
    }
  }

  async function openEdit(inv: SalesInvoice) {
    try {
      const token = await getAuthToken();
      const result = await apiGet(`/api/sales-invoices/${inv.id}`, token);
      if (!result.success || !result.data) throw new Error(result.error ?? "Failed to load invoice");
      setDetailId(null);
      setShowForm(false);
      setEditing(result.data as InvoiceDetail);
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Failed to open invoice", "error");
    }
  }

  async function deleteInvoice(inv: SalesInvoice) {
    const token = await getAuthToken();
    const result = await apiCall(`/api/sales-invoices/${inv.id}`, "DELETE", undefined, token);
    if (!result.success) throw new Error(result.error ?? "Failed to delete invoice");
    showToast(`Invoice ${inv.invoice_no} deleted`, "success");
    setDeleteTarget(null);
    load();
  }

  async function sendInvoice(inv: SalesInvoice, toEmail: string, isResend: boolean) {
    const token = await getAuthToken();
    const endpoint = isResend
      ? `/api/sales-invoices/${inv.id}/resend`
      : `/api/sales-invoices/${inv.id}/send`;
    const result = await apiCall(endpoint, "POST", { to_email: toEmail || null }, token);
    if (!result.success) throw new Error(result.error ?? "Failed to send invoice");
    showToast(`Invoice ${inv.invoice_no} sent to ${toEmail}`, "success");
    setSendModal(null);
  }

  function openSend(inv: SalesInvoice) {
    const cust = customers.find((c) => c.id === inv.customer_id);
    setSendModal({ invoice: inv, customerEmail: cust?.email ?? null });
  }

  async function loadAndShowDeliveries(inv: SalesInvoice) {
    try {
      const token = await getAuthToken();
      const result = await apiGet(`/api/sales-invoices/${inv.id}/deliveries`, token);
      const deliveries = (result.data as InvoiceDelivery[]) ?? [];
      setDeliveryModal({ invoice: inv, deliveries });
    } catch {
      showToast("Failed to load delivery history", "error");
    }
  }

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }

  /**
   * Bulk-import handler for the CSV/XLSX modal. Maps flat rows → grouped invoices
   * via the pure buildSalesInvoices() mapper, then creates each invoice through the
   * EXISTING /api/sales-invoices/ endpoint — the same path the manual form uses, so
   * there is no parallel invoice logic. Returns a per-invoice success/error report.
   */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const { invoices: built, errors } = buildSalesInvoices(rows, clientId, customers);
    const token = await getAuthToken();
    let imported = 0;

    for (const inv of built) {
      const { ref, ...payload } = inv; // drop the internal grouping key
      void ref;
      const result = await apiCall("/api/sales-invoices/", "POST", payload, token);
      if (result.success) {
        imported += inv.lines.length; // count line-rows so the totals match the upload
      } else {
        const label = inv.ref || `${inv.customer_id} / ${inv.invoice_date}`;
        errors.push(`Invoice "${label}": ${result.error ?? "failed to create"}`);
      }
    }

    if (imported > 0) load();
    return { imported, errors };
  }

  const SortTh = ({ k, label, align = "left" }: { k: SortKey; label: string; align?: "left" | "right" }) => (
    <th className={`px-3 py-3 font-semibold ${align === "right" ? "text-right" : "text-left"}`}>
      <button
        onClick={() => toggleSort(k)}
        className={`inline-flex items-center gap-1 hover:text-[#475569] ${sortKey === k ? "text-[#334155]" : ""}`}
      >
        {label}
        {sortKey === k && (sortDir === "asc" ? <ArrowUp size={10} /> : <ArrowDown size={10} />)}
      </button>
    </th>
  );

  const anyFilterActive =
    debouncedSearch.trim() !== "" || statusFilter !== "all" || customerFilter !== "all";

  return (
    <div className="space-y-4 max-w-5xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      {sendModal && (
        <SendInvoiceModal
          invoice={sendModal.invoice}
          defaultEmail={sendModal.customerEmail}
          onSend={(email) => sendInvoice(sendModal.invoice, email, false)}
          onClose={() => setSendModal(null)}
        />
      )}

      {deliveryModal && (
        <DeliveryHistoryModal
          invoice={deliveryModal.invoice}
          deliveries={deliveryModal.deliveries}
          onResend={(email) => {
            setDeliveryModal(null);
            setSendModal({ invoice: deliveryModal.invoice, customerEmail: email || null });
          }}
          onClose={() => setDeliveryModal(null)}
        />
      )}

      {deleteTarget && (
        <DeleteInvoiceModal
          invoice={deleteTarget}
          onConfirm={() => deleteInvoice(deleteTarget)}
          onClose={() => setDeleteTarget(null)}
        />
      )}

      {detailId && (
        <InvoiceDetailDrawer
          invoiceId={detailId}
          onClose={() => setDetailId(null)}
          onEdit={(inv) => openEdit(inv)}
          onIssue={(id) => { setDetailId(null); issueInvoice(id); }}
          onSend={(inv) => { setDetailId(null); openSend(inv); }}
          onToast={showToast}
        />
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-3">
        <SummaryCard label="Outstanding" value={fmt(stats.outstanding)} color="amber" />
        <SummaryCard label="Issued This FY" value={fmt(stats.issued)} color="blue" />
        <SummaryCard label="Paid This FY" value={fmt(stats.paid)} color="green" />
      </div>

      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {visible.length} of {invoices.length} invoice{invoices.length !== 1 ? "s" : ""}
        </p>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
          >
            <Upload size={12} /> Import
          </button>
          <button
            onClick={() => { setEditing(null); setShowForm(true); }}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> New Invoice
          </button>
        </div>
      </div>

      {/* Search + Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#94A3B8]" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search invoice no. or customer…"
            className="w-full pl-8 pr-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
        >
          <option value="all">All statuses</option>
          <option value="draft">Draft</option>
          <option value="issued">Issued</option>
          <option value="partially_paid">Partially paid</option>
          <option value="paid">Paid</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <select
          value={customerFilter}
          onChange={(e) => setCustomerFilter(e.target.value)}
          className="px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569] max-w-[160px]"
        >
          <option value="all">All customers</option>
          {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select
          value={dateMode}
          onChange={(e) => setDateMode(e.target.value as DateMode)}
          className="px-2.5 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
        >
          <option value="current">FY {financialYear}</option>
          <option value="previous">FY {previousFy(financialYear)}</option>
          <option value="custom">Custom range</option>
        </select>
        {dateMode === "custom" && (
          <>
            <input
              type="date"
              value={customFrom}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
            />
            <span className="text-xs text-[#94A3B8]">to</span>
            <input
              type="date"
              value={customTo}
              onChange={(e) => setCustomTo(e.target.value)}
              className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
            />
          </>
        )}
        {anyFilterActive && (
          <button
            onClick={() => { setSearch(""); setDebouncedSearch(""); setStatusFilter("all"); setCustomerFilter("all"); }}
            className="text-xs text-[#64748B] hover:text-[#334155] underline"
          >
            Clear
          </button>
        )}
      </div>

      {/* Edit / New Invoice Form */}
      {(showForm || editing) && (
        <InvoiceForm
          clientId={clientId}
          customers={customers}
          existing={editing}
          onSaved={() => {
            const wasEdit = !!editing;
            setShowForm(false); setEditing(null); load();
            showToast(wasEdit ? "Invoice updated" : "Invoice created", "success");
          }}
          onCancel={() => { setShowForm(false); setEditing(null); }}
        />
      )}

      {/* Bulk import (CSV / XLSX) — reuses the existing create endpoint */}
      {showImport && (
        <CsvImportModal
          title="Import Sales Invoices"
          columns={SALES_INVOICE_IMPORT_COLUMNS}
          templateFilename="sales-invoices-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />
          ))}
        </div>
      ) : invoices.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <FileText size={32} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-[#64748B]">No invoices in this period</p>
        </div>
      ) : visible.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <Search size={28} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-[#64748B]">No invoices match your search / filters</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <SortTh k="invoice_no" label="Invoice No" />
                  <SortTh k="invoice_date" label="Date" />
                  <th className="px-3 py-3 text-left font-semibold">Customer</th>
                  <th className="px-3 py-3 text-right font-semibold">Taxable</th>
                  <th className="px-3 py-3 text-right font-semibold">GST</th>
                  <SortTh k="total_paise" label="Total" align="right" />
                  <SortTh k="due_date" label="Due" />
                  <SortTh k="status" label="Status" />
                  <th className="px-4 py-3 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {visible.map((inv) => (
                  <tr
                    key={inv.id}
                    onClick={() => setDetailId(inv.id)}
                    className="hover:bg-[#F8FAFC] cursor-pointer"
                  >
                    <td className="px-4 py-2.5 font-mono font-medium text-[#1E293B]">{inv.invoice_no}</td>
                    <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">{inv.invoice_date}</td>
                    <td className="px-3 py-2.5 text-[#334155]">{inv.customer_name}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(inv.taxable_paise)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(inv.gst_paise)}</td>
                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#0F172A]">{fmt(inv.total_paise)}</td>
                    <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">{inv.due_date ?? "—"}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[inv.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                        {inv.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-2.5">
                        <button
                          onClick={() => setDetailId(inv.id)}
                          className="text-[#94A3B8] hover:text-[#334155]"
                          title="View details"
                        >
                          <Eye size={13} />
                        </button>
                        {inv.status === "draft" && (
                          <>
                            <button
                              onClick={() => openEdit(inv)}
                              className="text-[#94A3B8] hover:text-blue-600"
                              title="Edit draft"
                            >
                              <Pencil size={13} />
                            </button>
                            <button
                              onClick={() => issueInvoice(inv.id)}
                              className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                            >
                              <CheckCircle size={11} /> Issue
                            </button>
                            <button
                              onClick={() => setDeleteTarget(inv)}
                              className="text-[#CBD5E1] hover:text-red-600"
                              title="Delete draft"
                            >
                              <Trash2 size={13} />
                            </button>
                          </>
                        )}
                        {inv.status !== "draft" && inv.status !== "cancelled" && (
                          <button
                            onClick={() => openSend(inv)}
                            className="text-xs text-emerald-600 hover:underline flex items-center gap-1"
                          >
                            <Send size={11} /> Send
                          </button>
                        )}
                        {inv.status !== "draft" && inv.status !== "cancelled" && (
                          <button
                            onClick={() => loadAndShowDeliveries(inv)}
                            className="text-[#CBD5E1] hover:text-[#64748B]"
                            title="Delivery history"
                          >
                            <Clock size={11} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Invoice Create Form ────────────────────────────────────────────────────

function InvoiceForm({
  clientId,
  customers,
  existing,
  onSaved,
  onCancel,
}: {
  clientId: string;
  customers: Customer[];
  existing?: InvoiceDetail | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const isEdit = !!existing;

  const initialLines: InvoiceLine[] = existing && existing.lines.length > 0
    ? existing.lines.map((l) => ({
        description: l.description ?? "",
        hsn_sac: l.hsn_sac ?? "",
        qty: String(l.quantity ?? 1),
        rate: String((l.rate_paise ?? 0) / 100),
        gst_rate: Math.round((l.gst_rate_bps ?? 0) / 100),
      }))
    : [{ description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 }];

  const [customerId, setCustomerId] = useState(existing?.customer_id ?? "");
  const [invoiceDate, setInvoiceDate] = useState(existing?.invoice_date ?? today);
  const [dueDate, setDueDate] = useState(existing?.due_date ?? "");
  const [supplyStateCode, setSupplyStateCode] = useState(existing?.supply_state_code ?? "");
  const [isInterstate, setIsInterstate] = useState(existing?.is_interstate ?? false);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [lines, setLines] = useState<InvoiceLine[]>(initialLines);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const gst = computeGst(lines, isInterstate);

  function setLine(idx: number, patch: Partial<InvoiceLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 }]);
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleSave() {
    if (!customerId) { setError("Select a customer"); return; }
    if (!invoiceDate) { setError("Invoice date required"); return; }
    const validLines = lines.filter((l) => l.description.trim() && parseFloat(l.rate) > 0);
    if (validLines.length === 0) { setError("Add at least one line with description and rate"); return; }

    const linePayload = validLines.map((l) => ({
      description: l.description.trim(),
      hsn_sac: l.hsn_sac.trim() || undefined,
      quantity: parseFloat(l.qty),
      rate_paise: Math.round(parseFloat(l.rate) * 100),
      gst_rate_bps: l.gst_rate * 100,
    }));

    setSaving(true); setError(null);
    try {
      const token = await getAuthToken();
      let result;
      if (isEdit && existing) {
        // Update the existing draft in place (PATCH) — never creates a new invoice.
        result = await apiCall(
          `/api/sales-invoices/${existing.id}`,
          "PATCH",
          {
            customer_id: customerId,
            invoice_date: invoiceDate,
            due_date: dueDate || undefined,
            supply_state_code: supplyStateCode || undefined,
            notes: notes.trim() || undefined,
            is_inter_state: isInterstate,
            lines: linePayload,
          },
          token
        );
        if (!result.success) throw new Error(result.error ?? "Failed to update invoice");
      } else {
        result = await apiCall(
          "/api/sales-invoices/",
          "POST",
          {
            client_id: clientId,
            customer_id: customerId,
            invoice_date: invoiceDate,
            due_date: dueDate || undefined,
            supply_state_code: supplyStateCode || undefined,
            is_inter_state: isInterstate,
            notes: notes.trim() || undefined,
            lines: linePayload,
          },
          token
        );
        if (!result.success) throw new Error(result.error ?? "Failed to create invoice");
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save invoice");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">
          {isEdit ? `Edit Draft Invoice ${existing?.invoice_no ?? ""}` : "New Sales Invoice"}
        </h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="col-span-2">
          <label className="block text-xs font-medium text-[#475569] mb-1">Customer *</label>
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Select customer —</option>
            {customers.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Invoice Date *</label>
          <input
            type="date"
            value={invoiceDate}
            onChange={(e) => setInvoiceDate(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
          <input
            type="date"
            value={dueDate ?? ""}
            onChange={(e) => setDueDate(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Supply State</label>
          <select
            value={supplyStateCode ?? ""}
            onChange={(e) => setSupplyStateCode(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Select —</option>
            {INDIAN_STATES.map((s) => (
              <option key={s.code} value={s.code}>{s.code} — {s.name}</option>
            ))}
          </select>
        </div>
        <div className="flex items-end pb-1.5">
          <label className="flex items-center gap-2 text-xs text-[#475569] cursor-pointer">
            <input
              type="checkbox"
              checked={isInterstate}
              onChange={(e) => setIsInterstate(e.target.checked)}
              className="rounded"
            />
            Interstate supply (IGST)
          </label>
        </div>
      </div>

      {/* Lines */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="pb-2 text-left font-semibold">Description</th>
              <th className="pb-2 text-left font-semibold w-32">HSN/SAC</th>
              <th className="pb-2 text-right font-semibold w-16">Qty</th>
              <th className="pb-2 text-right font-semibold w-24">Rate (₹)</th>
              <th className="pb-2 text-right font-semibold w-20">GST %</th>
              <th className="pb-2 text-right font-semibold w-24">Amount</th>
              <th className="pb-2 w-6" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {lines.map((line, idx) => {
              const lineTaxable = Math.round((parseFloat(line.qty) || 0) * (parseFloat(line.rate) || 0) * 100);
              const lineTotal = lineTaxable + Math.round((lineTaxable * line.gst_rate) / 100);
              return (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <input
                      value={line.description}
                      onChange={(e) => setLine(idx, { description: e.target.value })}
                      placeholder="Item / service description"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <HsnAutocomplete
                      clientId={clientId}
                      description={line.description}
                      value={line.hsn_sac}
                      onChange={(v) => setLine(idx, { hsn_sac: v })}
                      onPickGst={(pct) => setLine(idx, { gst_rate: pct })}
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number"
                      min="0"
                      step="0.001"
                      value={line.qty}
                      onChange={(e) => setLine(idx, { qty: e.target.value })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.rate}
                      onChange={(e) => setLine(idx, { rate: e.target.value })}
                      placeholder="0.00"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <select
                      value={line.gst_rate}
                      onChange={(e) => setLine(idx, { gst_rate: parseInt(e.target.value) })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    >
                      {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                    </select>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-[#334155]">
                    {lineTotal > 0 ? fmt(lineTotal) : "—"}
                  </td>
                  <td className="py-1.5">
                    {lines.length > 1 && (
                      <button onClick={() => removeLine(idx)} className="text-[#CBD5E1] hover:text-red-600">
                        <X size={13} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button
        onClick={addLine}
        className="text-xs text-blue-600 hover:underline flex items-center gap-1"
      >
        <Plus size={12} /> Add line
      </button>

      {/* Notes */}
      <div>
        <label className="block text-xs font-medium text-[#475569] mb-1">Notes</label>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={2}
          placeholder="Optional notes shown on the invoice (terms, PO reference…)"
          className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      {/* GST Preview */}
      {gst.taxable_paise > 0 && (
        <div className="bg-[#F8FAFC] rounded-lg p-3 text-xs space-y-1">
          <p className="font-semibold text-[#334155] mb-2">GST Computation</p>
          <div className="flex justify-between text-[#475569]">
            <span>Taxable Value</span>
            <span className="font-mono">{fmt(gst.taxable_paise)}</span>
          </div>
          {isInterstate ? (
            <div className="flex justify-between text-[#475569]">
              <span>IGST @ {lines[0]?.gst_rate ?? 0}%</span>
              <span className="font-mono">{fmt(gst.igst_paise)}</span>
            </div>
          ) : (
            <>
              <div className="flex justify-between text-[#475569]">
                <span>CGST @ {(lines[0]?.gst_rate ?? 0) / 2}%</span>
                <span className="font-mono">{fmt(gst.cgst_paise)}</span>
              </div>
              <div className="flex justify-between text-[#475569]">
                <span>SGST @ {(lines[0]?.gst_rate ?? 0) / 2}%</span>
                <span className="font-mono">{fmt(gst.sgst_paise)}</span>
              </div>
            </>
          )}
          <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1 mt-1">
            <span>Total Invoice Amount</span>
            <span className="font-mono">{fmt(gst.total_paise)}</span>
          </div>
        </div>
      )}

      {isEdit && (
        <p className="text-[10px] text-[#94A3B8]">
          Editing a draft. GST is recomputed by the backend on save. Only drafts are editable —
          issued, paid and cancelled invoices are locked.
        </p>
      )}

      {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div className="flex gap-3 justify-end pt-1">
        <button onClick={onCancel} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : isEdit ? "Update Invoice" : "Save Invoice"}
        </button>
      </div>
    </div>
  );
}

// ── Send Invoice Modal ─────────────────────────────────────────────────────

function SendInvoiceModal({
  invoice,
  defaultEmail,
  onSend,
  onClose,
}: {
  invoice: SalesInvoice;
  defaultEmail: string | null;
  onSend: (email: string) => Promise<void>;
  onClose: () => void;
}) {
  const [email, setEmail] = useState(defaultEmail || "");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) { setError("Email address is required"); return; }
    setSending(true);
    setError(null);
    try {
      await onSend(email.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send invoice");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-[#0F172A]">Send Invoice {invoice.invoice_no}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={14} /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Recipient Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="customer@example.com"
              className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500"
              autoFocus
            />
            {!defaultEmail && (
              <p className="text-[10px] text-amber-600 mt-1">
                No email on the customer record — enter the address to send.
              </p>
            )}
          </div>
          <p className="text-xs text-[#64748B]">
            A PDF of this invoice will be attached and sent by email.
          </p>
          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
          <div className="flex gap-3 justify-end">
            <button
              type="button"
              onClick={onClose}
              className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={sending}
              className="text-xs px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 flex items-center gap-1.5"
            >
              {sending ? "Sending…" : <><Send size={11} /> Send Invoice</>}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Delivery History Modal ─────────────────────────────────────────────────

const DELIVERY_STATUS_LABEL: Record<string, string> = {
  queued: "Queued", sending: "Sending", sent: "Sent", failed: "Failed", bounced: "Bounced",
};
const DELIVERY_STATUS_COLOR: Record<string, string> = {
  queued:  "bg-[#F1F5F9] text-[#64748B]",
  sending: "bg-blue-50 text-blue-600",
  sent:    "bg-green-50 text-green-700",
  failed:  "bg-red-50 text-red-700",
  bounced: "bg-amber-50 text-amber-700",
};

function DeliveryHistoryModal({
  invoice,
  deliveries,
  onResend,
  onClose,
}: {
  invoice: SalesInvoice;
  deliveries: InvoiceDelivery[];
  onResend: (email: string) => void;
  onClose: () => void;
}) {
  const lastEmail = deliveries[0]?.sent_to ?? "";

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-lg shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-[#0F172A]">
            Delivery History — {invoice.invoice_no}
          </h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={14} /></button>
        </div>
        {deliveries.length === 0 ? (
          <p className="text-xs text-[#94A3B8] text-center py-8">No delivery attempts yet.</p>
        ) : (
          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {deliveries.map((d) => (
              <div key={d.id} className="border border-[#F1F5F9] rounded-lg p-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-[#334155] font-medium">{d.sent_to}</span>
                  <span
                    className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                      DELIVERY_STATUS_COLOR[d.status] ?? "bg-[#F1F5F9] text-[#64748B]"
                    }`}
                  >
                    {DELIVERY_STATUS_LABEL[d.status] ?? d.status}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-1 text-[#94A3B8]">
                  <span>
                    {d.sent_at
                      ? new Date(d.sent_at).toLocaleString("en-IN")
                      : new Date(d.created_at).toLocaleString("en-IN")}
                  </span>
                  {d.sent_by_email && <span>by {d.sent_by_email}</span>}
                </div>
                {d.error_message && (
                  <p className="mt-1 text-red-600 text-[10px]">{d.error_message}</p>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-[#F1F5F9]">
          <button
            onClick={() => onResend(lastEmail)}
            className="text-xs text-emerald-600 hover:underline flex items-center gap-1"
          >
            <Send size={11} /> Resend Invoice
          </button>
          <button
            onClick={onClose}
            className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── HSN/SAC Smart Suggestions (autocomplete) ────────────────────────────────

function HsnAutocomplete({
  clientId,
  description,
  value,
  onChange,
  onPickGst,
}: {
  clientId: string;
  description: string;
  value: string;
  onChange: (hsn: string) => void;
  onPickGst?: (gstPercent: number) => void;
}) {
  const [suggestions, setSuggestions] = useState<HsnSuggestion[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  // Debounced lookup keyed on the line description — the suggestion signal.
  // All ranking/learning happens server-side (zero business logic in the frontend).
  useEffect(() => {
    const q = description.trim();
    if (q.length < 2) { setSuggestions([]); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const token = await getAuthToken();
        const res = await apiGet(
          `/api/sales-invoices/hsn-suggestions?client_id=${encodeURIComponent(clientId)}&query=${encodeURIComponent(q)}`,
          token
        );
        if (!cancelled) setSuggestions((res.data as HsnSuggestion[]) ?? []);
      } catch {
        if (!cancelled) setSuggestions([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
  }, [description, clientId]);

  const showDropdown = open && (suggestions.length > 0 || loading);

  return (
    <div className="relative">
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="998314"
        className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs font-mono"
      />
      {showDropdown && (
        <div className="absolute z-30 mt-1 w-64 max-h-56 overflow-y-auto bg-white border border-[#E2E8F0] rounded-lg shadow-lg">
          {loading && suggestions.length === 0 ? (
            <div className="px-3 py-2 text-[10px] text-[#94A3B8] flex items-center gap-1">
              <Loader2 size={11} className="animate-spin" /> Finding HSN/SAC…
            </div>
          ) : (
            suggestions.map((s) => (
              <button
                key={s.hsn_sac}
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  onChange(s.hsn_sac);
                  if (onPickGst && s.gst_rate_bps != null) onPickGst(Math.round(s.gst_rate_bps / 100));
                  setOpen(false);
                }}
                className="w-full text-left px-3 py-2 hover:bg-[#F8FAFC] border-b border-[#F8FAFC] last:border-0"
              >
                <div className="font-mono text-xs text-[#1E293B]">{s.hsn_sac}</div>
                <div className="text-[10px] text-[#94A3B8]">{s.reason}</div>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── Invoice Detail Drawer ────────────────────────────────────────────────────

function DetailRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <span className="text-xs text-[#94A3B8] flex-shrink-0">{label}</span>
      <span className={`text-xs text-[#334155] text-right break-all ${mono ? "font-mono" : ""}`}>{value}</span>
    </div>
  );
}

function InvoiceDetailDrawer({
  invoiceId,
  onClose,
  onEdit,
  onIssue,
  onSend,
  onToast,
}: {
  invoiceId: string;
  onClose: () => void;
  onEdit: (inv: SalesInvoice) => void;
  onIssue: (id: string) => void;
  onSend: (inv: SalesInvoice) => void;
  onToast: (msg: string, type: "success" | "error") => void;
}) {
  const [inv, setInv] = useState<InvoiceDetail | null>(null);
  const [deliveries, setDeliveries] = useState<InvoiceDelivery[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      const token = await getAuthToken();
      const [d, del] = await Promise.all([
        apiGet(`/api/sales-invoices/${invoiceId}`, token),
        apiGet(`/api/sales-invoices/${invoiceId}/deliveries`, token),
      ]);
      if (cancelled) return;
      if (d.success) setInv(d.data as InvoiceDetail);
      setDeliveries((del.data as InvoiceDelivery[]) ?? []);
      setLoading(false);
    }
    load();
    return () => { cancelled = true; };
  }, [invoiceId]);

  async function handleViewPdf() {
    try { await viewInvoicePdf(invoiceId); }
    catch { onToast("Unable to open PDF", "error"); }
  }

  const customerName = inv?.customers?.name ?? "—";
  const outstanding = inv ? inv.total_paise - (inv.paid_paise ?? 0) : 0;
  const posted = !!inv?.journal_entry_id;
  const lastDelivery = deliveries[0];

  // Thin SalesInvoice projection for the edit / send callbacks.
  const summary: SalesInvoice | null = inv ? {
    id: inv.id, invoice_no: inv.invoice_no, invoice_date: inv.invoice_date,
    due_date: inv.due_date, customer_id: inv.customer_id, customer_name: customerName,
    taxable_paise: inv.taxable_amount_paise, gst_paise: inv.total_gst_paise,
    total_paise: inv.total_paise, paid_paise: inv.paid_paise, status: inv.status,
    supply_state_code: inv.supply_state_code, is_interstate: inv.is_interstate,
  } : null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full max-w-md bg-white h-full shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-[#F1F5F9] px-5 py-3 flex items-center justify-between z-10">
          <h3 className="text-sm font-semibold text-[#0F172A] font-mono">{inv ? inv.invoice_no : "Invoice"}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={16} /></button>
        </div>

        {loading || !inv ? (
          <div className="p-6 space-y-3">
            {[...Array(5)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
          </div>
        ) : (
          <div className="p-5 space-y-5">
            {/* Header */}
            <section className="space-y-2">
              <div className="flex items-center justify-between">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[inv.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                  {inv.status.replace("_", " ")}
                </span>
                <span className="text-[10px] text-[#94A3B8]">{inv.is_interstate ? "Inter-state (IGST)" : "Intra-state (CGST+SGST)"}</span>
              </div>
              <DetailRow label="Customer" value={customerName} />
              <DetailRow label="Invoice Date" value={inv.invoice_date} />
              <DetailRow label="Due Date" value={inv.due_date ?? "—"} />
              <DetailRow label="Amount" value={fmt(inv.total_paise)} />
              <DetailRow label="Outstanding" value={fmt(outstanding)} />
              <DetailRow label="Created By" value={inv.created_by_name ?? "—"} />
            </section>

            {/* Line Items */}
            <section>
              <h4 className="text-xs font-semibold text-[#334155] mb-2">Line Items</h4>
              <div className="overflow-x-auto border border-[#F1F5F9] rounded-lg">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-[#94A3B8] border-b border-[#F1F5F9]">
                      <th className="px-2 py-1.5 text-left font-semibold">Description</th>
                      <th className="px-2 py-1.5 text-left font-semibold">HSN/SAC</th>
                      <th className="px-2 py-1.5 text-right font-semibold">Qty</th>
                      <th className="px-2 py-1.5 text-right font-semibold">Rate</th>
                      <th className="px-2 py-1.5 text-right font-semibold">GST%</th>
                      <th className="px-2 py-1.5 text-right font-semibold">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {inv.lines.map((l, i) => (
                      <tr key={l.id ?? i}>
                        <td className="px-2 py-1.5 text-[#334155]">{l.description}</td>
                        <td className="px-2 py-1.5 font-mono text-[#64748B]">{l.hsn_sac || "—"}</td>
                        <td className="px-2 py-1.5 text-right text-[#334155]">{l.quantity}</td>
                        <td className="px-2 py-1.5 text-right font-mono text-[#334155]">{fmt(l.rate_paise)}</td>
                        <td className="px-2 py-1.5 text-right text-[#334155]">{l.gst_rate_bps / 100}%</td>
                        <td className="px-2 py-1.5 text-right font-mono text-[#0F172A]">{fmt(l.line_total_paise)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {/* Accounting */}
            <section className="space-y-2">
              <h4 className="text-xs font-semibold text-[#334155]">Accounting</h4>
              <DetailRow label="Journal Entry ID" value={inv.journal_entry_id ?? "—"} mono />
              <DetailRow label="Posting Status" value={posted ? "Posted" : "Not posted"} />
              <DetailRow label="Issued At" value={fmtDateTime(inv.issued_at)} />
            </section>

            {/* Delivery */}
            <section className="space-y-2">
              <h4 className="text-xs font-semibold text-[#334155]">Delivery</h4>
              {lastDelivery ? (
                <>
                  <DetailRow label="Email Status" value={DELIVERY_STATUS_LABEL[lastDelivery.status] ?? lastDelivery.status} />
                  <DetailRow label="Sent To" value={lastDelivery.sent_to} />
                  <DetailRow label="Sent At" value={fmtDateTime(lastDelivery.sent_at ?? lastDelivery.created_at)} />
                  {deliveries.length > 1 && (
                    <div className="text-[10px] text-[#94A3B8] pt-1">{deliveries.length} delivery attempts</div>
                  )}
                </>
              ) : (
                <p className="text-xs text-[#94A3B8]">Not sent yet.</p>
              )}
            </section>

            {/* Actions */}
            <div className="flex flex-wrap gap-2 pt-3 border-t border-[#F1F5F9]">
              {inv.status === "draft" && summary && (
                <button onClick={() => onEdit(summary)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] flex items-center gap-1">
                  <Pencil size={12} /> Edit
                </button>
              )}
              {inv.status === "draft" && (
                <button onClick={() => onIssue(inv.id)} className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 flex items-center gap-1">
                  <CheckCircle size={12} /> Issue
                </button>
              )}
              {inv.status !== "draft" && inv.status !== "cancelled" && summary && (
                <button onClick={() => onSend(summary)} className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 flex items-center gap-1">
                  <Send size={12} /> Send Email
                </button>
              )}
              <button onClick={handleViewPdf} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] flex items-center gap-1">
                <Download size={12} /> View PDF
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Delete Draft Confirmation ────────────────────────────────────────────────

function DeleteInvoiceModal({
  invoice,
  onConfirm,
  onClose,
}: {
  invoice: SalesInvoice;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handle() {
    setDeleting(true); setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete invoice");
      setDeleting(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-md shadow-xl">
        <div className="flex items-start gap-3 mb-4">
          <div className="p-2 rounded-full bg-red-50 text-red-600 flex-shrink-0"><AlertTriangle size={16} /></div>
          <div>
            <h3 className="text-sm font-semibold text-[#0F172A]">Delete draft invoice?</h3>
            <p className="text-xs text-[#64748B] mt-1">
              <span className="font-mono">{invoice.invoice_no}</span> will be removed from your invoice
              list. Only drafts can be deleted — issued, partially-paid, paid and cancelled invoices are
              permanent records and are protected.
            </p>
          </div>
        </div>
        {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2 mb-3">{error}</p>}
        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
          <button
            onClick={handle}
            disabled={deleting}
            className="text-xs px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {deleting ? "Deleting…" : <><Trash2 size={12} /> Delete Draft</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Customers Tab ──────────────────────────────────────────────────────────

function Customers({
  clientId,
}: {
  clientId: string;
  financialYear: string;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [editCustomer, setEditCustomer] = useState<Customer | null>(null);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("customers")
      .select(
        "id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active"
      )
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name");
    setCustomers((data as Customer[]) ?? []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }

  async function deactivateCustomer(id: string) {
    const supabase = getSupabaseClient();
    const { error } = await supabase
      .from("customers")
      .update({ is_active: false })
      .eq("id", id);
    if (error) { showToast("Failed to deactivate customer", "error"); return; }
    showToast("Customer deactivated", "success");
    load();
  }

  /** Bulk-import customers through the EXISTING /api/customers/ endpoint. */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const { records, errors } = buildCustomers(rows, clientId);
    const token = await getAuthToken();
    let imported = 0;
    for (const c of records) {
      const result = await apiCall("/api/customers/", "POST", c, token);
      if (result.success) imported++;
      else errors.push(`Customer "${c.name}": ${result.error ?? "failed to create"}`);
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  return (
    <div className="space-y-4 max-w-4xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {customers.length} active customer{customers.length !== 1 ? "s" : ""}
        </p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
          >
            <Upload size={12} /> Import
          </button>
          <button
            onClick={() => { setEditCustomer(null); setShowForm(true); }}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> Add Customer
          </button>
        </div>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Customers"
          columns={CUSTOMER_IMPORT_COLUMNS}
          templateFilename="customers-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {showForm && (
        <CustomerForm
          clientId={clientId}
          existing={editCustomer}
          onSaved={() => {
            setShowForm(false);
            setEditCustomer(null);
            load();
            showToast(editCustomer ? "Customer updated" : "Customer added", "success");
          }}
          onCancel={() => { setShowForm(false); setEditCustomer(null); }}
        />
      )}

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
        </div>
      ) : customers.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#64748B]">No customers yet</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-4 py-3 text-left font-semibold">Name</th>
                  <th className="px-3 py-3 text-left font-semibold">GSTIN</th>
                  <th className="px-3 py-3 text-left font-semibold">State</th>
                  <th className="px-3 py-3 text-right font-semibold">Credit Days</th>
                  <th className="px-3 py-3 text-right font-semibold">Opening Balance</th>
                  <th className="px-4 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {customers.map((c) => (
                  <tr key={c.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5 font-medium text-[#1E293B]">
                      {c.name}
                      {c.email && <div className="text-[10px] text-[#94A3B8]">{c.email}</div>}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-[#64748B]">{c.gstin ?? "—"}</td>
                    <td className="px-3 py-2.5 text-[#64748B]">{c.state ?? c.state_code ?? "—"}</td>
                    <td className="px-3 py-2.5 text-right text-[#334155]">{c.credit_days ?? 0}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#334155]">
                      {fmt(c.opening_balance_paise ?? 0)}
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-3">
                        <button
                          onClick={() => { setEditCustomer(c); setShowForm(true); }}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Edit
                        </button>
                        <button
                          onClick={() => deactivateCustomer(c.id)}
                          className="text-xs text-red-500 hover:underline"
                        >
                          Deactivate
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Customer Form ──────────────────────────────────────────────────────────

function CustomerForm({
  clientId,
  existing,
  onSaved,
  onCancel,
}: {
  clientId: string;
  existing: Customer | null;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(existing?.name ?? "");
  const [gstin, setGstin] = useState(existing?.gstin ?? "");
  const [stateCode, setStateCode] = useState(existing?.state_code ?? "");
  const [pan, setPan] = useState(existing?.pan ?? "");
  const [email, setEmail] = useState(existing?.email ?? "");
  const [phone, setPhone] = useState(existing?.phone ?? "");
  const [city, setCity] = useState(existing?.city ?? "");
  const [state, setState] = useState(existing?.state ?? "");
  const [openingBalance, setOpeningBalance] = useState(
    existing ? (existing.opening_balance_paise / 100).toFixed(2) : ""
  );
  const [creditDays, setCreditDays] = useState(String(existing?.credit_days ?? 30));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Auto-fill state code from GSTIN (first 2 digits)
  function handleGstinChange(val: string) {
    const upper = val.toUpperCase();
    setGstin(upper);
    if (upper.length >= 2) {
      setStateCode(upper.slice(0, 2));
    }
  }

  async function handleSave() {
    if (!name.trim()) { setError("Name is required"); return; }
    if (gstin && !isValidGstin(gstin)) { setError("Invalid GSTIN format (e.g. 27AABCU9603R1ZX)"); return; }
    if (pan && !isValidPan(pan)) { setError("Invalid PAN format (e.g. ABCDE1234F)"); return; }

    setSaving(true); setError(null);
    try {
      // All amounts in integer paise — user enters rupees, multiply by 100
      const openingBalancePaise = Math.round(parseFloat(openingBalance || "0") * 100);
      const token = await getAuthToken();

      if (existing) {
        // UPDATE: still use Supabase directly (no dedicated PATCH endpoint for customers)
        const supabase = getSupabaseClient();
        const { error: updErr } = await supabase
          .from("customers")
          .update({
            client_id: clientId,
            name: name.trim(),
            gstin: gstin.trim() || null,
            state_code: stateCode || null,
            pan: pan.trim() || null,
            email: email.trim() || null,
            phone: phone.trim() || null,
            city: city.trim() || null,
            state: state.trim() || null,
            opening_balance_paise: openingBalancePaise,
            credit_days: parseInt(creditDays) || 30,
            is_active: true,
          })
          .eq("id", existing.id);
        if (updErr) throw new Error(updErr.message);
      } else {
        const result = await apiCall(
          "/api/customers/",
          "POST",
          {
            client_id: clientId,
            name: name.trim(),
            gstin: gstin.trim() || undefined,
            state_code: stateCode || undefined,
            pan: pan.trim() || undefined,
            email: email.trim() || undefined,
            phone: phone.trim() || undefined,
            city: city.trim() || undefined,
            state: state.trim() || undefined,
            opening_balance_paise: openingBalancePaise,
            credit_days: parseInt(creditDays) || 30,
          },
          token
        );
        if (!result.success) throw new Error(result.error ?? "Failed to save customer");
      }
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save customer");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">
          {existing ? "Edit Customer" : "Add Customer"}
        </h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="col-span-2 lg:col-span-1">
          <label className="block text-xs font-medium text-[#475569] mb-1">Name *</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="ABC Pvt Ltd"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">GSTIN</label>
          <input
            value={gstin}
            onChange={(e) => handleGstinChange(e.target.value)}
            placeholder="27AABCU9603R1ZX"
            maxLength={15}
            className={`w-full px-3 py-1.5 text-xs border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono ${
              gstin && !isValidGstin(gstin) ? "border-red-300" : "border-[#E2E8F0]"
            }`}
          />
          {gstin && !isValidGstin(gstin) && (
            <p className="text-[10px] text-red-500 mt-0.5">Invalid GSTIN</p>
          )}
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">State Code</label>
          <select
            value={stateCode}
            onChange={(e) => setStateCode(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Select —</option>
            {INDIAN_STATES.map((s) => (
              <option key={s.code} value={s.code}>{s.code} — {s.name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">PAN</label>
          <input
            value={pan}
            onChange={(e) => setPan(e.target.value.toUpperCase())}
            placeholder="ABCDE1234F"
            maxLength={10}
            className={`w-full px-3 py-1.5 text-xs border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono ${
              pan && !isValidPan(pan) ? "border-red-300" : "border-[#E2E8F0]"
            }`}
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="billing@abc.com"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Phone</label>
          <input
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+91 98765 43210"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">City</label>
          <input
            value={city}
            onChange={(e) => setCity(e.target.value)}
            placeholder="Mumbai"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">State</label>
          <input
            value={state}
            onChange={(e) => setState(e.target.value)}
            placeholder="Maharashtra"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Opening Balance (₹)</label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={openingBalance}
            onChange={(e) => setOpeningBalance(e.target.value)}
            placeholder="0.00"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Credit Days</label>
          <input
            type="number"
            min="0"
            value={creditDays}
            onChange={(e) => setCreditDays(e.target.value)}
            placeholder="30"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : existing ? "Update Customer" : "Add Customer"}
        </button>
      </div>
    </div>
  );
}

// ── Receipts Tab ───────────────────────────────────────────────────────────

function Receipts({
  clientId,
  financialYear,
}: {
  clientId: string;
  financialYear: string;
}) {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);

    const [{ data: recData }, { data: custData }] = await Promise.all([
      supabase
        .from("receipts")
        .select("id, receipt_no, receipt_date, customer_id, amount_paise, payment_mode, reference_no, allocated_paise, customers(name)")
        .eq("client_id", clientId)
        .gte("receipt_date", start)
        .lte("receipt_date", end)
        .order("receipt_date", { ascending: false }),
      supabase
        .from("customers")
        .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name"),
    ]);

    const mapped: Receipt[] = ((recData ?? []) as unknown as Array<
      Receipt & { customers: { name: string } | null }
    >).map((r) => ({
      ...r,
      customer_name: r.customers?.name ?? "—",
    }));

    setReceipts(mapped);
    setCustomers((custData as Customer[]) ?? []);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }

  /** Bulk-import unallocated receipts through the EXISTING /api/receipts/ endpoint. */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const { records, errors } = buildReceipts(rows, clientId, customers);
    const token = await getAuthToken();
    let imported = 0;
    for (const rec of records) {
      const result = await apiCall("/api/receipts/", "POST", rec, token);
      if (result.success) imported++;
      else errors.push(`Receipt for "${rec.customer_id}" on ${rec.receipt_date}: ${result.error ?? "failed to create"}`);
    }
    if (imported > 0) load();
    return { imported, errors };
  }

  return (
    <div className="space-y-4 max-w-4xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {receipts.length} receipt{receipts.length !== 1 ? "s" : ""} in FY {financialYear}
        </p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
          >
            <Upload size={12} /> Import
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> Record Receipt
          </button>
        </div>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Receipts"
          columns={RECEIPT_IMPORT_COLUMNS}
          templateFilename="receipts-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {showForm && (
        <ReceiptForm
          clientId={clientId}
          customers={customers}
          onSaved={() => { setShowForm(false); load(); showToast("Receipt recorded", "success"); }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
        </div>
      ) : receipts.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#64748B]">No receipts in FY {financialYear}</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-4 py-3 text-left font-semibold">Receipt No</th>
                  <th className="px-3 py-3 text-left font-semibold">Date</th>
                  <th className="px-3 py-3 text-left font-semibold">Customer</th>
                  <th className="px-3 py-3 text-right font-semibold">Amount</th>
                  <th className="px-3 py-3 text-left font-semibold">Mode</th>
                  <th className="px-3 py-3 text-right font-semibold">Allocated</th>
                  <th className="px-4 py-3 text-right font-semibold">Unallocated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {receipts.map((r) => {
                  const unallocated = r.amount_paise - (r.allocated_paise ?? 0);
                  return (
                    <tr key={r.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-4 py-2.5 font-mono font-medium text-[#1E293B]">{r.receipt_no}</td>
                      <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">{r.receipt_date}</td>
                      <td className="px-3 py-2.5 text-[#334155]">{r.customer_name}</td>
                      <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#0F172A]">{fmt(r.amount_paise)}</td>
                      <td className="px-3 py-2.5">
                        <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#475569] uppercase">
                          {r.payment_mode}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-green-700">{fmt(r.allocated_paise ?? 0)}</td>
                      <td className="px-4 py-2.5 text-right font-mono text-amber-700">{fmt(unallocated)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Receipt Form ───────────────────────────────────────────────────────────

function ReceiptForm({
  clientId,
  customers,
  onSaved,
  onCancel,
}: {
  clientId: string;
  customers: Customer[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [customerId, setCustomerId] = useState("");
  const [receiptDate, setReceiptDate] = useState(today);
  const [amount, setAmount] = useState("");
  const [paymentMode, setPaymentMode] = useState("bank");
  const [referenceNo, setReferenceNo] = useState("");
  const [openInvoices, setOpenInvoices] = useState<SalesInvoice[]>([]);
  const [allocations, setAllocations] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load open invoices for selected customer
  useEffect(() => {
    if (!customerId) { setOpenInvoices([]); return; }
    async function loadInvoices() {
      const supabase = getSupabaseClient();
      const { data } = await supabase
        .from("client_sales_invoices")
        .select("id, invoice_no, invoice_date, total_paise, status")
        .eq("client_id", clientId)
        .eq("customer_id", customerId)
        .in("status", ["issued", "partially_paid"])
        .order("invoice_date");
      setOpenInvoices((data as SalesInvoice[]) ?? []);
    }
    loadInvoices();
  }, [customerId, clientId]);

  const amountPaise = Math.round(parseFloat(amount || "0") * 100);
  const totalAllocated = Object.values(allocations).reduce(
    (s, v) => s + Math.round(parseFloat(v || "0") * 100),
    0
  );

  async function handleSave() {
    if (!customerId) { setError("Select a customer"); return; }
    if (amountPaise <= 0) { setError("Amount must be greater than zero"); return; }
    if (!receiptDate) { setError("Receipt date required"); return; }

    setSaving(true); setError(null);
    try {
      const token = await getAuthToken();

      // Build allocations array for the API
      const allocationsList = Object.entries(allocations)
        .filter(([, v]) => parseFloat(v || "0") > 0)
        .map(([invoiceId, v]) => ({
          sales_invoice_id: invoiceId,
          allocated_paise: Math.round(parseFloat(v) * 100),
        }));

      const result = await apiCall(
        "/api/receipts/",
        "POST",
        {
          client_id: clientId,
          customer_id: customerId,
          receipt_date: receiptDate,
          amount_paise: amountPaise,
          payment_mode: paymentMode,
          reference_no: referenceNo.trim() || undefined,
          allocations: allocationsList.length > 0 ? allocationsList : undefined,
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to record receipt");

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record receipt");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">Record Receipt</h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="col-span-2 lg:col-span-1">
          <label className="block text-xs font-medium text-[#475569] mb-1">Customer *</label>
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Select customer —</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Receipt Date *</label>
          <input
            type="date"
            value={receiptDate}
            onChange={(e) => setReceiptDate(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Amount (₹) *</label>
          <input
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Payment Mode</label>
          <select
            value={paymentMode}
            onChange={(e) => setPaymentMode(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {PAYMENT_MODES.map((m) => (
              <option key={m} value={m}>{m.toUpperCase()}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Reference No.</label>
          <input
            value={referenceNo}
            onChange={(e) => setReferenceNo(e.target.value)}
            placeholder="UTR / cheque no."
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* Allocate against open invoices */}
      {openInvoices.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[#475569]">Allocate against open invoices (optional)</p>
          <div className="space-y-1.5">
            {openInvoices.map((inv) => (
              <div key={inv.id} className="flex items-center gap-3">
                <span className="text-xs text-[#475569] flex-1">
                  {inv.invoice_no} — {inv.invoice_date} — {fmt(inv.total_paise)}
                  <span className={`ml-2 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[inv.status]}`}>
                    {inv.status}
                  </span>
                </span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={allocations[inv.id] ?? ""}
                  onChange={(e) => setAllocations((prev) => ({ ...prev, [inv.id]: e.target.value }))}
                  placeholder="₹ 0.00"
                  className="w-28 px-2 py-1 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right font-mono"
                />
              </div>
            ))}
          </div>
          {totalAllocated > 0 && (
            <p className="text-xs text-[#64748B]">
              Allocated: {fmt(totalAllocated)} / Unallocated: {fmt(amountPaise - totalAllocated)}
            </p>
          )}
        </div>
      )}

      {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Record Receipt"}
        </button>
      </div>
    </div>
  );
}

// ── Credit Notes Tab ───────────────────────────────────────────────────────

function CreditNotes({
  clientId,
  financialYear,
}: {
  clientId: string;
  financialYear: string;
}) {
  const [creditNotes, setCreditNotes] = useState<CreditNote[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);

    const [{ data: cnData }, { data: custData }] = await Promise.all([
      supabase
        .from("credit_notes")
        .select(
          "id, credit_note_no, credit_note_date, customer_id, sales_invoice_id, reason, taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_paise, status, customers(name), client_sales_invoices(invoice_no)"
        )
        .eq("client_id", clientId)
        .gte("credit_note_date", start)
        .lte("credit_note_date", end)
        .order("credit_note_date", { ascending: false }),
      supabase
        .from("customers")
        .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name"),
    ]);

    const mapped: CreditNote[] = ((cnData ?? []) as unknown as Array<
      { id: string; credit_note_no: string; credit_note_date: string; customer_id: string;
        sales_invoice_id: string | null; reason: string; taxable_amount_paise: number;
        cgst_paise: number; sgst_paise: number; igst_paise: number; total_paise: number;
        status: string; customers: { name: string } | null;
        client_sales_invoices: { invoice_no: string } | null }
    >).map((r) => ({
      id: r.id,
      cn_no: r.credit_note_no,
      cn_date: r.credit_note_date,
      customer_id: r.customer_id,
      customer_name: r.customers?.name ?? "—",
      original_invoice_id: r.sales_invoice_id ?? null,
      original_invoice_no: r.client_sales_invoices?.invoice_no ?? null,
      reason: r.reason,
      taxable_paise: r.taxable_amount_paise,
      gst_paise: r.cgst_paise + r.sgst_paise + r.igst_paise,
      total_paise: r.total_paise,
      status: r.status as "draft" | "issued" | "cancelled",
    }));

    setCreditNotes(mapped);
    setCustomers((custData as Customer[]) ?? []);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }

  async function issueCreditNote(id: string) {
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/credit-notes/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue credit note");
      showToast("Credit note issued", "success");
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Error issuing credit note", "error");
    }
  }

  return (
    <div className="space-y-4 max-w-4xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {creditNotes.length} credit note{creditNotes.length !== 1 ? "s" : ""} in FY {financialYear}
        </p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> Create Credit Note
          </button>
        </div>
      </div>

      {showForm && (
        <CreditNoteForm
          clientId={clientId}
          customers={customers}
          onSaved={() => { setShowForm(false); load(); showToast("Credit note created", "success"); }}
          onCancel={() => setShowForm(false)}
        />
      )}

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}
        </div>
      ) : creditNotes.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#64748B]">No credit notes in FY {financialYear}</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-4 py-3 text-left font-semibold">CN No</th>
                  <th className="px-3 py-3 text-left font-semibold">Date</th>
                  <th className="px-3 py-3 text-left font-semibold">Customer</th>
                  <th className="px-3 py-3 text-left font-semibold">Orig. Invoice</th>
                  <th className="px-3 py-3 text-left font-semibold">Reason</th>
                  <th className="px-3 py-3 text-right font-semibold">Total</th>
                  <th className="px-3 py-3 text-left font-semibold">Status</th>
                  <th className="px-4 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {creditNotes.map((cn) => (
                  <tr key={cn.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5 font-mono font-medium text-[#1E293B]">{cn.cn_no}</td>
                    <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">{cn.cn_date}</td>
                    <td className="px-3 py-2.5 text-[#334155]">{cn.customer_name}</td>
                    <td className="px-3 py-2.5 font-mono text-[#64748B]">{cn.original_invoice_no ?? "—"}</td>
                    <td className="px-3 py-2.5 text-[#475569] max-w-[120px] truncate">{cn.reason}</td>
                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#0F172A]">{fmt(cn.total_paise)}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[cn.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                        {cn.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      {cn.status === "draft" && (
                        <button
                          onClick={() => issueCreditNote(cn.id)}
                          className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                        >
                          <CheckCircle size={11} /> Issue
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Credit Note Form ───────────────────────────────────────────────────────

function CreditNoteForm({
  clientId,
  customers,
  onSaved,
  onCancel,
}: {
  clientId: string;
  customers: Customer[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [customerId, setCustomerId] = useState("");
  const [cnDate, setCnDate] = useState(today);
  const [reason, setReason] = useState("");
  const [originalInvoiceId, setOriginalInvoiceId] = useState("");
  const [isInterstate, setIsInterstate] = useState(false);
  const [customerInvoices, setCustomerInvoices] = useState<SalesInvoice[]>([]);
  const [lines, setLines] = useState<InvoiceLine[]>([
    { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const gst = computeGst(lines, isInterstate);

  // Load customer's invoices for selection
  useEffect(() => {
    if (!customerId) { setCustomerInvoices([]); return; }
    async function loadInvoices() {
      const supabase = getSupabaseClient();
      const { data } = await supabase
        .from("client_sales_invoices")
        .select("id, invoice_no, invoice_date, total_paise, status")
        .eq("client_id", clientId)
        .eq("customer_id", customerId)
        .order("invoice_date", { ascending: false });
      setCustomerInvoices((data as SalesInvoice[]) ?? []);
    }
    loadInvoices();
  }, [customerId, clientId]);

  function setLine(idx: number, patch: Partial<InvoiceLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18 }]);
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }

  async function handleSave() {
    if (!customerId) { setError("Select a customer"); return; }
    if (!reason.trim()) { setError("Reason is required"); return; }
    const validLines = lines.filter((l) => l.description.trim() && parseFloat(l.rate) > 0);
    if (validLines.length === 0) { setError("Add at least one line with description and rate"); return; }

    setSaving(true); setError(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(
        "/api/credit-notes/",
        "POST",
        {
          client_id: clientId,
          customer_id: customerId,
          credit_note_date: cnDate,
          reason: reason.trim(),
          sales_invoice_id: originalInvoiceId || undefined,
          lines: validLines.map((l) => ({
            description: l.description.trim(),
            hsn_sac: l.hsn_sac.trim() || undefined,
            quantity: parseFloat(l.qty),
            rate_paise: Math.round(parseFloat(l.rate) * 100),
            gst_rate_bps: l.gst_rate * 100,
          })),
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to create credit note");

      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save credit note");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-[#0F172A]">Create Credit Note</h3>
        <button onClick={onCancel} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Customer *</label>
          <select
            value={customerId}
            onChange={(e) => setCustomerId(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">— Select customer —</option>
            {customers.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">CN Date *</label>
          <input
            type="date"
            value={cnDate}
            onChange={(e) => setCnDate(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-[#475569] mb-1">Original Invoice (optional)</label>
          <select
            value={originalInvoiceId}
            onChange={(e) => setOriginalInvoiceId(e.target.value)}
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            disabled={!customerId}
          >
            <option value="">— None —</option>
            {customerInvoices.map((inv) => (
              <option key={inv.id} value={inv.id}>
                {inv.invoice_no} — {fmt(inv.total_paise)}
              </option>
            ))}
          </select>
        </div>
        <div className="col-span-2">
          <label className="block text-xs font-medium text-[#475569] mb-1">Reason *</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Goods returned / rate correction / excess billed"
            className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex items-end pb-1.5">
          <label className="flex items-center gap-2 text-xs text-[#475569] cursor-pointer">
            <input
              type="checkbox"
              checked={isInterstate}
              onChange={(e) => setIsInterstate(e.target.checked)}
              className="rounded"
            />
            Interstate (IGST)
          </label>
        </div>
      </div>

      {/* Lines */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
              <th className="pb-2 text-left font-semibold">Description</th>
              <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
              <th className="pb-2 text-right font-semibold w-16">Qty</th>
              <th className="pb-2 text-right font-semibold w-24">Rate (₹)</th>
              <th className="pb-2 text-right font-semibold w-20">GST %</th>
              <th className="pb-2 text-right font-semibold w-24">Amount</th>
              <th className="pb-2 w-6" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F8FAFC]">
            {lines.map((line, idx) => {
              const lineTaxable = Math.round((parseFloat(line.qty) || 0) * (parseFloat(line.rate) || 0) * 100);
              const lineTotal = lineTaxable + Math.round((lineTaxable * line.gst_rate) / 100);
              return (
                <tr key={idx}>
                  <td className="py-1.5 pr-2">
                    <input
                      value={line.description}
                      onChange={(e) => setLine(idx, { description: e.target.value })}
                      placeholder="Item description"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      value={line.hsn_sac}
                      onChange={(e) => setLine(idx, { hsn_sac: e.target.value })}
                      placeholder="998314"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs font-mono"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number" min="0" step="0.001" value={line.qty}
                      onChange={(e) => setLine(idx, { qty: e.target.value })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      type="number" min="0" step="0.01" value={line.rate}
                      onChange={(e) => setLine(idx, { rate: e.target.value })}
                      placeholder="0.00"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <select
                      value={line.gst_rate}
                      onChange={(e) => setLine(idx, { gst_rate: parseInt(e.target.value) })}
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    >
                      {GST_RATES.map((r) => <option key={r} value={r}>{r}%</option>)}
                    </select>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono text-[#334155]">
                    {lineTotal > 0 ? fmt(lineTotal) : "—"}
                  </td>
                  <td className="py-1.5">
                    {lines.length > 1 && (
                      <button onClick={() => removeLine(idx)} className="text-[#CBD5E1] hover:text-red-600">
                        <X size={13} />
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <button onClick={addLine} className="text-xs text-blue-600 hover:underline flex items-center gap-1">
        <Plus size={12} /> Add line
      </button>

      {/* GST Preview */}
      {gst.taxable_paise > 0 && (
        <div className="bg-[#F8FAFC] rounded-lg p-3 text-xs space-y-1">
          <p className="font-semibold text-[#334155] mb-2">GST Computation (Credit Note)</p>
          <div className="flex justify-between text-[#475569]">
            <span>Taxable Value</span>
            <span className="font-mono">{fmt(gst.taxable_paise)}</span>
          </div>
          {isInterstate ? (
            <div className="flex justify-between text-[#475569]">
              <span>IGST</span>
              <span className="font-mono">{fmt(gst.igst_paise)}</span>
            </div>
          ) : (
            <>
              <div className="flex justify-between text-[#475569]">
                <span>CGST</span>
                <span className="font-mono">{fmt(gst.cgst_paise)}</span>
              </div>
              <div className="flex justify-between text-[#475569]">
                <span>SGST</span>
                <span className="font-mono">{fmt(gst.sgst_paise)}</span>
              </div>
            </>
          )}
          <div className="flex justify-between font-semibold text-[#0F172A] border-t border-[#E2E8F0] pt-1 mt-1">
            <span>Total Credit Note Amount</span>
            <span className="font-mono">{fmt(gst.total_paise)}</span>
          </div>
        </div>
      )}

      {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Credit Note"}
        </button>
      </div>
    </div>
  );
}

// ── Summary Card ───────────────────────────────────────────────────────────

function SummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: "amber" | "blue" | "green" | "red" | "gray";
}) {
  const colors = {
    amber: "bg-amber-50 border-amber-100",
    blue: "bg-blue-50 border-blue-100",
    green: "bg-green-50 border-green-100",
    red: "bg-red-50 border-red-100",
    gray: "bg-white border-[#F1F5F9]",
  };
  const text = {
    amber: "text-amber-800",
    blue: "text-blue-800",
    green: "text-green-800",
    red: "text-red-800",
    gray: "text-[#1E293B]",
  };
  return (
    <div className={`rounded-xl border p-4 ${colors[color]}`}>
      <p className="text-[10px] font-medium text-[#64748B] mb-1">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${text[color]}`}>{value}</p>
    </div>
  );
}
