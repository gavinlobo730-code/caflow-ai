"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { createPortal } from "react-dom";
import {
  Plus, RefreshCw, X, FileText, CheckCircle, Upload, Send, Clock,
  Pencil, Trash2, Eye, Download, Loader2, AlertTriangle,
  CreditCard, Copy, MoreHorizontal, RotateCcw, Ban, BookOpen,
} from "lucide-react";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { getSupabaseClient } from "@/lib/supabase/client";
import { selectAll } from "@/lib/supabase/selectAll";
import { formatPaise, formatDateTime, formatMoney } from "@/lib/services/formatting";
import { DataTable, exportSelectedAction } from "@/components/ui/data-table";
import type { Column, FilterDef } from "@/lib/table/types";
import { CustomerLookup } from "@/components/lookups/CustomerLookup";
import { HsnLookup } from "@/components/lookups/HsnLookup";
import CsvImportModal, { type ImportRow, type ReferenceResolver } from "@/components/CsvImportModal";
import { buildSalesInvoices, SALES_INVOICE_IMPORT_COLUMNS } from "@/lib/invoices/importMapping";
import { toInvoiceLinePayload } from "@/lib/invoices/lineItemPayload";
import { buildCustomers, CUSTOMER_IMPORT_COLUMNS, buildReceipts, RECEIPT_IMPORT_COLUMNS } from "@/lib/imports/mappers";
import { clearReports } from "@/lib/accounting/reportCache";
import { InvoiceViewDrawer } from "@/components/invoices/InvoiceViewDrawer";
import { CustomerFormModal } from "@/components/customers/CustomerFormModal";
import { ProductServiceFormModal } from "@/components/catalogue/ProductServiceFormModal";
import { api, type ApiResp } from "@/lib/api";
import { serviceToLine, type ServiceCatalogueItem } from "@/lib/catalogue/service";
import { ServiceCataloguePicker } from "@/components/lookups/ServiceCataloguePicker";
import { useRouter } from "next/navigation";
import { newInvoiceHref, editInvoiceHref } from "@/lib/invoices/workspaceNav";
import { writeDuplicateSeed } from "@/lib/invoices/duplicateSeed";
import {
  API, apiCall, apiGet, getAuthToken, fmt, computeGst, GST_RATES, STATUS_BADGE, DELIVERY_STATUS_LABEL,
  type InvoiceDelivery, type InvoiceDetail,
  type Customer, type SalesInvoice, type InvoiceLine,
  type CurrencyOption, type InvoiceStatus,
} from "@/lib/invoices/shared";


// ── Types ──────────────────────────────────────────────────────────────────

type SalesTab = "invoices" | "recurring" | "customers" | "receipts" | "credit-notes" | "statements";
const TABS: { id: SalesTab; label: string }[] = [
  { id: "invoices", label: "Sales Invoices" },
  { id: "recurring", label: "Recurring" },
  { id: "customers", label: "Customers" },
  { id: "receipts", label: "Receipts" },
  { id: "credit-notes", label: "Credit Notes" },
  { id: "statements", label: "Statements" },
];


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


// ── Helpers ────────────────────────────────────────────────────────────────

/** Money formatter — paise → ₹ string (CGST Act §15: all amounts in Indian rupees).
 * Delegates to the shared formatter; it preserves the sign, so a negative amount
 * (e.g. an over-credit) never renders as positive (audit M15). */

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

/** Format an ISO timestamp for display, or "—" when absent (shared formatter). */
const fmtDateTime = formatDateTime;

/**
 * Whether to surface the "Remind" affordance for an invoice. The authoritative
 * overdue/aging computation is server-side (collections sweep stores is_overdue);
 * the due-date fallback here is presentation-only so the button appears even
 * before the next sweep. The send itself is gated and re-validated by the backend
 * (it rejects anything not actually overdue), so no money logic lives here.
 */
function isOverdueForUi(inv: SalesInvoice): boolean {
  if (inv.status !== "issued" && inv.status !== "partially_paid") return false;
  const outstanding = inv.total_paise - (inv.paid_paise ?? 0);
  if (outstanding <= 0) return false;
  if (inv.is_overdue) return true;
  if (inv.due_date) return inv.due_date < new Date().toISOString().slice(0, 10);
  return false;
}

/**
 * Open the GST tax-invoice PDF in a new tab. The endpoint requires a Bearer
 * token, so we fetch with auth and open a blob URL (a plain window.open would
 * drop the Authorization header). Backend-generated PDF — no logic here.
 */

/**
 * Compute GST on invoice lines (paise arithmetic only — never floating point).
 * CGST Act §9: CGST+SGST for intra-state, IGST for inter-state.
 */

// CGST Act Schedule — all notified rates
const PAYMENT_MODES = ["bank", "cash", "cheque", "upi", "neft", "rtgs"];

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

