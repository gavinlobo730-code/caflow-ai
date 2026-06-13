"use client";

/**
 * Monthly Retainer Tracker — CA firms charge fixed monthly fees for services
 * GST on professional services (CA fees): CGST Act Section 9 read with Notification 11/2017-CT(Rate)
 * GST rate on CA services: 18% (CGST 9% + SGST 9%)
 * Invoice must show GSTIN of supplier and recipient — CGST Act Section 31
 */

import { useState, useEffect, useCallback } from "react";
import {
  IndianRupee,
  Users,
  FileText,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  X,
  Printer,
  AlertCircle,
  Plus,
} from "lucide-react";
import { getClients } from "@/lib/data/clients";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import type { Client } from "@/lib/types";

// ─── Constants ────────────────────────────────────────────────────────────────

const SERVICES = [
  "GST Returns",
  "TDS Returns",
  "ITR Filing",
  "Accounting",
  "MCA Filings",
  "Payroll",
  "Audit Support",
  "Other",
] as const;

type Service = (typeof SERVICES)[number];

const WORK_ITEMS = [
  { key: "gstr1", label: "GSTR-1 Filed" },
  { key: "gstr3b", label: "GSTR-3B Filed" },
  { key: "tds", label: "TDS Return Filed" },
  { key: "books", label: "Books Updated" },
] as const;

type WorkItemKey = (typeof WORK_ITEMS)[number]["key"];

const LS_RETAINERS = "practicesync_retainers";
const LS_INVOICES = "practicesync_invoices";
const LS_WORK = "practicesync_retainer_work";

// ─── Types ────────────────────────────────────────────────────────────────────

interface RetainerConfig {
  feePaise: number; // stored as integer paise — never floating point
  services: Service[];
  invoiceDay: number; // day of month to raise invoice
}

interface WorkStatus {
  [workKey: string]: boolean;
}

interface StoredInvoice {
  id: string;
  invoiceNo: string;
  clientId: string;
  clientName: string;
  amountPaise: number; // base fee in paise
  gstPaise: number;    // 18% GST in paise
  totalPaise: number;
  date: string;        // ISO date string
  month: string;       // "2026-06" — to detect same-month duplicates
}

// ─── localStorage helpers ─────────────────────────────────────────────────────

function loadRetainers(): Record<string, RetainerConfig> {
  try {
    return JSON.parse(localStorage.getItem(LS_RETAINERS) ?? "{}");
  } catch {
    return {};
  }
}

function saveRetainers(data: Record<string, RetainerConfig>) {
  localStorage.setItem(LS_RETAINERS, JSON.stringify(data));
}

function loadWork(): Record<string, WorkStatus> {
  try {
    return JSON.parse(localStorage.getItem(LS_WORK) ?? "{}");
  } catch {
    return {};
  }
}

function saveWork(data: Record<string, WorkStatus>) {
  localStorage.setItem(LS_WORK, JSON.stringify(data));
}

function loadInvoices(): StoredInvoice[] {
  try {
    return JSON.parse(localStorage.getItem(LS_INVOICES) ?? "[]");
  } catch {
    return [];
  }
}

function saveInvoices(data: StoredInvoice[]) {
  localStorage.setItem(LS_INVOICES, JSON.stringify(data));
}

// ─── Utility ──────────────────────────────────────────────────────────────────

