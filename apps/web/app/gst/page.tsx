"use client";

/**
 * GST Module — GSTR Filing Tracker & Reconciliation Hub
 * CGST Act Section 37: GSTR-1 (Outward Supplies) — due 11th of following month
 * CGST Act Section 39: GSTR-3B (Monthly Summary Return) — due 20th of following month
 * CGST Act Section 44: GSTR-9 (Annual Return) — due 31st December
 */

import { useState, useEffect } from "react";
import {
  FileText,
  Users,
  CheckCircle,
  AlertCircle,
  Clock,
  Plus,
  X,
  Calendar,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";

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

const TODAY = new Date("2026-06-01");

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
  const options: { value: string; label: string }[] = [];
  for (let i = 11; i >= 0; i--) {
    const d = new Date(TODAY.getFullYear(), TODAY.getMonth() - i, 1);
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

/** Determine status — Overdue if past due_date and not Filed */
function computeStatus(dueDate: string, filedDate: string | null): FilingStatus {
  if (filedDate) return "Filed";
  const due = new Date(dueDate + "T00:00:00");
  return TODAY > due ? "Overdue" : "Pending";
}

// ─── Key deadlines banner ─────────────────────────────────────────────────────

const currentMonth = MONTH_NAMES[TODAY.getMonth()];
const currentYear = TODAY.getFullYear();

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
      const filedDate = status === "Filed" ? TODAY.toISOString().slice(0, 10) : null;

      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      const { data, error } = await sb
        .from("compliance_entries")
        .insert({
          firm_id: firmId,
          client_id: clientId,
          client_name: selectedClient?.client_name ?? "",
          gstin: selectedClient?.gstin ?? null,
          category: "GST",
          return_type: returnType,
          period,
          due_date: dueDate,
          status: filedDate ? "Filed" : computeStatus(dueDate, null),
          filed_date: filedDate,
        })
        .select()
        .single();

      if (error) throw new Error(error.message);
      const filing = data as GSTFiling;
      filing.status = computeStatus(filing.due_date, filing.filed_date);
      onAdded(filing);
      onClose();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to save filing.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Add GST Filing</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X className="w-4 h-4" />
          </button>
        </div>

        {err && (
          <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{err}</p>
        )}

        {/* Client */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Client</label>
          <select
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {clients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.client_name}
                {c.gstin ? ` · ${c.gstin}` : ""}
              </option>
            ))}
          </select>
        </div>

        {/* Return Type */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Return Type</label>
          <select
            value={returnType}
            onChange={(e) => setReturnType(e.target.value as ReturnType)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {RETURN_TYPES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </div>

        {/* Period */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Period</label>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {MONTH_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {/* Due Date — auto-filled, editable */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">
            Due Date
            <span className="text-gray-400 font-normal ml-1">(auto-filled, editable)</span>
          </label>
          <input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-[10px] text-gray-400 mt-1">
            {returnType === "GSTR-1" && "CGST Act Section 37 — 11th of following month"}
            {returnType === "GSTR-3B" && "CGST Act Section 39 — 20th of following month"}
            {returnType === "GSTR-9" && "CGST Act Section 44 — 31st December"}
          </p>
        </div>

        {/* Status */}
        <div>
          <label className="text-xs font-medium text-gray-700 block mb-1">Status</label>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as FilingStatus)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="Pending">Pending</option>
            <option value="Filed">Filed</option>
            <option value="Overdue">Overdue</option>
          </select>
        </div>

        <div className="flex gap-2 pt-2">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50"
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
          CAflow never auto-submits to the GST portal. Always file manually after CA review.
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
  const [filterPeriod, setFilterPeriod] = useState("all");

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

        // Load compliance_entries filtered by firm and GST category
        if (resolvedFirmId) {
          const { data, error: dbErr } = await sb
            .from("compliance_entries")
            .select("*")
            .eq("firm_id", resolvedFirmId)
            .eq("category", "GST")
            .order("due_date", { ascending: true });

          if (dbErr) {
            // Table may not exist yet — show empty state instead of crashing
            if (dbErr.code === "42P01" || dbErr.message?.includes("does not exist")) {
              setFilings([]);
            } else {
              throw new Error(dbErr.message);
            }
          } else {
            const rows = (data ?? []) as GSTFiling[];
            // Recompute live status
            setFilings(rows.map((r) => ({ ...r, status: computeStatus(r.due_date, r.filed_date) })));
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
  async function handleMarkFiled(id: string) {
    const sb = getSupabaseClient();
    // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    const { error: dbErr } = await sb
      .from("compliance_entries")
      .update({ status: "Filed", filed_date: TODAY.toISOString().slice(0, 10) })
      .eq("id", id);

    if (!dbErr) {
      setFilings((prev) =>
        prev.map((f) =>
          f.id === id
            ? { ...f, status: "Filed", filed_date: TODAY.toISOString().slice(0, 10) }
            : f
        )
      );
    }
  }

  // ── Filter by period ───────────────────────────────────────────────────────
  const filteredFilings =
    filterPeriod === "all"
      ? filings
      : filings.filter((f) => f.period === filterPeriod);

  // ── Summary counts (current month) ────────────────────────────────────────
  const currentPeriod = `${MONTH_NAMES[TODAY.getMonth()]} ${TODAY.getFullYear()}`;

  const totalClients = new Set(filings.map((f) => f.client_id)).size;

  const filedThisMonth = filings.filter(
    (f) => f.period === currentPeriod && f.status === "Filed"
  ).length;

  const pendingThisMonth = filings.filter(
    (f) => f.period === currentPeriod && f.status === "Pending"
  ).length;

  const overdueCount = filings.filter((f) => f.status === "Overdue").length;

  // ── Unique periods from filings (for filter dropdown) ─────────────────────
  const uniquePeriods = Array.from(new Set(filings.map((f) => f.period)));

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">GST</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            GSTR Filing Tracker — CGST Act Sections 37, 39, 44
          </p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-3 py-2 rounded-lg hover:bg-blue-700"
        >
          <Plus className="w-3.5 h-3.5" />
          Add GST Filing
        </button>
      </div>

      {/* Error banner */}
      {error && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Key Deadlines Banner — CGST Act Sections 37, 39, 44 */}
      <div className="bg-white rounded-xl border border-gray-100 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Calendar className="w-4 h-4 text-gray-500" />
          <span className="text-xs font-semibold text-gray-700">
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
        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center">
              <Users className="w-4 h-4 text-blue-600" />
            </div>
            <span className="text-xs text-gray-500">Total GST Clients</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : totalClients}</p>
          <p className="text-xs text-gray-400 mt-0.5">With GST filings tracked</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-green-50 flex items-center justify-center">
              <CheckCircle className="w-4 h-4 text-green-600" />
            </div>
            <span className="text-xs text-gray-500">Filed This Month</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : filedThisMonth}</p>
          <p className="text-xs text-gray-400 mt-0.5">{currentPeriod}</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center">
              <Clock className="w-4 h-4 text-amber-600" />
            </div>
            <span className="text-xs text-gray-500">Pending This Month</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : pendingThisMonth}</p>
          <p className="text-xs text-gray-400 mt-0.5">{currentPeriod}</p>
        </div>

        <div className="bg-white rounded-xl border border-gray-100 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-8 h-8 rounded-lg bg-red-50 flex items-center justify-center">
              <AlertCircle className="w-4 h-4 text-red-600" />
            </div>
            <span className="text-xs text-gray-500">Overdue</span>
          </div>
          <p className="text-lg font-semibold text-gray-900">{loading ? "—" : overdueCount}</p>
          <p className="text-xs text-gray-400 mt-0.5">All periods</p>
        </div>
      </div>

      {/* Month Filter + Table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Filing Status</h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Per client · per return type · per period
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-gray-500">Period:</label>
            <select
              value={filterPeriod}
              onChange={(e) => setFilterPeriod(e.target.value)}
              className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All Periods</option>
              {uniquePeriods.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <div className="px-5 py-10 text-center text-sm text-gray-400">Loading…</div>
        ) : filteredFilings.length === 0 ? (
          <div className="px-5 py-12 text-center space-y-2">
            <FileText className="w-8 h-8 mx-auto text-gray-200" />
            <p className="text-sm text-gray-500 font-medium">No GST filings found</p>
            <p className="text-xs text-gray-400">
              {filings.length === 0
                ? "Add your first GST filing to start tracking GSTR-1, GSTR-3B and GSTR-9 deadlines."
                : "No filings match the selected period filter."}
            </p>
            {filings.length === 0 && (
              <button
                onClick={() => setShowAddModal(true)}
                className="mt-2 text-xs text-blue-600 hover:underline inline-flex items-center gap-1"
              >
                <Plus className="w-3 h-3" /> Add GST Filing
              </button>
            )}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50">
                  <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Client</th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">GSTIN</th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Return Type</th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Period</th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Due Date</th>
                  <th className="text-left text-xs font-medium text-gray-400 px-3 py-3">Status</th>
                  <th className="text-left text-xs font-medium text-gray-400 px-5 py-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredFilings.map((f) => (
                  <tr key={f.id} className="hover:bg-gray-50/50">
                    <td className="px-5 py-3">
                      <p className="text-sm font-medium text-gray-900">{f.client_name}</p>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs font-mono text-gray-500">{f.gstin ?? "—"}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                        {f.return_type}
                      </span>
                    </td>
                    <td className="px-3 py-3 text-sm text-gray-700">{f.period}</td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1.5">
                        <Clock className="w-3 h-3 text-gray-300" />
                        <span className="text-xs text-gray-600">{fmtDate(f.due_date)}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLE[f.status]}`}
                      >
                        {f.status}
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      {f.status !== "Filed" ? (
                        <button
                          onClick={() => handleMarkFiled(f.id)}
                          className="text-xs text-blue-600 hover:text-blue-800 font-medium whitespace-nowrap"
                        >
                          Mark as Filed
                        </button>
                      ) : (
                        <div className="flex items-center gap-1 text-green-600">
                          <CheckCircle className="w-3.5 h-3.5" />
                          <span className="text-xs">
                            {f.filed_date ? fmtDate(f.filed_date) : "Filed"}
                          </span>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {filteredFilings.length > 0 && (
          <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30">
            <p className="text-[10px] text-gray-400">
              {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
              GSTR-1 (Section 37): 11th · GSTR-3B (Section 39): 20th · GSTR-9 (Section 44): 31 Dec ·
              CAflow does not auto-submit to the GST portal — always file manually after CA review.
            </p>
          </div>
        )}
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
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6 space-y-4 text-center">
            <p className="text-sm text-gray-700 font-medium">No clients found</p>
            <p className="text-xs text-gray-500">
              Add clients in the Clients section before adding GST filings.
            </p>
            <button
              onClick={() => setShowAddModal(false)}
              className="w-full border border-gray-200 text-gray-600 text-sm py-2 rounded-lg hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
