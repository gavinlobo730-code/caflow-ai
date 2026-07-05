"use client";

/**
 * GST Module — GSTR Filing Tracker & Reconciliation Hub
 * CGST Act Section 37: GSTR-1 (Outward Supplies) — due 11th of following month
 * CGST Act Section 39: GSTR-3B (Monthly Summary Return) — due 20th of following month
 * CGST Act Section 44: GSTR-9 (Annual Return) — due 31st December
 */

import { useState, useEffect, useMemo } from "react";
import {
  Users,
  CheckCircle,
  AlertCircle,
  Clock,
  Plus,
  X,
  Calendar,
  GitMerge,
  FileText,
  Receipt,
} from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { DataTable } from "@/components/ui/data-table";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import type { Column, FilterDef } from "@/lib/table/types";
import { todayLocalISO, computeOverdueStatus } from "@/lib/dateMath";

// ─── Types ────────────────────────────────────────────────────────────────────

type FilingStatus = "Pending" | "Filed" | "Overdue";
type ReturnType = "GSTR-1" | "GSTR-3B" | "GSTR-9";

interface GSTFiling {
  id: string;
  client_id: string;
  client_name: string;
  gstin: string | null;
  return_type: ReturnType;
  period: string; // "MMM YYYY" e.g. "May 2026"
  due_date: string; // ISO date string
  status: FilingStatus;
  filed_date: string | null;
  created_at: string;
  firm_id: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const RETURN_TYPES: ReturnType[] = ["GSTR-1", "GSTR-3B", "GSTR-9"];

const MONTH_NAMES = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * Build month options for last 12 months (current + 11 prior) in MMM YYYY format.
 * Financial year runs April–March (CGST Act).
 */
function buildMonthOptions(): { value: string; label: string }[] {
  const today = new Date(todayLocalISO() + "T00:00:00");
  const options: { value: string; label: string }[] = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
    const label = `${MONTH_NAMES[d.getMonth()]} ${d.getFullYear()}`;
    options.push({ value: label, label });
  }
  return options;
}

const MONTH_OPTIONS = buildMonthOptions();

/** Auto-fill due date based on return type and period — CGST Act Sections 37, 39, 44 */
function getDueDate(returnType: ReturnType, period: string): string {
  if (returnType === "GSTR-9") {
    // CGST Act Section 44 — GSTR-9 due 31st December of the following FY
    const parts = period.split(" ");
    const year = parseInt(parts[1] ?? "0");
    return `${year + 1}-12-31`;
  }
  // Parse "MMM YYYY" into a date
  const parts = period.split(" ");
  if (parts.length < 2) return "";
  const monthIdx = MONTH_NAMES.indexOf(parts[0]);
  const year = parseInt(parts[1]);
  if (monthIdx === -1 || isNaN(year)) return "";

  // Advance to following month
  const nextMonth = monthIdx === 11 ? 0 : monthIdx + 1;
  const nextYear = monthIdx === 11 ? year + 1 : year;

  // GSTR-1: 11th of following month — CGST Act Section 37
  // GSTR-3B: 20th of following month — CGST Act Section 39
  const dueDay = returnType === "GSTR-1" ? 11 : 20;
  return `${nextYear}-${String(nextMonth + 1).padStart(2, "0")}-${String(dueDay).padStart(2, "0")}`;
}

