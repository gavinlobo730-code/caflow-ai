"use client";

/**
 * MCA Module — Ministry of Corporate Affairs / ROC Filings Tracker
 * Companies Act 2013:
 *   - Section 137: Filing of financial statements (AOC-4) within 30 days of AGM
 *   - Section 92: Annual return (MGT-7) within 60 days of AGM
 *   - Section 139: Auditor appointment (ADT-1) within 15 days of AGM
 *   - Section 10A: Declaration for commencement of business (INC-20A) within 180 days
 *   - Rule 12A Companies (Appointment and Qualification of Directors) Rules: DIR-3 KYC by 30 Sep annually
 *   - Section 77: Charge registration (CHG-1) within 30 days of creation
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  Building2,
  FileText,
  CheckCircle,
  AlertTriangle,
  Clock,
  Plus,
  ArrowLeft,
  X,
  Calendar,
  AlertCircle,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

// ─── Types ───────────────────────────────────────────────────────────────────

type FilingStatus = "Pending" | "Filed" | "Overdue";

interface MCAFiling {
  id: string;
  client_id: string;
  client_name: string;
  cin: string;
  form_type: string;
  due_date: string; // ISO date string
  status: FilingStatus;
  filed_date: string | null;
  created_at: string;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const TODAY = new Date("2026-06-01");

/**
 * MCA form types — Companies Act 2013
 * AGM is held within 6 months of FY end (31 Mar) → typically 30 Sep.
 * Deadlines computed from AGM date of 30 Sep 2025 for FY 2024-25:
 *   AOC-4: 30 days from AGM → 29 Oct 2025 (Section 137)
 *   MGT-7: 60 days from AGM → 28 Nov 2025 (Section 92)
 *   DIR-3 KYC: 30 Sep annually (Rule 12A)
 */
const FORM_TYPES = [
  { value: "AOC-4", label: "AOC-4 — Annual Financial Statement" },
  { value: "MGT-7", label: "MGT-7 — Annual Return (Pvt Ltd)" },
  { value: "MGT-7A", label: "MGT-7A — Annual Return (OPC/Small Co)" },
  { value: "ADT-1", label: "ADT-1 — Auditor Appointment" },
  { value: "INC-20A", label: "INC-20A — Commencement of Business" },
  { value: "DIR-3 KYC", label: "DIR-3 KYC — Director KYC" },
  { value: "CHG-1", label: "CHG-1 — Charge Creation" },
];

/** FY 2025-26 key MCA deadlines */
const KEY_DEADLINES = [
  { label: "DIR-3 KYC", date: "30 Sep 2025", note: "Rule 12A — Annual" },
  { label: "AOC-4", date: "29 Oct 2025", note: "Section 137 — 30 days from AGM" },
  { label: "MGT-7/7A", date: "28 Nov 2025", note: "Section 92 — 60 days from AGM" },
  { label: "ADT-1", date: "14 Oct 2025", note: "Section 139 — 15 days from AGM" },
  { label: "INC-20A", date: "26 Sep 2025", note: "Section 10A — 180 days from incorporation" },
  { label: "CHG-1", date: "Within 30 days", note: "Section 77 — charge creation" },
  { label: "MSME-1", date: "30 Apr 2026", note: "Half-yearly — Oct–Mar 2026" },
  { label: "BEN-2", date: "As applicable", note: "Section 90 — significant beneficial owner" },
];

