"use client";

/**
 * Notices Tracker — IT, GST, TDS, MCA and Other notices
 * IT Act Sections 143(1), 143(2), 148, 156, 271, 276
 * CGST Act — DRC-01, DRC-01A, DRC-10, ASMT-10, ASMT-14
 * TDS — IT Act Section 200A, 206C
 * MCA — Companies Act 2013
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * Never transmit notice responses to government portals without explicit CA confirmation.
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import { ArrowLeft, Plus, X, AlertTriangle, CheckCircle2, Clock, Bell, FileText, ChevronDown } from "lucide-react";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ────────────────────────────────────────────────────────────────────

type AuthorityType = "IT" | "GST" | "TDS" | "MCA" | "Other";
type NoticeStatus = "Received" | "In Progress" | "Responded" | "Closed" | "Dropped";
type Priority = "High" | "Medium" | "Low";

const IT_SECTIONS = ["143(1)", "143(2)", "148", "156", "271", "276", "144B", "245"] as const;
const GST_NOTICE_TYPES = ["DRC-01", "DRC-01A", "DRC-10", "ASMT-10", "ASMT-14"] as const;
const NOTICE_STATUSES: NoticeStatus[] = ["Received", "In Progress", "Responded", "Closed", "Dropped"];
const PRIORITIES: Priority[] = ["High", "Medium", "Low"];
const ASSESSMENT_YEARS = ["2026-27", "2025-26", "2024-25", "2023-24", "2022-23"] as const;

interface Notice {
  id: string;
  authority: AuthorityType;
  clientId: string;
  clientName: string;
  noticeDate: string;
  responseDueDate: string;
  status: NoticeStatus;
  priority: Priority;
  notes: string;
  demandAmountPaise: number;
  itSection?: string;
  assessmentYear?: string;
  gstNoticeType?: string;
  gstin?: string;
  gstPeriod?: string;
  scnNumber?: string;
  tdsSection?: string;
  tdsPeriod?: string;
  tdsChallanDetails?: string;
  mcaFormType?: string;
  companyCin?: string;
  mcaPeriod?: string;
  rocJurisdiction?: string;
  otherDetails?: string;
  createdAt: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function daysRemaining(dateStr: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dateStr);
  return Math.ceil((due.getTime() - today.getTime()) / 86400000);
}

function fmtDate(d: string): string {
  if (!d) return "—";
  const parts = d.split("-");
  if (parts.length < 3) return d;
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${parts[2]} ${months[parseInt(parts[1]) - 1]} ${parts[0]}`;
}

/** Integer paise display — no floating point */
function fmtPaise(p: number): string {
  if (!p) return "—";
  const rupees = Math.floor(p / 100);
  const paise = p % 100;
  return "₹" + rupees.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",") + "." + String(paise).padStart(2, "0");
}

function urgencyClass(days: number): string {
  if (days <= 7) return "text-red-600 bg-red-50 border-red-200";
  if (days <= 30) return "text-amber-700 bg-amber-50 border-amber-200";
  return "text-green-700 bg-green-50 border-green-200";
}

function statusBadgeClass(status: NoticeStatus): string {
  const map: Record<NoticeStatus, string> = {
    Received: "bg-red-100 text-red-700",
    "In Progress": "bg-blue-100 text-blue-700",
    Responded: "bg-amber-100 text-amber-700",
    Closed: "bg-green-100 text-green-700",
    Dropped: "bg-gray-100 text-gray-500",
  };
  return map[status];
}

function priorityBadgeClass(p: Priority): string {
  const map: Record<Priority, string> = {
    High: "bg-red-100 text-red-700",
    Medium: "bg-amber-100 text-amber-700",
    Low: "bg-gray-100 text-gray-600",
  };
  return map[p];
}

const STORAGE_KEY = "caflow_notices_v2";

function loadFromStorage(): Notice[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]"); }
  catch { return []; }
}

function saveToStorage(notices: Notice[]) {
  if (typeof window === "undefined") return;
  localStorage.setItem(STORAGE_KEY, JSON.stringify(notices));
}

// ─── Add Modal Form ───────────────────────────────────────────────────────────

