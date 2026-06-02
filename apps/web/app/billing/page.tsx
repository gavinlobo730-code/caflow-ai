"use client";

/**
 * CA Firm Fee Billing — Track fee engagements, invoices, outstanding and receipts
 * GST on CA services: 18% under SAC 998211 (Accounting and bookkeeping services)
 * All monetary values stored and calculated in integer paise (1 INR = 100 paise)
 */

import { useState, useEffect, useCallback } from "react";
import { Plus, RefreshCw, X, MessageCircle, IndianRupee } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

type ServiceType = "GST Filing" | "ITR Filing" | "Accounting" | "Payroll" | "MCA" | "Audit" | "Advisory";
type BillingCycle = "Monthly" | "Quarterly" | "Annual";
type InvoiceStatus = "Draft" | "Sent" | "Paid" | "Overdue";
type PaymentMode = "NEFT" | "RTGS" | "Cheque" | "Cash" | "UPI";

interface Engagement {
  id: string;
  firm_id: string;
  client_id: string;
  service_type: ServiceType;
  fee_paise: number;
  billing_cycle: BillingCycle;
  start_date: string;
  status: "Active" | "Paused";
  client_name?: string;
}

interface Invoice {
  id: string;
  firm_id: string;
  client_id: string;
  invoice_no: string;
  invoice_date: string;
  amount_paise: number;
  gst_paise: number;
  total_paise: number;
  status: InvoiceStatus;
  client_name?: string;
}

interface Receipt {
  id: string;
  firm_id: string;
  invoice_id: string;
  receipt_date: string;
  amount_paise: number;
  payment_mode: PaymentMode;
  reference_no: string;
  invoice_no?: string;
  client_name?: string;
}

interface OutstandingRow {
  client_id: string;
  client_name: string;
  invoiceCount: number;
  totalPaise: number;
  d0_30: number;
  d31_60: number;
  d61_90: number;
  d90plus: number;
  phone?: string;
}

type Tab = "engagements" | "invoices" | "outstanding" | "receipts";

const SERVICE_TYPES: ServiceType[] = ["GST Filing", "ITR Filing", "Accounting", "Payroll", "MCA", "Audit", "Advisory"];
const BILLING_CYCLES: BillingCycle[] = ["Monthly", "Quarterly", "Annual"];
const PAYMENT_MODES: PaymentMode[] = ["NEFT", "RTGS", "Cheque", "Cash", "UPI"];

// GST rate on CA services — SAC 998211 — 18%
const GST_RATE_BPS = 1800; // basis points (18%)

/** Convert paise to ₹ string with 2 decimal places — integer arithmetic only */
function fmtPaise(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const paiseRemainder = paise % 100;
  const rupeesStr = rupees.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return "₹" + rupeesStr + "." + String(paiseRemainder).padStart(2, "0");
}

/** Integer paise arithmetic — GST at 18% (basis points calculation) */
function calcGst(amountPaise: number): number {
  // 18% = 1800 basis points. Multiply first then divide to stay integer.
  return Math.round((amountPaise * GST_RATE_BPS) / 10000);
}