/** Format ISO date to readable string */
function fmtDate(iso: string): string {
  if (!iso) return "—";
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** Determine status — Overdue only once a full calendar day has passed the due date */
const computeStatus = computeOverdueStatus;

// ─── Key deadlines banner ─────────────────────────────────────────────────────

const _today = new Date(todayLocalISO() + "T00:00:00");
const currentMonth = MONTH_NAMES[_today.getMonth()];
const currentYear = _today.getFullYear();

/** CGST Act Section 37: GSTR-1 due 11th of this month (for prior month) */
const KEY_DEADLINES = [
  {
    label: "GSTR-1",
    date: `11 ${currentMonth} ${currentYear}`,
    note: "CGST Act Section 37 — Outward Supplies",
    color: "bg-blue-50 border-blue-200 text-blue-700",
  },
  {
    label: "GSTR-3B",
    date: `20 ${currentMonth} ${currentYear}`,
    note: "CGST Act Section 39 — Monthly Summary",
    color: "bg-amber-50 border-amber-200 text-amber-700",
  },
  {
    label: "GSTR-9",
    date: `31 Dec ${currentYear}`,
    note: "CGST Act Section 44 — Annual Return",
    color: "bg-purple-50 border-purple-200 text-purple-700",
  },
];

// ─── Status badge style map ───────────────────────────────────────────────────

const STATUS_STYLE: Record<FilingStatus, string> = {
  Filed: "bg-green-100 text-green-700",
  Pending: "bg-amber-100 text-amber-700",
  Overdue: "bg-red-100 text-red-700",
};

// ─── Add Filing Modal ─────────────────────────────────────────────────────────

interface AddFilingModalProps {
  clients: Client[];
  firmId: string;
  onClose: () => void;
  onAdded: (filing: GSTFiling) => void;
}

function AddFilingModal({ clients, firmId, onClose, onAdded }: AddFilingModalProps) {
  const [clientId, setClientId] = useState(clients[0]?.id ?? "");
  const [returnType, setReturnType] = useState<ReturnType>("GSTR-1");
  const [period, setPeriod] = useState(MONTH_OPTIONS[MONTH_OPTIONS.length - 1]?.value ?? "");
  const [dueDate, setDueDate] = useState(() => getDueDate("GSTR-1", MONTH_OPTIONS[MONTH_OPTIONS.length - 1]?.value ?? ""));
  const [status, setStatus] = useState<FilingStatus>("Pending");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Auto-fill due date when return type or period changes
  useEffect(() => {
    setDueDate(getDueDate(returnType, period));
  }, [returnType, period]);

  async function handleSave() {
    if (!clientId || !period) {
      setErr("Please fill all required fields.");
      return;
    }
    setSaving(true);
    setErr(null);
    try {
      const sb = getSupabaseClient();
      const selectedClient = clients.find((c) => c.id === clientId);
      const filedDate = status === "Filed" ? todayLocalISO() : null;

      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      // Map ReturnType to compliance_calendar compliance_type values
      const complianceTypeMap: Record<string, string> = { "GSTR-1": "GSTR1", "GSTR-3B": "GSTR3B", "GSTR-9": "GSTR9" };
      const [pYear, pMonth] = period.split("-").map(Number);
      const periodStart = `${pYear}-${String(pMonth).padStart(2, "0")}-01`;
      const periodEnd = new Date(pYear, pMonth, 0).toISOString().slice(0, 10);
      const { data, error } = await sb
        .from("compliance_calendar")
        .insert({
          firm_id: firmId,
          client_id: clientId,
          compliance_type: complianceTypeMap[returnType] ?? returnType,
          period_start: periodStart,
          period_end: periodEnd,
          due_date: dueDate,
          filing_status: filedDate ? "filed" : "pending",
          filed_date: filedDate,
        })
        .select()
        .single();

      if (error) throw new Error(error.message);
      const returnTypeMap: Record<string, ReturnType> = { GSTR1: "GSTR-1", GSTR3B: "GSTR-3B", GSTR9: "GSTR-9" };
      const r = data as Record<string, unknown>;
      const filing: GSTFiling = {
        id: r.id as string,
        firm_id: r.firm_id as string,
        client_id: r.client_id as string,
        client_name: selectedClient?.client_name ?? "",
        gstin: selectedClient?.gstin ?? null,
        return_type: returnTypeMap[r.compliance_type as string] ?? returnType,
        period: new Date((r.period_start as string) + "T00:00:00").toLocaleString("default", { month: "short", year: "numeric" }),
        due_date: r.due_date as string,
        status: computeStatus(r.due_date as string, r.filed_date as string | null),
        filed_date: r.filed_date as string | null,
        created_at: r.created_at as string,
      };
      onAdded(filing);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save filing.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[#0F172A]">Add GST Filing</h3>
          <button onClick={onClose} className="text-[#94A3B8] hover:text-[#475569]">
            <X className="w-4 h-4" />
          </button>
        </div>

        {err && (
          <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{err}</p>
        )}

        {/* Client */}
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

        {/* Return Type */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Return Type</label>
          <select
            value={returnType}
            onChange={(e) => setReturnType(e.target.value as ReturnType)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {RETURN_TYPES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>

        {/* Period */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Period</label>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {MONTH_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Due Date — auto-filled, editable */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">
            Due Date
            <span className="text-[#94A3B8] font-normal ml-1">(auto-filled, editable)</span>
          </label>
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-[10px] text-[#94A3B8] mt-1">
            {returnType === "GSTR-1" && "CGST Act Section 37 — 11th of following month"}
            {returnType === "GSTR-3B" && "CGST Act Section 39 — 20th of following month"}
            {returnType === "GSTR-9" && "CGST Act Section 44 — 31st December"}
          </p>
        </div>

        {/* Status */}
        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as FilingStatus)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="Pending">Pending</option>
            <option value="Filed">Filed</option>
            <option value="Overdue">Overdue</option>
          </select>
        </div>

        <div className="flex gap-2 pt-2">
          <button
            onClick={onClose}
            className="flex-1 border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex-1 bg-blue-600 text-white text-sm py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Filing"}
          </button>
        </div>

        <p className="text-[10px] text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          PracticeSync never auto-submits to the GST portal. Always file manually after CA review.
        </p>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function GSTPage() {
  const [filings, setFilings] = useState<GSTFiling[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [firmId, setFirmId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [filedModal, setFiledModal] = useState<{ filing: GSTFiling } | null>(null);
  const [filedForm, setFiledForm] = useState({ arn: "", filed_date: "" });
  const [filedLoading, setFiledLoading] = useState(false);
  const [filedError, setFiledError] = useState<string | null>(null);

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

        const cls = await getClients().catch(() => [] as Client[]);
        setClients(cls);

        // Load from compliance_calendar with client join for GST types
        if (resolvedFirmId) {
          const { data, error: dbErr } = await sb
            .from("compliance_calendar")
            .select("id, firm_id, client_id, compliance_type, period_start, period_end, due_date, filing_status, filed_date, created_at, clients(client_name, gstin)")
            .eq("firm_id", resolvedFirmId)
            .in("compliance_type", ["GSTR1", "GSTR3B", "GSTR9"])
            .order("due_date", { ascending: true });

          if (dbErr) {
            if (dbErr.code === "42P01" || dbErr.message?.includes("does not exist")) {
              setFilings([]);
            } else {
              throw new Error(dbErr.message);
            }
          } else {
            const returnTypeMap: Record<string, ReturnType> = { GSTR1: "GSTR-1", GSTR3B: "GSTR-3B", GSTR9: "GSTR-9" };
            const rows: GSTFiling[] = (data ?? []).map((r: Record<string, unknown>) => {
              const client = r.clients as { client_name?: string; gstin?: string } | null;
              return {
                id: r.id as string,
                firm_id: r.firm_id as string,
                client_id: r.client_id as string,
                client_name: client?.client_name ?? "",
                gstin: client?.gstin ?? null,
                return_type: returnTypeMap[r.compliance_type as string] ?? (r.compliance_type as ReturnType),
                period: new Date((r.period_start as string) + "T00:00:00").toLocaleString("default", { month: "short", year: "numeric" }),
                due_date: r.due_date as string,
                status: computeStatus(r.due_date as string, r.filed_date as string | null),
                filed_date: r.filed_date as string | null,
                created_at: r.created_at as string,
              };
            });
            setFilings(rows);
          }
        } else {
          setFilings([]);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load GST data.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // ── Mark as Filed ──────────────────────────────────────────────────────────
  function openMarkFiledModal(f: GSTFiling) {
    setFiledModal({ filing: f });
    setFiledForm({ arn: "", filed_date: todayLocalISO() });
    setFiledError(null);
  }

  async function handleMarkFiled() {
    if (!filedModal) return;
    if (!filedForm.arn.trim()) {
      setFiledError("Acknowledgement number is required");
      return;
    }
    if (!filedForm.filed_date) {
      setFiledError("Filing date is required");
      return;
    }
    const id = filedModal.filing.id;
    setFiledLoading(true);
    setFiledError(null);
    try {
      const sb = getSupabaseClient();
      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const { error: dbErr } = await sb
        .from("compliance_calendar")
        .update({
          filing_status: "filed",
          filed_date: filedForm.filed_date,
          arn_number: filedForm.arn.trim(),
        })
        .eq("id", id);
      if (dbErr) throw new Error(dbErr.message);

      setFilings((prev) =>
        prev.map((f) =>
          f.id === id
            ? { ...f, status: "Filed", filed_date: filedForm.filed_date }
            : f
        )
      );
      setFiledModal(null);
    } catch (err) {
      setFiledError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setFiledLoading(false);
    }
  }

  // ── Summary counts (current month) ────────────────────────────────────────
  const currentPeriod = `${currentMonth} ${currentYear}`;

  const totalClients = new Set(filings.map((f) => f.client_id)).size;

  const filedThisMonth = filings.filter(
    (f) => f.period === currentPeriod && f.status === "Filed"
  ).length;

  const pendingThisMonth = filings.filter(
    (f) => f.period === currentPeriod && f.status === "Pending"
  ).length;

  const overdueCount = filings.filter((f) => f.status === "Overdue").length;

  // ── Unique periods from filings (for filter dropdown) ─────────────────────
  const uniquePeriods = useMemo(
    () => Array.from(new Set(filings.map((f) => f.period))),
    [filings],
  );

  // ── DataTable columns (client × period filing tracker) ────────────────────
  const columns: Column<GSTFiling>[] = useMemo(() => [
    {
      key: "client_name", header: "Client", accessor: (f) => f.client_name,
      searchable: true, sortable: true, sticky: true, hideable: false,
      render: (f) => <span className="font-medium text-[#0F172A]">{f.client_name}</span>,
    },
    {
      key: "gstin", header: "GSTIN", accessor: (f) => f.gstin ?? "", searchable: true,
      render: (f) => <span className="font-mono text-xs text-[#64748B]">{f.gstin ?? "—"}</span>,
    },
    {
      key: "return_type", header: "Return Type", accessor: (f) => f.return_type, sortable: true,
      render: (f) => (
        <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
          {f.return_type}
        </span>
      ),
    },
    {
      key: "period", header: "Period", accessor: (f) => f.period, sortable: true,
      render: (f) => <span className="text-[#334155]">{f.period}</span>,
    },
    {
      key: "due_date", header: "Due Date", accessor: (f) => f.due_date, sortable: true,
      render: (f) => (
        <div className="flex items-center gap-1.5">
          <Clock className="w-3 h-3 text-[#CBD5E1]" />
          <span className="text-xs text-[#475569]">{fmtDate(f.due_date)}</span>
        </div>
      ),
    },
    {
      key: "filed_date", header: "Filed Date", accessor: (f) => f.filed_date ?? "",
      sortable: true, defaultHidden: true,
      render: (f) => <span className="text-xs text-[#475569]">{f.filed_date ? fmtDate(f.filed_date) : "—"}</span>,
    },
    {
      key: "status", header: "Status", accessor: (f) => f.status, sortable: true,
      render: (f) => (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[f.status]}`}>
          {f.status}
        </span>
      ),
    },
  ], []);

  const filters: FilterDef<GSTFiling>[] = useMemo(() => [
    {
      key: "status", label: "Status", type: "select", accessor: (f) => f.status,
      options: (["Pending", "Filed", "Overdue"] as FilingStatus[]).map((s) => ({ value: s, label: s })),
    },
    {
      key: "return_type", label: "Form Type", type: "select", accessor: (f) => f.return_type,
      options: RETURN_TYPES.map((r) => ({ value: r, label: r })),
    },
    {
      key: "period", label: "Period", type: "select", accessor: (f) => f.period,
      options: uniquePeriods.map((p) => ({ value: p, label: p })),
    },
  ], [uniquePeriods]);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">GST</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            GSTR Filing Tracker — CGST Act Sections 37, 39, 44
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/gst/gstr1"
            className="flex items-center gap-1.5 text-xs bg-white border border-[#E2E8F0] text-[#334155] px-3 py-2 rounded-lg hover:bg-[#F8FAFC]"
          >
            <FileText className="w-3.5 h-3.5" />
            GSTR-1
          </Link>
          <Link
            href="/gst/gstr3b"
            className="flex items-center gap-1.5 text-xs bg-white border border-[#E2E8F0] text-[#334155] px-3 py-2 rounded-lg hover:bg-[#F8FAFC]"
          >
            <Receipt className="w-3.5 h-3.5" />
            GSTR-3B
          </Link>
          <Link
            href="/gst/reconciliation"
            className="flex items-center gap-1.5 text-xs bg-white border border-[#E2E8F0] text-[#334155] px-3 py-2 rounded-lg hover:bg-[#F8FAFC]"
          >
            <GitMerge className="w-3.5 h-3.5" />
            GSTR-2B Reconciliation
          </Link>
          <button
            onClick={() => setShowAddModal(true)}
            className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700"
          >
            <Plus className="w-3.5 h-3.5" />
            Add GST Filing
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Key Deadlines Banner — CGST Act Sections 37, 39, 44 */}
      <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
        <div className="flex items-center gap-2 mb-3">
          <Calendar className="w-4 h-4 text-[#64748B]" />
          <span className="text-xs font-semibold text-[#334155]">
            Key GST Deadlines — {currentMonth} {currentYear}
          </span>
        </div>
        <div className="flex flex-wrap gap-2">
          {KEY_DEADLINES.map((d) => (
            <div
              key={d.label}
              className={`flex items-center gap-2 border rounded-lg px-3 py-2 text-xs ${d.color}`}
            >
              <span className="font-semibold">{d.label}</span>
              <span className="font-mono">{d.date}</span>
              <span className="text-opacity-75 hidden sm:inline">· {d.note}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Users className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-[#64748B]">Total GST Clients</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : totalClients}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">With GST filings tracked</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <CheckCircle className="w-4 h-4 text-green-600" />
            </div>
            <span className="text-xs text-[#64748B]">Filed This Month</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : filedThisMonth}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">{currentPeriod}</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-[#64748B]">Pending This Month</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : pendingThisMonth}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">{currentPeriod}</p>
        </div>

        <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <AlertCircle className="w-4 h-4 text-red-600" />
            </div>
            <span className="text-xs text-[#64748B]">Overdue</span>
          </div>
          <p className="text-lg font-semibold text-[#0F172A]">{loading ? "—" : overdueCount}</p>
          <p className="text-xs text-[#94A3B8] mt-0.5">All periods</p>
        </div>
      </div>

      {/* Filing Status — shared DataTable (search, filters, sort, pagination, export, prefs) */}
      <div className="space-y-2">
        <div>
          <h2 className="text-sm font-semibold text-[#0F172A]">Filing Status</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            Per client · per return type · per period
          </p>
        </div>

        <DataTable
          data={filings}
          columns={columns}
          filters={filters}
          getRowId={(f) => f.id}
          loading={loading}
          searchPlaceholder="Search by client or GSTIN…"
          initialSort={{ key: "due_date", dir: "asc" }}
          exportFilename="gst-tracker"
          persistKey="gst.tracker"
          emptyTitle="No GST filings found"
          emptyDescription="Add your first GST filing to start tracking GSTR-1, GSTR-3B and GSTR-9 deadlines."
          emptyAction={
            <button
              onClick={() => setShowAddModal(true)}
              className="mt-2 text-xs text-blue-600 hover:underline inline-flex items-center gap-1"
            >
              <Plus className="w-3 h-3" /> Add GST Filing
            </button>
          }
          rowActions={(f) =>
            f.status !== "Filed" ? (
              <button
                onClick={() => openMarkFiledModal(f)}
                className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
              >
                Mark as Filed
              </button>
            ) : (
              <div className="flex items-center justify-end gap-1 text-green-600">
                <CheckCircle className="w-3.5 h-3.5" />
                <span className="text-xs">
                  {f.filed_date ? fmtDate(f.filed_date) : "Filed"}
                </span>
              </div>
            )
          }
        />

        <p className="text-[10px] text-[#94A3B8]">
          {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
          GSTR-1 (Section 37): 11th · GSTR-3B (Section 39): 20th · GSTR-9 (Section 44): 31 Dec ·
          PracticeSync does not auto-submit to the GST portal — always file manually after CA review.
        </p>
      </div>

      {/* Add Filing Modal */}
      {showAddModal && clients.length > 0 && (
        <AddFilingModal
          clients={clients}
          firmId={firmId}
          onClose={() => setShowAddModal(false)}
          onAdded={(filing) => setFilings((prev) => [...prev, filing])}
        />
      )}

      {showAddModal && clients.length === 0 && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4 text-center">
            <p className="text-sm text-[#334155] font-medium">No clients found</p>
            <p className="text-xs text-[#64748B]">
              Add clients in the Clients section before adding GST filings.
            </p>
            <button
              onClick={() => setShowAddModal(false)}
              className="w-full border border-[#E2E8F0] text-[#475569] text-sm py-2 rounded-lg hover:bg-[#F8FAFC]"
            >
              Close
            </button>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* MODAL: Mark GST Return as Filed                                     */}
      {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT                            */}
      {/* ================================================================== */}
      {filedModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-[#F1F5F9]">
              <h3 className="text-base font-semibold text-[#0F172A]">Mark {filedModal.filing.return_type} as Filed</h3>
              <button onClick={() => setFiledModal(null)} className="text-[#94A3B8] hover:text-[#475569] transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">CA Confirmation Required</p>
                <p className="text-xs text-amber-700 mt-1">
                  This records an already-filed return. PracticeSync does NOT auto-submit to the GST Portal.
                  Verify the acknowledgement number before saving.
                </p>
              </div>

              <div className="text-sm text-[#334155] bg-[#F8FAFC] rounded-lg px-4 py-3">
                <p className="font-medium">{filedModal.filing.client_name}</p>
                <p className="text-xs text-[#94A3B8] mt-0.5 font-mono">
                  {filedModal.filing.gstin ?? ""} · {filedModal.filing.period}
                </p>
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  Acknowledgement Number (ARN) <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. AA270125001234A"
                  value={filedForm.arn}
                  onChange={(e) => setFiledForm((p) => ({ ...p, arn: e.target.value }))}
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  Date of Filing <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={filedForm.filed_date}
                  onChange={(e) => setFiledForm((p) => ({ ...p, filed_date: e.target.value }))}
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {filedError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{filedError}</p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-[#F1F5F9] flex gap-3 justify-end">
              <button
                onClick={() => setFiledModal(null)}
                className="px-4 py-2 text-sm font-medium text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-[#F8FAFC] transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleMarkFiled}
                disabled={filedLoading}
                className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                {filedLoading ? "Saving…" : "Confirm Filing"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