interface FormState {
  authority: AuthorityType;
  clientId: string;
  noticeDate: string;
  responseDueDate: string;
  priority: Priority;
  notes: string;
  demandAmountRs: string;
  itSection: string;
  assessmentYear: string;
  gstNoticeType: string;
  gstin: string;
  gstPeriod: string;
  scnNumber: string;
  tdsSection: string;
  tdsPeriod: string;
  tdsChallanDetails: string;
  mcaFormType: string;
  companyCin: string;
  mcaPeriod: string;
  rocJurisdiction: string;
  otherDetails: string;
}

const BLANK_FORM: FormState = {
  authority: "IT",
  clientId: "",
  noticeDate: new Date().toISOString().split("T")[0],
  responseDueDate: "",
  priority: "Medium",
  notes: "",
  demandAmountRs: "",
  itSection: "143(2)",
  assessmentYear: "2026-27",
  gstNoticeType: "DRC-01",
  gstin: "",
  gstPeriod: "",
  scnNumber: "",
  tdsSection: "",
  tdsPeriod: "",
  tdsChallanDetails: "",
  mcaFormType: "",
  companyCin: "",
  mcaPeriod: "",
  rocJurisdiction: "",
  otherDetails: "",
};

function AddModal({ clients, onClose, onAdded }: {
  clients: Client[];
  onClose: () => void;
  onAdded: (n: Notice) => void;
}) {
  const [form, setForm] = useState<FormState>({ ...BLANK_FORM, clientId: clients[0]?.id ?? "" });
  const [error, setError] = useState<string | null>(null);

  function upd(patch: Partial<FormState>) { setForm(f => ({ ...f, ...patch })); }

  function handleAdd() {
    if (!form.clientId || !form.responseDueDate) {
      setError("Select client and enter response due date");
      return;
    }
    const client = clients.find(c => c.id === form.clientId);
    // Integer paise: multiply by 100, no float stored
    const demandPaise = Math.round(parseFloat(form.demandAmountRs || "0") * 100);
    const notice: Notice = {
      id: `n-${Date.now()}`,
      authority: form.authority,
      clientId: form.clientId,
      clientName: client?.client_name ?? form.clientId,
      noticeDate: form.noticeDate,
      responseDueDate: form.responseDueDate,
      status: "Received",
      priority: form.priority,
      notes: form.notes,
      demandAmountPaise: demandPaise,
      itSection: form.itSection || undefined,
      assessmentYear: form.assessmentYear || undefined,
      gstNoticeType: form.gstNoticeType || undefined,
      gstin: form.gstin || undefined,
      gstPeriod: form.gstPeriod || undefined,
      scnNumber: form.scnNumber || undefined,
      tdsSection: form.tdsSection || undefined,
      tdsPeriod: form.tdsPeriod || undefined,
      tdsChallanDetails: form.tdsChallanDetails || undefined,
      mcaFormType: form.mcaFormType || undefined,
      companyCin: form.companyCin || undefined,
      mcaPeriod: form.mcaPeriod || undefined,
      rocJurisdiction: form.rocJurisdiction || undefined,
      otherDetails: form.otherDetails || undefined,
      createdAt: new Date().toISOString(),
    };
    onAdded(notice);
  }

  const inputCls = "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500";
  const lbl = "text-xs font-medium text-gray-700 block mb-1";

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-900">Add Notice</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        <div className="px-6 py-4 space-y-4">
          {error && <div className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>}

          <div>
            <label className={lbl}>Notice Authority</label>
            <div className="flex gap-1 flex-wrap">
              {(["IT","GST","TDS","MCA","Other"] as AuthorityType[]).map(a => (
                <button key={a} onClick={() => upd({ authority: a })}
                  className={`px-3 py-1.5 text-xs rounded-lg font-medium transition-colors ${
                    form.authority === a ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}>
                  {a}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className={lbl}>Client</label>
            <select value={form.clientId} onChange={e => upd({ clientId: e.target.value })} className={inputCls}>
              {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Notice Date</label>
              <input type="date" value={form.noticeDate} onChange={e => upd({ noticeDate: e.target.value })} className={inputCls} />
            </div>
            <div>
              <label className={lbl}>Response Due Date *</label>
              <input type="date" value={form.responseDueDate} onChange={e => upd({ responseDueDate: e.target.value })} className={inputCls} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={lbl}>Priority</label>
              <select value={form.priority} onChange={e => upd({ priority: e.target.value as Priority })} className={inputCls}>
                {PRIORITIES.map(p => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className={lbl}>Demand Amount (₹)</label>
              <input type="number" min="0" value={form.demandAmountRs}
                onChange={e => upd({ demandAmountRs: e.target.value })}
                placeholder="0" className={inputCls} />
            </div>
          </div>

          {form.authority === "IT" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={lbl}>Section</label>
                <select value={form.itSection} onChange={e => upd({ itSection: e.target.value })} className={inputCls}>
                  {IT_SECTIONS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className={lbl}>Assessment Year</label>
                <select value={form.assessmentYear} onChange={e => upd({ assessmentYear: e.target.value })} className={inputCls}>
                  {ASSESSMENT_YEARS.map(ay => <option key={ay} value={ay}>{ay}</option>)}
                </select>
              </div>
            </div>
          )}

          {form.authority === "GST" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={lbl}>Notice Type</label>
                  <select value={form.gstNoticeType} onChange={e => upd({ gstNoticeType: e.target.value })} className={inputCls}>
                    {GST_NOTICE_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <div>
                  <label className={lbl}>SCN Number</label>
                  <input type="text" value={form.scnNumber} onChange={e => upd({ scnNumber: e.target.value })} placeholder="SCN/ZZ/2025/001" className={inputCls} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={lbl}>GSTIN</label>
                  <input type="text" value={form.gstin} onChange={e => upd({ gstin: e.target.value })} placeholder="27XXXXX..." className={inputCls} />
                </div>
                <div>
                  <label className={lbl}>Period</label>
                  <input type="text" value={form.gstPeriod} onChange={e => upd({ gstPeriod: e.target.value })} placeholder="Apr 2025 – Mar 2026" className={inputCls} />
                </div>
              </div>
            </>
          )}

          {form.authority === "TDS" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={lbl}>Section</label>
                  <input type="text" value={form.tdsSection} onChange={e => upd({ tdsSection: e.target.value })} placeholder="e.g. 194C" className={inputCls} />
                </div>
                <div>
                  <label className={lbl}>Period</label>
                  <input type="text" value={form.tdsPeriod} onChange={e => upd({ tdsPeriod: e.target.value })} placeholder="Q1 FY 2025-26" className={inputCls} />
                </div>
              </div>
              <div>
                <label className={lbl}>Challan Details</label>
                <input type="text" value={form.tdsChallanDetails} onChange={e => upd({ tdsChallanDetails: e.target.value })} placeholder="Challan reference" className={inputCls} />
              </div>
            </>
          )}

          {form.authority === "MCA" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={lbl}>Form Type</label>
                <input type="text" value={form.mcaFormType} onChange={e => upd({ mcaFormType: e.target.value })} placeholder="e.g. MCA-DIN-12" className={inputCls} />
              </div>
              <div>
                <label className={lbl}>Company CIN</label>
                <input type="text" value={form.companyCin} onChange={e => upd({ companyCin: e.target.value })} placeholder="U12345MH2020PTC..." className={inputCls} />
              </div>
              <div>
                <label className={lbl}>Period</label>
                <input type="text" value={form.mcaPeriod} onChange={e => upd({ mcaPeriod: e.target.value })} placeholder="FY 2025-26" className={inputCls} />
              </div>
              <div>
                <label className={lbl}>ROC Jurisdiction</label>
                <input type="text" value={form.rocJurisdiction} onChange={e => upd({ rocJurisdiction: e.target.value })} placeholder="RoC Mumbai" className={inputCls} />
              </div>
            </div>
          )}

          {form.authority === "Other" && (
            <div>
              <label className={lbl}>Details</label>
              <input type="text" value={form.otherDetails} onChange={e => upd({ otherDetails: e.target.value })} placeholder="Authority / reference details" className={inputCls} />
            </div>
          )}

          <div>
            <label className={lbl}>Notes</label>
            <textarea rows={2} value={form.notes} onChange={e => upd({ notes: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
              placeholder="Additional details…" />
          </div>
        </div>

        <div className="sticky bottom-0 bg-white px-6 py-4 border-t border-gray-100 flex gap-2 justify-end">
          <button onClick={onClose}
            className="px-4 py-2 text-sm text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200">
            Cancel
          </button>
          <button onClick={handleAdd}
            className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700">
            Add Notice
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function NoticesPage() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [showAddModal, setShowAddModal] = useState(false);
  const [authorityFilter, setAuthorityFilter] = useState<AuthorityType | "all">("all");
  const [statusFilter, setStatusFilter] = useState<NoticeStatus | "all">("all");
  const [clientFilter, setClientFilter] = useState("");

  useEffect(() => {
    setNotices(loadFromStorage());
    getClients().then(c => setClients(c)).catch(() => {});
  }, []);

  function handleAdded(n: Notice) {
    const updated = [n, ...notices];
    setNotices(updated);
    saveToStorage(updated);
    setShowAddModal(false);
  }

  function updateStatus(id: string, status: NoticeStatus) {
    const updated = notices.map(n => n.id === id ? { ...n, status } : n);
    setNotices(updated);
    saveToStorage(updated);
  }

  function deleteNotice(id: string) {
    const updated = notices.filter(n => n.id !== id);
    setNotices(updated);
    saveToStorage(updated);
  }

  const filtered = notices.filter(n => {
    if (authorityFilter !== "all" && n.authority !== authorityFilter) return false;
    if (statusFilter !== "all" && n.status !== statusFilter) return false;
    if (clientFilter && !n.clientName.toLowerCase().includes(clientFilter.toLowerCase())) return false;
    return true;
  });

  const urgentNotices = notices.filter(n =>
    (n.status === "Received" || n.status === "In Progress") &&
    daysRemaining(n.responseDueDate) <= 7
  );

  const TABS: { id: AuthorityType | "all"; label: string }[] = [
    { id: "all", label: `All (${notices.length})` },
    { id: "IT", label: `Income Tax (${notices.filter(n => n.authority === "IT").length})` },
    { id: "GST", label: `GST (${notices.filter(n => n.authority === "GST").length})` },
    { id: "TDS", label: `TDS (${notices.filter(n => n.authority === "TDS").length})` },
    { id: "MCA", label: `MCA (${notices.filter(n => n.authority === "MCA").length})` },
    { id: "Other", label: `Other (${notices.filter(n => n.authority === "Other").length})` },
  ];

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <Link href="/income-tax"
            className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 mb-2">
            <ArrowLeft size={13} /> Income Tax
          </Link>
          <h1 className="text-lg md:text-xl font-semibold text-gray-900">Notices Tracker</h1>
          <p className="text-sm text-gray-500 mt-0.5">Track IT, GST, TDS, MCA and other notices</p>
        </div>
        <button onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700">
          <Plus size={15} /> Add Notice
        </button>
      </div>

      {urgentNotices.length > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 flex items-start gap-3">
          <Bell size={15} className="text-red-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-semibold text-red-800 uppercase tracking-wide">
              Urgent — Response Due Within 7 Days
            </p>
            <ul className="mt-1 space-y-0.5">
              {urgentNotices.map(n => {
                const days = daysRemaining(n.responseDueDate);
                return (
                  <li key={n.id} className="text-xs text-red-700">
                    <span className="font-medium">{n.clientName}</span> — {n.authority} Notice —{" "}
                    {days < 0 ? `${Math.abs(days)} days overdue` : days === 0 ? "Due today" : `${days} day${days !== 1 ? "s" : ""} remaining`}
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Total", value: notices.length, icon: FileText, color: "text-blue-600", bg: "bg-blue-50" },
          { label: "Received", value: notices.filter(n => n.status === "Received").length, icon: AlertTriangle, color: "text-red-600", bg: "bg-red-50" },
          { label: "In Progress", value: notices.filter(n => n.status === "In Progress").length, icon: Clock, color: "text-amber-600", bg: "bg-amber-50" },
          { label: "Resolved", value: notices.filter(n => n.status === "Closed" || n.status === "Dropped").length, icon: CheckCircle2, color: "text-green-600", bg: "bg-green-50" },
        ].map(({ label, value, icon: Icon, color, bg }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-4 py-4 flex items-center gap-3">
            <div className={`w-9 h-9 ${bg} rounded-lg flex items-center justify-center shrink-0`}>
              <Icon size={16} className={color} />
            </div>
            <div>
              <p className="text-xs text-gray-500">{label}</p>
              <p className="text-lg font-semibold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setAuthorityFilter(t.id)}
            className={`px-3 py-2.5 text-xs font-medium whitespace-nowrap border-b-2 transition-colors ${
              authorityFilter === t.id ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"
            }`}>
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-3">
        <input type="text" placeholder="Search client…" value={clientFilter}
          onChange={e => setClientFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm outline-none focus:border-blue-500 w-48" />
        <div className="relative">
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value as NoticeStatus | "all")}
            className="appearance-none border border-gray-200 rounded-lg pl-3 pr-8 py-1.5 text-sm outline-none focus:border-blue-500">
            <option value="all">All Statuses</option>
            {NOTICE_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
        </div>
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        {filtered.length === 0 ? (
          <div className="px-5 py-14 text-center space-y-3">
            <FileText className="w-10 h-10 text-gray-200 mx-auto" />
            <p className="text-sm text-gray-500">
              {notices.length === 0 ? "No notices tracked yet" : "No notices match filters"}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[900px]">
              <thead>
                <tr className="bg-gray-50 text-xs text-gray-500 font-medium">
                  <th className="px-4 py-3 text-left">Client</th>
                  <th className="px-4 py-3 text-left">Authority</th>
                  <th className="px-4 py-3 text-left">Details</th>
                  <th className="px-4 py-3 text-left">Notice Date</th>
                  <th className="px-4 py-3 text-left">Response Due</th>
                  <th className="px-4 py-3 text-right">Demand</th>
                  <th className="px-4 py-3 text-left">Priority</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-left">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map(n => {
                  const days = daysRemaining(n.responseDueDate);
                  const isActive = n.status === "Received" || n.status === "In Progress";
                  return (
                    <tr key={n.id} className="hover:bg-gray-50/50">
                      <td className="px-4 py-3 font-medium text-gray-900">{n.clientName}</td>
                      <td className="px-4 py-3">
                        <span className="text-xs font-semibold bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{n.authority}</span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-600 max-w-[180px] truncate">
                        {n.authority === "IT" && `${n.itSection ?? "—"} — AY ${n.assessmentYear ?? "—"}`}
                        {n.authority === "GST" && `${n.gstNoticeType ?? "—"} — ${n.gstin ?? "—"} — ${n.gstPeriod ?? "—"}`}
                        {n.authority === "TDS" && `${n.tdsSection ?? "—"} — ${n.tdsPeriod ?? "—"}`}
                        {n.authority === "MCA" && `${n.mcaFormType ?? "—"} — ${n.companyCin ?? "—"}`}
                        {n.authority === "Other" && (n.otherDetails ?? "—")}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap">{fmtDate(n.noticeDate)}</td>
                      <td className="px-4 py-3 text-xs whitespace-nowrap">
                        {isActive ? (
                          <span className={`px-2 py-0.5 rounded border text-xs font-medium ${urgencyClass(days)}`}>
                            {fmtDate(n.responseDueDate)}
                            {days <= 30 && ` (${days < 0 ? `${Math.abs(days)}d over` : days + "d"})`}
                          </span>
                        ) : fmtDate(n.responseDueDate)}
                      </td>
                      <td className="px-4 py-3 text-right font-mono text-xs text-gray-700">{fmtPaise(n.demandAmountPaise)}</td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${priorityBadgeClass(n.priority)}`}>
                          {n.priority}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${statusBadgeClass(n.status)}`}>
                          {n.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
                          {n.status === "Received" && (
                            <button onClick={() => updateStatus(n.id, "In Progress")}
                              className="text-xs px-2 py-1 bg-blue-50 text-blue-700 rounded hover:bg-blue-100 whitespace-nowrap">
                              Start
                            </button>
                          )}
                          {n.status === "In Progress" && (
                            <button onClick={() => updateStatus(n.id, "Responded")}
                              className="text-xs px-2 py-1 bg-amber-50 text-amber-700 rounded hover:bg-amber-100 whitespace-nowrap">
                              Responded
                            </button>
                          )}
                          {n.status === "Responded" && (
                            <button onClick={() => updateStatus(n.id, "Closed")}
                              className="text-xs px-2 py-1 bg-green-50 text-green-700 rounded hover:bg-green-100">
                              Close
                            </button>
                          )}
                          {n.status !== "Closed" && n.status !== "Dropped" && (
                            <button onClick={() => updateStatus(n.id, "Dropped")}
                              className="text-xs px-2 py-1 bg-gray-100 text-gray-500 rounded hover:bg-gray-200">
                              Drop
                            </button>
                          )}
                          <button onClick={() => deleteNotice(n.id)}
                            className="p-1 text-gray-300 hover:text-red-500">
                            <X size={13} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showAddModal && (
        <AddModal
          clients={clients}
          onClose={() => setShowAddModal(false)}
          onAdded={handleAdded}
        />
      )}
    </div>
  );
}