function fmtDate(date: string): string {
  if (!date) return "—";
  const [y, m, d] = date.split("-");
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d} ${months[parseInt(m) - 1]} ${y}`;
}

const STATUS_COLORS: Record<InvoiceStatus, string> = {
  Draft: "bg-gray-100 text-gray-600",
  Sent: "bg-blue-100 text-blue-700",
  Paid: "bg-green-100 text-green-700",
  Overdue: "bg-red-100 text-red-700",
};

// ─── Modals ───────────────────────────────────────────────────────────────────

function AddEngagementModal({ clients, onClose, onSaved }: {
  clients: Client[];
  onClose: () => void;
  onSaved: (e: Engagement) => void;
}) {
  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [serviceType, setServiceType] = useState<ServiceType>("GST Filing");
  const [feeRs, setFeeRs] = useState("");
  const [billingCycle, setBillingCycle] = useState<BillingCycle>("Monthly");
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    const feeFloat = parseFloat(feeRs || "0");
    // Integer paise: multiply by 100 and round
    const feePaise = Math.round(feeFloat * 100);
    if (!clientId || feePaise <= 0) { setError("Select a client and enter a valid fee"); return; }
    setSaving(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const { data, error: err } = await sb.from("fee_engagements").insert({
        firm_id: firmId,
        client_id: clientId,
        service_type: serviceType,
        fee_paise: feePaise,
        billing_cycle: billingCycle,
        start_date: startDate,
        status: "Active",
      }).select().single();
      if (err) throw new Error(err.message);
      const client = clients.find(c => c.id === clientId);
      onSaved({ ...(data as Engagement), client_name: client?.client_name });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Add Fee Engagement</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Client</label>
            <select value={clientId} onChange={e => setClientId(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
              {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Service Type</label>
            <select value={serviceType} onChange={e => setServiceType(e.target.value as ServiceType)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
              {SERVICE_TYPES.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Fee (₹)</label>
              <input type="number" min="0" step="0.01" value={feeRs} onChange={e => setFeeRs(e.target.value)}
                placeholder="5000"
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Billing Cycle</label>
              <select value={billingCycle} onChange={e => setBillingCycle(e.target.value as BillingCycle)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
                {BILLING_CYCLES.map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Start Date</label>
            <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
          </div>
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose}
            className="flex-1 border border-gray-200 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 bg-blue-600 text-white rounded-lg py-2 text-sm hover:bg-blue-700 disabled:opacity-60">
            {saving ? "Saving…" : "Save Engagement"}
          </button>
        </div>
      </div>
    </div>
  );
}

function AddReceiptModal({ invoices, onClose, onSaved }: {
  invoices: Invoice[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const unpaid = invoices.filter(i => i.status !== "Paid");
  const [invoiceId, setInvoiceId] = useState(unpaid[0]?.id ?? "");
  const [receiptDate, setReceiptDate] = useState(new Date().toISOString().split("T")[0]);
  const [amountRs, setAmountRs] = useState("");
  const [paymentMode, setPaymentMode] = useState<PaymentMode>("NEFT");
  const [referenceNo, setReferenceNo] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    const amtPaise = Math.round(parseFloat(amountRs || "0") * 100);
    if (!invoiceId || amtPaise <= 0) { setError("Select invoice and enter valid amount"); return; }
    setSaving(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const { error: err } = await sb.from("fee_receipts").insert({
        firm_id: firmId,
        invoice_id: invoiceId,
        receipt_date: receiptDate,
        amount_paise: amtPaise,
        payment_mode: paymentMode,
        reference_no: referenceNo,
      });
      if (err) throw new Error(err.message);
      await sb.from("fee_invoices").update({ status: "Paid" }).eq("id", invoiceId);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Record Receipt</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Invoice</label>
            <select value={invoiceId} onChange={e => setInvoiceId(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
              {unpaid.map(i => (
                <option key={i.id} value={i.id}>
                  {i.invoice_no} — {i.client_name} — {fmtPaise(i.total_paise)}
                </option>
              ))}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Receipt Date</label>
              <input type="date" value={receiptDate} onChange={e => setReceiptDate(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Amount (₹)</label>
              <input type="number" min="0" step="0.01" value={amountRs} onChange={e => setAmountRs(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Payment Mode</label>
              <select value={paymentMode} onChange={e => setPaymentMode(e.target.value as PaymentMode)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
                {PAYMENT_MODES.map(m => <option key={m} value={m}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Reference No.</label>
              <input type="text" value={referenceNo} onChange={e => setReferenceNo(e.target.value)}
                placeholder="UTR / Cheque no."
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500" />
            </div>
          </div>
        </div>
        <div className="flex gap-2 pt-1">
          <button onClick={onClose}
            className="flex-1 border border-gray-200 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-50">
            Cancel
          </button>
          <button onClick={handleSave} disabled={saving}
            className="flex-1 bg-green-600 text-white rounded-lg py-2 text-sm hover:bg-green-700 disabled:opacity-60">
            {saving ? "Saving…" : "Record Receipt"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function BillingPage() {
  const [tab, setTab] = useState<Tab>("engagements");
  const [clients, setClients] = useState<Client[]>([]);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [outstanding, setOutstanding] = useState<OutstandingRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showEngModal, setShowEngModal] = useState(false);
  const [showReceiptModal, setShowReceiptModal] = useState(false);
  const [raisingInvoice, setRaisingInvoice] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [clientList, firmId] = await Promise.all([getClients(), getFirmId()]);
      setClients(clientList);
      const clientMap = new Map(clientList.map(c => [c.id, c]));
      const sb = getSupabaseClient();

      const [engRes, invRes, recRes] = await Promise.all([
        sb.from("fee_engagements").select("*").eq("firm_id", firmId).order("created_at", { ascending: false }),
        sb.from("fee_invoices").select("*").eq("firm_id", firmId).order("invoice_date", { ascending: false }),
        sb.from("fee_receipts").select("*").eq("firm_id", firmId).order("receipt_date", { ascending: false }),
      ]);

      const engs: Engagement[] = (engRes.data ?? []).map((e: Engagement) => ({
        ...e,
        client_name: clientMap.get(e.client_id)?.client_name,
      }));
      const invs: Invoice[] = (invRes.data ?? []).map((i: Invoice) => ({
        ...i,
        client_name: clientMap.get(i.client_id)?.client_name,
      }));
      const recs: Receipt[] = (recRes.data ?? []).map((r: Receipt) => {
        const inv = invs.find(i => i.id === r.invoice_id);
        return { ...r, invoice_no: inv?.invoice_no, client_name: inv?.client_name };
      });

      setEngagements(engs);
      setInvoices(invs);
      setReceipts(recs);

      // Build aged outstanding from unpaid invoices
      const today = new Date();
      const unpaidInvs = invs.filter(i => i.status !== "Paid");
      const outMap = new Map<string, OutstandingRow>();
      for (const inv of unpaidInvs) {
        const invDate = new Date(inv.invoice_date);
        const days = Math.floor((today.getTime() - invDate.getTime()) / 86400000);
        const existing = outMap.get(inv.client_id);
        const row: OutstandingRow = existing ?? {
          client_id: inv.client_id,
          client_name: inv.client_name ?? "Unknown",
          invoiceCount: 0,
          totalPaise: 0,
          d0_30: 0, d31_60: 0, d61_90: 0, d90plus: 0,
        };
        row.invoiceCount++;
        row.totalPaise += inv.total_paise;
        if (days <= 30) row.d0_30 += inv.total_paise;
        else if (days <= 60) row.d31_60 += inv.total_paise;
        else if (days <= 90) row.d61_90 += inv.total_paise;
        else row.d90plus += inv.total_paise;
        outMap.set(inv.client_id, row);
      }
      setOutstanding(Array.from(outMap.values()));
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load";
      if (msg.includes("does not exist") || msg.includes("relation")) {
        setError("Billing tables not set up yet. Please run database migrations.");
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function handleRaiseInvoice() {
    setRaisingInvoice(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const now = new Date();
      const year = now.getFullYear();
      const month = String(now.getMonth() + 1).padStart(2, "0");

      const { count } = await sb.from("fee_invoices").select("*", { count: "exact", head: true }).eq("firm_id", firmId);
      let seq = (count ?? 0) + 1;

      const activeEngs = engagements.filter(e => e.status === "Active");
      if (activeEngs.length === 0) { setRaisingInvoice(false); return; }

      const newInvoices = activeEngs.map(eng => {
        // Integer arithmetic — GST 18% per SAC 998211
        const gstPaise = calcGst(eng.fee_paise);
        const totalPaise = eng.fee_paise + gstPaise;
        const invoiceNo = `FEE-${year}-${String(seq++).padStart(3, "0")}`;
        return {
          firm_id: firmId,
          client_id: eng.client_id,
          invoice_no: invoiceNo,
          invoice_date: `${year}-${month}-01`,
          amount_paise: eng.fee_paise,
          gst_paise: gstPaise,
          total_paise: totalPaise,
          status: "Draft",
        };
      });

      const { error: err } = await sb.from("fee_invoices").insert(newInvoices);
      if (err) throw new Error(err.message);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to raise invoices");
    } finally {
      setRaisingInvoice(false);
    }
  }

  const TABS: { id: Tab; label: string }[] = [
    { id: "engagements", label: "Engagements" },
    { id: "invoices", label: "Invoices" },
    { id: "outstanding", label: "Outstanding" },
    { id: "receipts", label: "Receipts" },
  ];

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg md:text-xl font-semibold text-gray-900">Fee Billing</h1>
          <p className="text-sm text-gray-500 mt-0.5">Manage CA firm fee engagements and invoices</p>
        </div>
        <button onClick={load} className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-500">
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 px-4 py-3 text-sm text-amber-800">{error}</div>
      )}

      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors ${
              tab === t.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* Engagements */}
      {tab === "engagements" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={() => setShowEngModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
              <Plus size={15} /> Add Engagement
            </button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm min-w-[700px]">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Client</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Service</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Fee</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Cycle</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Start Date</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading && [...Array(3)].map((_, i) => (
                  <tr key={i}>{[...Array(6)].map((__, j) => (
                    <td key={j} className="px-4 py-3"><div className="h-4 bg-gray-100 rounded animate-pulse" /></td>
                  ))}</tr>
                ))}
                {!loading && engagements.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-8 text-gray-400">No engagements yet</td></tr>
                )}
                {!loading && engagements.map(e => (
                  <tr key={e.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">{e.client_name ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-600">{e.service_type}</td>
                    <td className="px-4 py-3 text-gray-800 font-mono">{fmtPaise(e.fee_paise)}</td>
                    <td className="px-4 py-3 text-gray-600">{e.billing_cycle}</td>
                    <td className="px-4 py-3 text-gray-500">{fmtDate(e.start_date)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${e.status === "Active" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
                        {e.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Invoices */}
      {tab === "invoices" && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-500">GST @ 18% applied on CA services — SAC 998211</p>
            <button onClick={handleRaiseInvoice} disabled={raisingInvoice}
              className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-60">
              <IndianRupee size={15} /> {raisingInvoice ? "Raising…" : "Raise Invoice"}
            </button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm min-w-[800px]">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Invoice No.</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Date</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Client</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Amount</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">GST 18%</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Total</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading && [...Array(3)].map((_, i) => (
                  <tr key={i}>{[...Array(7)].map((__, j) => (
                    <td key={j} className="px-4 py-3"><div className="h-4 bg-gray-100 rounded animate-pulse" /></td>
                  ))}</tr>
                ))}
                {!loading && invoices.length === 0 && (
                  <tr><td colSpan={7} className="text-center py-8 text-gray-400">No invoices yet — click &quot;Raise Invoice&quot; to generate</td></tr>
                )}
                {!loading && invoices.map(inv => (
                  <tr key={inv.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-gray-700">{inv.invoice_no}</td>
                    <td className="px-4 py-3 text-gray-500">{fmtDate(inv.invoice_date)}</td>
                    <td className="px-4 py-3 font-medium text-gray-900">{inv.client_name ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-700">{fmtPaise(inv.amount_paise)}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-500">{fmtPaise(inv.gst_paise)}</td>
                    <td className="px-4 py-3 text-right font-mono font-semibold text-gray-900">{fmtPaise(inv.total_paise)}</td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[inv.status]}`}>
                        {inv.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Outstanding */}
      {tab === "outstanding" && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold text-gray-700">Aged Debtors Report</h2>
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm min-w-[800px]">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Client</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Invoices</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Total Outstanding</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">0–30 days</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">31–60 days</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">61–90 days</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">90+ days</th>
                  <th className="px-4 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {outstanding.length === 0 && (
                  <tr><td colSpan={8} className="text-center py-8 text-gray-400">No outstanding invoices</td></tr>
                )}
                {outstanding.map(row => (
                  <tr key={row.client_id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">{row.client_name}</td>
                    <td className="px-4 py-3 text-right text-gray-600">{row.invoiceCount}</td>
                    <td className="px-4 py-3 text-right font-semibold font-mono text-gray-900">{fmtPaise(row.totalPaise)}</td>
                    <td className="px-4 py-3 text-right font-mono text-gray-600">{fmtPaise(row.d0_30)}</td>
                    <td className="px-4 py-3 text-right font-mono text-amber-600">{fmtPaise(row.d31_60)}</td>
                    <td className="px-4 py-3 text-right font-mono text-orange-600">{fmtPaise(row.d61_90)}</td>
                    <td className="px-4 py-3 text-right font-mono text-red-600">{fmtPaise(row.d90plus)}</td>
                    <td className="px-4 py-3">
                      <a
                        href={`https://wa.me/${(row.phone ?? "").replace(/\D/g, "")}?text=${encodeURIComponent(
                          `Dear ${row.client_name}, this is a reminder that you have ${fmtPaise(row.totalPaise)} in outstanding fees. Please arrange payment. Thank you.`
                        )}`}
                        target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-1 text-xs text-green-600 hover:text-green-700 font-medium"
                      >
                        <MessageCircle size={13} /> Remind
                      </a>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Receipts */}
      {tab === "receipts" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <button onClick={() => setShowReceiptModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700">
              <Plus size={15} /> Record Receipt
            </button>
          </div>
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm min-w-[700px]">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Invoice</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Client</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Date</th>
                  <th className="text-right px-4 py-3 font-medium text-gray-600">Amount</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Mode</th>
                  <th className="text-left px-4 py-3 font-medium text-gray-600">Reference</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {receipts.length === 0 && (
                  <tr><td colSpan={6} className="text-center py-8 text-gray-400">No receipts recorded</td></tr>
                )}
                {receipts.map(r => (
                  <tr key={r.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-mono text-gray-700">{r.invoice_no ?? "—"}</td>
                    <td className="px-4 py-3 font-medium text-gray-900">{r.client_name ?? "—"}</td>
                    <td className="px-4 py-3 text-gray-500">{fmtDate(r.receipt_date)}</td>
                    <td className="px-4 py-3 text-right font-mono font-semibold text-green-700">{fmtPaise(r.amount_paise)}</td>
                    <td className="px-4 py-3 text-gray-600">{r.payment_mode}</td>
                    <td className="px-4 py-3 font-mono text-gray-500 text-xs">{r.reference_no || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showEngModal && (
        <AddEngagementModal
          clients={clients}
          onClose={() => setShowEngModal(false)}
          onSaved={e => { setEngagements(prev => [e, ...prev]); setShowEngModal(false); }}
        />
      )}
      {showReceiptModal && (
        <AddReceiptModal
          invoices={invoices}
          onClose={() => setShowReceiptModal(false)}
          onSaved={() => { setShowReceiptModal(false); load(); }}
        />
      )}
    </div>
  );
}
