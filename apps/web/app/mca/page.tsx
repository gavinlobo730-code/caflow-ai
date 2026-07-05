"use client";

/**
 * MCA Module — Ministry of Corporate Affairs / ROC Compliance Tracker
 * Companies Act 2013:
 *   Section 92: Annual return (MGT-7) within 60 days of AGM
 *   Section 137: Filing of financial statements (AOC-4) within 30 days of AGM
 *   Section 139: Auditor appointment (ADT-1) within 15 days of AGM
 *   Section 10A: Commencement of business (INC-20A) within 180 days
 *   Section 77: Charge registration (CHG-1) within 30 days
 *   Rule 12A (Director KYC Rules): DIR-3 KYC by 30 Sep annually
 */

import { useState, useEffect, useMemo } from "react";
import {
  Building2, FileText, CheckCircle, AlertTriangle, Clock,
  Plus, X, AlertCircle, Users, Calendar,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { useToast } from "@/components/ui/use-toast";
import { DataTable } from "@/components/ui/data-table";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import type { Column, FilterDef } from "@/lib/table/types";
import { todayLocalISO, daysBetweenLocalISO, toLocalISO, computeOverdueStatus } from "@/lib/dateMath";

// ─── Types ───────────────────────────────────────────────────────────────────

type FilingStatus = "Pending" | "Filed" | "Overdue";

interface MCAFiling {
  id: string;
  firm_id?: string;
  client_id: string;
  client_name: string;
  company_cin: string;
  form_type: string;
  period: string;
  due_date: string;
  filed_date: string | null;
  srn: string | null;
  status: FilingStatus;
  notes: string | null;
}

interface Director {
  id: string;
  name: string;
  din: string;
  pan: string;
  designation: string;
  appointment_date: string;
  kyc_due_date: string;
}

interface CompanyClient {
  id: string;
  client_name: string;
  cin: string;
  incorp_date: string;
  auth_capital_paise: number;
  paidup_capital_paise: number;
  regd_office: string;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const TODAY = new Date();

const FORM_TYPES = [
  { value: "AOC-4",      label: "AOC-4 — Annual Financial Statement (Section 137)" },
  { value: "MGT-7",      label: "MGT-7 — Annual Return Pvt Ltd (Section 92)" },
  { value: "MGT-7A",     label: "MGT-7A — Annual Return OPC/Small Co (Section 92)" },
  { value: "ADT-1",      label: "ADT-1 — Auditor Appointment (Section 139)" },
  { value: "INC-20A",    label: "INC-20A — Commencement of Business (Section 10A)" },
  { value: "DIR-3 KYC",  label: "DIR-3 KYC — Director KYC (Rule 12A)" },
  { value: "CHG-1",      label: "CHG-1 — Charge Creation (Section 77)" },
  { value: "MSME-1",     label: "MSME-1 — Outstanding payments to MSME" },
];

const TABS = ["Companies", "Filings", "Directors", "Deadlines"];

const STATUS_STYLE: Record<FilingStatus, string> = {
  Filed:    "bg-green-100 text-green-700",
  Pending:  "bg-amber-100 text-amber-700",
  Overdue:  "bg-red-100 text-red-700",
};

// Key annual MCA deadlines — Companies Act 2013. This is a generic "upcoming
// deadlines" summary (not tied to any one company's actual AGM date), so it
// assumes the statutory-latest AGM fallback of 30 Sep — the same convention
// services/compliance_engine.py::MCA_AGM_OFFSET_DAYS uses on the backend.
// Recomputed relative to the real current date every time this module loads,
// rather than a year hardcoded once (R3.1 fix — the previous version froze
// both "today" and every deadline's year, so it silently went stale).
function _nextOccurrence(month: number, day: number): Date {
  const thisYear = new Date(TODAY.getFullYear(), month - 1, day);
  // Compare calendar dates, not a midnight Date against a live instant — a
  // direct `thisYear >= TODAY` comparison is false on the target day itself
  // (any time after local midnight already exceeds thisYear's own midnight),
  // which would wrongly skip straight to next year on the one day it's due.
  return toLocalISO(thisYear) >= todayLocalISO() ? thisYear : new Date(TODAY.getFullYear() + 1, month - 1, day);
}
function _daysUntil(d: Date): number {
  return Math.ceil((d.getTime() - TODAY.getTime()) / 86400000);
}
function _fmtShort(d: Date): string {
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
const _AGM = _nextOccurrence(9, 30); // statutory-latest AGM (30 Sep)
function _fromAgm(days: number): Date {
  return new Date(_AGM.getFullYear(), _AGM.getMonth(), _AGM.getDate() + days);
}
function _nextMsme1(): { date: Date; label: string; period: string } {
  const h1 = _nextOccurrence(10, 31);  // Apr-Sep half, due 31 Oct
  const h2 = _nextOccurrence(4, 30);   // Oct-Mar half, due 30 Apr
  return h1 < h2
    ? { date: h1, label: "MSME-1 (H1)", period: `Apr–Sep ${h1.getFullYear()}` }
    : { date: h2, label: "MSME-1 (H2)", period: `Oct ${h2.getFullYear() - 1}–Mar ${h2.getFullYear()}` };
}
const _msme1 = _nextMsme1();
const KEY_DEADLINES = [
  { label: "DIR-3 KYC",  date: _fmtShort(_AGM), note: "Rule 12A — Director KYC annual", daysLeft: _daysUntil(_AGM) },
  { label: "ADT-1",      date: _fmtShort(_fromAgm(15)), note: "Section 139 — 15 days from AGM", daysLeft: _daysUntil(_fromAgm(15)) },
  { label: "AOC-4",      date: _fmtShort(_fromAgm(30)), note: "Section 137 — 30 days from AGM", daysLeft: _daysUntil(_fromAgm(30)) },
  { label: "MGT-7/7A",   date: _fmtShort(_fromAgm(60)), note: "Section 92 — 60 days from AGM", daysLeft: _daysUntil(_fromAgm(60)) },
  { label: _msme1.label, date: _fmtShort(_msme1.date), note: `Half-yearly — ${_msme1.period}`, daysLeft: _daysUntil(_msme1.date) },
];

// MCA filings, companies, and directors are loaded from the firm's real data;
// empty until recorded (no fictional seed records shown to users).

const computeStatus = computeOverdueStatus;

/** Days from today until a director's KYC due date (negative once overdue). */
function daysUntilKyc(kycDueDate: string): number {
  return daysBetweenLocalISO(todayLocalISO(), kycDueDate) ?? 0;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function fmtLakhs(paise: number) {
  const rupees = paise / 100;
  if (rupees >= 10000000) return `₹${(rupees / 10000000).toFixed(2)} Cr`;
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(2)} L`;
  return `₹${rupees.toLocaleString("en-IN")}`;
}

// ─── Add Filing Modal ────────────────────────────────────────────────────────

function AddFilingModal({ clients, firmId, onClose, onAdded }: {
  clients: Client[];
  firmId: string;
  onClose: () => void;
  onAdded: (f: MCAFiling) => void;
}) {
  const { toast } = useToast();
  const [clientId, setClientId] = useState("");
  const [cin, setCin] = useState("");
  const [formType, setFormType] = useState("AOC-4");
  const [period, setPeriod] = useState("FY 2025-26");
  const [dueDate, setDueDate] = useState("");
  const [srn, setSrn] = useState("");
  const [status, setStatus] = useState<FilingStatus>("Pending");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function handleSubmit() {
    if (!clientId || !cin.trim() || !dueDate) { setErr("Client, CIN and Due Date are required."); return; }
    setSaving(true); setErr(null);
    try {
      const sb = getSupabaseClient();
      const selectedClient = clients.find(c => c.id === clientId);
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA portal
      const { data, error } = await sb.from("mca_filings").insert({
        firm_id: firmId,
        client_id: clientId,
        client_name: selectedClient?.client_name ?? "",
        cin: cin.trim().toUpperCase(),           // DB column is 'cin'
        company_cin: cin.trim().toUpperCase(),    // alias column added in migration 038
        form_type: formType,
        period,
        due_date: dueDate,
        filed_date: status === "Filed" ? todayLocalISO() : null,
        srn: srn.trim() || null,
        status: status === "Pending" ? "not_started" : status.toLowerCase(),  // DB: not_started|filed|overdue
        notes: notes.trim() || null,
      }).select().single();
      if (error) throw new Error(error.message);
      const filing = data as MCAFiling;
      filing.status = computeStatus(filing.due_date, filing.filed_date);
      onAdded(filing);
      toast({ title: "MCA filing added" });
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add MCA Filing</h3>
          <button onClick={onClose}><X className="w-4 h-4 text-[#94A3B8]" /></button>
        </div>
        {err && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{err}</p>}
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Client</label>
            <div className="w-full">
              <ClientLookup
                clients={clients}
                value={clientId}
                onChange={setClientId}
                ariaLabel="Client"
                placeholder="Select client…"
              />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">CIN / LLPIN</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="U17200MH2010PTC205678" value={cin} onChange={e => setCin(e.target.value.toUpperCase())} />
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Form Type</label>
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={formType} onChange={e => setFormType(e.target.value)}>
              {FORM_TYPES.map(f => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Period</label>
              <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={period} onChange={e => setPeriod(e.target.value)} placeholder="FY 2025-26" />
            </div>
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Due Date</label>
              <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={dueDate} onChange={e => setDueDate(e.target.value)} />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Status</label>
              <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={status} onChange={e => setStatus(e.target.value as FilingStatus)}>
                <option value="Pending">Pending</option>
                <option value="Filed">Filed</option>
                <option value="Overdue">Overdue</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">SRN (if filed)</label>
              <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500" value={srn} onChange={e => setSrn(e.target.value)} placeholder="SRN12345678" />
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-[#334155] block mb-1">Notes</label>
            <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional" />
          </div>
        </div>
        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg">Cancel</button>
          <button onClick={handleSubmit} disabled={saving} className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving ? "Saving…" : "Add Filing"}
          </button>
        </div>
        <p className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          All filings must be submitted manually on MCA21 portal (mca.gov.in) after CA review.
        </p>
      </div>
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function MCAPage() {
  const [activeTab, setActiveTab] = useState(0);
  const [firmId, setFirmId] = useState("");
  const [filings, setFilings] = useState<MCAFiling[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [companies, setCompanies] = useState<CompanyClient[]>([]);
  const [directors, setDirectors] = useState<Director[]>([]);
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState(false);
  const [showModal, setShowModal] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const fid = await getFirmId().catch(() => "");
        setFirmId(fid);
        const cls = await getClients().catch(() => [] as Client[]);
        setClients(cls);
        if (!fid) return;
        const sb = getSupabaseClient();
        const { data, error } = await sb.from("mca_filings").select("*").eq("firm_id", fid).order("due_date");
        if (error) { setTableError(true); }
        else {
          const rows = ((data ?? []) as MCAFiling[]).map(r => ({ ...r, status: computeStatus(r.due_date, r.filed_date) }));
          setFilings(rows);   // real data only; empty firm shows the empty state
        }
        // Companies + directors from the firm's real data (migration 038). Empty
        // arrays when none exist — never fall back to fictional seed records.
        const { data: coData } = await sb.from("mca_companies").select("*").eq("firm_id", fid).order("company_name");
        setCompanies((coData ?? []).map((c: Record<string, unknown>) => ({
          id: c.id as string,
          client_name: (c.company_name ?? "") as string,
          cin: (c.cin ?? "") as string,
          incorp_date: (c.incorp_date ?? "") as string,
          auth_capital_paise: (c.authorized_capital_paise ?? 0) as number,
          paidup_capital_paise: (c.paid_up_capital_paise ?? 0) as number,
          regd_office: (c.registered_office ?? "") as string,
        })));
        const { data: dirData } = await sb.from("mca_directors").select("*").eq("firm_id", fid).order("director_name");
        setDirectors((dirData ?? []).map((d: Record<string, unknown>) => ({
          id: d.id as string,
          name: d.director_name as string,
          din: d.din as string,
          pan: (d.pan ?? "") as string,
          designation: (d.designation ?? "Director") as string,
          appointment_date: (d.date_of_appointment ?? "") as string,
          kyc_due_date: (d.kyc_due_date ?? "") as string,
        })));
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleMarkFiled(id: string) {
    setFilings(prev => prev.map(f => f.id === id ? { ...f, status: "Filed" as FilingStatus, filed_date: todayLocalISO() } : f));
    if (!tableError && firmId) {
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const sb = getSupabaseClient();
      await sb.from("mca_filings").update({ status: "filed", filed_date: todayLocalISO() }).eq("id", id);
    }
  }

  const totalCompanies = companies.length;
  const dueThisMonth = filings.filter(f => { const d = new Date(f.due_date); return d.getMonth() === TODAY.getMonth() && d.getFullYear() === TODAY.getFullYear() && f.status !== "Filed"; }).length;
  const overdueCount = filings.filter(f => f.status === "Overdue").length;
  const kycDueSoon = directors.filter(d => {
    const diff = daysUntilKyc(d.kyc_due_date);
    return diff >= 0 && diff <= 30;
  }).length;

  // ── Companies tab DataTable — money in integer paise (aligned right) ────────
  const companyColumns: Column<CompanyClient>[] = useMemo(() => [
    {
      key: "client_name", header: "Company Name", accessor: (c) => c.client_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (c) => (
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-md bg-blue-50 flex items-center justify-center shrink-0"><Building2 className="w-3.5 h-3.5 text-blue-600" /></div>
          <span className="text-sm font-medium text-[#0F172A]">{c.client_name}</span>
        </div>
      ),
    },
    {
      key: "cin", header: "CIN", accessor: (c) => c.cin, searchable: true, sortable: true,
      render: (c) => <span className="font-mono text-xs text-[#475569]">{c.cin}</span>,
    },
    {
      key: "incorp_date", header: "Incorp. Date", accessor: (c) => c.incorp_date, sortable: true,
      render: (c) => <span className="text-xs text-[#475569]">{c.incorp_date ? fmtDate(c.incorp_date) : "—"}</span>,
    },
    {
      key: "auth_capital_paise", header: "Auth. Capital", accessor: (c) => c.auth_capital_paise,
      sortable: true, align: "right", exportValue: (c) => c.auth_capital_paise / 100,
      render: (c) => <span className="text-[#0F172A]">{fmtLakhs(c.auth_capital_paise)}</span>,
    },
    {
      key: "paidup_capital_paise", header: "Paid-up Capital", accessor: (c) => c.paidup_capital_paise,
      sortable: true, align: "right", exportValue: (c) => c.paidup_capital_paise / 100,
      render: (c) => <span className="text-[#0F172A]">{fmtLakhs(c.paidup_capital_paise)}</span>,
    },
    {
      key: "regd_office", header: "Regd. Office", accessor: (c) => c.regd_office,
      render: (c) => <span className="text-xs text-[#475569]">{c.regd_office}</span>,
    },
  ], []);

  // ── Filings tab DataTable ──────────────────────────────────────────────────
  const filingColumns: Column<MCAFiling>[] = useMemo(() => [
    {
      key: "client_name", header: "Company Name", accessor: (f) => f.client_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (f) => <span className="font-medium text-[#0F172A]">{f.client_name}</span>,
    },
    {
      key: "company_cin", header: "CIN", accessor: (f) => f.company_cin ?? "", searchable: true,
      render: (f) => <span className="font-mono text-xs text-[#475569]">{f.company_cin}</span>,
    },
    {
      key: "form_type", header: "Form Type", accessor: (f) => f.form_type, searchable: true, sortable: true,
      render: (f) => (
        <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
          <FileText className="w-3 h-3" />{f.form_type}
        </span>
      ),
    },
    {
      key: "period", header: "Period", accessor: (f) => f.period,
      render: (f) => <span className="text-xs text-[#475569]">{f.period}</span>,
    },
    {
      key: "due_date", header: "Due Date", accessor: (f) => f.due_date, sortable: true,
      render: (f) => <span className="text-xs text-[#475569]">{fmtDate(f.due_date)}</span>,
    },
    {
      key: "filed_date", header: "Filed Date", accessor: (f) => f.filed_date ?? "", sortable: true,
      render: (f) => <span className="text-xs text-[#475569]">{f.filed_date ? fmtDate(f.filed_date) : "—"}</span>,
    },
    {
      key: "srn", header: "SRN", accessor: (f) => f.srn ?? "",
      render: (f) => <span className="font-mono text-xs text-[#475569]">{f.srn || "—"}</span>,
    },
    {
      key: "status", header: "Status", accessor: (f) => f.status, sortable: true,
      render: (f) => (
        <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLE[f.status]}`}>
          {f.status === "Filed" && <CheckCircle className="w-3 h-3" />}
          {f.status === "Overdue" && <AlertTriangle className="w-3 h-3" />}
          {f.status === "Pending" && <Clock className="w-3 h-3" />}
          {f.status}
        </span>
      ),
    },
  ], []);

  const filingFilters: FilterDef<MCAFiling>[] = useMemo(() => [
    {
      key: "form_type", label: "Form Type", type: "select", accessor: (f) => f.form_type,
      options: FORM_TYPES.map((f) => ({ value: f.value, label: f.value })),
    },
  ], []);

  // ── Directors tab DataTable — KYC-overdue emphasis in the status cell ───────
  const directorColumns: Column<Director>[] = useMemo(() => [
    {
      key: "name", header: "Name", accessor: (d) => d.name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (d) => <span className="font-medium text-[#0F172A]">{d.name}</span>,
    },
    {
      key: "din", header: "DIN", accessor: (d) => d.din, searchable: true, sortable: true,
      render: (d) => <span className="font-mono text-xs text-[#475569]">{d.din}</span>,
    },
    {
      key: "pan", header: "PAN", accessor: (d) => d.pan,
      render: (d) => <span className="font-mono text-xs text-[#475569]">{d.pan}</span>,
    },
    {
      key: "designation", header: "Designation", accessor: (d) => d.designation,
      render: (d) => <span className="text-xs text-[#475569]">{d.designation}</span>,
    },
    {
      key: "appointment_date", header: "Appointment Date", accessor: (d) => d.appointment_date, sortable: true,
      render: (d) => <span className="text-xs text-[#475569]">{d.appointment_date ? fmtDate(d.appointment_date) : "—"}</span>,
    },
    {
      key: "kyc_due_date", header: "KYC Due Date", accessor: (d) => d.kyc_due_date, sortable: true,
      render: (d) => <span className="text-xs text-[#475569]">{d.kyc_due_date ? fmtDate(d.kyc_due_date) : "—"}</span>,
    },
    {
      key: "kyc_status", header: "KYC Status", accessor: (d) => {
        // Sort/export by days-to-KYC so overdue (most negative) surfaces first.
        return daysUntilKyc(d.kyc_due_date);
      }, sortable: true,
      exportValue: (d) => {
        const days = daysUntilKyc(d.kyc_due_date);
        return days < 0 ? "Overdue" : days <= 30 ? `Due in ${days}d` : "Valid";
      },
      render: (d) => {
        const daysToKyc = daysUntilKyc(d.kyc_due_date);
        const kycStyle = daysToKyc < 0 ? "bg-red-100 text-red-700" : daysToKyc <= 30 ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700";
        const kycLabel = daysToKyc < 0 ? "Overdue" : daysToKyc <= 30 ? `Due in ${daysToKyc}d` : "Valid";
        return <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${kycStyle}`}>{kycLabel}</span>;
      },
    },
  ], []);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">MCA / ROC Module</h1>
          <p className="text-sm text-[#64748B] mt-0.5">Ministry of Corporate Affairs — Companies Act 2013 compliance tracker</p>
        </div>
        {activeTab === 1 && (
          <button onClick={() => setShowModal(true)} className="flex items-center gap-1.5 bg-blue-600 text-white text-sm px-3 py-2 rounded-lg hover:bg-blue-700">
            <Plus className="w-4 h-4" /> Add Filing
          </button>
        )}
      </div>

      {tableError && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-700">MCA filings table not found — showing sample data. Run migration to create <code className="font-mono bg-amber-100 px-1 rounded">mca_filings</code>.</p>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { icon: <Building2 className="w-4 h-4 text-blue-600" />,    bg: "bg-blue-50",   label: "Total Companies",       value: String(totalCompanies), sub: "Company clients" },
          { icon: <Clock className="w-4 h-4 text-amber-600" />,       bg: "bg-amber-50",  label: "Filings Due This Month", value: loading ? "—" : String(dueThisMonth), sub: TODAY.toLocaleDateString("en-IN", { month: "short", year: "numeric" }) },
          { icon: <AlertTriangle className="w-4 h-4 text-red-600" />, bg: "bg-red-50",    label: "Overdue Filings",       value: loading ? "—" : String(overdueCount), sub: "Past due date" },
          { icon: <Users className="w-4 h-4 text-purple-600" />,      bg: "bg-purple-50", label: "Directors KYC Due",     value: String(kycDueSoon), sub: "Within 30 days" },
        ].map(c => (
          <div key={c.label} className="bg-white rounded-xl border border-[#F1F5F9] p-4">
            <div className="flex items-center gap-2 mb-3">
              <div className={`w-8 h-8 rounded-lg ${c.bg} flex items-center justify-center`}>{c.icon}</div>
              <span className="text-xs text-[#64748B]">{c.label}</span>
            </div>
            <p className="text-lg font-semibold text-[#0F172A]">{c.value}</p>
            <p className="text-xs text-[#94A3B8] mt-0.5">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {TABS.map((tab, i) => (
          <button key={tab} onClick={() => setActiveTab(i)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === i ? "border-blue-600 text-blue-700" : "border-transparent text-[#64748B] hover:text-[#334155]"}`}>
            {tab}
          </button>
        ))}
      </div>

      {/* Tab: Companies — shared DataTable (search, sort, pagination, export, prefs) */}
      {activeTab === 0 && (
        <div className="space-y-2">
          <div>
            <h2 className="text-sm font-semibold text-[#0F172A]">Company Clients</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Companies Act 2013 — incorporated entities</p>
          </div>
          <DataTable
            data={companies}
            columns={companyColumns}
            getRowId={(c) => c.id}
            loading={loading}
            searchPlaceholder="Search by company name or CIN…"
            initialSort={{ key: "client_name", dir: "asc" }}
            exportFilename="mca-companies"
            persistKey="mca.companies"
            emptyTitle="No company clients yet"
            emptyDescription="Company records appear here once added for your firm."
          />
        </div>
      )}

      {/* Tab: Filings — shared DataTable (search, filter, sort, pagination, export, prefs) */}
      {activeTab === 1 && (
        <div className="space-y-2">
          <div>
            <h2 className="text-sm font-semibold text-[#0F172A]">ROC Filing Tracker</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Companies Act 2013 — ROC/MCA filing obligations</p>
          </div>
          <DataTable
            data={filings}
            columns={filingColumns}
            filters={filingFilters}
            getRowId={(f) => f.id}
            loading={loading}
            searchPlaceholder="Search by company or form type…"
            initialSort={{ key: "due_date", dir: "asc" }}
            exportFilename="mca-filings"
            persistKey="mca.filings"
            emptyTitle="No ROC filings yet"
            emptyDescription={'Click "Add Filing" to start tracking ROC/MCA obligations.'}
            rowActions={(f) =>
              f.status !== "Filed" ? (
                <button onClick={() => handleMarkFiled(f.id)} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Mark Filed</button>
              ) : (
                <span className="text-xs text-[#94A3B8]">Done</span>
              )
            }
          />
          <p className="text-[10px] text-[#94A3B8]">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            All filings must be submitted manually on MCA21 portal. PracticeSync does not auto-submit.
          </p>
        </div>
      )}

      {/* Tab: Directors — shared DataTable (search, sort, pagination, export, prefs) */}
      {activeTab === 2 && (
        <div className="space-y-2">
          <div>
            <h2 className="text-sm font-semibold text-[#0F172A]">Director Master</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Director KYC due date: 30 Sep annually — Rule 12A Companies (Appointment and Qualification of Directors) Rules</p>
          </div>
          <DataTable
            data={directors}
            columns={directorColumns}
            getRowId={(d) => d.id}
            loading={loading}
            searchPlaceholder="Search by name or DIN…"
            initialSort={{ key: "kyc_status", dir: "asc" }}
            exportFilename="mca-directors"
            persistKey="mca.directors"
            emptyTitle="No directors yet"
            emptyDescription="Director records appear here once added for your firm."
          />
        </div>
      )}

      {/* Tab: Deadlines */}
      {activeTab === 3 && (
        <div className="space-y-4">
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-4 py-3 flex gap-2">
            <AlertCircle className="w-4 h-4 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-blue-800">MCA Deadlines for FY 2025-26 / 2026-27</p>
              <p className="text-xs text-blue-700 mt-0.5">AGM is typically held by 30 Sep (6 months after FY end 31 Mar). Deadlines computed from AGM date.</p>
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {KEY_DEADLINES.map(d => (
              <div key={d.label} className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center"><Calendar className="w-4 h-4 text-blue-600" /></div>
                  <span className="text-sm font-semibold text-[#0F172A]">{d.label}</span>
                </div>
                <p className="text-base font-bold text-blue-600">{d.date}</p>
                <p className="text-xs text-[#94A3B8] mt-1">{d.note}</p>
                <p className={`text-xs font-medium mt-2 ${d.daysLeft < 30 ? "text-amber-600" : "text-[#64748B]"}`}>
                  {d.daysLeft > 0 ? `${d.daysLeft} days remaining` : "Past due"}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {showModal && (
        <AddFilingModal clients={clients} firmId={firmId} onClose={() => setShowModal(false)} onAdded={f => setFilings(prev => [...prev, f])} />
      )}
    </div>
  );
}
