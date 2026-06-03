"use client";

/**
 * Income Tax / ITR Tracking Module
 * IT Act Section 139 — ITR filing due dates:
 *   - Non-audit cases: 31st July
 *   - Audit cases: 31st October
 * IT Act Section 208 — Advance tax installments
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * All filing actions require explicit CA confirmation. Never auto-submit to Income Tax Portal.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  FileText,
  Clock,
  CheckCircle2,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Plus,
  X,
  CalendarDays,
  IndianRupee,
} from "lucide-react";
import { StatCard } from "@/components/stat-card";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getClients } from "@/lib/data/clients";
import { formatDate } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ITREntry {
  id: string;
  client_id: string;
  compliance_type: string;
  period_start: string;
  period_end: string;
  due_date: string;
  filing_status: string;
  filed_date?: string | null;
  arn_number?: string | null;
  notes?: string | null;
  clients?: { client_name: string; pan: string; entity_type: string } | null;
}

const ITR_FORMS = ["ITR-1", "ITR-2", "ITR-3", "ITR-4", "ITR-5", "ITR-6", "ITR-7"] as const;
type ITRForm = (typeof ITR_FORMS)[number];

const ASSESSMENT_YEARS = ["2024-25", "2025-26", "2026-27"] as const;
type AY = (typeof ASSESSMENT_YEARS)[number];

const AY_PERIOD: Record<AY, { start: string; end: string }> = {
  "2024-25": { start: "2024-04-01", end: "2025-03-31" },
  "2025-26": { start: "2025-04-01", end: "2026-03-31" },
  "2026-27": { start: "2026-04-01", end: "2027-03-31" },
};

// IT Act Section 139 — due dates
const DUE_DATE_AUDIT: Record<AY, string> = {
  "2024-25": "2024-10-31",
  "2025-26": "2025-10-31",
  "2026-27": "2026-10-31",
};
const DUE_DATE_NON_AUDIT: Record<AY, string> = {
  "2024-25": "2024-07-31",
  "2025-26": "2025-07-31",
  "2026-27": "2026-07-31",
};

// Entity types that require audit (October deadline) — IT Act Section 44AB
const AUDIT_ENTITY_TYPES = new Set([
  "private_limited",
  "public_limited",
  "llp",
  "partnership",
  "trust",
  "aop",
  "boi",
]);

function isAuditCase(entityType: string): boolean {
  return AUDIT_ENTITY_TYPES.has(entityType?.toLowerCase() ?? "");
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-amber-100 text-amber-700",
  overdue: "bg-red-100 text-red-700",
  filed: "bg-green-100 text-green-700",
  in_progress: "bg-blue-100 text-blue-700",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  overdue: "Overdue",
  filed: "Filed",
  in_progress: "In Progress",
};

// ---------------------------------------------------------------------------
// Advance Tax installments — IT Act Section 208
// ---------------------------------------------------------------------------

const ADVANCE_TAX_INSTALLMENTS = [
  { label: "1st Installment", due: "15 Jun 2025", percent: 15, cumulative: "15%" },
  { label: "2nd Installment", due: "15 Sep 2025", percent: 30, cumulative: "45%" },
  { label: "3rd Installment", due: "15 Dec 2025", percent: 30, cumulative: "75%" },
  { label: "4th Installment", due: "15 Mar 2026", percent: 25, cumulative: "100%" },
];

// ---------------------------------------------------------------------------
// getFirmId helper (same pattern as compliance.ts)
// ---------------------------------------------------------------------------

async function getFirmId(): Promise<string> {
  const sb = getSupabaseClient();
  const {
    data: { session },
  } = await sb.auth.getSession();
  if (!session) throw new Error("Not authenticated");
  const { data } = await sb
    .from("users")
    .select("firm_id")
    .eq("auth_user_id", session.user.id)
    .single();
  if (!data?.firm_id) throw new Error("Firm not found — please complete onboarding.");
  return data.firm_id;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const TABS = ["ITR Status", "Advance Tax"] as const;
type Tab = (typeof TABS)[number];

export default function IncomeTaxPage() {
  const [activeTab, setActiveTab] = useState<Tab>("ITR Status");
  const [entries, setEntries] = useState<ITREntry[]>([]);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add ITR modal
  const [showAddModal, setShowAddModal] = useState(false);
  const [addForm, setAddForm] = useState({
    client_id: "",
    itr_form: "ITR-1" as ITRForm,
    assessment_year: "2025-26" as AY,
    due_date: "2025-07-31",
  });
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);

  // Mark as Filed modal
  const [filedModal, setFiledModal] = useState<{ entry: ITREntry } | null>(null);
  const [filedForm, setFiledForm] = useState({ arn: "", filed_date: "" });
  const [filedLoading, setFiledLoading] = useState(false);
  const [filedError, setFiledError] = useState<string | null>(null);

  // ITR guide
  const [showGuide, setShowGuide] = useState(false);

  // ---------------------------------------------------------------------------
  // Load data
  // ---------------------------------------------------------------------------

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [clientList, firmId] = await Promise.all([getClients(), getFirmId()]);
      setClients(clientList);

      const sb = getSupabaseClient();
      const { data, error: dbErr } = await sb
        .from("compliance_calendar")
        .select("*, clients(client_name, pan, entity_type)")
        .eq("firm_id", firmId)
        .in("compliance_type", ITR_FORMS)
        .order("due_date");

      if (dbErr) throw new Error(dbErr.message);
      setEntries((data ?? []) as ITREntry[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // ---------------------------------------------------------------------------
  // Derived stats
  // ---------------------------------------------------------------------------

  const today = new Date().toISOString().split("T")[0];
  const currentAY = "2025-26";

  const totalDue = entries.length;
  const filed = entries.filter((e) => e.filing_status === "filed").length;
  const overdue = entries.filter(
    (e) => e.filing_status !== "filed" && e.due_date < today
  ).length;
  const pending = entries.filter(
    (e) => e.filing_status !== "filed" && e.due_date >= today
  ).length;

  // Next deadline — earliest non-filed entry
  const nextDeadlineEntry = entries
    .filter((e) => e.filing_status !== "filed" && e.due_date >= today)
    .sort((a, b) => a.due_date.localeCompare(b.due_date))[0];

  // ---------------------------------------------------------------------------
  // Add ITR deadline
  // ---------------------------------------------------------------------------

  function handleAddFormChange(
    field: keyof typeof addForm,
    value: string
  ) {
    setAddForm((prev) => {
      const updated = { ...prev, [field]: value };

      // Auto-fill due date based on AY and entity type
      if (field === "client_id" || field === "assessment_year") {
        const clientId = field === "client_id" ? value : prev.client_id;
        const ay = (field === "assessment_year" ? value : prev.assessment_year) as AY;
        const client = clients.find((c) => c.id === clientId);
        if (client) {
          updated.due_date = isAuditCase(client.entity_type)
            ? DUE_DATE_AUDIT[ay]
            : DUE_DATE_NON_AUDIT[ay];
        }
      }

      return updated;
    });
  }

  async function handleAddSubmit() {
    if (!addForm.client_id) {
      setAddError("Please select a client");
      return;
    }
    setAddLoading(true);
    setAddError(null);
    try {
      const firmId = await getFirmId();
      const ay = addForm.assessment_year as AY;
      const period = AY_PERIOD[ay];

      const sb = getSupabaseClient();
      const { error: insertErr } = await sb.from("compliance_calendar").insert({
        firm_id: firmId,
        client_id: addForm.client_id,
        compliance_type: addForm.itr_form,
        period_start: period.start,
        period_end: period.end,
        due_date: addForm.due_date,
        filing_status: "pending",
      });

      if (insertErr) throw new Error(insertErr.message);
      setShowAddModal(false);
      setAddForm({ client_id: "", itr_form: "ITR-1", assessment_year: "2025-26", due_date: "2025-07-31" });
      await loadData();
    } catch (err) {
      setAddError(err instanceof Error ? err.message : "Failed to add ITR deadline");
    } finally {
      setAddLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Mark as Filed
  // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
  // ---------------------------------------------------------------------------

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
    setFiledLoading(true);
    setFiledError(null);
    try {
      const sb = getSupabaseClient();
      const { error: updateErr } = await sb
        .from("compliance_calendar")
        .update({
          filing_status: "filed",
          filed_date: filedForm.filed_date,
          arn_number: filedForm.arn.trim(),
          updated_at: new Date().toISOString(),
        })
        .eq("id", filedModal.entry.id);

      if (updateErr) throw new Error(updateErr.message);
      setFiledModal(null);
      setFiledForm({ arn: "", filed_date: "" });
      await loadData();
    } catch (err) {
      setFiledError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setFiledLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function getAYFromDates(periodStart: string): string {
    const year = parseInt(periodStart.slice(0, 4));
    const month = parseInt(periodStart.slice(5, 7));
    const fyStart = month >= 4 ? year : year - 1;
    return `${fyStart}-${String(fyStart + 1).slice(-2)}`;
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Income Tax</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            ITR Tracking — IT Act Section 139
          </p>
          {/* Sub-navigation */}
          <div className="flex gap-2 mt-3">
            <a href="/income-tax/capital-gains" className="text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 bg-blue-50 px-2.5 py-1 rounded-lg hover:bg-blue-100 transition-colors">
              Capital Gains Calculator
            </a>
            <a href="/income-tax/advance-tax" className="text-xs font-medium text-gray-500 hover:text-gray-700 border border-gray-200 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors">
              Advance Tax
            </a>
            <a href="/income-tax/notices" className="text-xs font-medium text-gray-500 hover:text-gray-700 border border-gray-200 px-2.5 py-1 rounded-lg hover:bg-gray-50 transition-colors">
              Notices
            </a>
          </div>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          Add ITR Deadline
        </button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="Total ITRs Due"
          value={String(totalDue)}
          icon={FileText}
          gradient="bg-gradient-to-br from-indigo-500 to-indigo-600"
        />
        <StatCard
          label="Filed This Year"
          value={String(filed)}
          icon={CheckCircle2}
          gradient="bg-gradient-to-br from-emerald-500 to-teal-600"
        />
        <StatCard
          label="Pending / Overdue"
          value={String(pending + overdue)}
          icon={Clock}
          gradient="bg-gradient-to-br from-amber-400 to-orange-500"
          alert={overdue > 0}
        />
        <StatCard
          label="Next Deadline"
          value={
            nextDeadlineEntry
              ? formatDate(nextDeadlineEntry.due_date)
              : "—"
          }
          icon={CalendarDays}
          gradient="bg-gradient-to-br from-violet-500 to-purple-600"
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* TAB: ITR Status                                                     */}
      {/* ------------------------------------------------------------------ */}
      {activeTab === "ITR Status" && (
        <div className="space-y-4">
          {/* ITR Status Table */}
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-gray-900">
                ITR Status — AY {currentAY}
              </h2>
              {overdue > 0 && (
                <span className="flex items-center gap-1 text-xs text-red-600 font-medium">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {overdue} overdue
                </span>
              )}
            </div>

            {loading ? (
              <div className="px-5 py-12 text-center text-sm text-gray-400">
                Loading ITR data…
              </div>
            ) : error ? (
              <div className="px-5 py-12 text-center text-sm text-red-500">
                {error}
              </div>
            ) : entries.length === 0 ? (
              <div className="px-5 py-14 text-center space-y-3">
                <FileText className="w-10 h-10 text-gray-200 mx-auto" />
                <p className="text-sm font-medium text-gray-600">
                  No ITR deadlines added yet
                </p>
                <p className="text-xs text-gray-400 max-w-sm mx-auto">
                  Click &ldquo;Add ITR Deadline&rdquo; to manually track ITR filings for
                  your clients. Each entry records the ITR form, assessment year,
                  due date, and filing status.
                </p>
                <button
                  onClick={() => setShowAddModal(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-lg hover:bg-blue-100 transition-colors mt-1"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add first ITR deadline
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 text-xs text-gray-500 font-medium uppercase tracking-wider">
                      <th className="px-5 py-2.5 text-left">Client Name</th>
                      <th className="px-4 py-2.5 text-left">PAN</th>
                      <th className="px-4 py-2.5 text-left">Entity</th>
                      <th className="px-4 py-2.5 text-left">ITR Form</th>
                      <th className="px-4 py-2.5 text-left">AY</th>
                      <th className="px-4 py-2.5 text-left">Due Date</th>
                      <th className="px-4 py-2.5 text-left">Status</th>
                      <th className="px-4 py-2.5 text-left">ARN / Ack No</th>
                      <th className="px-4 py-2.5 text-left">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {entries.map((entry) => {
                      const isOverdue =
                        entry.filing_status !== "filed" && entry.due_date < today;
                      const effectiveStatus = isOverdue
                        ? "overdue"
                        : entry.filing_status;

                      return (
                        <tr
                          key={entry.id}
                          className="hover:bg-gray-50/50 transition-colors"
                        >
                          <td className="px-5 py-3 font-medium text-gray-900">
                            {entry.clients?.client_name ?? "—"}
                          </td>
                          <td className="px-4 py-3">
                            <span className="font-mono text-xs text-gray-600 bg-gray-50 px-1.5 py-0.5 rounded">
                              {entry.clients?.pan ?? "—"}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-gray-600 text-xs capitalize">
                            {(entry.clients?.entity_type ?? "—").replace(/_/g, " ")}
                          </td>
                          <td className="px-4 py-3">
                            <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
                              {entry.compliance_type}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-gray-600 text-xs">
                            {getAYFromDates(entry.period_start)}
                          </td>
                          <td className="px-4 py-3 text-gray-600 text-xs">
                            {formatDate(entry.due_date)}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                STATUS_STYLES[effectiveStatus] ??
                                "bg-gray-100 text-gray-600"
                              }`}
                            >
                              {STATUS_LABELS[effectiveStatus] ?? effectiveStatus}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs font-mono text-gray-500">
                            {entry.arn_number ?? (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            {entry.filing_status !== "filed" ? (
                              <button
                                onClick={() => {
                                  setFiledModal({ entry });
                                  setFiledForm({
                                    arn: "",
                                    filed_date: today,
                                  });
                                  setFiledError(null);
                                }}
                                className="text-xs px-2.5 py-1 bg-green-50 text-green-700 font-medium rounded hover:bg-green-100 transition-colors"
                              >
                                Mark Filed
                              </button>
                            ) : (
                              <span className="text-xs text-gray-400">
                                Filed {entry.filed_date ? formatDate(entry.filed_date) : ""}
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* ITR Form Guide — collapsible */}
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <button
              onClick={() => setShowGuide((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-4 text-sm font-semibold text-gray-900 hover:bg-gray-50/50 transition-colors"
            >
              <span className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-gray-400" />
                ITR Form Guide
              </span>
              {showGuide ? (
                <ChevronUp className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              )}
            </button>
            {showGuide && (
              <div className="px-5 pb-5 grid sm:grid-cols-2 gap-3 border-t border-gray-50 pt-4">
                {[
                  {
                    form: "ITR-1",
                    desc: "Salaried individuals, income up to ₹50 lakh",
                    tag: "Individual",
                  },
                  {
                    form: "ITR-2",
                    desc: "Capital gains, multiple properties, foreign income",
                    tag: "Individual / HUF",
                  },
                  {
                    form: "ITR-3",
                    desc: "Business or profession income (non-presumptive)",
                    tag: "Individual / HUF",
                  },
                  {
                    form: "ITR-4",
                    desc: "Presumptive taxation — IT Act Sections 44AD / 44ADA",
                    tag: "Individual / HUF / Firm",
                  },
                  {
                    form: "ITR-5",
                    desc: "Partnership firms, LLPs, AOPs, BOIs",
                    tag: "Firm / LLP",
                  },
                  {
                    form: "ITR-6",
                    desc: "Companies other than those claiming exemption u/s 11",
                    tag: "Company",
                  },
                  {
                    form: "ITR-7",
                    desc: "Trusts, political parties, research associations",
                    tag: "Trust / Other",
                  },
                ].map(({ form, desc, tag }) => (
                  <div
                    key={form}
                    className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg"
                  >
                    <span className="text-xs font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded shrink-0">
                      {form}
                    </span>
                    <div>
                      <p className="text-xs font-medium text-gray-700">{desc}</p>
                      <p className="text-xs text-gray-400 mt-0.5">{tag}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* TAB: Advance Tax — IT Act Section 208                               */}
      {/* ------------------------------------------------------------------ */}
      {activeTab === "Advance Tax" && (
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">
                Advance Tax Installments — FY 2025-26
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                IT Act Section 208 — applicable when tax liability ≥ ₹10,000
              </p>
            </div>
            <div className="divide-y divide-gray-50">
              {ADVANCE_TAX_INSTALLMENTS.map((inst) => {
                const dueDate = inst.due.replace(/(\d+) (\w+) (\d+)/, (_, d, m, y) => {
                  const months: Record<string, string> = {
                    Jan: "01", Feb: "02", Mar: "03", Apr: "04",
                    May: "05", Jun: "06", Jul: "07", Aug: "08",
                    Sep: "09", Oct: "10", Nov: "11", Dec: "12",
                  };
                  return `${y}-${months[m]}-${d.padStart(2, "0")}`;
                });
                const isPast = dueDate < today;
                const isUpcoming = !isPast && dueDate <= new Date(Date.now() + 30 * 86400000).toISOString().split("T")[0];

                return (
                  <div
                    key={inst.label}
                    className="flex items-center gap-4 px-5 py-4"
                  >
                    <div className="flex items-center justify-center w-10 h-10 bg-blue-50 rounded-full shrink-0">
                      <IndianRupee className="w-5 h-5 text-blue-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900">
                        {inst.label}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        Due: {inst.due} · Cumulative {inst.cumulative} of estimated tax
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-semibold text-gray-700">
                        {inst.percent}%
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">of estimated tax</p>
                    </div>
                    <span
                      className={`text-xs px-2.5 py-1 rounded-full font-medium shrink-0 ${
                        isPast
                          ? "bg-gray-100 text-gray-500"
                          : isUpcoming
                          ? "bg-amber-100 text-amber-700"
                          : "bg-blue-50 text-blue-600"
                      }`}
                    >
                      {isPast ? "Due passed" : isUpcoming ? "Upcoming" : "Scheduled"}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-semibold text-blue-800 uppercase tracking-wide mb-1">
                Advance Tax Calculator
              </p>
              <p className="text-sm text-blue-700">
                Calculate exact advance tax instalments, apply slab rates for FY
                2026-27, and compute Section 234B/234C interest on shortfalls —
                per client.
              </p>
            </div>
            <Link
              href="/income-tax/advance-tax"
              className="shrink-0 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              Open Calculator →
            </Link>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* Quick links to sub-tools                                           */}
      {/* ================================================================== */}
      <div className="grid sm:grid-cols-2 gap-3">
        <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold text-blue-800 uppercase tracking-wide mb-1">
              AIS Ingestion Tool
            </p>
            <p className="text-sm text-blue-700">
              Upload and review Annual Information Statement JSON — compare AIS with books before filing ITR.
            </p>
          </div>
          <Link
            href="/income-tax/ais"
            className="shrink-0 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
          >
            Open AIS Tool →
          </Link>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide mb-1">
              IT Notice Tracker
            </p>
            <p className="text-sm text-amber-700">
              Track and manage IT notices, faceless assessments, demand notices and penalty proceedings.
            </p>
          </div>
          <Link
            href="/income-tax/notices"
            className="shrink-0 px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700 transition-colors"
          >
            Open Tracker →
          </Link>
        </div>
      </div>

      {/* ================================================================== */}
      {/* MODAL: Add ITR Deadline                                             */}
      {/* ================================================================== */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
              <h3 className="text-base font-semibold text-gray-900">
                Add ITR Deadline
              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Client */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Client <span className="text-red-500">*</span>
                </label>
                <select
                  value={addForm.client_id}
                  onChange={(e) => handleAddFormChange("client_id", e.target.value)}
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="">Select client…</option>
                  {clients.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.client_name}
                    </option>
                  ))}
                </select>
              </div>

              {/* ITR Form */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  ITR Form
                </label>
                <select
                  value={addForm.itr_form}
                  onChange={(e) =>
                    handleAddFormChange("itr_form", e.target.value)
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {ITR_FORMS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>

              {/* Assessment Year */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Assessment Year
                </label>
                <select
                  value={addForm.assessment_year}
                  onChange={(e) =>
                    handleAddFormChange("assessment_year", e.target.value)
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {ASSESSMENT_YEARS.map((ay) => (
                    <option key={ay} value={ay}>
                      {ay}
                    </option>
                  ))}
                </select>
              </div>

              {/* Due Date — pre-filled, editable */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Due Date
                  <span className="ml-1 text-gray-400 font-normal">
                    (31 Jul — non-audit · 31 Oct — audit, IT Act S.139)
                  </span>
                </label>
                <input
                  type="date"
                  value={addForm.due_date}
                  onChange={(e) =>
                    handleAddFormChange("due_date", e.target.value)
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {addError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {addError}
                </p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleAddSubmit}
                disabled={addLoading}
                className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {addLoading ? "Adding…" : "Add Deadline"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* MODAL: Mark as Filed                                                */}
      {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT                            */}
      {/* ================================================================== */}
      {filedModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-gray-100">
              <h3 className="text-base font-semibold text-gray-900">
                Mark ITR as Filed
              </h3>
              <button
                onClick={() => setFiledModal(null)}
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Warning banner — CA Review */}
              <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3">
                <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">
                  CA Confirmation Required
                </p>
                <p className="text-xs text-amber-700 mt-1">
                  This records an already-filed return. CAflow does NOT
                  auto-submit to the Income Tax Portal. Verify the
                  acknowledgement number before saving.
                </p>
              </div>

              <div className="text-sm text-gray-700 bg-gray-50 rounded-lg px-4 py-3">
                <p className="font-medium">
                  {filedModal.entry.clients?.client_name ?? "Client"}
                </p>
                <p className="text-xs text-gray-400 mt-0.5 font-mono">
                  {filedModal.entry.clients?.pan ?? ""} ·{" "}
                  {filedModal.entry.compliance_type}
                </p>
              </div>

              {/* Acknowledgement Number */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Acknowledgement Number (ARN){" "}
                  <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="e.g. 123456789012345"
                  value={filedForm.arn}
                  onChange={(e) =>
                    setFiledForm((p) => ({ ...p, arn: e.target.value }))
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Filing Date */}
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1.5">
                  Date of Filing <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={filedForm.filed_date}
                  onChange={(e) =>
                    setFiledForm((p) => ({ ...p, filed_date: e.target.value }))
                  }
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {filedError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {filedError}
                </p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-gray-100 flex gap-3 justify-end">
              <button
                onClick={() => setFiledModal(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
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
