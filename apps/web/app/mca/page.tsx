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

import { useState, useEffect } from "react";
import {
  Building2, FileText, CheckCircle, AlertTriangle, Clock,
  Plus, X, AlertCircle, Users, Calendar,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { useToast } from "@/components/ui/use-toast";

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

const TODAY = new Date("2026-06-02");

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

// Key annual MCA deadlines — Companies Act 2013
const KEY_DEADLINES = [
  { label: "DIR-3 KYC",    date: "30 Sep 2026", note: "Rule 12A — Director KYC annual", daysLeft: Math.ceil((new Date("2026-09-30").getTime() - TODAY.getTime()) / 86400000) },
  { label: "AOC-4",        date: "30 Oct 2026", note: "Section 137 — 30 days from AGM", daysLeft: Math.ceil((new Date("2026-10-30").getTime() - TODAY.getTime()) / 86400000) },
  { label: "MGT-7/7A",     date: "29 Nov 2026", note: "Section 92 — 60 days from AGM", daysLeft: Math.ceil((new Date("2026-11-29").getTime() - TODAY.getTime()) / 86400000) },
  { label: "ADT-1",        date: "14 Oct 2026", note: "Section 139 — 15 days from AGM", daysLeft: Math.ceil((new Date("2026-10-14").getTime() - TODAY.getTime()) / 86400000) },
  { label: "MSME-1 (H2)",  date: "30 Apr 2027", note: "Half-yearly — Oct 2026–Mar 2027", daysLeft: Math.ceil((new Date("2027-04-30").getTime() - TODAY.getTime()) / 86400000) },
];

// Seed data
const SEED_FILINGS: MCAFiling[] = [
  { id: "s1", client_id: "", client_name: "Joshi Textiles Pvt Ltd",   company_cin: "U17200MH2010PTC205678", form_type: "AOC-4",     period: "FY 2024-25", due_date: "2025-10-29", filed_date: "2025-10-20", srn: "SRN12345678", status: "Filed",   notes: null },
  { id: "s2", client_id: "", client_name: "Joshi Textiles Pvt Ltd",   company_cin: "U17200MH2010PTC205678", form_type: "MGT-7",     period: "FY 2024-25", due_date: "2025-11-28", filed_date: "2025-11-15", srn: "SRN12345679", status: "Filed",   notes: null },
  { id: "s3", client_id: "", client_name: "Sharma Industries Pvt Ltd", company_cin: "U15200MH2015PTC301234", form_type: "DIR-3 KYC", period: "FY 2025-26", due_date: "2025-09-30", filed_date: null,          srn: null,           status: "Overdue", notes: null },
  { id: "s4", client_id: "", client_name: "Mehta Consulting LLP",      company_cin: "AAC-1234",              form_type: "MGT-7A",    period: "FY 2024-25", due_date: "2025-11-28", filed_date: "2025-11-20", srn: "SRN12345680", status: "Filed",   notes: null },
  { id: "s5", client_id: "", client_name: "Patel Pharma Pvt Ltd",      company_cin: "U24200GJ2018PTC102345", form_type: "AOC-4",     period: "FY 2025-26", due_date: "2026-10-30", filed_date: null,          srn: null,           status: "Pending", notes: null },
];

const SEED_COMPANIES: CompanyClient[] = [
  { id: "co1", client_name: "Joshi Textiles Pvt Ltd",   cin: "U17200MH2010PTC205678", incorp_date: "2010-05-15", auth_capital_paise: 100000000, paidup_capital_paise: 50000000, regd_office: "Mumbai, Maharashtra" },
  { id: "co2", client_name: "Sharma Industries Pvt Ltd", cin: "U15200MH2015PTC301234", incorp_date: "2015-08-22", auth_capital_paise: 50000000,  paidup_capital_paise: 25000000, regd_office: "Pune, Maharashtra" },
  { id: "co3", client_name: "Patel Pharma Pvt Ltd",      cin: "U24200GJ2018PTC102345", incorp_date: "2018-03-10", auth_capital_paise: 200000000, paidup_capital_paise: 100000000, regd_office: "Ahmedabad, Gujarat" },
];

const SEED_DIRECTORS: Director[] = [
  { id: "d1", name: "Vikram Joshi",   din: "01234567", pan: "ABCPJ1234K", designation: "Managing Director", appointment_date: "2010-05-15", kyc_due_date: "2026-09-30" },
  { id: "d2", name: "Priya Sharma",   din: "02345678", pan: "CDFPS5678L", designation: "Director",           appointment_date: "2015-08-22", kyc_due_date: "2026-09-30" },
  { id: "d3", name: "Rajesh Patel",   din: "03456789", pan: "EFGRP9012M", designation: "Director",           appointment_date: "2018-03-10", kyc_due_date: "2026-09-30" },
  { id: "d4", name: "Sunita Mehta",   din: "04567890", pan: "GHISM3456N", designation: "Independent Director", appointment_date: "2020-01-01", kyc_due_date: "2025-09-30" }, // KYC overdue
];

function computeStatus(dueDate: string, filed: string | null): FilingStatus {
  if (filed) return "Filed";
  return TODAY > new Date(dueDate) ? "Overdue" : "Pending";
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
        filed_date: status === "Filed" ? TODAY.toISOString().slice(0, 10) : null,
        srn: srn.trim() || null,
        status: status.toLowerCase(),             // DB stores lowercase
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
            <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={clientId} onChange={e => setClientId(e.target.value)}>
              <option value="">Select client…</option>
              {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
            </select>
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
  const [filings, setFilings] = useState<MCAFiling[]>(SEED_FILINGS);
  const [clients, setClients] = useState<Client[]>([]);
  const [companies] = useState<CompanyClient[]>(SEED_COMPANIES);
  const [directors, setDirectors] = useState<Director[]>(SEED_DIRECTORS);
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
          if (rows.length > 0) setFilings(rows);
        }
        // Load directors from mca_directors table (migration 038)
        const { data: dirData } = await sb.from("mca_directors").select("*").eq("firm_id", fid).order("director_name");
        if (dirData && dirData.length > 0) {
          setDirectors(dirData.map((d: Record<string, unknown>) => ({
            id: d.id as string,
            name: d.director_name as string,
            din: d.din as string,
            pan: (d.pan ?? "") as string,
            designation: (d.designation ?? "Director") as string,
            appointment_date: (d.date_of_appointment ?? "") as string,
            kyc_due_date: (d.kyc_due_date ?? "") as string,
          })));
        }
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  async function handleMarkFiled(id: string) {
    setFilings(prev => prev.map(f => f.id === id ? { ...f, status: "Filed" as FilingStatus, filed_date: TODAY.toISOString().slice(0, 10) } : f));
    if (!tableError && firmId) {
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const sb = getSupabaseClient();
      await sb.from("mca_filings").update({ status: "filed", filed_date: TODAY.toISOString().slice(0, 10) }).eq("id", id);
    }
  }

  const totalCompanies = companies.length;
  const dueThisMonth = filings.filter(f => { const d = new Date(f.due_date); return d.getMonth() === TODAY.getMonth() && d.getFullYear() === TODAY.getFullYear() && f.status !== "Filed"; }).length;
  const overdueCount = filings.filter(f => f.status === "Overdue").length;
  const kycDueSoon = directors.filter(d => {
    const diff = Math.ceil((new Date(d.kyc_due_date).getTime() - TODAY.getTime()) / 86400000);
    return diff >= 0 && diff <= 30;
  }).length;

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
          { icon: <Clock className="w-4 h-4 text-amber-600" />,       bg: "bg-amber-50",  label: "Filings Due This Month", value: loading ? "—" : String(dueThisMonth), sub: "Jun 2026" },
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

      {/* Tab: Companies */}
      {activeTab === 0 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-[#0F172A]">Company Clients</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Companies Act 2013 — incorporated entities</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  {["Company Name", "CIN", "Incorp. Date", "Auth. Capital", "Paid-up Capital", "Regd. Office"].map(h => (
                    <th key={h} className="text-left text-xs font-medium text-[#94A3B8] px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {companies.map(c => (
                  <tr key={c.id} className="hover:bg-[#F8FAFC]/50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-md bg-blue-50 flex items-center justify-center shrink-0"><Building2 className="w-3.5 h-3.5 text-blue-600" /></div>
                        <span className="text-sm font-medium text-[#0F172A]">{c.client_name}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs font-mono text-[#475569]">{c.cin}</td>
                    <td className="px-4 py-3 text-xs text-[#475569]">{fmtDate(c.incorp_date)}</td>
                    <td className="px-4 py-3 text-sm text-[#0F172A]">{fmtLakhs(c.auth_capital_paise)}</td>
                    <td className="px-4 py-3 text-sm text-[#0F172A]">{fmtLakhs(c.paidup_capital_paise)}</td>
                    <td className="px-4 py-3 text-xs text-[#475569]">{c.regd_office}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab: Filings */}
      {activeTab === 1 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-[#0F172A]">ROC Filing Tracker</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Companies Act 2013 — ROC/MCA filing obligations</p>
          </div>
          {loading ? <div className="px-5 py-10 text-center text-sm text-[#94A3B8]">Loading…</div> : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-50">
                    {["Company Name", "CIN", "Form Type", "Period", "Due Date", "Filed Date", "SRN", "Status", "Action"].map(h => (
                      <th key={h} className="text-left text-xs font-medium text-[#94A3B8] px-4 py-3">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  {filings.map(f => (
                    <tr key={f.id} className="hover:bg-[#F8FAFC]/50">
                      <td className="px-4 py-3 text-sm font-medium text-[#0F172A]">{f.client_name}</td>
                      <td className="px-4 py-3 text-xs font-mono text-[#475569]">{f.company_cin}</td>
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                          <FileText className="w-3 h-3" />{f.form_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{f.period}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{fmtDate(f.due_date)}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{f.filed_date ? fmtDate(f.filed_date) : "—"}</td>
                      <td className="px-4 py-3 text-xs font-mono text-[#475569]">{f.srn || "—"}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLE[f.status]}`}>
                          {f.status === "Filed" && <CheckCircle className="w-3 h-3" />}
                          {f.status === "Overdue" && <AlertTriangle className="w-3 h-3" />}
                          {f.status === "Pending" && <Clock className="w-3 h-3" />}
                          {f.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {f.status !== "Filed" ? (
                          <button onClick={() => handleMarkFiled(f.id)} className="text-xs text-blue-600 hover:text-blue-800 font-medium">Mark Filed</button>
                        ) : (
                          <span className="text-xs text-[#94A3B8]">Done</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="px-5 py-3 border-t border-gray-50 bg-[#F8FAFC]/30">
            <p className="text-[10px] text-[#94A3B8]">
              {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
              All filings must be submitted manually on MCA21 portal. PracticeSync does not auto-submit.
            </p>
          </div>
        </div>
      )}

      {/* Tab: Directors */}
      {activeTab === 2 && (
        <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-[#0F172A]">Director Master</h2>
            <p className="text-xs text-[#94A3B8] mt-0.5">Director KYC due date: 30 Sep annually — Rule 12A Companies (Appointment and Qualification of Directors) Rules</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  {["Name", "DIN", "PAN", "Designation", "Appointment Date", "KYC Due Date", "KYC Status"].map(h => (
                    <th key={h} className="text-left text-xs font-medium text-[#94A3B8] px-4 py-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {directors.map(d => {
                  const kycDate = new Date(d.kyc_due_date);
                  const daysToKyc = Math.ceil((kycDate.getTime() - TODAY.getTime()) / 86400000);
                  const kycStyle = daysToKyc < 0 ? "bg-red-100 text-red-700" : daysToKyc <= 30 ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700";
                  const kycLabel = daysToKyc < 0 ? "Overdue" : daysToKyc <= 30 ? `Due in ${daysToKyc}d` : "Valid";
                  return (
                    <tr key={d.id} className="hover:bg-[#F8FAFC]/50">
                      <td className="px-4 py-3 text-sm font-medium text-[#0F172A]">{d.name}</td>
                      <td className="px-4 py-3 text-xs font-mono text-[#475569]">{d.din}</td>
                      <td className="px-4 py-3 text-xs font-mono text-[#475569]">{d.pan}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{d.designation}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{fmtDate(d.appointment_date)}</td>
                      <td className="px-4 py-3 text-xs text-[#475569]">{fmtDate(d.kyc_due_date)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex text-xs font-medium px-2 py-0.5 rounded-full ${kycStyle}`}>{kycLabel}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
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
