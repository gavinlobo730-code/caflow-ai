"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, RefreshCw, Upload, AlertCircle, CheckCircle, X } from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";

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
  if (!res.ok) {
    // Try to parse a structured error from the response body.
    // FastAPI returns { detail: ... } for 422/4xx; our API returns { error: ... }.
    const text = await res.text().catch(() => "");
    let errorMsg = `Request failed (HTTP ${res.status})`;
    if (text) {
      try {
        const json = JSON.parse(text);
        if (typeof json.error === "string" && json.error) {
          errorMsg = json.error;
        } else if (json.detail) {
          if (typeof json.detail === "string") {
            errorMsg = json.detail;
          } else if (Array.isArray(json.detail)) {
            // FastAPI validation errors: [{ loc, msg, type }, ...]
            errorMsg = json.detail
              .map((e: { loc?: string[]; msg?: string }) =>
                [e.loc?.slice(1).join("."), e.msg].filter(Boolean).join(": ")
              )
              .join("; ");
          }
        }
      } catch {
        // Not JSON — use the raw text if it's short enough to be meaningful
        if (text.length < 300) errorMsg = text;
      }
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

type PurchaseTab = "bills" | "vendors" | "payments";
const TABS: { id: PurchaseTab; label: string }[] = [
  { id: "bills", label: "Purchase Bills" },
  { id: "vendors", label: "Vendors" },
  { id: "payments", label: "Payments" },
];

function fmt(paise: number): string {
  if (paise === 0) return "—";
  return "₹" + new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(paise) / 100);
}

function fyRange(fy: string): { start: string; end: string } {
  const [y] = fy.split("-");
  const yr = parseInt(y);
  return { start: `${yr}-04-01`, end: `${yr + 1}-03-31` };
}

function toDate(): string {
  return new Date().toISOString().split("T")[0];
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function PurchasesPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<PurchaseTab>("bills");

  if (!clientId || clientId === "_placeholder") {
    return (
      <div className="px-6 py-4">
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[#F8FAFC] animate-pulse" />)}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex-shrink-0 overflow-x-auto px-6 pt-5 pb-0">
        <div className="flex gap-0.5 bg-[#F8FAFC] rounded-lg p-1 w-fit">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors whitespace-nowrap ${
                tab === t.id ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 pb-6 pt-4 min-h-0">
        {tab === "bills" && <PurchaseBills clientId={clientId} financialYear={financialYear} />}
        {tab === "vendors" && <Vendors clientId={clientId} financialYear={financialYear} />}
        {tab === "payments" && <Payments clientId={clientId} financialYear={financialYear} />}
      </div>
    </div>
  );
}

// ── Status badge ───────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#475569]",
  received: "bg-blue-100 text-blue-700",
  partially_paid: "bg-amber-100 text-amber-700",
  paid: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-700",
};

// ── TDS section options ────────────────────────────────────────────────────

const TDS_SECTIONS = [
  { value: "194C", label: "194C — Contractors (1%/2%)" },
  { value: "194I", label: "194I — Rent (10%)" },
  { value: "194J", label: "194J — Professional/Technical (10%)" },
  { value: "194H", label: "194H — Commission (5%)" },
  { value: "194A", label: "194A — Interest (10%)" },
];

const TDS_DEFAULT_RATES: Record<string, number> = {
  "194C": 200,  // 2% in bps
  "194I": 1000, // 10%
  "194J": 1000, // 10%
  "194H": 500,  // 5%
  "194A": 1000, // 10%
};

const GST_RATES = [
  { label: "0%", bps: 0 },
  { label: "5%", bps: 500 },
  { label: "12%", bps: 1200 },
  { label: "18%", bps: 1800 },
  { label: "28%", bps: 2800 },
];

// ── Purchase Bills ─────────────────────────────────────────────────────────

interface BillLine {
  description: string;
  hsn_sac: string;
  quantity: number;
  rate: number; // rupees
  gst_rate_bps: number;
  expense_account_id: string;
}

interface Vendor {
  id: string;
  name: string;
  gstin: string | null;
  tds_applicable: boolean;
  tds_section: string | null;
  tds_rate_bps: number;
}

interface PurchaseBillRow {
  id: string;
  bill_no: string | null;
  our_reference: string | null;
  bill_date: string;
  due_date: string | null;
  vendor_id: string;
  vendors?: { name: string };
  taxable_amount_paise: number;
  total_gst_paise: number;
  tds_paise: number;
  net_payable_paise: number;
  total_paise: number;
  status: string;
  is_ai_extracted: boolean;
}

function PurchaseBills({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [bills, setBills] = useState<PurchaseBillRow[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [accounts, setAccounts] = useState<{ id: string; account_code: string; account_name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [aiExtracted, setAiExtracted] = useState<Record<string, unknown> | null>(null);

  // Form state
  const [vendorId, setVendorId] = useState("");
  const [billNo, setBillNo] = useState("");
  const [billDate, setBillDate] = useState(toDate());
  const [dueDate, setDueDate] = useState("");
  const [lines, setLines] = useState<BillLine[]>([
    { description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800, expense_account_id: "" },
  ]);

  const selectedVendor = vendors.find((v) => v.id === vendorId);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    const [billsRes, vendorsRes, accsRes] = await Promise.all([
      supabase
        .from("purchase_bills")
        .select("*, vendors(name)")
        .eq("client_id", clientId)
        .gte("bill_date", start)
        .lte("bill_date", end)
        .order("bill_date", { ascending: false }),
      supabase
        .from("vendors")
        .select("id, name, gstin, tds_applicable, tds_section, tds_rate_bps")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name"),
      supabase
        .from("chart_of_accounts")
        .select("id, account_code, account_name")
        .or(`client_id.eq.${clientId},client_id.is.null`)
        .in("account_type", ["Expense", "Asset"])
        .eq("is_active", true)
        .order("account_code"),
    ]);
    setBills((billsRes.data as PurchaseBillRow[]) ?? []);
    setVendors((vendorsRes.data as Vendor[]) ?? []);
    setAccounts(accsRes.data ?? []);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  // Compute GST for a line (integer basis points)
  function lineGst(line: BillLine) {
    const taxable = Math.round(line.quantity * line.rate * 100); // paise
    const gst_paise = Math.floor((taxable * line.gst_rate_bps) / 10000);
    return {
      taxable_paise: taxable,
      gst_paise,
      line_total: taxable + gst_paise,
    };
  }

  const totals = lines.reduce(
    (acc, l) => {
      const g = lineGst(l);
      return {
        taxable: acc.taxable + g.taxable_paise,
        gst: acc.gst + g.gst_paise,
        total: acc.total + g.line_total,
      };
    },
    { taxable: 0, gst: 0, total: 0 }
  );

  const tds_paise =
    selectedVendor?.tds_applicable && selectedVendor.tds_rate_bps > 0
      ? Math.floor((totals.taxable * selectedVendor.tds_rate_bps) / 10000)
      : 0;

  const net_payable = totals.total - tds_paise;

  function setLine(idx: number, patch: Partial<BillLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }

  // AI document extraction
  async function handleExtract() {
    if (!uploadFile) return;
    setExtracting(true);
    setAiExtracted(null);
    try {
      const formData = new FormData();
      formData.append("file", uploadFile);
      formData.append("client_id", clientId);
      const token = (await getSupabaseClient().auth.getSession()).data.session?.access_token;
      const res = await fetch(`${API}/api/document-intelligence-v1/extract-invoice`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      const json = await res.json();
      if (json.success && json.data?.extracted) {
        const ex = json.data.extracted;
        setAiExtracted(ex);
        // Pre-fill form
        if (ex.invoice_no) setBillNo(ex.invoice_no);
        if (ex.invoice_date) setBillDate(ex.invoice_date);
        if (ex.line_items?.length) {
          setLines(
            (ex.line_items as Array<Record<string, unknown>>).map((li) => ({
              description: String(li.description ?? ""),
              hsn_sac: String(li.hsn_sac ?? ""),
              quantity: Number(li.quantity ?? 1),
              rate: Math.floor(Number(li.rate_paise ?? 0)) / 100,
              gst_rate_bps: Number(li.gst_rate_bps ?? 1800),
              expense_account_id: "",
            }))
          );
        }
      }
    } catch {
      /* non-blocking */
    } finally {
      setExtracting(false);
    }
  }

  async function handleSave() {
    if (!vendorId) { setMsg({ type: "err", text: "Select a vendor" }); return; }
    if (lines.some((l) => !l.description)) { setMsg({ type: "err", text: "All lines need a description" }); return; }
    setSaving(true);
    setMsg(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(
        "/api/purchase-bills/",
        "POST",
        {
          client_id: clientId,
          vendor_id: vendorId,
          bill_date: billDate,
          due_date: dueDate || undefined,
          bill_no: billNo || undefined,
          lines: lines.map((l) => ({
            description: l.description,
            hsn_sac: l.hsn_sac || undefined,
            quantity: l.quantity,
            rate_paise: Math.round(l.rate * 100),
            gst_rate_bps: l.gst_rate_bps,
            expense_account_id: l.expense_account_id || undefined,
          })),
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to create bill");

      setMsg({ type: "ok", text: "Purchase bill saved as draft." });
      setShowForm(false);
      setLines([{ description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800, expense_account_id: "" }]);
      setBillNo(""); setVendorId(""); setBillDate(toDate()); setDueDate(""); setAiExtracted(null);
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  async function handleReceive(billId: string) {
    try {
      const token = await getAuthToken();
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      await apiCall(`/api/purchase-bills/${billId}/receive`, "POST", undefined, token);
      load();
    } catch { /* skip */ }
  }

  const totalPayable = bills.filter((b) => !["paid", "cancelled"].includes(b.status))
    .reduce((s, b) => s + b.net_payable_paise, 0);
  const totalThisFy = bills.reduce((s, b) => s + b.total_paise, 0);

  return (
    <div className="space-y-4 max-w-5xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      {/* Summary strip */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Outstanding Payable</p>
          <p className="text-lg font-bold text-orange-700 tabular-nums">{fmt(totalPayable)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Total Bills (FY)</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{fmt(totalThisFy)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Bills This FY</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{bills.length}</p>
        </div>
      </div>

      <div className="flex justify-between items-center">
        <p className="text-xs font-semibold text-[#334155]">Purchase Bills — FY {financialYear}</p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC]">
            <RefreshCw size={13} className={loading ? "animate-spin text-[#94A3B8]" : "text-[#94A3B8]"} />
          </button>
          <button
            onClick={() => setShowForm((s) => !s)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> New Bill
          </button>
        </div>
      </div>

      {/* Create form */}
      {showForm && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#0F172A]">New Purchase Bill</h3>
            <button onClick={() => setShowForm(false)} className="text-[#94A3B8] hover:text-[#475569]"><X size={16} /></button>
          </div>

          {/* AI Upload */}
          <div className="bg-amber-50 border border-amber-100 rounded-lg p-3 space-y-2">
            <p className="text-xs font-medium text-amber-800 flex items-center gap-1.5"><Upload size={12} /> Upload Invoice (AI Extract)</p>
            <div className="flex items-center gap-2">
              <input
                type="file"
                accept=".pdf,.png,.jpg,.jpeg"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                className="text-xs text-[#475569]"
              />
              <button
                onClick={handleExtract}
                disabled={!uploadFile || extracting}
                className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40"
              >
                {extracting ? "Extracting…" : "Extract"}
              </button>
            </div>
            {aiExtracted && (
              <div className="mt-1 text-[10px] text-amber-700 bg-amber-100 rounded px-2 py-1.5">
                ✓ AI extracted data pre-filled below. <strong>Review before saving.</strong>
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
              <select value={vendorId} onChange={(e) => setVendorId(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">— Select vendor —</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}{v.tds_applicable ? ` (TDS ${(v.tds_rate_bps / 100).toFixed(0)}%)` : ""}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor Invoice No.</label>
              <input value={billNo} onChange={(e) => setBillNo(e.target.value)} placeholder="INV-001" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Bill Date *</label>
              <input type="date" value={billDate} onChange={(e) => setBillDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Due Date</label>
              <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          {/* TDS info banner */}
          {selectedVendor?.tds_applicable && (
            <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 text-xs text-blue-700">
              TDS applicable — §{selectedVendor.tds_section} @ {(selectedVendor.tds_rate_bps / 100).toFixed(1)}%
              {totals.taxable > 0 && ` | TDS: ${fmt(tds_paise)} | Net payable: ${fmt(net_payable)}`}
            </div>
          )}

          {/* Lines */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="pb-2 text-left font-semibold">Description *</th>
                  <th className="pb-2 text-left font-semibold w-24">HSN/SAC</th>
                  <th className="pb-2 text-left font-semibold w-28">Expense Account</th>
                  <th className="pb-2 text-right font-semibold w-16">Qty</th>
                  <th className="pb-2 text-right font-semibold w-28">Rate (₹)</th>
                  <th className="pb-2 text-right font-semibold w-20">GST %</th>
                  <th className="pb-2 text-right font-semibold w-28">Amount</th>
                  <th className="pb-2 w-6" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {lines.map((line, idx) => {
                  const g = lineGst(line);
                  return (
                    <tr key={idx}>
                      <td className="py-1.5 pr-2">
                        <input value={line.description} onChange={(e) => setLine(idx, { description: e.target.value })} placeholder="Item description" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <input value={line.hsn_sac} onChange={(e) => setLine(idx, { hsn_sac: e.target.value })} placeholder="HSN/SAC" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.expense_account_id} onChange={(e) => setLine(idx, { expense_account_id: e.target.value })} className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          <option value="">— Account —</option>
                          {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_code} {a.account_name}</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0.001" step="0.001" value={line.quantity} onChange={(e) => setLine(idx, { quantity: parseFloat(e.target.value) || 1 })} className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs text-right" />
                      </td>
                      <td className="py-1.5 px-1">
                        <input type="number" min="0" step="0.01" value={line.rate || ""} onChange={(e) => setLine(idx, { rate: parseFloat(e.target.value) || 0 })} placeholder="0.00" className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs text-right" />
                      </td>
                      <td className="py-1.5 px-1">
                        <select value={line.gst_rate_bps} onChange={(e) => setLine(idx, { gst_rate_bps: parseInt(e.target.value) })} className="w-full px-1 py-1 border border-[#E2E8F0] rounded focus:outline-none text-xs">
                          {GST_RATES.map((r) => <option key={r.bps} value={r.bps}>{r.label}</option>)}
                        </select>
                      </td>
                      <td className="py-1.5 px-1 text-right font-mono text-[#334155]">
                        {g.taxable_paise > 0 ? fmt(g.line_total) : "—"}
                      </td>
                      <td className="py-1.5 pl-1">
                        {lines.length > 1 && <button onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))} className="text-[#CBD5E1] hover:text-red-600 font-bold">×</button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="border-t border-[#F1F5F9] text-xs font-semibold">
                  <td colSpan={6} className="pt-2 text-right text-[#64748B] pr-2">Taxable</td>
                  <td className="pt-2 text-right font-mono text-[#334155] px-1">{fmt(totals.taxable)}</td>
                  <td />
                </tr>
                <tr className="text-xs">
                  <td colSpan={6} className="text-right text-[#94A3B8] pr-2">Total GST</td>
                  <td className="text-right font-mono text-[#64748B] px-1">{fmt(totals.gst)}</td>
                  <td />
                </tr>
                {tds_paise > 0 && (
                  <tr className="text-xs">
                    <td colSpan={6} className="text-right text-blue-600 pr-2">Less: TDS</td>
                    <td className="text-right font-mono text-blue-600 px-1">({fmt(tds_paise)})</td>
                    <td />
                  </tr>
                )}
                <tr className="text-xs font-bold border-t border-[#E2E8F0]">
                  <td colSpan={6} className="pt-1 text-right text-[#1E293B] pr-2">Net Payable</td>
                  <td className="pt-1 text-right font-mono text-[#0F172A] px-1">{fmt(net_payable)}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
          <button onClick={() => setLines((prev) => [...prev, { description: "", hsn_sac: "", quantity: 1, rate: 0, gst_rate_bps: 1800, expense_account_id: "" }])} className="text-xs text-blue-600 hover:underline flex items-center gap-1"><Plus size={12} /> Add line</button>

          <div className="flex gap-3 justify-end pt-1">
            <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">
              {saving ? "Saving…" : "Save Draft"}
            </button>
          </div>
        </div>
      )}

      {/* Bills table */}
      {loading ? (
        <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[#F8FAFC] animate-pulse" />)}</div>
      ) : bills.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <p className="text-sm text-[#94A3B8]">No purchase bills for FY {financialYear}.</p>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                  <th className="px-4 py-3 text-left font-semibold">Our Ref</th>
                  <th className="px-3 py-3 text-left font-semibold">Vendor Invoice</th>
                  <th className="px-3 py-3 text-left font-semibold">Vendor</th>
                  <th className="px-3 py-3 text-left font-semibold">Date</th>
                  <th className="px-3 py-3 text-right font-semibold">Taxable</th>
                  <th className="px-3 py-3 text-right font-semibold">GST</th>
                  <th className="px-3 py-3 text-right font-semibold">TDS</th>
                  <th className="px-3 py-3 text-right font-semibold">Net Payable</th>
                  <th className="px-3 py-3 text-left font-semibold">Status</th>
                  <th className="px-4 py-3 text-left font-semibold">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {bills.map((b) => (
                  <tr key={b.id} className="hover:bg-[#F8FAFC]">
                    <td className="px-4 py-2.5 font-mono text-[#475569] text-[10px]">{b.our_reference ?? "—"}</td>
                    <td className="px-3 py-2.5 text-[#475569]">{b.bill_no ?? "—"}{b.is_ai_extracted && <span className="ml-1 text-[9px] bg-amber-100 text-amber-600 px-1 rounded">AI</span>}</td>
                    <td className="px-3 py-2.5 font-medium text-[#1E293B]">{(b.vendors as { name: string } | undefined)?.name ?? "—"}</td>
                    <td className="px-3 py-2.5 text-[#64748B]">{b.bill_date}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(b.taxable_amount_paise)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-[#64748B]">{fmt(b.total_gst_paise)}</td>
                    <td className="px-3 py-2.5 text-right font-mono text-blue-600">{b.tds_paise > 0 ? fmt(b.tds_paise) : "—"}</td>
                    <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#1E293B]">{fmt(b.net_payable_paise)}</td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_COLORS[b.status] ?? "bg-[#F1F5F9] text-[#475569]"}`}>{b.status}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      {b.status === "draft" && (
                        <button onClick={() => handleReceive(b.id)} className="text-xs text-blue-600 hover:underline">Receive</button>
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

// ── Vendors ────────────────────────────────────────────────────────────────

interface VendorRow {
  id: string;
  name: string;
  gstin: string | null;
  state_code: string | null;
  pan: string | null;
  email: string | null;
  phone: string | null;
  tds_applicable: boolean;
  tds_section: string | null;
  tds_rate_bps: number;
  opening_balance_paise: number;
  is_active: boolean;
}

const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

function Vendors({ clientId }: { clientId: string; financialYear: string }) {
  const [vendors, setVendors] = useState<VendorRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [name, setName] = useState("");
  const [gstin, setGstin] = useState("");
  const [pan, setPan] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [tdsApplicable, setTdsApplicable] = useState(false);
  const [tdsSection, setTdsSection] = useState("194C");
  const [tdsRate, setTdsRate] = useState("2");
  const [openingBalance, setOpeningBalance] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("vendors")
      .select("*")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("name");
    setVendors((data as VendorRow[]) ?? []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function handleSave() {
    if (!name.trim()) { setMsg({ type: "err", text: "Name is required" }); return; }
    if (gstin && !GSTIN_RE.test(gstin.trim().toUpperCase())) { setMsg({ type: "err", text: "Invalid GSTIN format (15 chars: 2-digit state + PAN + entity + Z + check)" }); return; }
    setSaving(true);
    setMsg(null);
    try {
      const token = await getAuthToken();
      const cleanGstin = gstin.trim().toUpperCase() || undefined;
      const stateCode = cleanGstin ? cleanGstin.slice(0, 2) : undefined;
      const rateBps = tdsApplicable ? Math.round(parseFloat(tdsRate) * 100) : 0;

      const result = await apiCall(
        "/api/vendors/",
        "POST",
        {
          client_id: clientId,
          name: name.trim(),
          gstin: cleanGstin,
          state_code: stateCode,
          pan: pan.trim().toUpperCase() || undefined,
          email: email.trim() || undefined,
          phone: phone.trim() || undefined,
          tds_applicable: tdsApplicable,
          tds_section: tdsApplicable ? tdsSection : undefined,
          tds_rate_bps: rateBps,
          opening_balance_paise: Math.round(parseFloat(openingBalance || "0") * 100),
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to add vendor");
      setMsg({ type: "ok", text: "Vendor added." });
      setShowForm(false);
      setName(""); setGstin(""); setPan(""); setEmail(""); setPhone("");
      setTdsApplicable(false); setTdsSection("194C"); setTdsRate("2"); setOpeningBalance("");
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4 max-w-4xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">{vendors.length} vendor{vendors.length !== 1 ? "s" : ""}</p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC]"><RefreshCw size={13} className={loading ? "animate-spin text-[#94A3B8]" : "text-[#94A3B8]"} /></button>
          <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"><Plus size={12} /> Add Vendor</button>
        </div>
      </div>

      {showForm && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#0F172A]">New Vendor</h3>
            <button onClick={() => setShowForm(false)}><X size={16} className="text-[#94A3B8]" /></button>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-xs font-medium text-[#475569] mb-1">Name *</label>
              <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Vendor legal name" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">GSTIN</label>
              <input value={gstin} onChange={(e) => setGstin(e.target.value.toUpperCase())} placeholder="27AABCS1429B1Z5" maxLength={15} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">PAN</label>
              <input value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())} placeholder="ABCDE1234F" maxLength={10} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Email</label>
              <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Phone</label>
              <input value={phone} onChange={(e) => setPhone(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Opening Balance (₹ payable)</label>
              <input type="number" min="0" step="0.01" value={openingBalance} onChange={(e) => setOpeningBalance(e.target.value)} placeholder="0.00" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          {/* TDS section */}
          <div className="bg-blue-50 border border-blue-100 rounded-lg p-3 space-y-2">
            <div className="flex items-center gap-2">
              <input type="checkbox" id="tds-toggle" checked={tdsApplicable} onChange={(e) => setTdsApplicable(e.target.checked)} className="rounded" />
              <label htmlFor="tds-toggle" className="text-xs font-medium text-blue-800">TDS Applicable (IT Act §194C/I/J)</label>
            </div>
            {tdsApplicable && (
              <div className="grid grid-cols-2 gap-3 pt-1">
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">TDS Section</label>
                  <select value={tdsSection} onChange={(e) => { setTdsSection(e.target.value); setTdsRate(String(TDS_DEFAULT_RATES[e.target.value] / 100)); }} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                    {TDS_SECTIONS.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#475569] mb-1">TDS Rate (%)</label>
                  <input type="number" min="0" max="30" step="0.1" value={tdsRate} onChange={(e) => setTdsRate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">{saving ? "Saving…" : "Add Vendor"}</button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[#F8FAFC] animate-pulse" />)}</div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-3 text-left font-semibold">Name</th><th className="px-3 py-3 text-left font-semibold">GSTIN</th><th className="px-3 py-3 text-center font-semibold">TDS</th><th className="px-3 py-3 text-left font-semibold">Section</th><th className="px-3 py-3 text-right font-semibold">Rate</th><th className="px-4 py-3 text-right font-semibold">Opening Bal</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {vendors.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[#94A3B8]">No vendors added yet.</td></tr>
              ) : vendors.map((v) => (
                <tr key={v.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-4 py-2.5 font-medium text-[#1E293B]">{v.name}</td>
                  <td className="px-3 py-2.5 font-mono text-[#64748B] text-[10px]">{v.gstin ?? "—"}</td>
                  <td className="px-3 py-2.5 text-center">{v.tds_applicable ? <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">Yes</span> : "—"}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{v.tds_section ?? "—"}</td>
                  <td className="px-3 py-2.5 text-right text-[#475569]">{v.tds_rate_bps > 0 ? `${(v.tds_rate_bps / 100).toFixed(1)}%` : "—"}</td>
                  <td className="px-4 py-2.5 text-right font-mono text-[#334155]">{v.opening_balance_paise > 0 ? fmt(v.opening_balance_paise) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Payments ───────────────────────────────────────────────────────────────

interface PaymentRow {
  id: string;
  payment_no: string;
  payment_date: string;
  vendor_id: string;
  vendors?: { name: string };
  purchase_bill_id: string | null;
  amount_paise: number;
  payment_mode: string;
  reference_no: string | null;
}

function Payments({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [vendors, setVendors] = useState<{ id: string; name: string }[]>([]);
  const [openBills, setOpenBills] = useState<{ id: string; our_reference: string; bill_no: string | null; net_payable_paise: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const [vendorId, setVendorId] = useState("");
  const [billId, setBillId] = useState("");
  const [payDate, setPayDate] = useState(toDate());
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("bank");
  const [refNo, setRefNo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);
    const [pmtRes, vendorRes] = await Promise.all([
      supabase
        .from("purchase_payments")
        .select("*, vendors(name)")
        .eq("client_id", clientId)
        .gte("payment_date", start)
        .lte("payment_date", end)
        .order("payment_date", { ascending: false }),
      supabase.from("vendors").select("id, name").eq("client_id", clientId).eq("is_active", true).order("name"),
    ]);
    setPayments((pmtRes.data as PaymentRow[]) ?? []);
    setVendors(vendorRes.data ?? []);
    setLoading(false);
  }, [clientId, financialYear]);

  useEffect(() => { load(); }, [load]);

  async function loadOpenBills(vId: string) {
    const supabase = getSupabaseClient();
    const { data } = await supabase
      .from("purchase_bills")
      .select("id, our_reference, bill_no, net_payable_paise")
      .eq("client_id", clientId)
      .eq("vendor_id", vId)
      .in("status", ["received", "partially_paid"])
      .order("bill_date", { ascending: false });
    setOpenBills(data ?? []);
    setBillId("");
  }

  async function handleSave() {
    if (!vendorId) { setMsg({ type: "err", text: "Select a vendor" }); return; }
    const amtPaise = Math.round(parseFloat(amount || "0") * 100);
    if (amtPaise <= 0) { setMsg({ type: "err", text: "Amount must be positive" }); return; }
    setSaving(true); setMsg(null);
    try {
      const token = await getAuthToken();
      const result = await apiCall(
        "/api/purchase-payments",
        "POST",
        {
          client_id: clientId,
          vendor_id: vendorId,
          payment_date: payDate,
          amount_paise: amtPaise,
          payment_mode: mode,
          reference_no: refNo || undefined,
          purchase_bill_id: billId || undefined,
        },
        token
      );
      if (!result.success) throw new Error(result.error ?? "Failed to record payment");

      setMsg({ type: "ok", text: "Payment recorded." });
      setShowForm(false);
      setVendorId(""); setBillId(""); setAmount(""); setRefNo(""); setMode("bank");
      load();
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  }

  const totalPaid = payments.reduce((s, p) => s + p.amount_paise, 0);

  return (
    <div className="space-y-4 max-w-4xl">
      {msg && (
        <div className={`flex items-center gap-2 px-4 py-3 rounded-lg text-sm ${msg.type === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.type === "ok" ? <CheckCircle size={14} /> : <AlertCircle size={14} />}
          {msg.text}
          <button onClick={() => setMsg(null)} className="ml-auto"><X size={13} /></button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Total Paid (FY)</p>
          <p className="text-lg font-bold text-green-700 tabular-nums">{fmt(totalPaid)}</p>
        </div>
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <p className="text-[10px] text-[#64748B] mb-1">Transactions</p>
          <p className="text-lg font-bold text-[#1E293B] tabular-nums">{payments.length}</p>
        </div>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">Payments — FY {financialYear}</p>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC]"><RefreshCw size={13} className={loading ? "animate-spin text-[#94A3B8]" : "text-[#94A3B8]"} /></button>
          <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"><Plus size={12} /> Record Payment</button>
        </div>
      </div>

      {showForm && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-[#0F172A]">Record Payment</h3>
            <button onClick={() => setShowForm(false)}><X size={16} className="text-[#94A3B8]" /></button>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
            <div className="col-span-2 lg:col-span-1">
              <label className="block text-xs font-medium text-[#475569] mb-1">Vendor *</label>
              <select value={vendorId} onChange={(e) => { setVendorId(e.target.value); if (e.target.value) loadOpenBills(e.target.value); }} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">— Select vendor —</option>
                {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Against Bill (optional)</label>
              <select value={billId} onChange={(e) => setBillId(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">— Advance / Select bill —</option>
                {openBills.map((b) => <option key={b.id} value={b.id}>{b.our_reference ?? b.bill_no} ({fmt(b.net_payable_paise)})</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Date *</label>
              <input type="date" value={payDate} onChange={(e) => setPayDate(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Amount (₹) *</label>
              <input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Mode</label>
              <select value={mode} onChange={(e) => setMode(e.target.value)} className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500">
                {["bank", "cash", "cheque", "upi", "neft", "rtgs"].map((m) => <option key={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Reference No.</label>
              <input value={refNo} onChange={(e) => setRefNo(e.target.value)} placeholder="UTR / cheque no." className="w-full px-3 py-1.5 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div className="flex gap-3 justify-end">
            <button onClick={() => setShowForm(false)} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button onClick={handleSave} disabled={saving} className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-40">{saving ? "Saving…" : "Record Payment"}</button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="space-y-2">{[...Array(4)].map((_, i) => <div key={i} className="h-10 rounded-lg bg-[#F8FAFC] animate-pulse" />)}</div>
      ) : (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-[#F1F5F9] text-[#94A3B8]"><th className="px-4 py-3 text-left font-semibold">Payment No</th><th className="px-3 py-3 text-left font-semibold">Date</th><th className="px-3 py-3 text-left font-semibold">Vendor</th><th className="px-3 py-3 text-right font-semibold">Amount</th><th className="px-3 py-3 text-left font-semibold">Mode</th><th className="px-4 py-3 text-left font-semibold">Reference</th></tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {payments.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-8 text-center text-[#94A3B8]">No payments for FY {financialYear}.</td></tr>
              ) : payments.map((p) => (
                <tr key={p.id} className="hover:bg-[#F8FAFC]">
                  <td className="px-4 py-2.5 font-mono text-[#475569] text-[10px]">{p.payment_no}</td>
                  <td className="px-3 py-2.5 text-[#64748B]">{p.payment_date}</td>
                  <td className="px-3 py-2.5 font-medium text-[#1E293B]">{(p.vendors as { name: string } | undefined)?.name ?? "—"}</td>
                  <td className="px-3 py-2.5 text-right font-mono font-semibold text-[#1E293B]">{fmt(p.amount_paise)}</td>
                  <td className="px-3 py-2.5 text-[#64748B] capitalize">{p.payment_mode}</td>
                  <td className="px-4 py-2.5 text-[#94A3B8] text-[10px]">{p.reference_no ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