/** Sample seed data shown when table doesn't exist yet */
const SEED_FILINGS: MCAFiling[] = [
  {
    id: "seed-1",
    client_id: "",
    client_name: "Joshi Textiles Pvt Ltd",
    cin: "U17200MH2010PTC205678",
    form_type: "AOC-4",
    due_date: "2025-10-29",
    status: "Filed",
    filed_date: "2025-10-20",
    created_at: "",
  },
  {
    id: "seed-2",
    client_id: "",
    client_name: "Joshi Textiles Pvt Ltd",
    cin: "U17200MH2010PTC205678",
    form_type: "MGT-7",
    due_date: "2025-11-28",
    status: "Filed",
    filed_date: "2025-11-15",
    created_at: "",
  },
  {
    id: "seed-3",
    client_id: "",
    client_name: "Sharma Industries Pvt Ltd",
    cin: "U15200MH2015PTC301234",
    form_type: "DIR-3 KYC",
    due_date: "2025-09-30",
    status: "Overdue",
    filed_date: null,
    created_at: "",
  },
  {
    id: "seed-4",
    client_id: "",
    client_name: "Mehta Consulting LLP",
    cin: "AAC-1234",
    form_type: "MGT-7A",
    due_date: "2025-11-28",
    status: "Filed",
    filed_date: "2025-11-20",
    created_at: "",
  },
  {
    id: "seed-5",
    client_id: "",
    client_name: "Patel Pharma Pvt Ltd",
    cin: "U24200GJ2018PTC102345",
    form_type: "ADT-1",
    due_date: "2025-10-14",
    status: "Pending",
    filed_date: null,
    created_at: "",
  },
  {
    id: "seed-6",
    client_id: "",
    client_name: "Gupta Infra Pvt Ltd",
    cin: "U45200DL2020PTC375890",
    form_type: "INC-20A",
    due_date: "2025-09-26",
    status: "Overdue",
    filed_date: null,
    created_at: "",
  },
];

// ─── Status helpers ───────────────────────────────────────────────────────────

const STATUS_STYLE: Record<FilingStatus, string> = {
  Filed: "bg-green-100 text-green-700",
  Pending: "bg-amber-100 text-amber-700",
  Overdue: "bg-red-100 text-red-700",
};