// Portal + fixed position (above the InvoiceViewDrawer's z-50 and the
// slide-over panels' z-[80]) so an error/success from an action taken
// INSIDE an open drawer (Issue, Duplicate, Delete, …) is never hidden
// behind it — a plain in-flow div here previously rendered underneath the
// drawer's own content, invisible to whatever the CA was actually looking
// at when they triggered the action.
function Toast({ msg, type }: { msg: string; type: "success" | "error" }) {
  if (!msg || typeof document === "undefined") return null;
  return createPortal(
    <div
      className={`fixed top-4 right-4 z-[110] max-w-sm rounded-lg px-4 py-3 text-sm font-medium shadow-lg ${
        type === "success"
          ? "bg-green-50 border border-green-100 text-green-700"
          : "bg-red-50 border border-red-100 text-red-700"
      }`}
    >
      {msg}
    </div>,
    document.body,
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────

export default function SalesPage() {
  const { clientId, financialYear } = useClientNav();
  const [tab, setTab] = useState<SalesTab>("invoices");

  // Cross-tab navigation (e.g. Customers → "View Invoices" / "View Ledger").
  // The target customer is stashed in the URL (?cust=) and the tab switches;
  // the destination tab hydrates its customer filter from that param on mount.
  function navigateTo(target: SalesTab, custId?: string) {
    if (custId) {
      const p = new URLSearchParams(window.location.search);
      p.set("cust", custId);
      window.history.replaceState(null, "", `${window.location.pathname}?${p.toString()}`);
    }
    setTab(target);
  }

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
        {tab === "recurring" && (
          <RecurringInvoices clientId={clientId} />
        )}
        {tab === "customers" && (
          <Customers clientId={clientId} financialYear={financialYear} onNavigate={navigateTo} />
        )}
        {tab === "receipts" && (
          <Receipts clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "credit-notes" && (
          <CreditNotes clientId={clientId} financialYear={financialYear} />
        )}
        {tab === "statements" && (
          <Statements clientId={clientId} financialYear={financialYear} />
        )}
      </div>
    </div>
  );
}

// ── Recurring Invoices (Phase 4.3) — draft generation from templates ─────────
// Templates generate DRAFT invoices via the existing invoice engine. Never
// auto-issued, never auto-emailed. All money/GST math is server-side.

interface RecurringLine {
  description: string; hsn_sac: string | null; quantity: number;
  rate_paise: number; gst_rate_bps: number; is_service: boolean; sort_order?: number;
}
interface RecurringTemplate {
  id: string; client_id: string; customer_id: string; title: string;
  description: string | null; frequency: string; start_date: string;
  end_date: string | null; next_run_date: string | null; notes: string | null;
  is_inter_state: boolean; status: "active" | "paused" | "archived";
  lines: RecurringLine[];
}
interface RecurringRun {
  id: string; occurrence_date: string; status: string; created_at: string;
  invoice: { id: string; invoice_no: string | null; status: string | null; total_paise: number | null } | null;
}
type RecEditorLine = { description: string; hsn_sac: string; quantity: string; rate: string; gst: number; is_service: boolean };

const FREQ_LABEL: Record<string, string> = {
  weekly: "Weekly", monthly: "Monthly", quarterly: "Quarterly", half_yearly: "Half-Yearly", yearly: "Yearly",
};
const REC_STATUS_BADGE: Record<string, string> = {
  active: "bg-green-50 text-green-700", paused: "bg-amber-50 text-amber-700", archived: "bg-[#F1F5F9] text-[#64748B]",
};
const recBase = (lines: RecurringLine[]) =>
  lines.reduce((s, l) => s + Math.round((l.rate_paise || 0) * (l.quantity || 0)), 0);

function RecurringInvoices({ clientId }: { clientId: string }) {
  const [templates, setTemplates] = useState<RecurringTemplate[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [editor, setEditor] = useState<RecurringTemplate | "new" | null>(null);
  const [historyFor, setHistoryFor] = useState<RecurringTemplate | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);

  const showToast = (msg: string, type: "success" | "error") => { setToast({ msg, type }); setTimeout(() => setToast(null), 4000); };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const token = await getAuthToken();
      const supabase = getSupabaseClient();
      const [tplRes, { data: custData }] = await Promise.all([
        apiGet(`/api/recurring-invoices?client_id=${encodeURIComponent(clientId)}`, token),
        selectAll(() => supabase.from("customers")
          .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
          .eq("client_id", clientId).eq("is_active", true).order("name").order("id")),
      ]);
      setTemplates((tplRes.data as RecurringTemplate[]) ?? []);
      setCustomers((custData as Customer[]) ?? []);
    } finally {
      // Always clear the skeleton, even if the network call throws (audit M17).
      setLoading(false);
    }
  }, [clientId]);
  useEffect(() => { load(); }, [load]);

  const custName = (id: string) => customers.find((c) => c.id === id)?.name ?? "—";

  async function runNow(t: RecurringTemplate) {
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/recurring-invoices/${t.id}/run`, "POST", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Run failed");
      const d = res.data as { generated_count: number; skipped_count: number };
      showToast(`Generated ${d.generated_count} draft${d.generated_count === 1 ? "" : "s"}`
        + (d.skipped_count ? `; ${d.skipped_count} already existed` : ""), "success");
      load();
    } catch (e) { showToast(e instanceof Error ? e.message : "Run failed", "error"); }
  }

  async function changeStatus(t: RecurringTemplate, action: "pause" | "resume" | "archive") {
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/recurring-invoices/${t.id}/${action}`, "POST", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Update failed");
      showToast(`Template ${action === "resume" ? "resumed" : action + "d"}`, "success");
      load();
    } catch (e) { showToast(e instanceof Error ? e.message : "Update failed", "error"); }
  }

  function toggleRow(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }
  function toggleSelectAll() {
    setSelected((prev) => (prev.size === templates.length ? new Set() : new Set(templates.map((t) => t.id))));
  }

  // Bulk pause/resume/archive — eligibility mirrors the single-row buttons
  // (pause only shows for active, resume only for paused, archive for
  // anything not already archived). Ineligible selected rows are reported
  // as "skipped", not "failed".
  async function bulkChangeStatus(action: "pause" | "resume" | "archive") {
    const eligible = templates.filter((t) => selected.has(t.id) && (
      action === "pause" ? t.status === "active" :
      action === "resume" ? t.status === "paused" :
      t.status !== "archived"
    ));
    if (eligible.length === 0) { showToast("No eligible templates in selection", "error"); return; }
    setBulkBusy(true);
    const token = await getAuthToken();
    let ok = 0;
    const failures: string[] = [];
    await Promise.all(eligible.map(async (t) => {
      try {
        const res = await apiCall(`/api/recurring-invoices/${t.id}/${action}`, "POST", undefined, token);
        if (!res.success) throw new Error(res.error ?? "failed");
        ok++;
      } catch (e) {
        failures.push(`${t.title}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    setBulkBusy(false);
    const skipped = selected.size - eligible.length;
    const parts: string[] = [];
    if (ok) parts.push(`${ok} ${action === "resume" ? "resumed" : action + "d"}`);
    if (skipped) parts.push(`${skipped} not eligible`);
    if (failures.length) parts.push(`${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`);
    showToast(parts.join(", "), failures.length ? "error" : "success");
    if (ok) { setSelected(new Set()); load(); }
  }

  return (
    <div className="space-y-4 max-w-screen-2xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      {editor && (
        <RecurringEditor
          clientId={clientId}
          customers={customers}
          existing={editor === "new" ? null : editor}
          onClose={() => setEditor(null)}
          onSaved={(msg) => { setEditor(null); showToast(msg, "success"); load(); }}
        />
      )}
      {historyFor && (
        <RecurringHistoryDrawer
          template={historyFor}
          customerName={custName(historyFor.customer_id)}
          onClose={() => setHistoryFor(null)}
        />
      )}

      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-semibold text-[#334155]">
            {templates.length} template{templates.length !== 1 ? "s" : ""}
          </p>
          <p className="text-[11px] text-[#94A3B8] mt-0.5">
            Recurring templates generate <strong>draft</strong> invoices for CA review — never auto-issued or auto-emailed.
          </p>
        </div>
        <div className="flex gap-2">
          <button onClick={load} className="p-1.5 rounded border border-[#E2E8F0] hover:bg-[#F8FAFC] text-[#64748B]">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <button onClick={() => setEditor("new")}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700">
            <Plus size={12} /> New Template
          </button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-10 rounded bg-[#F8FAFC] animate-pulse" />)}</div>
      ) : templates.length === 0 ? (
        <div className="bg-white rounded-xl border border-[#F1F5F9] text-center py-16">
          <Clock size={32} className="text-gray-200 mx-auto mb-3" />
          <p className="text-sm text-[#64748B]">No recurring templates yet</p>
          <p className="text-xs text-[#94A3B8] mt-1">Create one to auto-generate draft invoices on a schedule.</p>
        </div>
      ) : (
        <>
          {selected.size > 0 && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[#C7D2FE] bg-[#EEF2FF] px-3 py-2 text-xs">
              <span className="font-semibold text-[#3730A3]">{selected.size} selected</span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <button onClick={() => bulkChangeStatus("pause")} disabled={bulkBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2FE] bg-white px-2.5 py-1.5 font-medium text-[#4338CA] hover:bg-[#E0E7FF] disabled:cursor-not-allowed disabled:opacity-50">
                  Pause
                </button>
                <button onClick={() => bulkChangeStatus("resume")} disabled={bulkBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#C7D2FE] bg-white px-2.5 py-1.5 font-medium text-[#4338CA] hover:bg-[#E0E7FF] disabled:cursor-not-allowed disabled:opacity-50">
                  Resume
                </button>
                <button onClick={() => bulkChangeStatus("archive")} disabled={bulkBusy}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-2.5 py-1.5 font-medium text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50">
                  Archive
                </button>
                <button onClick={() => setSelected(new Set())} disabled={bulkBusy} className="text-[#6366F1] hover:text-[#4338CA] disabled:opacity-50" aria-label="Clear selection">
                  <X size={14} />
                </button>
              </div>
            </div>
          )}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-[#F1F5F9] text-[#94A3B8]">
                    <th className="px-4 py-3 text-left font-semibold w-8">
                      <input
                        type="checkbox"
                        aria-label="Select all templates"
                        checked={templates.length > 0 && selected.size === templates.length}
                        ref={(el) => { if (el) el.indeterminate = selected.size > 0 && selected.size < templates.length; }}
                        onChange={toggleSelectAll}
                        className="h-3.5 w-3.5 rounded border-[#CBD5E1]"
                      />
                    </th>
                    <th className="px-3 py-3 text-left font-semibold">Template</th>
                    <th className="px-3 py-3 text-left font-semibold">Customer</th>
                    <th className="px-3 py-3 text-left font-semibold">Frequency</th>
                    <th className="px-3 py-3 text-left font-semibold">Next Run</th>
                    <th className="px-3 py-3 text-right font-semibold">Base (excl. GST)</th>
                    <th className="px-3 py-3 text-left font-semibold">Status</th>
                    <th className="px-4 py-3 text-right font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {templates.map((t) => (
                    <tr key={t.id} className="hover:bg-[#F8FAFC]">
                      <td className="px-4 py-2.5">
                        <input
                          type="checkbox"
                          aria-label={`Select ${t.title}`}
                          checked={selected.has(t.id)}
                          onChange={() => toggleRow(t.id)}
                          className="h-3.5 w-3.5 rounded border-[#CBD5E1]"
                        />
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="font-medium text-[#1E293B]">{t.title}</div>
                        {t.description && <div className="text-[10px] text-[#94A3B8]">{t.description}</div>}
                      </td>
                      <td className="px-3 py-2.5 text-[#334155]">{custName(t.customer_id)}</td>
                      <td className="px-3 py-2.5 text-[#64748B]">{FREQ_LABEL[t.frequency] ?? t.frequency}</td>
                      <td className="px-3 py-2.5 text-[#64748B] whitespace-nowrap">
                        {t.status === "active" ? (t.next_run_date ?? "—") : <span className="text-[#CBD5E1]">—</span>}
                      </td>
                      <td className="px-3 py-2.5 text-right font-mono text-[#334155]">{fmt(recBase(t.lines ?? []))}</td>
                      <td className="px-3 py-2.5">
                        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${REC_STATUS_BADGE[t.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
                          {t.status}
                        </span>
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center justify-end gap-2.5">
                          {t.status === "active" && (
                            <button onClick={() => runNow(t)} className="text-xs text-blue-600 hover:underline">Run now</button>
                          )}
                          <button onClick={() => setHistoryFor(t)} className="text-[#94A3B8] hover:text-[#334155]" title="History & upcoming">
                            <Clock size={13} />
                          </button>
                          {t.status !== "archived" && (
                            <button onClick={() => setEditor(t)} className="text-[#94A3B8] hover:text-blue-600" title="Edit"><Pencil size={13} /></button>
                          )}
                          {t.status === "active" && (
                            <button onClick={() => changeStatus(t, "pause")} className="text-xs text-amber-600 hover:underline">Pause</button>
                          )}
                          {t.status === "paused" && (
                            <button onClick={() => changeStatus(t, "resume")} className="text-xs text-emerald-600 hover:underline">Resume</button>
                          )}
                          {t.status !== "archived" && (
                            <button onClick={() => changeStatus(t, "archive")} className="text-[#CBD5E1] hover:text-red-600" title="Archive"><Trash2 size={13} /></button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function RecurringEditor({
  clientId, customers, existing, onClose, onSaved,
}: {
  clientId: string;
  customers: Customer[];
  existing: RecurringTemplate | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
}) {
  const [customerId, setCustomerId] = useState(existing?.customer_id ?? "");
  const [title, setTitle] = useState(existing?.title ?? "");
  const [description, setDescription] = useState(existing?.description ?? "");
  const [frequency, setFrequency] = useState(existing?.frequency ?? "monthly");
  const [startDate, setStartDate] = useState(existing?.start_date ?? new Date().toISOString().slice(0, 10));
  const [endDate, setEndDate] = useState(existing?.end_date ?? "");
  const [isInterState, setIsInterState] = useState(existing?.is_inter_state ?? false);
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const [lines, setLines] = useState<RecEditorLine[]>(
    existing?.lines?.length
      ? existing.lines.map((l) => ({
          description: l.description, hsn_sac: l.hsn_sac ?? "", quantity: String(l.quantity ?? 1),
          rate: String((l.rate_paise ?? 0) / 100), gst: (l.gst_rate_bps ?? 1800) / 100, is_service: l.is_service,
        }))
      : [{ description: "", hsn_sac: "", quantity: "1", rate: "", gst: 18, is_service: true }]
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setLine = (i: number, patch: Partial<RecEditorLine>) =>
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  const addLine = () => setLines((ls) => [...ls, { description: "", hsn_sac: "", quantity: "1", rate: "", gst: 18, is_service: true }]);
  const removeLine = (i: number) => setLines((ls) => (ls.length > 1 ? ls.filter((_, idx) => idx !== i) : ls));

  const baseTotal = lines.reduce((s, l) => s + Math.round((parseFloat(l.rate) || 0) * (parseFloat(l.quantity) || 0) * 100), 0);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!customerId) { setError("Select a customer"); return; }
    if (!title.trim()) { setError("Title is required"); return; }
    const payloadLines = lines.filter((l) => l.description.trim()).map((l) => ({
      description: l.description.trim(), hsn_sac: l.hsn_sac.trim() || null,
      quantity: parseFloat(l.quantity) || 1, rate_paise: Math.round((parseFloat(l.rate) || 0) * 100),
      gst_rate_percent: l.gst, is_service: l.is_service,
    }));
    if (payloadLines.length === 0) { setError("Add at least one line item"); return; }
    if (endDate && endDate < startDate) { setError("End date cannot be before start date"); return; }
    setSaving(true); setError(null);
    try {
      const token = await getAuthToken();
      const body: Record<string, unknown> = {
        title: title.trim(), description: description.trim() || null, frequency,
        start_date: startDate, end_date: endDate || null, is_inter_state: isInterState,
        notes: notes.trim() || null, lines: payloadLines,
      };
      let res;
      if (existing) {
        res = await apiCall(`/api/recurring-invoices/${existing.id}`, "PUT", body, token);
      } else {
        body.client_id = clientId; body.customer_id = customerId;
        res = await apiCall(`/api/recurring-invoices`, "POST", body, token);
      }
      if (!res.success) throw new Error(res.error ?? "Save failed");
      onSaved(existing ? "Template updated" : "Template created");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-[#0F172A]">{existing ? "Edit" : "New"} Recurring Template</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={14} /></button>
        </div>
        <form onSubmit={submit} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Customer</label>
              <CustomerLookup
                customers={customers}
                value={customerId}
                onChange={setCustomerId}
                disabled={!!existing}
                placeholder="Select customer…"
                ariaLabel="Customer"
              />
              {existing && <p className="text-[10px] text-[#94A3B8] mt-1">Customer can&apos;t be changed after creation.</p>}
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Title</label>
              <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Monthly bookkeeping fee"
                className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Description (optional)</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Frequency</label>
              <select value={frequency} onChange={(e) => setFrequency(e.target.value)}
                className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                {Object.entries(FREQ_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Start date</label>
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)}
                className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">End date (optional)</label>
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)}
                className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
            </div>
          </div>

          {/* Line items */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="text-xs font-medium text-[#475569]">Line items</label>
              <button type="button" onClick={addLine} className="text-[11px] text-blue-600 hover:underline flex items-center gap-1"><Plus size={11} /> Add line</button>
            </div>
            <div className="space-y-2">
              {lines.map((l, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-center">
                  <input value={l.description} onChange={(e) => setLine(i, { description: e.target.value })} placeholder="Description"
                    className="col-span-4 px-2 py-1.5 border border-[#E2E8F0] rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
                  <input value={l.hsn_sac} onChange={(e) => setLine(i, { hsn_sac: e.target.value })} placeholder="HSN/SAC"
                    className="col-span-2 px-2 py-1.5 border border-[#E2E8F0] rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
                  <input value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} placeholder="Qty" inputMode="decimal"
                    className="col-span-1 px-2 py-1.5 border border-[#E2E8F0] rounded text-xs text-right focus:outline-none focus:ring-1 focus:ring-blue-500" />
                  <input value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} placeholder="Rate ₹" inputMode="decimal"
                    className="col-span-2 px-2 py-1.5 border border-[#E2E8F0] rounded text-xs text-right focus:outline-none focus:ring-1 focus:ring-blue-500" />
                  <select value={l.gst} onChange={(e) => setLine(i, { gst: parseFloat(e.target.value) })}
                    className="col-span-2 px-1 py-1.5 border border-[#E2E8F0] rounded text-xs focus:outline-none focus:ring-1 focus:ring-blue-500">
                    {[0, 5, 12, 18, 28].map((g) => <option key={g} value={g}>{g}%</option>)}
                  </select>
                  <button type="button" onClick={() => removeLine(i)} className="col-span-1 text-[#CBD5E1] hover:text-red-600 flex justify-center"><Trash2 size={13} /></button>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-[#94A3B8] mt-2">
              Base (excl. GST): <span className="font-mono text-[#334155]">{fmt(baseTotal)}</span>. GST is computed by the invoice engine at generation.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Notes (optional)</label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)}
              className="w-full px-3 py-2 border border-[#E2E8F0] rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-blue-500" />
          </div>

          <label className="flex items-center gap-2 text-xs text-[#475569]">
            <input type="checkbox" checked={isInterState} onChange={(e) => setIsInterState(e.target.checked)} />
            Inter-state supply (IGST)
          </label>

          <p className="text-[11px] text-[#94A3B8] bg-[#F8FAFC] rounded px-3 py-2">
            Each run creates a <strong>draft</strong> invoice for CA review — it is never issued or emailed automatically.
          </p>

          {error && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
          <div className="flex gap-3 justify-end">
            <button type="button" onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Cancel</button>
            <button type="submit" disabled={saving}
              className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? "Saving…" : existing ? "Save changes" : "Create template"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function RecurringHistoryDrawer({
  template, customerName, onClose,
}: {
  template: RecurringTemplate;
  customerName: string;
  onClose: () => void;
}) {
  const [runs, setRuns] = useState<RecurringRun[]>([]);
  const [upcoming, setUpcoming] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const token = await getAuthToken();
        const [h, p] = await Promise.all([
          apiGet(`/api/recurring-invoices/${template.id}/history`, token),
          apiGet(`/api/recurring-invoices/${template.id}/preview?count=5`, token),
        ]);
        if (cancelled) return;
        setRuns((h.data as RecurringRun[]) ?? []);
        setUpcoming(((p.data as { occurrences: string[] } | null)?.occurrences) ?? []);
      } finally {
        // Clear the skeleton even if a request throws (audit M17).
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [template.id]);

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-lg shadow-xl max-h-[85vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-[#0F172A]">{template.title}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={14} /></button>
        </div>
        <p className="text-[11px] text-[#94A3B8] mb-4">{customerName} · {FREQ_LABEL[template.frequency] ?? template.frequency}</p>

        {loading ? (
          <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-9 rounded bg-[#F8FAFC] animate-pulse" />)}</div>
        ) : (
          <div className="space-y-5">
            {template.status === "active" && (
              <div>
                <p className="text-[11px] font-semibold text-[#475569] mb-2 uppercase tracking-wide">Upcoming</p>
                {upcoming.length === 0 ? (
                  <p className="text-xs text-[#94A3B8]">No upcoming runs.</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {upcoming.map((d) => <span key={d} className="px-2 py-0.5 rounded bg-[#F8FAFC] border border-[#F1F5F9] text-[11px] text-[#475569]">{d}</span>)}
                  </div>
                )}
              </div>
            )}
            <div>
              <p className="text-[11px] font-semibold text-[#475569] mb-2 uppercase tracking-wide">History</p>
              {runs.length === 0 ? (
                <p className="text-xs text-[#94A3B8]">No invoices generated yet.</p>
              ) : (
                <div className="space-y-2">
                  {runs.map((r) => (
                    <div key={r.id} className="border border-[#F1F5F9] rounded-lg p-3 text-xs flex items-center justify-between">
                      <div>
                        <div className="font-medium text-[#334155]">{r.occurrence_date}</div>
                        <div className="text-[10px] text-[#94A3B8]">
                          {r.invoice?.invoice_no ? `${r.invoice.invoice_no} · ${r.invoice.status ?? "draft"}` : "—"}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {r.invoice?.total_paise != null && <span className="font-mono text-[#334155]">{fmt(r.invoice.total_paise)}</span>}
                        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${r.status === "generated" ? "bg-green-50 text-green-700" : r.status === "failed" ? "bg-red-50 text-red-700" : "bg-[#F1F5F9] text-[#64748B]"}`}>
                          {r.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
        <div className="flex justify-end mt-5 pt-4 border-t border-[#F1F5F9]">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Close</button>
        </div>
      </div>
    </div>
  );
}

// ── Customer Statements (Phase 4.1) — read-only account statement ────────────

interface StmtTxn {
  date: string; type: string; reference: string | null; particulars: string;
  debit_paise: number; credit_paise: number; running_balance_paise: number;
}
interface StmtData {
  customer: { id: string; name: string; email: string | null; gstin: string | null };
  period: { start_date: string; end_date: string };
  opening_balance_paise: number; closing_balance_paise: number;
  transactions: StmtTxn[];
  totals: { invoiced_paise: number; received_paise: number; credited_paise: number; transaction_count: number };
}

const stmtRupees = (p: number) => (Math.abs(p) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const stmtBal = (p: number) => `₹${stmtRupees(p)} ${p >= 0 ? "Dr" : "Cr"}`;
const stmtAmt = (p: number) => (p ? `₹${stmtRupees(p)}` : "—");

function Statements({ clientId, financialYear }: { clientId: string; financialYear: string }) {
  const def = fyRange(financialYear);
  const [customers, setCustomers] = useState<{ id: string; name: string; email: string | null }[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [start, setStart] = useState(def.start);
  const [end, setEnd] = useState(def.end);
  const [stmt, setStmt] = useState<StmtData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [emailModal, setEmailModal] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [emailing, setEmailing] = useState(false);
  const [emailMsg, setEmailMsg] = useState<string | null>(null);

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("cust")) setCustomerId(p.get("cust") as string);
    if (p.get("from")) setStart(p.get("from") as string);
    if (p.get("to")) setEnd(p.get("to") as string);
  }, []);

  function syncUrl(cust: string, f: string, t: string) {
    const p = new URLSearchParams(window.location.search);
    if (cust) p.set("cust", cust); else p.delete("cust");
    p.set("from", f); p.set("to", t);
    window.history.replaceState(null, "", `?${p.toString()}`);
  }

  const loadCustomers = useCallback(async () => {
    const token = await getAuthToken();
    const res = await apiGet(`/api/customers/?client_id=${clientId}`, token);
    if (res.success) setCustomers((res.data as { id: string; name: string; email: string | null }[]) ?? []);
  }, [clientId]);
  useEffect(() => { loadCustomers(); }, [loadCustomers]);

  async function generate() {
    if (!customerId) { setError("Select a customer first."); return; }
    setLoading(true); setError(null); setStmt(null);
    try {
      const token = await getAuthToken();
      const res = await apiGet(`/api/customer-statements?client_id=${clientId}&customer_id=${customerId}&start_date=${start}&end_date=${end}`, token);
      if (res.success) { setStmt(res.data as StmtData); syncUrl(customerId, start, end); }
      else setError(res.error ?? "Could not generate the statement.");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not generate the statement."); }
    finally { setLoading(false); }
  }

  async function downloadPdf() {
    if (!stmt) return;
    const token = await getAuthToken();
    const res = await fetch(`${API}/api/customer-statements/pdf?client_id=${clientId}&customer_id=${customerId}&start_date=${start}&end_date=${end}`,
      { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) { setError("PDF download failed."); return; }
    const blob = await res.blob();
    window.open(URL.createObjectURL(blob), "_blank");
  }

  function openEmail() {
    setEmailTo(stmt?.customer.email ?? "");
    setEmailMsg(null); setEmailModal(true);
  }
  async function sendEmail() {
    setEmailing(true); setEmailMsg(null);
    try {
      const token = await getAuthToken();
      const res = await apiCall("/api/customer-statements/email", "POST",
        { client_id: clientId, customer_id: customerId, start_date: start, end_date: end, to_email: emailTo || undefined }, token);
      if (res.success) { setEmailModal(false); setEmailMsg(null); }
      else setEmailMsg(res.error ?? "Email failed.");
    } catch (e) { setEmailMsg(e instanceof Error ? e.message : "Email failed."); }
    finally { setEmailing(false); }
  }

  return (
    <div className="space-y-4 max-w-screen-2xl">
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-4 space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="sm:col-span-2">
            <label className="block text-xs font-medium text-[#475569] mb-1">Customer</label>
            <CustomerLookup
              customers={customers}
              value={customerId}
              onChange={setCustomerId}
              clearable
              ariaLabel="Customer"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">From</label>
            <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">To</label>
            <input type="date" value={end} onChange={(e) => setEnd(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={generate} disabled={loading || !customerId}
            className="text-xs px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {loading ? "Generating…" : "Generate"}
          </button>
          {stmt && (
            <>
              <button onClick={downloadPdf} className="text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569] flex items-center gap-1.5"><Download size={13} /> Download PDF</button>
              <button onClick={openEmail} className="text-xs px-3 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#475569] flex items-center gap-1.5"><Send size={13} /> Email</button>
            </>
          )}
        </div>
        {error && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-2.5">{error}</p>}
      </div>

      {stmt && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-4 py-3 border-b border-gray-50 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-[#0F172A]">{stmt.customer.name}</p>
              <p className="text-[10px] text-[#94A3B8]">{stmt.period.start_date} → {stmt.period.end_date}{stmt.customer.gstin ? ` · GSTIN ${stmt.customer.gstin}` : ""}</p>
            </div>
            <div className="text-right">
              <p className="text-[10px] text-[#94A3B8]">Closing Outstanding</p>
              <p className={`text-sm font-mono font-semibold ${stmt.closing_balance_paise >= 0 ? "text-blue-700" : "text-orange-700"}`}>{stmtBal(stmt.closing_balance_paise)}</p>
            </div>
          </div>
          <table className="w-full text-xs">
            <thead className="bg-[#F8FAFC] text-[#64748B]"><tr>
              <th className="px-3 py-2 text-left font-medium">Date</th>
              <th className="px-3 py-2 text-left font-medium">Particulars</th>
              <th className="px-3 py-2 text-left font-medium">Ref</th>
              <th className="px-3 py-2 text-right font-medium">Debit</th>
              <th className="px-3 py-2 text-right font-medium">Credit</th>
              <th className="px-3 py-2 text-right font-medium">Balance</th>
            </tr></thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              <tr className="bg-[#F8FAFC] font-medium text-[#475569]">
                <td className="px-3 py-2" colSpan={3}>Opening Balance</td>
                <td className="px-3 py-2 text-right">—</td><td className="px-3 py-2 text-right">—</td>
                <td className="px-3 py-2 text-right font-mono">{stmtBal(stmt.opening_balance_paise)}</td>
              </tr>
              {stmt.transactions.map((t, i) => (
                <tr key={i} className="hover:bg-[#F8FAFC]">
                  <td className="px-3 py-2 whitespace-nowrap text-[#64748B]">{t.date}</td>
                  <td className="px-3 py-2 text-[#334155]">{t.particulars}</td>
                  <td className="px-3 py-2 font-mono text-[#94A3B8]">{t.reference ?? "—"}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#334155]">{stmtAmt(t.debit_paise)}</td>
                  <td className="px-3 py-2 text-right font-mono text-[#334155]">{stmtAmt(t.credit_paise)}</td>
                  <td className="px-3 py-2 text-right font-mono">{stmtBal(t.running_balance_paise)}</td>
                </tr>
              ))}
              <tr className="bg-[#F8FAFC] font-semibold text-[#0F172A] border-t border-[#E2E8F0]">
                <td className="px-3 py-2" colSpan={3}>Closing Outstanding</td>
                <td className="px-3 py-2 text-right">—</td><td className="px-3 py-2 text-right">—</td>
                <td className="px-3 py-2 text-right font-mono">{stmtBal(stmt.closing_balance_paise)}</td>
              </tr>
            </tbody>
          </table>
          {stmt.transactions.length === 0 && (
            <p className="px-4 py-4 text-center text-xs text-[#94A3B8]">No transactions in this period.</p>
          )}
        </div>
      )}

      {emailModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30" onClick={() => setEmailModal(false)}>
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-5 space-y-3" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-sm font-semibold text-[#0F172A]">Email statement to customer</h3>
            <label className="block">
              <span className="text-xs font-medium text-[#475569]">Recipient email</span>
              <input value={emailTo} onChange={(e) => setEmailTo(e.target.value)} placeholder="customer@example.com"
                className="mt-1 w-full px-3 py-2 text-sm border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </label>
            {emailMsg && <p className="text-xs text-red-700 bg-red-50 border border-red-100 rounded-lg p-2.5">{emailMsg}</p>}
            <div className="flex justify-end gap-2">
              <button onClick={() => setEmailModal(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg text-[#475569] hover:bg-[#F8FAFC]">Cancel</button>
              <button onClick={sendEmail} disabled={emailing || !emailTo} className="text-xs px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">{emailing ? "Sending…" : "Send"}</button>
            </div>
          </div>
        </div>
      )}
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
  // Client's own Product/Service catalogue — only needed for the CSV import's
  // "resolve missing references" step (product_service column). The manual
  // editor loads this itself via ServiceCataloguePicker.
  const [services, setServices] = useState<ServiceCatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const [showImport, setShowImport] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);
  const [sendModal, setSendModal] = useState<{ invoice: SalesInvoice; customerEmail: string | null } | null>(null);
  const [remindModal, setRemindModal] = useState<{ invoice: SalesInvoice; customerEmail: string | null } | null>(null);
  const [deliveryModal, setDeliveryModal] = useState<{ invoice: SalesInvoice; deliveries: InvoiceDelivery[] } | null>(null);
  const [paymentModal, setPaymentModal] = useState<SalesInvoice | null>(null);

  // Detail drawer (deep-linked via ?invoice=) / delete
  const [detailId, setDetailId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SalesInvoice | null>(null);
  const [issuingId, setIssuingId] = useState<string | null>(null);
  // Row overflow menu — everything except the draft row's one-click "Issue"
  // lives here so the actions column reads as one button, not a strip of
  // mixed icon/text buttons. Anchored to the viewport (mirrors the Customers
  // tab's own menu below) since the table scrolls/clips an in-flow dropdown.
  const [menu, setMenu] = useState<{ id: string; top: number; left: number } | null>(null);
  function openMenuFor(e: React.MouseEvent, inv: SalesInvoice) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ id: inv.id, top: r.bottom + 4, left: Math.max(8, r.right - 192) });
  }

  // FY / date-window selector that SCOPES THE SERVER QUERY (which rows load).
  // Client-side search/sort/status/amount/date filtering is owned by DataTable
  // below (persisted via persistKey). The FY window + customer scope stay here
  // (the FY selector renders in the table toolbar; the customer scope is also
  // seeded from ?cust= for cross-tab "View Invoices" navigation).
  const [customerFilter, setCustomerFilter] = useState<string>("all");
  const [dateMode, setDateMode] = useState<DateMode>("current");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  // Summary stats
  const [stats, setStats] = useState({ outstanding: 0, issued: 0, paid: 0 });

  // ── URL state: hydrate the FY window + customer scope once on mount, then
  // mirror them back. (Search/sort/filters now persist via the DataTable.) ───
  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    if (p.get("cust")) setCustomerFilter(p.get("cust")!);
    if (p.get("fy")) setDateMode(p.get("fy") as DateMode);
    if (p.get("from")) setCustomFrom(p.get("from")!);
    if (p.get("to")) setCustomTo(p.get("to")!);
    // Deep-link: ?invoice=<id> opens the View drawer directly (refresh-safe).
    if (p.get("invoice")) setDetailId(p.get("invoice"));
    // One-shot success feedback after the editor saves/issues/sends (Batch 3):
    // ?flash=<msg> → toast, then strip the param so a refresh doesn't repeat it.
    const flash = p.get("flash");
    if (flash) {
      showToast(flash, "success");
      p.delete("flash");
      const qs = p.toString();
      window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
    }
  }, []);

  useEffect(() => {
    const p = new URLSearchParams(window.location.search);
    const set = (k: string, v: string, def: string) => (v && v !== def ? p.set(k, v) : p.delete(k));
    set("cust", customerFilter, "all");
    set("fy", dateMode, "current");
    set("from", dateMode === "custom" ? customFrom : "", "");
    set("to", dateMode === "custom" ? customTo : "", "");
    // Mirror the open detail drawer as ?invoice=<id> for deep-linking.
    if (detailId) p.set("invoice", detailId); else p.delete("invoice");
    const qs = p.toString();
    window.history.replaceState(null, "", qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
  }, [customerFilter, dateMode, customFrom, customTo, detailId]);

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

    const [{ data: invData }, { data: custData }, servicesRes] = await Promise.all([
      selectAll(() => supabase
        .from("client_sales_invoices")
        .select(
          "id, invoice_no, invoice_date, due_date, customer_id, taxable_amount_paise, total_gst_paise, total_paise, paid_paise, status, supply_state_code, is_interstate, is_overdue, days_overdue, reminder_count, last_reminded_at, customers(name)"
        )
        .eq("client_id", clientId)
        .is("deleted_at", null)
        .gte("invoice_date", range.start)
        .lte("invoice_date", range.end)
        .order("invoice_date", { ascending: false })
        .order("id")),
      selectAll(() => supabase
        .from("customers")
        .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name")
        .order("id")),
      api.serviceCatalogue.list(clientId, { limit: 100 }) as Promise<ApiResp<ServiceCatalogueItem[]>>,
    ]);
    setServices(servicesRes.data ?? []);

    const mapped: SalesInvoice[] = ((invData ?? []) as unknown as Array<
      { id: string; invoice_no: string; invoice_date: string; due_date: string | null;
        customer_id: string; taxable_amount_paise: number; total_gst_paise: number;
        total_paise: number; paid_paise: number; status: string; supply_state_code: string | null;
        is_interstate: boolean; is_overdue: boolean | null; days_overdue: number | null;
        reminder_count: number | null; last_reminded_at: string | null;
        customers: { name: string } | null }
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
      is_overdue: r.is_overdue ?? false,
      days_overdue: r.days_overdue ?? 0,
      reminder_count: r.reminder_count ?? 0,
      last_reminded_at: r.last_reminded_at,
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

  // Customer scope is a toolbar control (also seeded from ?cust= for cross-tab
  // navigation), so it pre-filters the rows the DataTable then searches/sorts.
  const scoped = useMemo(
    () => (customerFilter === "all" ? invoices : invoices.filter((inv) => inv.customer_id === customerFilter)),
    [invoices, customerFilter],
  );

  async function issueInvoice(id: string) {
    if (issuingId) return; // already posting one — the button is disabled, but a
    // programmatic double-call (e.g. the detail drawer's onIssue) shouldn't race it.
    setIssuingId(id);
    try {
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const token = await getAuthToken();
      const result = await apiCall(`/api/sales-invoices/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue invoice");
      showToast("Invoice issued successfully", "success");
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Error issuing invoice", "error");
    } finally {
      setIssuingId(null);
    }
  }

  function openEdit(inv: SalesInvoice) {
    // Navigate to the dedicated Edit route (Batch 2). The edit page loads the
    // invoice detail itself and enforces draft-only editing.
    setDetailId(null);
    router.push(editInvoiceHref(clientId, inv.id));
  }

  // Duplicate: QuickBooks-style — nothing is created server-side up front.
  // The source invoice is stashed (writeDuplicateSeed) and the New Invoice
  // route is opened; InvoiceEditor pre-fills its unsaved form from it (the
  // customer and line items, never the number/dates/payment state — those
  // start exactly like any other new invoice). The CA reviews, types their
  // own invoice number, and saves like normal; a colliding number surfaces
  // the SAME inline "already exists" error every manually-typed one does,
  // right there in the editor — never a surprise on a different screen.
  function handleDuplicate(inv: InvoiceDetail) {
    writeDuplicateSeed(inv);
    setDetailId(null);
    router.push(newInvoiceHref(clientId));
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

  // Bulk "Delete / Void" — per row, does the CORRECT operation for its status:
  // a draft is truly deleted (DELETE, existing endpoint); anything issued is
  // VOIDED (POST .../cancel, existing endpoint) — that reverses the posted
  // journal but keeps the invoice number on record (CGST Rule 46(b): an
  // issued number must stay explainable, never just vanish). One warning
  // covers both, since from the CA's point of view it's the same "make this
  // invoice go away" action; only the mechanism differs underneath.
  async function bulkDeleteOrVoid(selected: SalesInvoice[]): Promise<boolean> {
    const token = await getAuthToken();
    let deleted = 0, voided = 0;
    const failures: string[] = [];
    await Promise.all(selected.map(async (inv) => {
      try {
        if (inv.status === "draft") {
          const result = await apiCall(`/api/sales-invoices/${inv.id}`, "DELETE", undefined, token);
          if (!result.success) throw new Error(result.error ?? "delete failed");
          deleted++;
        } else if (inv.status === "cancelled") {
          failures.push(`${inv.invoice_no}: already voided`);
        } else {
          const result = await apiCall(`/api/sales-invoices/${inv.id}/cancel`, "POST", undefined, token);
          if (!result.success) throw new Error(result.error ?? "void failed");
          voided++;
        }
      } catch (e) {
        failures.push(`${inv.invoice_no}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const parts: string[] = [];
    if (deleted) parts.push(`${deleted} draft${deleted !== 1 ? "s" : ""} deleted`);
    if (voided) parts.push(`${voided} invoice${voided !== 1 ? "s" : ""} voided`);
    if (failures.length) parts.push(`${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`);
    showToast(parts.join(", ") || "Nothing to do", failures.length ? "error" : "success");
    if (deleted || voided) load();
    return failures.length === 0;
  }

  // Bulk Send — same per-invoice guard as the single "Send" row action (no
  // sending a draft/cancelled invoice, and no email on file is a per-row
  // skip, not a hard stop for the rest of the batch).
  async function bulkSendInvoices(selected: SalesInvoice[]): Promise<boolean> {
    const token = await getAuthToken();
    let sent = 0;
    const failures: string[] = [];
    await Promise.all(selected.map(async (inv) => {
      if (inv.status === "draft" || inv.status === "cancelled") {
        failures.push(`${inv.invoice_no}: cannot send a ${inv.status} invoice`);
        return;
      }
      const cust = customers.find((c) => c.id === inv.customer_id);
      if (!cust?.email) {
        failures.push(`${inv.invoice_no}: no email on file`);
        return;
      }
      try {
        const result = await apiCall(`/api/sales-invoices/${inv.id}/send`, "POST", { to_email: cust.email }, token);
        if (!result.success) throw new Error(result.error ?? "send failed");
        sent++;
      } catch (e) {
        failures.push(`${inv.invoice_no}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const summary = failures.length
      ? `${sent} sent, ${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`
      : `${sent} invoice${sent !== 1 ? "s" : ""} sent`;
    showToast(summary, failures.length ? "error" : "success");
    return failures.length === 0;
  }

  function openSend(inv: SalesInvoice) {
    const cust = customers.find((c) => c.id === inv.customer_id);
    setSendModal({ invoice: inv, customerEmail: cust?.email ?? null });
  }

  function openRemind(inv: SalesInvoice) {
    const cust = customers.find((c) => c.id === inv.customer_id);
    setRemindModal({ invoice: inv, customerEmail: cust?.email ?? null });
  }

  // Manual overdue-payment reminder. Collections-only: the backend emails the
  // customer (invoice PDF attached) and records the send; it posts no journal
  // and re-validates that the invoice is actually overdue. Throws on failure so
  // the modal surfaces the error; reloads to refresh reminder_count on success.
  async function remindInvoice(inv: SalesInvoice) {
    const token = await getAuthToken();
    const result = await apiCall(`/api/sales-invoices/${inv.id}/remind`, "POST", undefined, token);
    if (!result.success) throw new Error(result.error ?? "Failed to send reminder");
    showToast(`Payment reminder sent for ${inv.invoice_no}`, "success");
    setRemindModal(null);
    load();
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
   * via the pure buildSalesInvoices() mapper, then creates them all in ONE request
   * via /api/sales-invoices/bulk (same _create_invoice_core logic the manual form's
   * single-create endpoint uses — no parallel invoice logic, just no per-row network
   * round-trip). Returns a per-invoice success/error report.
   */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const { invoices: built, errors } = buildSalesInvoices(rows, clientId, customers, services);
    if (built.length === 0) return { imported: 0, errors };
    const token = await getAuthToken();

    let imported = 0;
    const result = await apiCall("/api/sales-invoices/bulk", "POST", { invoices: built }, token);
    if (result.success) {
      const data = result.data as {
        created: { invoice_no: string; lines?: unknown[] }[];
        errors: { invoice_no: string; error: string }[];
      };
      for (const inv of data.created) {
        imported += Array.isArray(inv.lines) ? inv.lines.length : 0; // count line-rows so the totals match the upload
      }
      for (const e of data.errors) {
        errors.push(`Invoice "${e.invoice_no}": ${e.error}`);
      }
    } else {
      errors.push(result.error ?? "Bulk import failed");
    }

    if (imported > 0) load();
    return { imported, errors };
  }

  // "Resolve missing references" step (Sales Invoice Import Alignment) — a row
  // naming a customer or product/service that doesn't exist yet for this
  // client gets a "+ Add" action opening the SAME creation dialog the rest of
  // the app uses, right inside the import modal. Fresh closures over
  // customers/services every render, so a newly-created record immediately
  // drops out of the "missing" list — see ReferenceResolver's contract.
  const importResolvers: ReferenceResolver[] = [
    {
      column: "customer",
      label: "Customers",
      isKnown: (name) => customers.some((c) => c.name.trim().toLowerCase() === name.trim().toLowerCase()),
      renderCreate: (name, onDone) => (
        <CustomerFormModal
          clientId={clientId}
          existing={null}
          seedName={name}
          onClose={onDone}
          onSaved={(customer) => { setCustomers((prev) => [...prev, customer]); onDone(); }}
        />
      ),
    },
    {
      column: "product_service",
      label: "Products & Services",
      isKnown: (name) => services.some((s) => s.name.trim().toLowerCase() === name.trim().toLowerCase()),
      renderCreate: (name, onDone) => (
        <ProductServiceFormModal
          clientId={clientId}
          existing={null}
          seedName={name}
          onClose={onDone}
          onSaved={(item) => { setServices((prev) => [...prev, item]); onDone(); }}
          onError={(msg) => showToast(msg, "error")}
        />
      ),
    },
  ];

  // ── DataTable columns / filters (client-side over the loaded FY window) ────
  const columns: Column<SalesInvoice>[] = useMemo(() => [
    { key: "invoice_no", header: "Invoice No", accessor: (i) => i.invoice_no, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (i) => <span className="font-mono font-medium text-[#1E293B]">{i.invoice_no}</span> },
    { key: "invoice_date", header: "Date", accessor: (i) => i.invoice_date, sortable: true,
      render: (i) => <span className="text-[#64748B] whitespace-nowrap">{i.invoice_date}</span> },
    { key: "customer_name", header: "Customer", accessor: (i) => i.customer_name ?? "", searchable: true,
      render: (i) => <span className="text-[#334155]">{i.customer_name}</span> },
    { key: "taxable_paise", header: "Taxable", accessor: (i) => i.taxable_paise, align: "right", exportValue: (i) => formatPaise(i.taxable_paise),
      render: (i) => <span className="font-mono text-[#334155]">{fmt(i.taxable_paise)}</span> },
    { key: "gst_paise", header: "GST", accessor: (i) => i.gst_paise, align: "right", exportValue: (i) => formatPaise(i.gst_paise),
      render: (i) => <span className="font-mono text-[#334155]">{fmt(i.gst_paise)}</span> },
    { key: "total_paise", header: "Total", accessor: (i) => i.total_paise, sortable: true, align: "right", exportValue: (i) => formatPaise(i.total_paise),
      render: (i) => <span className="font-mono font-semibold text-[#0F172A]">{fmt(i.total_paise)}</span> },
    { key: "due_date", header: "Due", accessor: (i) => i.due_date ?? "", sortable: true,
      render: (i) => (
        <span className={`whitespace-nowrap ${isOverdueForUi(i) ? "text-red-600 font-medium" : "text-[#64748B]"}`}>
          {i.due_date ?? "—"}
          {isOverdueForUi(i) && i.days_overdue ? <span className="ml-1 text-[10px]">({i.days_overdue}d)</span> : null}
        </span>
      ) },
    { key: "status", header: "Status", accessor: (i) => i.status, sortable: true,
      render: (i) => (
        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[i.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
          {i.status.replace("_", " ")}
        </span>
      ) },
  ], []);

  const filters: FilterDef<SalesInvoice>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (i) => i.status, options: [
      { value: "draft", label: "Draft" },
      { value: "issued", label: "Issued" },
      { value: "partially_paid", label: "Partially paid" },
      { value: "paid", label: "Paid" },
      { value: "cancelled", label: "Cancelled" },
    ] },
    { key: "invoice_date", label: "Invoice date", type: "dateRange", accessor: (i) => i.invoice_date },
    { key: "total_paise", label: "Total", type: "amountRange", accessor: (i) => i.total_paise },
  ], []);

  return (
    <div className="space-y-4 max-w-screen-2xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      {sendModal && (
        <SendInvoiceModal
          invoice={sendModal.invoice}
          defaultEmail={sendModal.customerEmail}
          onSend={(email) => sendInvoice(sendModal.invoice, email, false)}
          onClose={() => setSendModal(null)}
        />
      )}

      {remindModal && (
        <RemindInvoiceModal
          invoice={remindModal.invoice}
          customerEmail={remindModal.customerEmail}
          onConfirm={() => remindInvoice(remindModal.invoice)}
          onClose={() => setRemindModal(null)}
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

      {paymentModal && (
        <PaymentLinkModal invoice={paymentModal} onClose={() => setPaymentModal(null)} />
      )}

      {detailId && (
        <InvoiceViewDrawer
          invoiceId={detailId}
          clientId={clientId}
          onClose={() => setDetailId(null)}
          onEdit={(inv) => openEdit(inv)}
          onIssue={(id) => { setDetailId(null); issueInvoice(id); }}
          onSend={(inv) => { setDetailId(null); openSend(inv); }}
          onDelete={(inv) => { setDetailId(null); setDeleteTarget(inv); }}
          onDuplicate={(inv) => handleDuplicate(inv)}
          onPaymentLink={(inv) => setPaymentModal(inv)}
          onChanged={load}
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
          {invoices.length} invoice{invoices.length !== 1 ? "s" : ""} in this period
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 text-xs border border-[#E2E8F0] text-[#475569] px-3 py-1.5 rounded-lg hover:bg-[#F8FAFC]"
          >
            <Upload size={12} /> Import
          </button>
          <button
            onClick={() => router.push(newInvoiceHref(clientId))}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-1.5 rounded-lg hover:bg-blue-700"
          >
            <Plus size={12} /> New Invoice
          </button>
        </div>
      </div>

      {/* Bulk import (CSV / XLSX) — reuses the existing create endpoint */}
      {showImport && (
        <CsvImportModal
          title="Import Sales Invoices"
          columns={SALES_INVOICE_IMPORT_COLUMNS}
          templateFilename="sales-invoices-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
          resolvers={importResolvers}
        />
      )}

      {/* Row overflow menu — View/Edit/Delete/Send/Remind/Deliveries/Pay link,
          everything except a draft's own visible "Issue" button. */}
      {menu && (() => {
        const inv = scoped.find((x) => x.id === menu.id);
        if (!inv) return null;
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
            <div
              className="fixed z-50 w-48 bg-white rounded-lg border border-[#E2E8F0] shadow-lg py-1 text-xs"
              style={{ top: menu.top, left: menu.left }}
            >
              <button onClick={() => { setMenu(null); setDetailId(inv.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                <Eye size={13} /> View details
              </button>
              {inv.status === "draft" && (
                <>
                  <button onClick={() => { setMenu(null); openEdit(inv); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                    <Pencil size={13} /> Edit draft
                  </button>
                  <div className="my-1 border-t border-[#F1F5F9]" />
                  <button onClick={() => { setMenu(null); setDeleteTarget(inv); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                    <Trash2 size={13} /> Delete draft
                  </button>
                </>
              )}
              {inv.status !== "draft" && inv.status !== "cancelled" && (
                <>
                  <button onClick={() => { setMenu(null); openSend(inv); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                    <Send size={13} /> Send
                  </button>
                  {isOverdueForUi(inv) && (
                    <button
                      onClick={() => { setMenu(null); openRemind(inv); }}
                      title={inv.last_reminded_at
                        ? `Last reminded ${fmtDateTime(inv.last_reminded_at)} · ${inv.reminder_count ?? 0} sent`
                        : "Send an overdue-payment reminder"}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-amber-700"
                    >
                      <AlertTriangle size={13} /> Remind{inv.reminder_count ? ` (${inv.reminder_count})` : ""}
                    </button>
                  )}
                  <button onClick={() => { setMenu(null); loadAndShowDeliveries(inv); }}
                    className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                    <Clock size={13} /> Delivery history
                  </button>
                  {(inv.status === "issued" || inv.status === "partially_paid") && (
                    <button onClick={() => { setMenu(null); setPaymentModal(inv); }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                      <CreditCard size={13} /> Pay link
                    </button>
                  )}
                </>
              )}
            </div>
          </>
        );
      })()}

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={scoped}
        columns={columns}
        filters={filters}
        getRowId={(i) => i.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search invoice no. or customer…"
        initialSort={{ key: "invoice_date", dir: "desc" }}
        exportFilename="sales-invoices"
        persistKey="sales.invoices"
        emptyTitle="No invoices in this period"
        onRowClick={(inv) => setDetailId(inv.id)}
        bulkActions={[
          {
            id: "delete-void",
            label: "Delete / Void",
            icon: <Trash2 size={13} />,
            variant: "danger",
            confirm: "Delete the selected draft invoices and void the selected issued invoices? Voiding reverses the accounting entry but keeps the invoice number on record. This cannot be undone.",
            run: bulkDeleteOrVoid,
          },
          {
            id: "send",
            label: "Send",
            icon: <Send size={13} />,
            confirm: "Email the selected invoices to their customers?",
            run: bulkSendInvoices,
          },
          exportSelectedAction("sales-invoices-selected.csv", columns),
        ]}
        toolbarExtra={
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-[180px]">
              <CustomerLookup
                customers={customers}
                value={customerFilter === "all" ? "" : customerFilter}
                onChange={(id) => setCustomerFilter(id || "all")}
                clearable
                size="sm"
                placeholder="All customers"
                ariaLabel="Filter by customer"
              />
            </div>
            <select
              value={dateMode}
              onChange={(e) => setDateMode(e.target.value as DateMode)}
              aria-label="Financial year"
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
                  aria-label="From date"
                  className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
                />
                <span className="text-xs text-[#94A3B8]">to</span>
                <input
                  type="date"
                  value={customTo}
                  onChange={(e) => setCustomTo(e.target.value)}
                  aria-label="To date"
                  className="px-2 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-[#475569]"
                />
              </>
            )}
          </div>
        }
        rowActions={(inv) => (
          <div className="flex items-center justify-end gap-2">
            {inv.status === "draft" && (
              <button
                onClick={() => issueInvoice(inv.id)}
                disabled={issuingId === inv.id}
                className="text-xs text-blue-600 hover:underline flex items-center gap-1 disabled:opacity-50 disabled:no-underline"
              >
                {issuingId === inv.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />} Issue
              </button>
            )}
            <button
              onClick={(e) => openMenuFor(e, inv)}
              aria-label={`Actions for invoice ${inv.invoice_no}`}
              className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"
            >
              <MoreHorizontal size={16} />
            </button>
          </div>
        )}
      />
    </div>
  );
}

// ── Online Payment Link Modal (Phase 4.6) ──────────────────────────────────
// Generate / copy / send a hosted payment link and view payment history for an
// invoice. Pure presentation: outstanding, links and payments come from the
// server; the gateway never touches accounting (a verified capture creates the
// receipt server-side through the existing receipt engine).

interface PaymentLinkRow { id: string; short_url: string | null; amount_paise: number; status: string; provider: string; created_at?: string }
interface CustomerPaymentRow { id: string; amount_paise: number; status: string; provider: string; provider_payment_id: string | null; receipt_id: string | null; created_at?: string }
interface PaymentHistory { outstanding_paise: number; links: PaymentLinkRow[]; payments: CustomerPaymentRow[] }

const PAY_STATUS_BADGE: Record<string, string> = {
  created: "bg-[#F1F5F9] text-[#64748B]", active: "bg-blue-100 text-blue-700",
  paid: "bg-green-100 text-green-700", captured: "bg-green-100 text-green-700",
  authorized: "bg-amber-100 text-amber-700", failed: "bg-red-100 text-red-600",
  refunded: "bg-purple-100 text-purple-700", expired: "bg-[#F1F5F9] text-[#94A3B8]",
  cancelled: "bg-red-50 text-red-500",
};

function PaymentLinkModal({ invoice, onClose }: { invoice: SalesInvoice; onClose: () => void }) {
  const [hist, setHist] = useState<PaymentHistory | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const load = useCallback(async () => {
    try {
      const token = await getAuthToken();
      const res = await apiGet(`/api/payments?invoice_id=${invoice.id}`, token);
      if (res.success) setHist(res.data as PaymentHistory);
      else setMsg({ text: res.error ?? "Could not load payments", type: "error" });
    } catch {
      setMsg({ text: "Could not load payments", type: "error" });
    }
  }, [invoice.id]);
  useEffect(() => { load(); }, [load]);

  async function generate() {
    setBusy(true); setMsg(null);
    try {
      const token = await getAuthToken();
      const res = await apiCall("/api/payments/links", "POST", { invoice_id: invoice.id }, token);
      if (!res.success) throw new Error(res.error ?? "Could not create link");
      setMsg({ text: "Payment link ready", type: "success" });
      await load();
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : "Could not create link", type: "error" }); }
    finally { setBusy(false); }
  }

  async function copy(url: string | null) {
    if (!url) return;
    try { await navigator.clipboard.writeText(url); setMsg({ text: "Link copied to clipboard", type: "success" }); }
    catch { setMsg({ text: "Copy failed — select the link and copy manually", type: "error" }); }
  }

  async function send(linkId: string) {
    setBusy(true); setMsg(null);
    try {
      const token = await getAuthToken();
      const res = await apiCall(`/api/payments/links/${linkId}/send`, "POST", undefined, token);
      if (!res.success) throw new Error(res.error ?? "Could not send");
      const d = res.data as { sent: boolean; to: string };
      setMsg({ text: d.sent ? `Payment link emailed to ${d.to}` : "Email not sent (check customer email / mail config)", type: d.sent ? "success" : "error" });
    } catch (e) { setMsg({ text: e instanceof Error ? e.message : "Could not send", type: "error" }); }
    finally { setBusy(false); }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-lg shadow-xl max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-1">
          <h3 className="text-sm font-semibold text-[#0F172A]">Online Payment · {invoice.invoice_no}</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={14} /></button>
        </div>
        <p className="text-[11px] text-[#94A3B8] mb-4">
          A verified payment posts a receipt automatically through the standard receipt workflow — no manual entry.
        </p>

        {msg && (
          <div className={`rounded-lg px-3 py-2 text-xs mb-3 ${msg.type === "success" ? "bg-green-50 text-green-700 border border-green-100" : "bg-red-50 text-red-700 border border-red-100"}`}>
            {msg.text}
          </div>
        )}

        <div className="flex items-center justify-between rounded-lg bg-[#F8FAFC] border border-[#F1F5F9] px-3 py-2.5 mb-4">
          <div>
            <p className="text-[10px] uppercase tracking-wide text-[#94A3B8]">Outstanding</p>
            <p className="text-base font-semibold text-[#0F172A] font-mono">{hist ? fmt(hist.outstanding_paise) : "…"}</p>
          </div>
          <button onClick={generate} disabled={busy || !hist || hist.outstanding_paise <= 0}
            className="flex items-center gap-1.5 text-xs bg-indigo-600 text-white px-3 py-2 rounded-lg hover:bg-indigo-700 disabled:opacity-50">
            <CreditCard size={13} /> Generate Payment Link
          </button>
        </div>

        {/* Links */}
        <p className="text-[11px] font-semibold text-[#475569] uppercase tracking-wide mb-2">Payment Links</p>
        {!hist ? (
          <div className="h-10 rounded bg-[#F8FAFC] animate-pulse" />
        ) : hist.links.length === 0 ? (
          <p className="text-xs text-[#94A3B8] mb-4">No payment links yet. Generate one above.</p>
        ) : (
          <div className="space-y-2 mb-4">
            {hist.links.map((l) => (
              <div key={l.id} className="border border-[#F1F5F9] rounded-lg p-2.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-[#334155] truncate">{l.short_url ?? "—"}</span>
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${PAY_STATUS_BADGE[l.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>{l.status}</span>
                </div>
                <div className="flex items-center justify-between mt-1.5">
                  <span className="font-mono text-[#64748B]">{fmt(l.amount_paise)}</span>
                  <div className="flex items-center gap-3">
                    <button onClick={() => copy(l.short_url)} className="text-[#64748B] hover:text-indigo-600 flex items-center gap-1"><Copy size={11} /> Copy</button>
                    <button onClick={() => send(l.id)} disabled={busy} className="text-emerald-600 hover:underline flex items-center gap-1 disabled:opacity-50"><Send size={11} /> Email</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Payment history / timeline */}
        <p className="text-[11px] font-semibold text-[#475569] uppercase tracking-wide mb-2">Payment History</p>
        {!hist || hist.payments.length === 0 ? (
          <p className="text-xs text-[#94A3B8]">No payments recorded yet.</p>
        ) : (
          <div className="space-y-2">
            {hist.payments.map((p) => (
              <div key={p.id} className="flex items-center justify-between border border-[#F1F5F9] rounded-lg p-2.5 text-xs">
                <div>
                  <div className="font-mono text-[#334155]">{fmt(p.amount_paise)}</div>
                  <div className="text-[10px] text-[#94A3B8]">{p.provider}{p.receipt_id ? " · receipt posted" : ""}{p.created_at ? ` · ${fmtDateTime(p.created_at)}` : ""}</div>
                </div>
                <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${PAY_STATUS_BADGE[p.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>{p.status}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex justify-end mt-5 pt-4 border-t border-[#F1F5F9]">
          <button onClick={onClose} className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]">Close</button>
        </div>
      </div>
    </div>
  );
}

// ── Invoice Create Form ────────────────────────────────────────────────────

/** A customer's GST state code: explicit state_code, else the GSTIN's first 2 digits. */

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

// ── Payment Reminder Modal (Phase 4.2) ─────────────────────────────────────

function RemindInvoiceModal({
  invoice,
  customerEmail,
  onConfirm,
  onClose,
}: {
  invoice: SalesInvoice;
  customerEmail: string | null;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const outstanding = invoice.total_paise - (invoice.paid_paise ?? 0);

  async function handleConfirm() {
    setSending(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send reminder");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/30 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-[#0F172A]">Send Payment Reminder</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#334155]"><X size={14} /></button>
        </div>
        <div className="space-y-3 text-xs">
          <div className="rounded-lg bg-[#F8FAFC] border border-[#F1F5F9] p-3 space-y-1">
            <div className="flex justify-between">
              <span className="text-[#64748B]">Invoice</span>
              <span className="font-mono font-medium text-[#1E293B]">{invoice.invoice_no}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B]">Outstanding</span>
              <span className="font-mono font-semibold text-[#0F172A]">{fmt(outstanding)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B]">Due date</span>
              <span className="text-red-600 font-medium">
                {invoice.due_date ?? "—"}{invoice.days_overdue ? ` (${invoice.days_overdue}d overdue)` : ""}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-[#64748B]">Reminders sent</span>
              <span className="text-[#334155]">{invoice.reminder_count ?? 0}</span>
            </div>
          </div>
          {customerEmail ? (
            <p className="text-[#64748B]">
              A reminder email — with the original invoice PDF attached — will be sent to{" "}
              <span className="font-medium text-[#334155]">{customerEmail}</span>.
            </p>
          ) : (
            <p className="text-amber-600">
              No email on the customer record. Add one to the customer before sending a reminder.
            </p>
          )}
          <p className="text-[10px] text-[#94A3B8]">
            Reminders are a collections communication only — they do not change any accounting entry.
          </p>
          {error && <p className="text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
        </div>
        <div className="flex gap-3 justify-end mt-4">
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-4 py-2 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={sending || !customerEmail}
            className="text-xs px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 flex items-center gap-1.5"
          >
            {sending ? "Sending…" : <><AlertTriangle size={11} /> Send Reminder</>}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Delivery History Modal ─────────────────────────────────────────────────

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
                  <span className="text-[#334155] font-medium flex items-center gap-1.5">
                    {d.sent_to}
                    {d.kind === "reminder" && (
                      <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-700">
                        Reminder
                      </span>
                    )}
                  </span>
                  <span
                    className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                      DELIVERY_STATUS_COLOR[d.status] ?? "bg-[#F1F5F9] text-[#64748B]"
                    }`}
                  >
                    {DELIVERY_STATUS_LABEL[d.status] ?? d.status}
                  </span>
                </div>
                <div className="flex items-center justify-between mt-1 text-[#94A3B8]">
                  <span>{fmtDateTime(d.sent_at ?? d.created_at)}</span>
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

// ── Invoice Detail Drawer ────────────────────────────────────────────────────



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

interface CustomerDependencies {
  can_delete: boolean;
  dependencies: Record<string, number>;
  total: number;
}

function Customers({
  clientId,
  onNavigate,
}: {
  clientId: string;
  financialYear: string;
  onNavigate: (tab: SalesTab, custId?: string) => void;
}) {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [editCustomer, setEditCustomer] = useState<Customer | null>(null);
  const [deactivateTarget, setDeactivateTarget] = useState<Customer | null>(null);
  const [deactivating, setDeactivating] = useState(false);
  // Row actions overflow menu (anchored to the viewport to avoid table clipping).
  const [menu, setMenu] = useState<{ id: string; top: number; left: number } | null>(null);
  // Permanent-delete flow: target + the dependency report that gates it.
  const [deleteTarget, setDeleteTarget] = useState<Customer | null>(null);
  const [deleteDeps, setDeleteDeps] = useState<CustomerDependencies | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: "success" | "error" } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    // Load all customers; active/inactive scoping is a client-side DataTable filter.
    const { data } = await selectAll(() =>
      supabase
        .from("customers")
        .select(
          "id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active"
        )
        .eq("client_id", clientId)
        .order("name")
        .order("id"),
    );
    setCustomers((data as Customer[]) ?? []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  function showToast(msg: string, type: "success" | "error") {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 4000);
  }

  // Deactivation is destructive (the customer disappears from new-invoice
  // pickers), so it is gated behind an explicit confirmation modal. We only
  // flip is_active; existing invoices, receipts and journal entries are never
  // touched — accounting history must remain intact.
  async function confirmDeactivate() {
    if (!deactivateTarget) return;
    setDeactivating(true);
    const supabase = getSupabaseClient();
    const { error } = await supabase
      .from("customers")
      .update({ is_active: false })
      .eq("id", deactivateTarget.id);
    setDeactivating(false);
    if (error) {
      showToast("Failed to deactivate customer", "error");
      setDeactivateTarget(null);
      return;
    }
    showToast("Customer deactivated", "success");
    setDeactivateTarget(null);
    load();
  }

  // Reactivate an inactive customer (Inactive → Active). History is untouched;
  // it simply becomes selectable for new invoices again.
  async function reactivateCustomer(c: Customer) {
    const supabase = getSupabaseClient();
    const { error } = await supabase.from("customers").update({ is_active: true }).eq("id", c.id);
    if (error) { showToast("Failed to reactivate customer", "error"); return; }
    showToast("Customer reactivated", "success");
    load();
  }

  // Open the permanent-delete flow: ask the backend which accounting records (if
  // any) reference this customer, then show either the blocked or confirm dialog.
  async function startDelete(c: Customer) {
    setDeleteTarget(c);
    setDeleteDeps(null);
    const token = await getAuthToken();
    const res = await apiGet(`/api/customers/${c.id}/dependencies`, token);
    if (res.success) setDeleteDeps(res.data as CustomerDependencies);
    else { showToast("Could not check customer dependencies", "error"); setDeleteTarget(null); }
  }

  // Permanent delete — only reachable when the dependency check returned clean.
  // The backend re-checks and refuses (409) if anything was created meanwhile.
  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleteBusy(true);
    const token = await getAuthToken();
    const res = await apiCall(`/api/customers/${deleteTarget.id}?permanent=true`, "DELETE", undefined, token);
    setDeleteBusy(false);
    if (!res.success) {
      showToast(res.error ?? "Failed to delete customer", "error");
      return;
    }
    showToast("Customer deleted", "success");
    setDeleteTarget(null);
    setDeleteDeps(null);
    load();
  }

  // Anchor the overflow menu to the viewport (the table scrolls/clips, so an
  // in-flow dropdown would be cut off). Right-align a 176px menu under the button.
  function openMenuFor(e: React.MouseEvent, c: Customer) {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setMenu({ id: c.id, top: r.bottom + 4, left: Math.max(8, r.right - 176) });
  }

  /** Bulk-import customers through /api/customers/bulk — one request for the
   *  whole file instead of one POST per row (was the real bottleneck on a
   *  100-row import: 100 sequential round-trips, each re-running the same
   *  dedup query). Master-data integrity: re-importing the same file must
   *  NOT create duplicates. We detect existing customers BEFORE sending —
   *  by GSTIN (CGST Act §25, preferred), then PAN (IT Act §139A), then
   *  normalised name — and skip them client-side. The bulk endpoint applies
   *  the same GSTIN/PAN guard as a second line of defence (its `duplicates`
   *  entries are also counted as skipped); name-only matching has no backend
   *  equivalent, so that pass stays here. */
  async function handleImport(
    rows: ImportRow[]
  ): Promise<{ imported: number; errors: string[]; skipped: number; skippedDetail: string[] }> {
    const { records, errors } = buildCustomers(rows, clientId);
    if (records.length === 0) return { imported: 0, errors, skipped: 0, skippedDetail: [] };
    const token = await getAuthToken();

    // Snapshot the current active customers to match against.
    const supabase = getSupabaseClient();
    const { data: existingRows } = await selectAll(() => supabase
      .from("customers")
      .select("name, gstin, pan")
      .eq("client_id", clientId)
      .eq("is_active", true)
      .order("id"));

    const keyOf = (r: { gstin?: string | null; pan?: string | null; name?: string | null }): string | null => {
      if (r.gstin) return "g:" + r.gstin.trim().toUpperCase();
      if (r.pan) return "p:" + r.pan.trim().toUpperCase();
      if (r.name) return "n:" + r.name.trim().toLowerCase();
      return null;
    };

    const seen = new Set<string>();
    for (const e of existingRows ?? []) {
      const k = keyOf(e);
      if (k) seen.add(k);
    }

    let skipped = 0;
    const skippedDetail: string[] = [];
    const toCreate: typeof records = [];
    for (const c of records) {
      const k = keyOf(c);
      // Already present (in the firm's books or earlier in this same file).
      if (k && seen.has(k)) {
        skipped++;
        skippedDetail.push(`"${c.name}" already exists — skipped`);
        continue;
      }
      if (k) seen.add(k);
      toCreate.push(c);
    }

    let imported = 0;
    if (toCreate.length > 0) {
      const result = await apiCall("/api/customers/bulk", "POST", { customers: toCreate }, token);
      if (result.success) {
        const data = result.data as {
          created: unknown[];
          duplicates: { name?: string }[];
          errors: { name?: string; error: string }[];
        };
        imported = data.created.length;
        for (const d of data.duplicates) {
          skipped++;
          skippedDetail.push(`"${d.name ?? "?"}" already exists — skipped`);
        }
        for (const e of data.errors) {
          errors.push(`Customer "${e.name ?? "?"}": ${e.error}`);
        }
      } else {
        errors.push(result.error ?? "Bulk import failed");
      }
    }

    if (imported > 0) { load(); clearReports(clientId); }
    return { imported, errors, skipped, skippedDetail };
  }

  // Bulk deactivate — routed through the real API (unlike confirmDeactivate
  // above, which writes to Supabase directly and leaves no audit trail) so a
  // batch deactivation is still auditable. Unconditionally safe, same as the
  // single-row version: existing invoices/receipts/journals are untouched.
  async function bulkDeactivate(selected: Customer[]): Promise<boolean> {
    const token = await getAuthToken();
    const targets = selected.filter((c) => c.is_active);
    let deactivated = 0;
    const failures: string[] = [];
    await Promise.all(targets.map(async (c) => {
      try {
        const result = await apiCall(`/api/customers/${c.id}`, "DELETE", undefined, token);
        if (!result.success) throw new Error(result.error ?? "failed");
        deactivated++;
      } catch (e) {
        failures.push(`${c.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const skipped = selected.length - targets.length;
    const parts: string[] = [];
    if (deactivated) parts.push(`${deactivated} deactivated`);
    if (skipped) parts.push(`${skipped} already inactive`);
    if (failures.length) parts.push(`${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`);
    showToast(parts.join(", ") || "Nothing to do", failures.length ? "error" : "success");
    if (deactivated) load();
    return failures.length === 0;
  }

  // Bulk permanent delete — no pre-check GET here (unlike the single-row
  // startDelete flow): the backend re-validates dependencies on every call
  // and returns 409 for any customer with linked accounting records, so a
  // blocked row is just reported as a failure rather than fetched twice.
  async function bulkDeletePermanent(selected: Customer[]): Promise<boolean> {
    const token = await getAuthToken();
    let deleted = 0;
    const failures: string[] = [];
    await Promise.all(selected.map(async (c) => {
      try {
        const result = await apiCall(`/api/customers/${c.id}?permanent=true`, "DELETE", undefined, token);
        if (!result.success) throw new Error(result.error ?? "failed");
        deleted++;
      } catch (e) {
        failures.push(`${c.name}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const summary = failures.length
      ? `${deleted} deleted, ${failures.length} failed (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`
      : `${deleted} customer${deleted !== 1 ? "s" : ""} deleted`;
    showToast(summary, failures.length ? "error" : "success");
    if (deleted) load();
    return failures.length === 0;
  }

  // ── DataTable columns / filters ───────────────────────────────────────────
  const columns: Column<Customer>[] = useMemo(() => [
    { key: "name", header: "Name", accessor: (c) => c.name, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (c) => (
        <div>
          <span className="font-medium text-[#1E293B]">{c.name}</span>
          {c.email && <div className="text-[10px] text-[#94A3B8]">{c.email}</div>}
        </div>
      ) },
    { key: "gstin", header: "GSTIN", accessor: (c) => c.gstin ?? "", searchable: true,
      render: (c) => <span className="font-mono text-[#64748B]">{c.gstin ?? "—"}</span> },
    // Not shown as a column, but included so search covers phone/email as required.
    { key: "phone", header: "Phone", accessor: (c) => c.phone ?? "", searchable: true, defaultHidden: true,
      render: (c) => <span className="text-[#64748B]">{c.phone ?? "—"}</span> },
    { key: "state", header: "State", accessor: (c) => c.state ?? c.state_code ?? "",
      render: (c) => <span className="text-[#64748B]">{c.state ?? c.state_code ?? "—"}</span> },
    { key: "credit_days", header: "Credit Days", accessor: (c) => c.credit_days ?? 0, align: "right",
      render: (c) => <span className="text-[#334155]">{c.credit_days ?? 0}</span> },
    { key: "opening_balance_paise", header: "Opening Balance", accessor: (c) => c.opening_balance_paise ?? 0, align: "right",
      exportValue: (c) => formatPaise(c.opening_balance_paise ?? 0),
      render: (c) => <span className="font-mono text-[#334155]">{fmt(c.opening_balance_paise ?? 0)}</span> },
    { key: "is_active", header: "Status", accessor: (c) => (c.is_active ? "active" : "inactive"),
      render: (c) => c.is_active ? (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 text-green-700">Active</span>
      ) : (
        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#64748B]">Inactive</span>
      ) },
  ], []);

  const filters: FilterDef<Customer>[] = useMemo(() => [
    { key: "is_active", label: "Status", type: "select", accessor: (c) => (c.is_active ? "active" : "inactive"), options: [
      { value: "active", label: "Active" },
      { value: "inactive", label: "Inactive" },
    ] },
  ], []);

  return (
    <div className="space-y-4 max-w-screen-2xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-xs font-semibold text-[#334155]">
          {customers.length} customer{customers.length !== 1 ? "s" : ""}
        </p>
        <div className="flex gap-2">
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
        <CustomerFormModal
          clientId={clientId}
          existing={editCustomer}
          onSaved={() => {
            setShowForm(false);
            setEditCustomer(null);
            load();
            showToast(editCustomer ? "Customer updated" : "Customer added", "success");
          }}
          onClose={() => { setShowForm(false); setEditCustomer(null); }}
        />
      )}

      {deactivateTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="px-6 py-5 border-b border-[#F1F5F9]">
              <h2 className="text-base font-semibold text-[#0F172A]">Deactivate Customer?</h2>
            </div>
            <div className="px-6 py-5 space-y-2">
              <p className="text-sm text-[#475569]">
                <span className="font-medium text-[#1E293B]">{deactivateTarget.name}</span> will no
                longer be available for new invoices.
              </p>
              <p className="text-sm text-[#475569]">
                Existing invoices and accounting records will remain unchanged. You can reactivate
                this customer later.
              </p>
            </div>
            <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-end gap-2">
              <button
                onClick={() => setDeactivateTarget(null)}
                disabled={deactivating}
                className="px-4 py-2 text-sm text-[#475569] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeactivate}
                disabled={deactivating}
                className="px-4 py-2 text-sm font-medium text-white rounded-lg bg-red-600 hover:bg-red-700 disabled:opacity-50"
              >
                {deactivating ? "Deactivating…" : "Deactivate"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Permanent-delete flow: checking → blocked (has records) → confirm (clean) */}
      {deleteTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            {deleteDeps === null ? (
              <div className="px-6 py-10 flex items-center justify-center gap-2 text-sm text-[#475569]">
                <Loader2 size={16} className="animate-spin" /> Checking for linked records…
              </div>
            ) : deleteDeps.can_delete ? (
              <>
                <div className="px-6 py-5 border-b border-[#F1F5F9]">
                  <h2 className="text-base font-semibold text-[#0F172A]">Delete Customer?</h2>
                </div>
                <div className="px-6 py-5 space-y-2">
                  <p className="text-sm text-[#475569]">
                    <span className="font-medium text-[#1E293B]">{deleteTarget.name}</span> has no
                    linked invoices, receipts, credit notes or opening balance.
                  </p>
                  <p className="text-sm text-[#475569]">
                    This permanently removes the customer and cannot be undone.
                  </p>
                </div>
                <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-end gap-2">
                  <button
                    onClick={() => { setDeleteTarget(null); setDeleteDeps(null); }}
                    disabled={deleteBusy}
                    className="px-4 py-2 text-sm text-[#475569] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC] disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmDelete}
                    disabled={deleteBusy}
                    className="px-4 py-2 text-sm font-medium text-white rounded-lg bg-red-600 hover:bg-red-700 disabled:opacity-50"
                  >
                    {deleteBusy ? "Deleting…" : "Delete permanently"}
                  </button>
                </div>
              </>
            ) : (
              <>
                <div className="px-6 py-5 border-b border-[#F1F5F9] flex items-center gap-2">
                  <AlertTriangle size={18} className="text-amber-500" />
                  <h2 className="text-base font-semibold text-[#0F172A]">Can&apos;t delete this customer</h2>
                </div>
                <div className="px-6 py-5 space-y-3">
                  <p className="text-sm text-[#475569]">
                    <span className="font-medium text-[#1E293B]">{deleteTarget.name}</span> has linked
                    accounting records, so it can&apos;t be permanently deleted:
                  </p>
                  <ul className="text-sm text-[#475569] space-y-1">
                    {([
                      ["invoices", "Invoices"],
                      ["receipts", "Receipts"],
                      ["credit_notes", "Credit notes"],
                      ["recurring_templates", "Recurring templates"],
                      ["opening_balance", "Opening balance"],
                    ] as const)
                      .filter(([k]) => (deleteDeps.dependencies?.[k] ?? 0) > 0)
                      .map(([k, label]) => (
                        <li key={k} className="flex items-center gap-2">
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                          {k === "opening_balance"
                            ? "Has an opening balance"
                            : `${label}: ${deleteDeps.dependencies[k]}`}
                        </li>
                      ))}
                  </ul>
                  <p className="text-sm text-[#475569]">
                    Deactivate the customer instead — this keeps all history and removes it from new
                    invoices.
                  </p>
                </div>
                <div className="px-6 py-4 border-t border-[#F1F5F9] flex justify-end gap-2">
                  <button
                    onClick={() => { setDeleteTarget(null); setDeleteDeps(null); }}
                    className="px-4 py-2 text-sm text-[#475569] rounded-lg border border-[#E2E8F0] hover:bg-[#F8FAFC]"
                  >
                    Close
                  </button>
                  {deleteTarget.is_active && (
                    <button
                      onClick={() => { const t = deleteTarget; setDeleteTarget(null); setDeleteDeps(null); setDeactivateTarget(t); }}
                      className="px-4 py-2 text-sm font-medium text-white rounded-lg bg-blue-600 hover:bg-blue-700"
                    >
                      Deactivate instead
                    </button>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Row actions overflow menu (viewport-anchored to dodge table clipping) */}
      {menu && (() => {
        const c = customers.find((x) => x.id === menu.id);
        if (!c) return null;
        return (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setMenu(null)} />
            <div
              className="fixed z-50 w-44 bg-white rounded-lg border border-[#E2E8F0] shadow-lg py-1 text-xs"
              style={{ top: menu.top, left: menu.left }}
            >
              <button onClick={() => { setMenu(null); setEditCustomer(c); setShowForm(true); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                <Pencil size={13} /> Edit
              </button>
              <button onClick={() => { setMenu(null); onNavigate("invoices", c.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                <FileText size={13} /> View Invoices
              </button>
              <button onClick={() => { setMenu(null); onNavigate("statements", c.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                <BookOpen size={13} /> View Ledger
              </button>
              <div className="my-1 border-t border-[#F1F5F9]" />
              {c.is_active ? (
                <button onClick={() => { setMenu(null); setDeactivateTarget(c); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-[#334155]">
                  <Ban size={13} /> Deactivate
                </button>
              ) : (
                <button onClick={() => { setMenu(null); reactivateCustomer(c); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[#F8FAFC] text-green-700">
                  <RotateCcw size={13} /> Reactivate
                </button>
              )}
              <button onClick={() => { setMenu(null); startDelete(c); }}
                className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-red-50 text-red-600">
                <Trash2 size={13} /> Delete
              </button>
            </div>
          </>
        );
      })()}

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={customers}
        columns={columns}
        filters={filters}
        getRowId={(c) => c.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search by name, GSTIN, email, or phone…"
        initialSort={{ key: "name", dir: "asc" }}
        initialFilters={{ is_active: "active" }}
        exportFilename="customers"
        persistKey="sales.customers"
        emptyTitle="No customers yet"
        bulkActions={[
          {
            id: "deactivate",
            label: "Deactivate",
            icon: <Ban size={13} />,
            confirm: "Deactivate the selected customers? They will no longer be available for new invoices. Existing records are unaffected and this can be undone.",
            run: bulkDeactivate,
          },
          {
            id: "delete-permanent",
            label: "Delete permanently",
            icon: <Trash2 size={13} />,
            variant: "danger",
            confirm: "Permanently delete the selected customers? Any customer with linked invoices, receipts, credit notes or an opening balance will be skipped. This cannot be undone.",
            run: bulkDeletePermanent,
          },
          exportSelectedAction("customers-selected.csv", columns),
        ]}
        rowActions={(c) => (
          <button
            onClick={(e) => openMenuFor(e, c)}
            aria-label={`Actions for ${c.name}`}
            className="p-1 rounded hover:bg-[#F1F5F9] text-[#64748B]"
          >
            <MoreHorizontal size={16} />
          </button>
        )}
      />
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
      selectAll(() => supabase
        .from("receipts")
        .select("id, receipt_no, receipt_date, customer_id, amount_paise, payment_mode, reference_no, allocated_paise, customers(name)")
        .eq("client_id", clientId)
        .gte("receipt_date", start)
        .lte("receipt_date", end)
        .order("receipt_date", { ascending: false })
        .order("id")),
      selectAll(() => supabase
        .from("customers")
        .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name")
        .order("id")),
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

  // ── DataTable columns / filters ───────────────────────────────────────────
  const columns: Column<Receipt>[] = useMemo(() => [
    { key: "receipt_no", header: "Receipt No", accessor: (r) => r.receipt_no, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (r) => <span className="font-mono font-medium text-[#1E293B]">{r.receipt_no}</span> },
    { key: "receipt_date", header: "Date", accessor: (r) => r.receipt_date, sortable: true,
      render: (r) => <span className="text-[#64748B] whitespace-nowrap">{r.receipt_date}</span> },
    { key: "customer_name", header: "Customer", accessor: (r) => r.customer_name ?? "", searchable: true,
      render: (r) => <span className="text-[#334155]">{r.customer_name}</span> },
    { key: "amount_paise", header: "Amount", accessor: (r) => r.amount_paise, sortable: true, align: "right", exportValue: (r) => formatPaise(r.amount_paise),
      render: (r) => <span className="font-mono font-semibold text-[#0F172A]">{fmt(r.amount_paise)}</span> },
    { key: "payment_mode", header: "Mode", accessor: (r) => r.payment_mode, searchable: true,
      render: (r) => (
        <span className="px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-[#F1F5F9] text-[#475569] uppercase">
          {r.payment_mode}
        </span>
      ) },
    { key: "allocated_paise", header: "Allocated", accessor: (r) => r.allocated_paise ?? 0, align: "right", exportValue: (r) => formatPaise(r.allocated_paise ?? 0),
      render: (r) => <span className="font-mono text-green-700">{fmt(r.allocated_paise ?? 0)}</span> },
    { key: "unallocated_paise", header: "Unallocated", accessor: (r) => r.amount_paise - (r.allocated_paise ?? 0), align: "right",
      exportValue: (r) => formatPaise(r.amount_paise - (r.allocated_paise ?? 0)),
      render: (r) => <span className="font-mono text-amber-700">{fmt(r.amount_paise - (r.allocated_paise ?? 0))}</span> },
  ], []);

  const filters: FilterDef<Receipt>[] = useMemo(() => [
    { key: "unallocated", label: "Unallocated only", type: "boolean", accessor: (r) => r.amount_paise - (r.allocated_paise ?? 0) > 0,
      trueLabel: "Unallocated", falseLabel: "Fully allocated" },
  ], []);

  return (
    <div className="space-y-4 max-w-screen-2xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {receipts.length} receipt{receipts.length !== 1 ? "s" : ""} in FY {financialYear}
        </p>
        <div className="flex gap-2">
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

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={receipts}
        columns={columns}
        filters={filters}
        getRowId={(r) => r.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search receipt no., customer, or mode…"
        initialSort={{ key: "receipt_date", dir: "desc" }}
        exportFilename="receipts"
        persistKey="sales.receipts"
        emptyTitle={`No receipts in FY ${financialYear}`}
      />
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

  // Multi-Currency (Phase 3 backend, UI added here). A receipt is either
  // wholly domestic or wholly foreign — the backend rejects allocating a
  // foreign receipt against an INR invoice or vice versa (currency
  // mismatch), so the open-invoice list below is filtered to the selected
  // currency to make that mismatch unreachable from the UI.
  const [currency, setCurrency] = useState("");
  const [exchangeRate, setExchangeRate] = useState("");
  const [mcActive, setMcActive] = useState(false);
  const [currencies, setCurrencies] = useState<CurrencyOption[]>([]);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    (async () => {
      const token = await getAuthToken();
      const pol = await apiGet(`/api/currencies/policy?client_id=${clientId}`, token);
      if (cancelled) return;
      const active = Boolean(pol.success && (pol.data as { active?: boolean } | null)?.active);
      setMcActive(active);
      if (!active) return;
      const list = await apiGet(`/api/currencies?active_only=true`, token);
      if (!cancelled && list.success) setCurrencies((list.data as CurrencyOption[]) ?? []);
    })();
    return () => { cancelled = true; };
  }, [clientId]);

  const isForeign = currency !== "" && currency !== "INR";
  const rateNum = parseFloat(exchangeRate);

  function fmtAmt(paise: number): string {
    return isForeign ? formatMoney(paise, currency) : fmt(paise);
  }

  // Load open invoices for selected customer, then keep only those in the
  // receipt's own currency (INR when domestic, matching code when foreign).
  useEffect(() => {
    if (!customerId) { setOpenInvoices([]); return; }
    async function loadInvoices() {
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() => supabase
        .from("client_sales_invoices")
        .select("id, invoice_no, invoice_date, total_paise, status, txn_currency, exchange_rate, txn_total, paid_txn")
        .eq("client_id", clientId)
        .eq("customer_id", customerId)
        .in("status", ["issued", "partially_paid"])
        .order("invoice_date")
        .order("id"));
      setOpenInvoices((data as SalesInvoice[]) ?? []);
    }
    loadInvoices();
  }, [customerId, clientId]);

  const visibleInvoices = openInvoices.filter(
    (inv) => (inv.txn_currency || "INR").toUpperCase() === (currency || "INR").toUpperCase()
  );

  // Mirrors the pre-existing INR display (invoice total, not outstanding)
  // exactly; a foreign invoice's own total_paise is its INR-equivalent, not
  // its face value, so substitute txn_total (the foreign-native figure) —
  // the unit the allocation input below expects for a foreign receipt.
  function invoiceDisplayTotal(inv: SalesInvoice): number {
    return isForeign ? (inv.txn_total ?? 0) : inv.total_paise;
  }

  const amountPaise = Math.round(parseFloat(amount || "0") * 100);
  const totalAllocated = Object.values(allocations).reduce(
    (s, v) => s + Math.round(parseFloat(v || "0") * 100),
    0
  );

  async function handleSave() {
    if (!customerId) { setError("Select a customer"); return; }
    if (amountPaise <= 0) { setError("Amount must be greater than zero"); return; }
    if (!receiptDate) { setError("Receipt date required"); return; }
    if (isForeign && (!exchangeRate.trim() || !(rateNum > 0))) {
      setError(`Enter a valid exchange rate for ${currency} → INR`);
      return;
    }

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
          currency: isForeign ? currency : undefined,
          exchange_rate: isForeign ? exchangeRate : undefined,
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
          <CustomerLookup
            customers={customers}
            value={customerId}
            onChange={setCustomerId}
            ariaLabel="Customer"
          />
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
          <label className="block text-xs font-medium text-[#475569] mb-1">Amount ({isForeign ? currency : "₹"}) *</label>
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

      {/* Multi-Currency (Phase 3 backend, UI added here). A receipt settles
          against invoices in ONE currency only — the backend rejects mixing
          a foreign receipt with an INR invoice (and vice versa) — so this
          picker also drives which open invoices are offered for allocation
          below. */}
      {mcActive && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <div>
            <label className="block text-xs font-medium text-[#475569] mb-1">Currency</label>
            <select
              value={currency}
              onChange={(e) => { setCurrency(e.target.value); setExchangeRate(""); setAllocations({}); }}
              className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="">INR (default)</option>
              {currencies.filter((c) => c.code !== "INR").map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code}{c.display_name ? ` — ${c.display_name}` : ""}
                </option>
              ))}
            </select>
          </div>
          {isForeign && (
            <div>
              <label className="block text-xs font-medium text-[#475569] mb-1">Cash Exchange Rate *</label>
              <input
                type="number"
                min="0"
                step="0.0001"
                value={exchangeRate}
                onChange={(e) => setExchangeRate(e.target.value)}
                placeholder={`1 ${currency} = ? INR`}
                className="w-full px-3 py-1.5 text-xs border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-right font-mono"
              />
              <p className="mt-1 text-[10px] text-[#94A3B8]">
                Rate on the day cash was received — may differ from an invoice&apos;s booking rate; the
                difference posts as Realized FX Gain/Loss.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Allocate against open invoices */}
      {visibleInvoices.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[#475569]">Allocate against open invoices (optional)</p>
          <div className="space-y-1.5">
            {visibleInvoices.map((inv) => (
              <div key={inv.id} className="flex items-center gap-3">
                <span className="text-xs text-[#475569] flex-1">
                  {inv.invoice_no} — {inv.invoice_date} — {fmtAmt(invoiceDisplayTotal(inv))}
                  {isForeign && inv.exchange_rate && (
                    <span className="ml-1 text-[10px] text-[#94A3B8]">(booked @ {inv.exchange_rate})</span>
                  )}
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
                  placeholder={isForeign ? `${currency} 0.00` : "₹ 0.00"}
                  className="w-28 px-2 py-1 text-xs border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-right font-mono"
                />
              </div>
            ))}
          </div>
          {totalAllocated > 0 && (
            <p className="text-xs text-[#64748B]">
              Allocated: {fmtAmt(totalAllocated)} / Unallocated: {fmtAmt(amountPaise - totalAllocated)}
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
  const [issuingId, setIssuingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const supabase = getSupabaseClient();
    const { start, end } = fyRange(financialYear);

    const [{ data: cnData }, { data: custData }] = await Promise.all([
      selectAll(() => supabase
        .from("credit_notes")
        .select(
          "id, credit_note_no, credit_note_date, customer_id, sales_invoice_id, reason, taxable_amount_paise, cgst_paise, sgst_paise, igst_paise, total_paise, status, customers(name), client_sales_invoices(invoice_no)"
        )
        .eq("client_id", clientId)
        .gte("credit_note_date", start)
        .lte("credit_note_date", end)
        .order("credit_note_date", { ascending: false })
        .order("id")),
      selectAll(() => supabase
        .from("customers")
        .select("id, name, gstin, state_code, pan, email, phone, city, state, opening_balance_paise, credit_days, is_active")
        .eq("client_id", clientId)
        .eq("is_active", true)
        .order("name")
        .order("id")),
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
    if (issuingId) return;
    setIssuingId(id);
    try {
      const token = await getAuthToken();
      const result = await apiCall(`/api/credit-notes/${id}/issue`, "POST", undefined, token);
      if (!result.success) throw new Error(result.error ?? "Failed to issue credit note");
      showToast("Credit note issued", "success");
      load();
    } catch (err) {
      showToast(err instanceof Error ? err.message : "Error issuing credit note", "error");
    } finally {
      setIssuingId(null);
    }
  }

  // Bulk delete — draft-only (backend rejects issued/applied credit notes
  // with a 422, CGST Act §34: once issued they've already reduced the
  // original invoice's outstanding balance and there is no cancel/void path
  // for credit notes, unlike sales invoices).
  async function bulkDeleteCreditNotes(selected: CreditNote[]): Promise<boolean> {
    const token = await getAuthToken();
    let deleted = 0;
    const failures: string[] = [];
    await Promise.all(selected.map(async (cn) => {
      try {
        const result = await apiCall(`/api/credit-notes/${cn.id}`, "DELETE", undefined, token);
        if (!result.success) throw new Error(result.error ?? "failed");
        deleted++;
      } catch (e) {
        failures.push(`${cn.cn_no}: ${e instanceof Error ? e.message : "failed"}`);
      }
    }));
    const summary = failures.length
      ? `${deleted} deleted, ${failures.length} skipped (${failures.slice(0, 3).join("; ")}${failures.length > 3 ? "…" : ""})`
      : `${deleted} credit note${deleted !== 1 ? "s" : ""} deleted`;
    showToast(summary, failures.length ? "error" : "success");
    if (deleted) load();
    return failures.length === 0;
  }

  // ── DataTable columns / filters ───────────────────────────────────────────
  const columns: Column<CreditNote>[] = useMemo(() => [
    { key: "cn_no", header: "CN No", accessor: (cn) => cn.cn_no, searchable: true, sortable: true, sticky: true, hideable: false,
      render: (cn) => <span className="font-mono font-medium text-[#1E293B]">{cn.cn_no}</span> },
    { key: "cn_date", header: "Date", accessor: (cn) => cn.cn_date, sortable: true,
      render: (cn) => <span className="text-[#64748B] whitespace-nowrap">{cn.cn_date}</span> },
    { key: "customer_name", header: "Customer", accessor: (cn) => cn.customer_name ?? "", searchable: true,
      render: (cn) => <span className="text-[#334155]">{cn.customer_name}</span> },
    { key: "original_invoice_no", header: "Orig. Invoice", accessor: (cn) => cn.original_invoice_no ?? "",
      render: (cn) => <span className="font-mono text-[#64748B]">{cn.original_invoice_no ?? "—"}</span> },
    { key: "reason", header: "Reason", accessor: (cn) => cn.reason, searchable: true,
      render: (cn) => <span className="block max-w-[120px] truncate text-[#475569]">{cn.reason}</span> },
    { key: "total_paise", header: "Total", accessor: (cn) => cn.total_paise, sortable: true, align: "right", exportValue: (cn) => formatPaise(cn.total_paise),
      render: (cn) => <span className="font-mono font-semibold text-[#0F172A]">{fmt(cn.total_paise)}</span> },
    { key: "status", header: "Status", accessor: (cn) => cn.status, sortable: true,
      render: (cn) => (
        <span className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[cn.status] ?? "bg-[#F1F5F9] text-[#64748B]"}`}>
          {cn.status}
        </span>
      ) },
  ], []);

  const filters: FilterDef<CreditNote>[] = useMemo(() => [
    { key: "status", label: "Status", type: "select", accessor: (cn) => cn.status, options: [
      { value: "draft", label: "Draft" },
      { value: "issued", label: "Issued" },
      { value: "cancelled", label: "Cancelled" },
    ] },
  ], []);

  return (
    <div className="space-y-4 max-w-screen-2xl">
      {toast && <Toast msg={toast.msg} type={toast.type} />}

      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-[#334155]">
          {creditNotes.length} credit note{creditNotes.length !== 1 ? "s" : ""} in FY {financialYear}
        </p>
        <div className="flex gap-2">
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

      {/* Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
      <DataTable
        data={creditNotes}
        columns={columns}
        filters={filters}
        getRowId={(cn) => cn.id}
        loading={loading}
        onRefresh={load}
        searchPlaceholder="Search CN no., customer, or reason…"
        initialSort={{ key: "cn_date", dir: "desc" }}
        exportFilename="credit-notes"
        persistKey="sales.credit-notes"
        emptyTitle={`No credit notes in FY ${financialYear}`}
        bulkActions={[
          {
            id: "delete",
            label: "Delete draft(s)",
            icon: <Trash2 size={13} />,
            variant: "danger",
            confirm: "Delete the selected draft credit notes? Issued credit notes will be skipped. This cannot be undone.",
            run: bulkDeleteCreditNotes,
          },
          exportSelectedAction("credit-notes-selected.csv", columns),
        ]}
        rowActions={(cn) =>
          cn.status === "draft" ? (
            <button
              onClick={() => issueCreditNote(cn.id)}
              disabled={issuingId === cn.id}
              className="text-xs text-blue-600 hover:underline flex items-center gap-1 disabled:opacity-50 disabled:no-underline"
            >
              {issuingId === cn.id ? <Loader2 size={11} className="animate-spin" /> : <CheckCircle size={11} />} Issue
            </button>
          ) : null
        }
      />
    </div>
  );
}

// ── Credit Note Form ───────────────────────────────────────────────────────

// A credit note line reuses the invoice-line shape, plus the Product/Service
// it was picked from — for a goods return this links the line to a stock-in
// movement (domain.inventory_service.apply_credit_note_to_inventory).
// Optional: a line with no pick just never moves stock.
interface CreditNoteLine extends InvoiceLine {
  service_catalogue_id?: string;
  product?: ServiceCatalogueItem | null;
}

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
  const [lines, setLines] = useState<CreditNoteLine[]>([
    { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "" },
  ]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const gst = computeGst(lines, isInterstate);

  // Load customer's invoices for selection
  useEffect(() => {
    if (!customerId) { setCustomerInvoices([]); return; }
    async function loadInvoices() {
      const supabase = getSupabaseClient();
      const { data } = await selectAll(() => supabase
        .from("client_sales_invoices")
        .select("id, invoice_no, invoice_date, total_paise, status")
        .eq("client_id", clientId)
        .eq("customer_id", customerId)
        .order("invoice_date", { ascending: false })
        .order("id"));
      setCustomerInvoices((data as SalesInvoice[]) ?? []);
    }
    loadInvoices();
  }, [customerId, clientId]);

  function setLine(idx: number, patch: Partial<CreditNoteLine>) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, ...patch } : l)));
  }
  function addLine() {
    setLines((prev) => [...prev, { description: "", hsn_sac: "", qty: "1", rate: "", gst_rate: 18, unit: "" }]);
  }
  function removeLine(idx: number) {
    if (lines.length <= 1) return;
    setLines((prev) => prev.filter((_, i) => i !== idx));
  }
  // A Product/Service picked on this row pre-fills description/HSN/rate and
  // links the line for inventory stock-in tracking on issue (goods only —
  // a service pick is harmless traceability, apply_credit_note_to_inventory
  // only acts on kind='good' items server-side).
  function onPickProduct(idx: number, item: ServiceCatalogueItem) {
    setLine(idx, { ...serviceToLine(item), service_catalogue_id: item.id, product: item });
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
          lines: validLines.map((l) => toInvoiceLinePayload({ ...l, serviceCatalogueId: l.service_catalogue_id })),
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
          <CustomerLookup
            customers={customers}
            value={customerId}
            onChange={setCustomerId}
            ariaLabel="Customer"
          />
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
              <th className="pb-2 text-left font-semibold w-36">Product/Service</th>
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
                    {/* Links this line to a Product/Service for inventory
                        stock-in tracking on issue (goods only — optional,
                        a return with no pick just never restocks anything). */}
                    <ServiceCataloguePicker
                      clientId={clientId}
                      value={line.product}
                      onPick={(item) => onPickProduct(idx, item)}
                      size="sm"
                      ariaLabel={`Line ${idx + 1} product or service`}
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <input
                      value={line.description}
                      onChange={(e) => setLine(idx, { description: e.target.value })}
                      placeholder="Item description"
                      className="w-full px-2 py-1 border border-[#E2E8F0] rounded focus:outline-none focus:ring-1 focus:ring-blue-500 text-xs"
                    />
                  </td>
                  <td className="py-1.5 pr-2">
                    <HsnLookup
                      clientId={clientId}
                      value={line.hsn_sac}
                      onChange={(v) => setLine(idx, { hsn_sac: v })}
                      onPick={(p) => { if (p.gst_rate_bps != null) setLine(idx, { gst_rate: Math.round(p.gst_rate_bps / 100) }); }}
                      description={line.description}
                      size="sm"
                      ariaLabel="HSN or SAC code"
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