function currentMonthKey(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function generateInvoiceNo(existingInvoices: StoredInvoice[]): string {
  const prefix = "CAF";
  const year = new Date().getFullYear();
  const count = existingInvoices.filter(inv => inv.invoiceNo.startsWith(`${prefix}/${year}/`)).length + 1;
  return `${prefix}/${year}/${String(count).padStart(4, "0")}`;
}

// Integer paise arithmetic — CGST Act Section 9 read with Notification 11/2017-CT(Rate)
// GST on CA professional services: 18% (CGST 9% + SGST 9%)
function calcGST(feePaise: number): { cgst: number; sgst: number; total: number } {
  // Use integer arithmetic to avoid floating point errors
  const cgst = Math.round(feePaise * 9 / 100);
  const sgst = Math.round(feePaise * 9 / 100);
  return { cgst, sgst, total: cgst + sgst };
}

// ─── SetRetainerModal ─────────────────────────────────────────────────────────

interface SetRetainerModalProps {
  client: Client;
  existing: RetainerConfig | undefined;
  onSave: (config: RetainerConfig) => void;
  onClose: () => void;
}

function SetRetainerModal({ client, existing, onSave, onClose }: SetRetainerModalProps) {
  const [feeRupees, setFeeRupees] = useState(
    existing ? String(Math.round(existing.feePaise / 100)) : ""
  );
  const [selectedServices, setSelectedServices] = useState<Service[]>(existing?.services ?? []);
  const [invoiceDay, setInvoiceDay] = useState(existing?.invoiceDay ?? 1);

  function toggleService(s: Service) {
    setSelectedServices(prev =>
      prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
    );
  }

  function handleSave() {
    const rupees = parseInt(feeRupees, 10);
    if (isNaN(rupees) || rupees <= 0) return;
    // Store as paise — integer arithmetic only
    onSave({ feePaise: rupees * 100, services: selectedServices, invoiceDay });
    onClose();
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-5 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Set Retainer — {client.client_name}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Monthly Fee */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Monthly Fee (₹)</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm">₹</span>
            <input
              type="number"
              min="0"
              step="1"
              className="w-full border border-[#E2E8F0] rounded-lg pl-7 pr-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="15000"
              value={feeRupees}
              onChange={e => setFeeRupees(e.target.value)}
            />
          </div>
          <p className="text-[10px] text-[#94A3B8] mt-1">Stored as paise internally — integer arithmetic</p>
        </div>

        {/* Services */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-2">Services Included</label>
          <div className="grid grid-cols-2 gap-2">
            {SERVICES.map(s => (
              <label key={s} className="flex items-center gap-2 text-xs text-[#334155] cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedServices.includes(s)}
                  onChange={() => toggleService(s)}
                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                {s}
              </label>
            ))}
          </div>
        </div>

        {/* Invoice Day */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Invoice Day of Month</label>
          <select
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={invoiceDay}
            onChange={e => setInvoiceDay(parseInt(e.target.value, 10))}
          >
            {Array.from({ length: 28 }, (_, i) => i + 1).map(d => (
              <option key={d} value={d}>{d}{d === 1 ? "st" : d === 2 ? "nd" : d === 3 ? "rd" : "th"} of month</option>
            ))}
          </select>
        </div>

        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]">
            Cancel
          </button>
          <button
            disabled={!feeRupees || parseInt(feeRupees, 10) <= 0}
            onClick={handleSave}
            className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            Save Retainer
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── InvoiceModal ─────────────────────────────────────────────────────────────

interface InvoiceModalProps {
  client: Client;
  config: RetainerConfig;
  workStatus: WorkStatus;
  invoiceNo: string;
  firmName: string;
  firmGstin: string | null;
  onClose: () => void;
  onConfirm: (invoice: StoredInvoice) => void;
  alreadyGenerated: boolean;
}

function InvoiceModal({
  client,
  config,
  workStatus,
  invoiceNo,
  firmName,
  firmGstin,
  onClose,
  onConfirm,
  alreadyGenerated,
}: InvoiceModalProps) {
  const today = new Date();
  const dateStr = today.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  const monthKey = currentMonthKey();
  const { cgst, sgst, total: gstTotal } = calcGST(config.feePaise);
  const grandTotal = config.feePaise + gstTotal;

  const completedWork = WORK_ITEMS.filter(w => workStatus[w.key]);

  function handlePrint() {
    window.print();
  }

  function handleConfirm() {
    const inv: StoredInvoice = {
      id: crypto.randomUUID(),
      invoiceNo,
      clientId: client.id,
      clientName: client.client_name,
      amountPaise: config.feePaise,
      gstPaise: gstTotal,
      totalPaise: grandTotal,
      date: today.toISOString(),
      month: monthKey,
    };
    onConfirm(inv);
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Print-friendly invoice body */}
        <div id="invoice-print-area" className="p-8 space-y-5">
          {/* Header */}
          <div className="flex items-start justify-between border-b border-[#E2E8F0] pb-5">
            <div>
              <h2 className="text-lg font-bold text-[#0F172A]">{firmName}</h2>
              {firmGstin && <p className="text-xs text-[#64748B] mt-0.5">GSTIN: {firmGstin}</p>}
            </div>
            <div className="text-right">
              <p className="text-base font-semibold text-blue-700">TAX INVOICE</p>
              <p className="text-xs text-[#64748B] mt-0.5">No: {invoiceNo}</p>
              <p className="text-xs text-[#64748B]">Date: {dateStr}</p>
            </div>
          </div>

          {/* Bill To */}
          <div className="grid grid-cols-2 gap-4 text-xs">
            <div>
              <p className="font-semibold text-[#334155] mb-1">Bill To</p>
              <p className="text-[#0F172A] font-medium">{client.client_name}</p>
              {client.gstin && <p className="text-[#64748B] font-mono">GSTIN: {client.gstin}</p>}
              {client.pan && <p className="text-[#64748B] font-mono">PAN: {client.pan}</p>}
              {client.address_line1 && <p className="text-[#64748B]">{client.address_line1}</p>}
              {client.city && <p className="text-[#64748B]">{client.city}{client.state ? `, ${client.state}` : ""}</p>}
            </div>
            <div className="text-right">
              <p className="font-semibold text-[#334155] mb-1">Invoice Details</p>
              <p className="text-[#475569]">Month: {today.toLocaleDateString("en-IN", { month: "long", year: "numeric" })}</p>
            </div>
          </div>

          {/* Line Items */}
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-[#F8FAFC] rounded">
                <th className="text-left font-semibold text-[#475569] px-3 py-2">Description</th>
                <th className="text-right font-semibold text-[#475569] px-3 py-2">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F1F5F9]">
              <tr>
                <td className="px-3 py-2">
                  <p className="font-medium text-[#0F172A]">Monthly Retainer Fee</p>
                  <p className="text-[#64748B] text-[10px] mt-0.5">
                    Services: {config.services.length > 0 ? config.services.join(", ") : "As agreed"}
                  </p>
                  {completedWork.length > 0 && (
                    <p className="text-[#94A3B8] text-[10px] mt-0.5">
                      Completed: {completedWork.map(w => w.label).join(", ")}
                    </p>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-medium text-[#0F172A]">{formatPaise(config.feePaise)}</td>
              </tr>
            </tbody>
          </table>

          {/* GST breakdown — CGST Act Section 9, Notification 11/2017-CT(Rate), 18% on CA services */}
          <div className="border-t border-[#F1F5F9] pt-3 space-y-1.5 text-xs">
            <div className="flex justify-between text-[#475569]">
              <span>Subtotal</span>
              <span>{formatPaise(config.feePaise)}</span>
            </div>
            {firmGstin && (
              <>
                {/* CGST Act Section 9 — CGST 9% on professional services */}
                <div className="flex justify-between text-[#475569]">
                  <span>CGST @ 9%</span>
                  <span>{formatPaise(cgst)}</span>
                </div>
                {/* CGST Act Section 9 — SGST 9% on professional services (intra-state) */}
                <div className="flex justify-between text-[#475569]">
                  <span>SGST @ 9%</span>
                  <span>{formatPaise(sgst)}</span>
                </div>
              </>
            )}
            <div className="flex justify-between font-bold text-[#0F172A] text-sm border-t border-[#E2E8F0] pt-2 mt-2">
              <span>Total</span>
              <span>{formatPaise(firmGstin ? grandTotal : config.feePaise)}</span>
            </div>
          </div>

          <p className="text-[10px] text-[#94A3B8] text-center border-t border-[#F1F5F9] pt-3">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            This invoice is generated by PracticeSync AI. Review before sending to client.
          </p>
        </div>

        {/* Action buttons — hidden during print */}
        <div className="px-6 pb-6 flex gap-2 print:hidden">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]">
            Close
          </button>
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 px-4 border border-[#E2E8F0] text-[#334155] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]"
          >
            <Printer className="w-4 h-4" />
            Print
          </button>
          {!alreadyGenerated && (
            <button
              onClick={handleConfirm}
              className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700"
            >
              Save Invoice
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function RetainerPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [firmName, setFirmName] = useState("Your CA Firm");
  const [firmGstin, setFirmGstin] = useState<string | null>(null);

  // localStorage state
  const [retainers, setRetainers] = useState<Record<string, RetainerConfig>>({});
  const [workMap, setWorkMap] = useState<Record<string, WorkStatus>>({});
  const [invoices, setInvoices] = useState<StoredInvoice[]>([]);

  // UI state
  const [modalClient, setModalClient] = useState<Client | null>(null);
  const [expandedWork, setExpandedWork] = useState<string | null>(null);
  const [invoiceClient, setInvoiceClient] = useState<Client | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  // Load from localStorage on mount
  useEffect(() => {
    setRetainers(loadRetainers());
    setWorkMap(loadWork());
    setInvoices(loadInvoices());
  }, []);

  // Load clients and firm info from Supabase
  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const cls = await getClients();
        setClients(cls);

        // Load firm info for invoice header
        const sb = getSupabaseClient();
        const { data: { session } } = await sb.auth.getSession();
        if (session) {
          const { data: userData } = await sb.from("users").select("firm_id").eq("auth_user_id", session.user.id).maybeSingle();
          if (userData?.firm_id) {
            const { data: firmData } = await sb.from("firms").select("name, gstin").eq("id", userData.firm_id).single();
            if (firmData) {
              setFirmName((firmData as { name: string; gstin?: string }).name ?? "Your CA Firm");
              setFirmGstin((firmData as { name: string; gstin?: string | null }).gstin ?? null);
            }
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load data");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  const saveRetainerConfig = useCallback((clientId: string, config: RetainerConfig) => {
    setRetainers(prev => {
      const updated = { ...prev, [clientId]: config };
      saveRetainers(updated);
      return updated;
    });
  }, []);

  const toggleWorkItem = useCallback((clientId: string, workKey: WorkItemKey) => {
    setWorkMap(prev => {
      const clientWork = prev[clientId] ?? {};
      const updated = {
        ...prev,
        [clientId]: { ...clientWork, [workKey]: !clientWork[workKey] },
      };
      saveWork(updated);
      return updated;
    });
  }, []);

  const handleInvoiceConfirm = useCallback((inv: StoredInvoice) => {
    setInvoices(prev => {
      const updated = [inv, ...prev];
      saveInvoices(updated);
      return updated;
    });
    setInvoiceClient(null);
  }, []);

  // Clients that have a retainer configured
  const retainerClients = clients.filter(c => retainers[c.id]);
  const monthKey = currentMonthKey();

  // Summary calculations — integer paise arithmetic
  const totalRevenuePaise = retainerClients.reduce((sum, c) => sum + (retainers[c.id]?.feePaise ?? 0), 0);
  const invoicesThisMonth = invoices.filter(inv => inv.month === monthKey).length;
  const invoicedClientIds = new Set(invoices.filter(inv => inv.month === monthKey).map(inv => inv.clientId));
  const outstandingCount = retainerClients.filter(c => !invoicedClientIds.has(c.id)).length;

  // Clients with retainer configured that are not yet invoiced this month
  const pendingInvoiceClients = retainerClients.filter(c => !invoicedClientIds.has(c.id));

  // Generate invoice number for selected client
  const currentInvoiceNo = invoiceClient ? generateInvoiceNo(invoices) : "";

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-[#0F172A]">Monthly Retainer Tracker</h1>
        <p className="text-sm text-[#64748B] mt-0.5">Track fixed-fee retainer clients, work done, and generate invoices</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Monthly Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Users className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-[#64748B]">Retainer Clients</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : retainerClients.length}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">of {clients.length} total clients</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <IndianRupee className="w-4 h-4 text-green-600" />
            </div>
            <span className="text-xs text-[#64748B]">Monthly Revenue</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : formatPaise(totalRevenuePaise)}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">Sum of all retainer fees</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center">
              <FileText className="w-4 h-4 text-purple-600" />
            </div>
            <span className="text-xs text-[#64748B]">Invoiced This Month</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{invoicesThisMonth}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">{monthKey}</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <AlertCircle className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-[#64748B]">Outstanding</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{outstandingCount}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">Not yet invoiced</p>
        </div>
      </div>

      {/* Retainer Clients Table */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-[#0F172A]">Retainer Clients</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Click &quot;Set Retainer&quot; to configure a client</p>
          </div>
        </div>

        {loading ? (
          <div className="px-5 py-8 text-center text-sm text-[#94A3B8]">Loading clients...</div>
        ) : clients.length === 0 ? (
          <div className="px-5 py-8 text-center text-sm text-[#94A3B8]">No clients found — add clients first</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-5 py-3">Client Name</th>
                  <th className="text-right text-xs font-medium text-[#94A3B8] px-3 py-3">Monthly Fee</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Services</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Work Status</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Invoice Status</th>
                  <th className="text-left text-xs font-medium text-[#94A3B8] px-5 py-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {clients.map(client => {
                  const config = retainers[client.id];
                  const work = workMap[client.id] ?? {};
                  const completedCount = WORK_ITEMS.filter(w => work[w.key]).length;
                  const isExpanded = expandedWork === client.id;
                  const isInvoiced = invoicedClientIds.has(client.id);

                  return (
                    <>
                      <tr key={client.id} className="hover:bg-[#F8FAFC]/50">
                        <td className="px-5 py-3">
                          <p className="text-sm font-medium text-[#0F172A]">{client.client_name}</p>
                          {client.gstin && (
                            <p className="text-[10px] font-mono text-[#94A3B8]">{client.gstin}</p>
                          )}
                        </td>
                        <td className="px-3 py-3 text-right">
                          {config ? (
                            <span className="text-sm font-semibold text-[#0F172A]">{formatPaise(config.feePaise)}</span>
                          ) : (
                            <span className="text-xs text-[#CBD5E1]">Not set</span>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          {config && config.services.length > 0 ? (
                            <div className="flex flex-wrap gap-1">
                              {config.services.slice(0, 2).map(s => (
                                <span key={s} className="text-[10px] bg-blue-50 text-blue-700 rounded px-1.5 py-0.5">{s}</span>
                              ))}
                              {config.services.length > 2 && (
                                <span className="text-[10px] text-[#94A3B8]">+{config.services.length - 2} more</span>
                              )}
                            </div>
                          ) : (
                            <span className="text-xs text-[#CBD5E1]">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          {config ? (
                            <button
                              onClick={() => setExpandedWork(isExpanded ? null : client.id)}
                              className="flex items-center gap-1 text-xs text-[#475569] hover:text-[#0F172A]"
                            >
                              <span className={`text-[10px] rounded-full px-1.5 py-0.5 font-medium ${completedCount === WORK_ITEMS.length ? "bg-green-100 text-green-700" : completedCount > 0 ? "bg-amber-100 text-amber-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
                                {completedCount}/{WORK_ITEMS.length}
                              </span>
                              {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                            </button>
                          ) : (
                            <span className="text-xs text-[#CBD5E1]">—</span>
                          )}
                        </td>
                        <td className="px-3 py-3">
                          {isInvoiced ? (
                            <span className="flex items-center gap-1 text-[10px] bg-green-100 text-green-700 rounded-full px-2 py-0.5">
                              <CheckCircle className="w-3 h-3" />
                              Invoiced
                            </span>
                          ) : config ? (
                            <span className="text-[10px] bg-amber-100 text-amber-700 rounded-full px-2 py-0.5">Pending</span>
                          ) : (
                            <span className="text-xs text-[#CBD5E1]">—</span>
                          )}
                        </td>
                        <td className="px-5 py-3">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => setModalClient(client)}
                              className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap flex items-center gap-1"
                            >
                              <Plus className="w-3 h-3" />
                              {config ? "Edit" : "Set"} Retainer
                            </button>
                            {config && !isInvoiced && (
                              <button
                                onClick={() => setInvoiceClient(client)}
                                className="text-xs text-green-600 hover:text-green-800 font-medium whitespace-nowrap flex items-center gap-1"
                              >
                                <FileText className="w-3 h-3" />
                                Generate Invoice
                              </button>
                            )}
                            {config && isInvoiced && (
                              <button
                                onClick={() => setInvoiceClient(client)}
                                className="text-xs text-[#94A3B8] hover:text-[#475569] font-medium whitespace-nowrap"
                              >
                                View Invoice
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>

                      {/* Work Done Expansion Row */}
                      {isExpanded && config && (
                        <tr key={`${client.id}-work`} className="bg-blue-50/30">
                          <td colSpan={6} className="px-5 py-3">
                            <p className="text-[11px] font-semibold text-[#475569] mb-2">Work Done This Month</p>
                            <div className="flex flex-wrap gap-3">
                              {WORK_ITEMS.map(item => (
                                <label key={item.key} className="flex items-center gap-2 text-xs text-[#334155] cursor-pointer">
                                  <input
                                    type="checkbox"
                                    checked={work[item.key] ?? false}
                                    onChange={() => toggleWorkItem(client.id, item.key as WorkItemKey)}
                                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                                  />
                                  {item.label}
                                  {work[item.key] && <CheckCircle className="w-3 h-3 text-green-500" />}
                                </label>
                              ))}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Invoice History */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
        <div
          className="px-5 py-4 border-b border-gray-50 flex items-center justify-between cursor-pointer"
          onClick={() => setShowHistory(h => !h)}
        >
          <div>
            <h2 className="text-sm font-semibold text-[#0F172A]">Invoice History</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">{invoices.length} invoices generated</p>
          </div>
          {showHistory ? <ChevronUp className="w-4 h-4 text-[#94A3B8]" /> : <ChevronDown className="w-4 h-4 text-[#94A3B8]" />}
        </div>
        {showHistory && (
          invoices.length === 0 ? (
            <div className="px-5 py-6 text-sm text-[#94A3B8] text-center">No invoices generated yet</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    <th className="text-left text-xs font-medium text-[#94A3B8] px-5 py-3">Invoice No</th>
                    <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Client</th>
                    <th className="text-left text-xs font-medium text-[#94A3B8] px-3 py-3">Month</th>
                    <th className="text-right text-xs font-medium text-[#94A3B8] px-3 py-3">Amount</th>
                    <th className="text-right text-xs font-medium text-[#94A3B8] px-3 py-3">GST</th>
                    <th className="text-right text-xs font-medium text-[#94A3B8] px-5 py-3">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {invoices.map(inv => (
                    <tr key={inv.id} className="hover:bg-[#F8FAFC]/50">
                      <td className="px-5 py-3 text-xs font-mono text-blue-700">{inv.invoiceNo}</td>
                      <td className="px-3 py-3 text-sm text-[#0F172A]">{inv.clientName}</td>
                      <td className="px-3 py-3 text-xs text-[#64748B]">{inv.month}</td>
                      <td className="px-3 py-3 text-right text-sm text-[#0F172A]">{formatPaise(inv.amountPaise)}</td>
                      <td className="px-3 py-3 text-right text-xs text-[#64748B]">{formatPaise(inv.gstPaise)}</td>
                      <td className="px-5 py-3 text-right text-sm font-semibold text-[#0F172A]">{formatPaise(inv.totalPaise)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-[#F1F5F9] bg-[#F8FAFC]/50">
                    <td colSpan={3} className="px-5 py-3 text-xs font-medium text-[#64748B]">Total</td>
                    <td className="px-3 py-3 text-right text-sm font-semibold text-[#0F172A]">
                      {formatPaise(invoices.reduce((s, inv) => s + inv.amountPaise, 0))}
                    </td>
                    <td className="px-3 py-3 text-right text-xs font-semibold text-[#64748B]">
                      {formatPaise(invoices.reduce((s, inv) => s + inv.gstPaise, 0))}
                    </td>
                    <td className="px-5 py-3 text-right text-sm font-semibold text-[#0F172A]">
                      {formatPaise(invoices.reduce((s, inv) => s + inv.totalPaise, 0))}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )
        )}
      </div>

      {/* Pending Invoices reminder */}
      {pendingInvoiceClients.length > 0 && (
        <div className="bg-amber-50 border border-amber-100 rounded-lg px-4 py-3 flex gap-2">
          <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-800">
              {pendingInvoiceClients.length} client{pendingInvoiceClients.length > 1 ? "s" : ""} not yet invoiced this month
            </p>
            <p className="text-xs text-amber-700 mt-0.5">
              {pendingInvoiceClients.map(c => c.client_name).join(", ")}
            </p>
          </div>
        </div>
      )}

      {/* Set Retainer Modal */}
      {modalClient && (
        <SetRetainerModal
          client={modalClient}
          existing={retainers[modalClient.id]}
          onSave={config => saveRetainerConfig(modalClient.id, config)}
          onClose={() => setModalClient(null)}
        />
      )}

      {/* Generate Invoice Modal */}
      {invoiceClient && retainers[invoiceClient.id] && (
        <InvoiceModal
          client={invoiceClient}
          config={retainers[invoiceClient.id]}
          workStatus={workMap[invoiceClient.id] ?? {}}
          invoiceNo={currentInvoiceNo}
          firmName={firmName}
          firmGstin={firmGstin}
          onClose={() => setInvoiceClient(null)}
          onConfirm={handleInvoiceConfirm}
          alreadyGenerated={invoicedClientIds.has(invoiceClient.id)}
        />
      )}
    </div>
  );
}