function computeStatus(dueDate: string, filed: string | null): FilingStatus {
  if (filed) return "Filed";
  const due = new Date(dueDate);
  return TODAY > due ? "Overdue" : "Pending";
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

// ─── Add Filing Modal ─────────────────────────────────────────────────────────

interface AddFilingModalProps {
  clients: Client[];
  firmId: string;
  onClose: () => void;
  onAdded: (filing: MCAFiling) => void;
}

function AddFilingModal({ clients, firmId, onClose, onAdded }: AddFilingModalProps) {
  const [clientId, setClientId] = useState("");
  const [cin, setCin] = useState("");
  const [formType, setFormType] = useState("AOC-4");
  const [dueDate, setDueDate] = useState("");
  const [status, setStatus] = useState<FilingStatus>("Pending");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Auto-fill CIN from selected client if available
  useEffect(() => {
    if (!clientId) return;
    const c = clients.find((cl) => cl.id === clientId);
    if (c && (c as unknown as Record<string, string>).cin) {
      setCin((c as unknown as Record<string, string>).cin);
    }
  }, [clientId, clients]);

  async function handleSubmit() {
    if (!clientId || !cin.trim() || !dueDate) {
      setErr("Client, CIN and Due Date are required.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const sb = getSupabaseClient();
      const selectedClient = clients.find((c) => c.id === clientId);
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const { data, error } = await sb
        .from("mca_filings")
        .insert({
          firm_id: firmId,
          client_id: clientId,
          client_name: selectedClient?.client_name ?? "",
          cin: cin.trim().toUpperCase(),
          form_type: formType,
          due_date: dueDate,
          status,
          filed_date: status === "Filed" ? new Date().toISOString().slice(0, 10) : null,
        })
        .select()
        .single();
      if (error) throw new Error(error.message);
      const filing = data as MCAFiling;
      filing.status = computeStatus(filing.due_date, filing.filed_date);
      onAdded(filing);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save filing");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Add MCA Filing</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        {err && (
          <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{err}</p>
        )}

        {/* Client */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Client</label>
          <select
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
          >
            <option value="">Select client…</option>
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.client_name}
              </option>
            ))}
          </select>
        </div>

        {/* CIN */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">
            CIN / LLPIN
          </label>
          <input
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
            placeholder="e.g. U17200MH2010PTC205678"
            value={cin}
            onChange={(e) => setCin(e.target.value.toUpperCase())}
          />
        </div>

        {/* Form Type */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Form Type</label>
          <select
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={formType}
            onChange={(e) => setFormType(e.target.value)}
          >
            {FORM_TYPES.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>

        {/* Due Date */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Due Date</label>
          <input
            type="date"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </div>

        {/* Status */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Status</label>
          <select
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            value={status}
            onChange={(e) => setStatus(e.target.value as FilingStatus)}
          >
            <option value="Pending">Pending</option>
            <option value="Filed">Filed</option>
            <option value="Overdue">Overdue</option>
          </select>
        </div>

        <div className="flex gap-2 pt-1">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving}
            className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Add Filing"}
          </button>
        </div>

        <p className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          All MCA filings must be submitted manually on the MCA21 portal after CA review.
        </p>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function MCAPage() {
  const [filings, setFilings] = useState<MCAFiling[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [firmId, setFirmId] = useState("");
  const [loading, setLoading] = useState(true);
  const [tableError, setTableError] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showModal, setShowModal] = useState(false);

  // ── Load data ──────────────────────────────────────────────────────────────
  useEffect(() => {
    async function load() {
      try {
        setLoading(true);
        const sb = getSupabaseClient();

        // Resolve firm_id from authenticated user
        const {
          data: { session },
        } = await sb.auth.getSession();

        let resolvedFirmId = "";
        if (session?.user?.id) {
          const { data: userData } = await sb
            .from("users")
            .select("firm_id")
            .eq("auth_user_id", session.user.id)
            .single();
          resolvedFirmId = userData?.firm_id ?? "";
        }
        setFirmId(resolvedFirmId);

        // Load clients for the Add Filing modal
        const cls = await getClients().catch(() => []);
        setClients(cls);

        // Load mca_filings — gracefully handle missing table
        // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        const { data, error: dbErr } = await sb
          .from("mca_filings")
          .select("*")
          .order("due_date");

        if (dbErr) {
          // Table likely doesn't exist yet
          setTableError(true);
          setFilings(SEED_FILINGS);
        } else {
          const rows = (data ?? []) as MCAFiling[];
          // Recompute status based on today's date
          const enriched = rows.map((r) => ({
            ...r,
            status: computeStatus(r.due_date, r.filed_date),
          }));
          setFilings(enriched.length > 0 ? enriched : SEED_FILINGS);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load MCA data");
        setFilings(SEED_FILINGS);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // ── Mark as Filed ──────────────────────────────────────────────────────────
  async function handleMarkFiled(id: string) {
    // Optimistic update
    setFilings((prev) =>
      prev.map((f) =>
        f.id === id
          ? { ...f, status: "Filed", filed_date: TODAY.toISOString().slice(0, 10) }
          : f
      )
    );

    if (!tableError) {
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const sb = getSupabaseClient();
      await sb
        .from("mca_filings")
        .update({
          status: "Filed",
          filed_date: TODAY.toISOString().slice(0, 10),
        })
        .eq("id", id);
    }
  }

  // ── Summary counts ──────────────────────────────────────────────────────────
  const totalFilings = filings.length;
  const pendingCount = filings.filter((f) => f.status === "Pending").length;
  const overdueCount = filings.filter((f) => f.status === "Overdue").length;
  const thisMonth = TODAY.getMonth();
  const thisYear = TODAY.getFullYear();
  const filedThisMonth = filings.filter((f) => {
    if (!f.filed_date) return false;
    const d = new Date(f.filed_date);
    return d.getMonth() === thisMonth && d.getFullYear() === thisYear;
  }).length;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link
          href="/dashboard"
          className="text-gray-400 hover:text-gray-600 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-gray-900">MCA / ROC Filings</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Ministry of Corporate Affairs — Companies Act 2013 compliance tracker
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 bg-blue-600 text-white text-sm px-3 py-2 rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add Filing
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Migration notice when table missing */}
      {tableError && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex gap-2">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-amber-800">MCA module not yet migrated</p>
            <p className="text-xs text-amber-700 mt-0.5">
              Run migration to enable MCA module: <code className="font-mono bg-amber-100 px-1 rounded">CREATE TABLE mca_filings (...)</code> — showing sample data below.
            </p>
          </div>
        </div>
      )}

      {/* Key Deadlines Banner — FY 2025-26 */}
      <div>
        <p className="text-xs font-medium text-gray-500 mb-2 flex items-center gap-1.5">
          <Calendar className="w-3.5 h-3.5" />
          Key MCA Deadlines — FY 2025-26
        </p>
        <div className="flex gap-2 overflow-x-auto pb-1">
          {KEY_DEADLINES.map((d) => (
            <div
              key={d.label}
              className="shrink-0 border border-gray-200 bg-white rounded-lg px-3 py-2 min-w-[140px]"
            >
              <p className="text-xs font-semibold text-gray-800">{d.label}</p>
              <p className="text-[11px] text-blue-600 font-medium mt-0.5">{d.date}</p>
              <p className="text-[10px] text-gray-400 mt-0.5 leading-tight">{d.note}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Building2 className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-gray-500">Total Filings</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">
            {loading ? "—" : totalFilings}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">All tracked</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-gray-500">Pending</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">
            {loading ? "—" : pendingCount}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">Not yet filed</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <AlertTriangle className="w-4 h-4 text-red-600" />
            </div>
            <span className="text-xs text-gray-500">Overdue</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">
            {loading ? "—" : overdueCount}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">Past due date</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <CheckCircle className="w-4 h-4 text-green-600" />
            </div>
            <span className="text-xs text-gray-500">Filed This Month</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">
            {loading ? "—" : filedThisMonth}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">Jun 2026</p>
        </div>
      </div>

      {/* Filing Tracker Table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Filing Tracker</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              ROC / MCA filing obligations — Companies Act 2013
            </p>
          </div>
          <FileText className="w-4 h-4 text-gray-300" />
        </div>

        {loading ? (
          <div className="px-5 py-10 text-center text-sm text-gray-400">
            Loading filings…
          </div>
        ) : filings.length === 0 ? (
          <div className="px-5 py-10 text-center">
            <Building2 className="w-8 h-8 text-gray-200 mx-auto mb-3" />
            <p className="text-sm text-gray-500 font-medium">No filings tracked yet</p>
            <p className="text-xs text-gray-400 mt-1">
              Click &ldquo;Add Filing&rdquo; to start tracking MCA obligations.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">
                    Client Name
                  </th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">
                    CIN / LLPIN
                  </th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">
                    Form Type
                  </th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">
                    Due Date
                  </th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">
                    Status
                  </th>
                  <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filings.map((f) => (
                  <tr key={f.id} className="hover:bg-gray-50/50">
                    {/* Client Name */}
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-md bg-blue-50 flex items-center justify-center shrink-0">
                          <Building2 className="w-3.5 h-3.5 text-blue-600" />
                        </div>
                        <span className="text-sm font-medium text-gray-900">
                          {f.client_name}
                        </span>
                      </div>
                    </td>

                    {/* CIN */}
                    <td className="px-3 py-3">
                      <span className="text-xs font-mono text-gray-600">{f.cin}</span>
                    </td>

                    {/* Form Type */}
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center gap-1 text-xs font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                        <FileText className="w-3 h-3" />
                        {f.form_type}
                      </span>
                    </td>

                    {/* Due Date */}
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3 h-3 text-gray-300" />
                        <span className="text-xs text-gray-600">
                          {formatDate(f.due_date)}
                        </span>
                      </div>
                    </td>

                    {/* Status */}
                    <td className="px-3 py-3">
                      <span
                        className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${STATUS_STYLE[f.status]}`}
                      >
                        {f.status === "Filed" && <CheckCircle className="w-3 h-3" />}
                        {f.status === "Overdue" && <AlertTriangle className="w-3 h-3" />}
                        {f.status === "Pending" && <Clock className="w-3 h-3" />}
                        {f.status}
                      </span>
                    </td>

                    {/* Action */}
                    <td className="px-5 py-3">
                      {f.status === "Filed" ? (
                        <span className="text-xs text-gray-400">
                          {f.filed_date ? `Filed ${formatDate(f.filed_date)}` : "Filed"}
                        </span>
                      ) : (
                        <button
                          onClick={() => handleMarkFiled(f.id)}
                          className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
                        >
                          Mark as Filed
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Footer note */}
        <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30">
          <p className="text-[10px] text-gray-400">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            All filings must be submitted manually on MCA21 portal (mca.gov.in) after CA review. CAflow does not auto-submit to any government portal.
          </p>
        </div>
      </div>

      {/* Add Filing Modal */}
      {showModal && (
        <AddFilingModal
          clients={clients}
          firmId={firmId}
          onClose={() => setShowModal(false)}
          onAdded={(filing) => setFilings((prev) => [...prev, filing])}
        />
      )}
    </div>
  );
}
