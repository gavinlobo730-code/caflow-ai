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

import { useState, useEffect, useCallback, useMemo } from "react";
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
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import { todayLocalISO, daysBetweenLocalISO } from "@/lib/dateMath";
import { useToast } from "@/components/ui/use-toast";

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

/** Derive assessment year (e.g. "2025-26") from a period's start date. */
function getAYFromDates(periodStart: string): string {
  const year = parseInt(periodStart.slice(0, 4));
  const month = parseInt(periodStart.slice(5, 7));
  const fyStart = month >= 4 ? year : year - 1;
  return `${fyStart}-${String(fyStart + 1).slice(-2)}`;
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
// Bulk Mark as Filed modal — batch reference-entry
// CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
//
// The single-row "Mark Filed" flow (see handleMarkFiled/filedModal below)
// requires one real ARN per filing, so bulk marking can't be a one-click
// action — this modal collects a per-row ARN plus one shared filing date,
// then writes each row individually so a failure on one row never blocks
// the others.
// ---------------------------------------------------------------------------

function BulkMarkFiledModal({
  selected,
  onClose,
  onFiled,
}: {
  /** Rows the user checked in the table — may include already-filed rows. */
  selected: ITREntry[];
  onClose: () => void;
  /** Re-loads the underlying table data after a write. */
  onFiled: () => Promise<void> | void;
}) {
  const { toast } = useToast();

  // Already-filed rows never appear in this modal.
  const pending = useMemo(
    () => selected.filter((e) => e.filing_status !== "filed"),
    [selected],
  );

  const [filedDate, setFiledDate] = useState(todayLocalISO());
  const [arns, setArns] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});
  // Rows already written successfully on a prior (partially-failed) submit —
  // excluded from the next retry so we never re-check/re-block on them.
  const [succeededIds, setSucceededIds] = useState<Set<string>>(new Set());

  if (pending.length === 0) return null;

  const remaining = pending.filter((e) => !succeededIds.has(e.id));
  const allArnsFilled =
    remaining.length > 0 && remaining.every((e) => (arns[e.id] ?? "").trim().length > 0);
  const submitDisabled = loading || !filedDate || !allArnsFilled;

  async function handleSubmit() {
    if (submitDisabled || remaining.length === 0) return;
    setLoading(true);
    setError(null);
    setRowErrors({});

    const sb = getSupabaseClient();
    const results = await Promise.all(
      remaining.map(async (entry) => {
        try {
          const { error: updateErr } = await sb
            .from("compliance_calendar")
            .update({
              filing_status: "filed",
              filed_date: filedDate,
              arn_number: arns[entry.id].trim(),
              updated_at: new Date().toISOString(),
            })
            .eq("id", entry.id);
          if (updateErr) throw new Error(updateErr.message);
          return { id: entry.id, ok: true as const };
        } catch (err) {
          return {
            id: entry.id,
            ok: false as const,
            message: err instanceof Error ? err.message : "Failed to update status",
          };
        }
      }),
    );

    const failed = results.filter((r) => !r.ok);
    const newlySucceeded = results.filter((r) => r.ok).map((r) => r.id);

    try {
      if (failed.length > 0) {
        // Keep the modal open — list which rows failed so the CA can fix and retry.
        setSucceededIds((prev) => new Set([...Array.from(prev), ...newlySucceeded]));
        setRowErrors(Object.fromEntries(failed.map((f) => [f.id, f.message])));
        setError(
          `${failed.length} of ${remaining.length} filing${remaining.length === 1 ? "" : "s"} ` +
            `could not be updated. Fix the row(s) below and submit again.`,
        );
        await onFiled();
        return;
      }

      await onFiled();
      toast({
        title: `Marked ${pending.length} ITR filing${pending.length === 1 ? "" : "s"} as filed`,
      });
      onClose();
    } catch (e) {
      // Each row reports its own failure above, so reaching here means the
      // parent's refresh threw after the updates landed: the filings ARE marked,
      // the list behind this modal is stale. Keep the modal open and say so.
      setError(e instanceof Error ? e.message : "Marked as filed, but the list could not be refreshed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-5 border-b border-[#F1F5F9]">
          <h3 className="text-base font-semibold text-[#0F172A]">
            Mark {pending.length} ITR Filing{pending.length === 1 ? "" : "s"} as Filed
          </h3>
          <button
            onClick={onClose}
            className="text-[#94A3B8] hover:text-[#475569] transition-colors"
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
              This records already-filed returns. PracticeSync does NOT
              auto-submit to the Income Tax Portal. Verify every
              acknowledgement number before saving.
            </p>
          </div>

          {/* Shared Filed Date — applied to every row below on submit */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1.5">
              Date of Filing <span className="text-red-500">*</span>
              <span className="ml-1 text-[#94A3B8] font-normal">
                (applied to all rows below)
              </span>
            </label>
            <input
              type="date"
              value={filedDate}
              onChange={(e) => setFiledDate(e.target.value)}
              className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Per-row Acknowledgement Number (ARN) entry */}
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1.5">
              Acknowledgement Number (ARN) — one per filing{" "}
              <span className="text-red-500">*</span>
            </label>
            <div className="max-h-[45vh] overflow-y-auto rounded-lg border border-[#F1F5F9]">
              {pending.map((entry) => {
                const isDone = succeededIds.has(entry.id);
                const rowError = rowErrors[entry.id];
                return (
                  <div
                    key={entry.id}
                    className="flex items-center gap-3 px-4 py-3 border-b border-[#F1F5F9] last:border-0 bg-white"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-[#0F172A] truncate">
                        {entry.clients?.client_name ?? "Client"}
                      </p>
                      <p className="text-xs text-[#94A3B8] mt-0.5 font-mono">
                        {entry.compliance_type} · AY {getAYFromDates(entry.period_start)}
                      </p>
                    </div>
                    {isDone ? (
                      <span className="flex items-center gap-1 text-xs font-medium text-green-700 shrink-0">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Filed
                      </span>
                    ) : (
                      <div className="w-44 shrink-0">
                        <input
                          type="text"
                          placeholder="e.g. 123456789012345"
                          value={arns[entry.id] ?? ""}
                          onChange={(e) =>
                            setArns((p) => ({ ...p, [entry.id]: e.target.value }))
                          }
                          className={`w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                            rowError ? "border-red-400" : "border-[#E2E8F0]"
                          }`}
                        />
                        {rowError && (
                          <p className="text-[10px] text-red-600 mt-1">{rowError}</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {error && (
            <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
              {error}
            </p>
          )}
        </div>

        <div className="px-6 py-4 border-t border-[#F1F5F9] flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-[#F8FAFC] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitDisabled}
            className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-lg hover:bg-green-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Saving…" : `Confirm Filing (${remaining.length})`}
          </button>
        </div>
      </div>
    </div>
  );
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

  // Bulk Mark as Filed modal (batch reference-entry — see BulkMarkFiledModal above)
  const [bulkFiledSelection, setBulkFiledSelection] = useState<ITREntry[] | null>(null);
  const { toast } = useToast();

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

  const today = todayLocalISO();
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
  // Bulk Mark as Filed — opens the batch reference-entry modal
  // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
  // ---------------------------------------------------------------------------

  function openBulkFiledModal(selected: ITREntry[]) {
    const pendingCount = selected.filter((e) => e.filing_status !== "filed").length;
    if (pendingCount === 0) {
      toast({
        title: "Nothing to file",
        description: "All selected ITR filings are already marked as filed.",
      });
      return;
    }
    setBulkFiledSelection(selected);
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  // Effective status: an unfiled entry past its due date reads as "overdue".
  const effectiveStatusOf = useCallback(
    (entry: ITREntry): string =>
      entry.filing_status !== "filed" && entry.due_date < today ? "overdue" : entry.filing_status,
    [today],
  );

  // ---------------------------------------------------------------------------
  // ITR Status DataTable — columns, filters
  // ---------------------------------------------------------------------------

  const itrColumns: Column<ITREntry>[] = useMemo(() => [
    {
      key: "client_name", header: "Client Name", sticky: true, hideable: false, sortable: true, searchable: true,
      accessor: (e) => e.clients?.client_name ?? "",
      render: (e) => <span className="font-medium text-[#0F172A]">{e.clients?.client_name ?? "—"}</span>,
    },
    {
      key: "pan", header: "PAN", searchable: true, sortable: true,
      accessor: (e) => e.clients?.pan ?? "",
      render: (e) => (
        <span className="font-mono text-xs text-[#475569] bg-[#F8FAFC] px-1.5 py-0.5 rounded">
          {e.clients?.pan ?? "—"}
        </span>
      ),
    },
    {
      key: "entity_type", header: "Entity", sortable: true,
      accessor: (e) => (e.clients?.entity_type ?? "").replace(/_/g, " "),
      render: (e) => (
        <span className="text-[#475569] text-xs capitalize">
          {(e.clients?.entity_type ?? "—").replace(/_/g, " ")}
        </span>
      ),
    },
    {
      key: "itr_form", header: "ITR Form", sortable: true,
      accessor: (e) => e.compliance_type,
      render: (e) => (
        <span className="text-xs font-semibold text-blue-700 bg-blue-50 px-2 py-0.5 rounded">
          {e.compliance_type}
        </span>
      ),
    },
    {
      key: "ay", header: "AY", sortable: true,
      accessor: (e) => getAYFromDates(e.period_start),
      render: (e) => <span className="text-[#475569] text-xs">{getAYFromDates(e.period_start)}</span>,
    },
    {
      key: "due_date", header: "Due Date", sortable: true,
      accessor: (e) => e.due_date,
      render: (e) => <span className="text-[#475569] text-xs">{formatDate(e.due_date)}</span>,
    },
    {
      key: "status", header: "Status", sortable: true,
      accessor: (e) => effectiveStatusOf(e),
      render: (e) => {
        const s = effectiveStatusOf(e);
        return (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[s] ?? "bg-[#F1F5F9] text-[#475569]"}`}>
            {STATUS_LABELS[s] ?? s}
          </span>
        );
      },
    },
    {
      key: "arn_number", header: "ARN / Ack No",
      accessor: (e) => e.arn_number ?? "",
      render: (e) => (
        <span className="text-xs font-mono text-[#64748B]">
          {e.arn_number ?? <span className="text-[#CBD5E1]">—</span>}
        </span>
      ),
    },
  ], [effectiveStatusOf]);

  const itrFilters: FilterDef<ITREntry>[] = useMemo(() => {
    const defs: FilterDef<ITREntry>[] = [];
    // Entity type — only when at least one row carries one.
    const entityOpts = Array.from(
      new Set(entries.map((e) => (e.clients?.entity_type ?? "").trim()).filter(Boolean)),
    ).sort();
    if (entityOpts.length > 0) {
      defs.push({
        key: "entity_type", label: "Entity", type: "select",
        accessor: (e) => (e.clients?.entity_type ?? "").replace(/_/g, " "),
        options: entityOpts.map((v) => ({ value: v.replace(/_/g, " "), label: v.replace(/_/g, " ") })),
      });
    }
    defs.push(
      {
        key: "ay", label: "AY / FY", type: "select",
        accessor: (e) => getAYFromDates(e.period_start),
        options: [...ASSESSMENT_YEARS].map((ay) => ({ value: ay, label: ay })),
      },
      {
        key: "itr_form", label: "ITR Form", type: "select",
        accessor: (e) => e.compliance_type,
        options: [...ITR_FORMS].map((f) => ({ value: f, label: f })),
      },
      {
        key: "status", label: "Status", type: "select",
        accessor: (e) => effectiveStatusOf(e),
        options: ["pending", "in_progress", "overdue", "filed"].map((s) => ({
          value: s, label: STATUS_LABELS[s] ?? s,
        })),
      },
    );
    return defs;
  }, [entries, effectiveStatusOf]);

  // Bulk actions — "Mark Filed" just opens the batch reference-entry modal;
  // the modal (not this action) performs the actual Supabase writes.
  const itrBulkActions: BulkAction<ITREntry>[] = [
    {
      id: "mark-filed",
      label: "Mark Filed",
      icon: <CheckCircle2 className="w-3.5 h-3.5" />,
      run: (selected) => {
        openBulkFiledModal(selected);
        return false;
      },
    },
  ];

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Income Tax</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            ITR Tracking — IT Act Section 139
          </p>
          {/* Sub-navigation */}
          <div className="flex gap-2 mt-3">
            <a href="/income-tax/capital-gains" className="text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 bg-blue-50 px-2.5 py-1 rounded-lg hover:bg-blue-100 transition-colors">
              Capital Gains Calculator
            </a>
            <a href="/income-tax/advance-tax" className="text-xs font-medium text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] px-2.5 py-1 rounded-lg hover:bg-[#F8FAFC] transition-colors">
              Advance Tax
            </a>
            <a href="/income-tax/notices" className="text-xs font-medium text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] px-2.5 py-1 rounded-lg hover:bg-[#F8FAFC] transition-colors">
              Notices
            </a>
            <a href="/income-tax/deductions" className="text-xs font-medium text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] px-2.5 py-1 rounded-lg hover:bg-[#F8FAFC] transition-colors">
              Deductions
            </a>
            <a href="/income-tax/tax-audit" className="text-xs font-medium text-[#64748B] hover:text-[#334155] border border-[#E2E8F0] px-2.5 py-1 rounded-lg hover:bg-[#F8FAFC] transition-colors">
              Tax Audit
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
          gradient="bg-gradient-to-br from-blue-600 to-blue-500"
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
      <div className="flex gap-1 border-b border-[#F1F5F9]">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-[#64748B] hover:text-[#334155]"
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
          {/* ITR Status Table — shared DataTable (search, sort, filters, pagination, export, prefs) */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-[#0F172A]">
                ITR Status — AY {currentAY}
              </h2>
              {overdue > 0 && (
                <span className="flex items-center gap-1 text-xs text-red-600 font-medium">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {overdue} overdue
                </span>
              )}
            </div>

            <div className="p-4">
              <DataTable
                data={entries}
                columns={itrColumns}
                filters={itrFilters}
                getRowId={(e) => e.id}
                loading={loading}
                error={error}
                onRetry={loadData}
                onRefresh={loadData}
                searchPlaceholder="Search by client name or PAN…"
                initialSort={{ key: "due_date", dir: "asc" }}
                bulkActions={itrBulkActions}
                exportFilename="itr-status"
                persistKey="income-tax.itr"
                emptyTitle="No ITR deadlines added yet"
                emptyDescription={
                  "Click “Add ITR Deadline” to manually track ITR filings for your clients. " +
                  "Each entry records the ITR form, assessment year, due date, and filing status."
                }
                emptyAction={
                  <button
                    onClick={() => setShowAddModal(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-lg hover:bg-blue-100 transition-colors mt-1"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    Add first ITR deadline
                  </button>
                }
                rowActions={(entry) =>
                  entry.filing_status !== "filed" ? (
                    <button
                      onClick={() => {
                        setFiledModal({ entry });
                        setFiledForm({ arn: "", filed_date: today });
                        setFiledError(null);
                      }}
                      className="text-xs px-2.5 py-1 bg-green-50 text-green-700 font-medium rounded hover:bg-green-100 transition-colors"
                    >
                      Mark Filed
                    </button>
                  ) : (
                    <span className="text-xs text-[#94A3B8]">
                      Filed {entry.filed_date ? formatDate(entry.filed_date) : ""}
                    </span>
                  )
                }
              />
            </div>
          </div>

          {/* ITR Form Guide — collapsible */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <button
              onClick={() => setShowGuide((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-4 text-sm font-semibold text-[#0F172A] hover:bg-[#F8FAFC]/50 transition-colors"
            >
              <span className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-[#94A3B8]" />
                ITR Form Guide
              </span>
              {showGuide ? (
                <ChevronUp className="w-4 h-4 text-[#94A3B8]" />
              ) : (
                <ChevronDown className="w-4 h-4 text-[#94A3B8]" />
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
                    className="flex items-start gap-3 p-3 bg-[#F8FAFC] rounded-lg"
                  >
                    <span className="text-xs font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded shrink-0">
                      {form}
                    </span>
                    <div>
                      <p className="text-xs font-medium text-[#334155]">{desc}</p>
                      <p className="text-xs text-[#94A3B8] mt-0.5">{tag}</p>
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
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-[#0F172A]">
                Advance Tax Installments — FY 2025-26
              </h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">
                IT Act Section 208 — applicable when tax liability ≥ ₹10,000
              </p>
            </div>
            <div className="divide-y divide-[#F8FAFC]">
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
                const isUpcoming = !isPast && (daysBetweenLocalISO(today, dueDate) ?? 999) <= 30;

                return (
                  <div
                    key={inst.label}
                    className="flex items-center gap-4 px-5 py-4"
                  >
                    <div className="flex items-center justify-center w-10 h-10 bg-blue-50 rounded-full shrink-0">
                      <IndianRupee className="w-5 h-5 text-blue-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-[#0F172A]">
                        {inst.label}
                      </p>
                      <p className="text-xs text-[#94A3B8] mt-0.5">
                        Due: {inst.due} · Cumulative {inst.cumulative} of estimated tax
                      </p>
                    </div>
                    <div className="text-right shrink-0">
                      <p className="text-sm font-semibold text-[#334155]">
                        {inst.percent}%
                      </p>
                      <p className="text-xs text-[#94A3B8] mt-0.5">of estimated tax</p>
                    </div>
                    <span
                      className={`text-xs px-2.5 py-1 rounded-full font-medium shrink-0 ${
                        isPast
                          ? "bg-[#F1F5F9] text-[#64748B]"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-[#F1F5F9]">
              <h3 className="text-base font-semibold text-[#0F172A]">
                Add ITR Deadline
              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-[#94A3B8] hover:text-[#475569] transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Client */}
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  Client <span className="text-red-500">*</span>
                </label>
                <select
                  value={addForm.client_id}
                  onChange={(e) => handleAddFormChange("client_id", e.target.value)}
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  ITR Form
                </label>
                <select
                  value={addForm.itr_form}
                  onChange={(e) =>
                    handleAddFormChange("itr_form", e.target.value)
                  }
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  Assessment Year
                </label>
                <select
                  value={addForm.assessment_year}
                  onChange={(e) =>
                    handleAddFormChange("assessment_year", e.target.value)
                  }
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  Due Date
                  <span className="ml-1 text-[#94A3B8] font-normal">
                    (31 Jul — non-audit · 31 Oct — audit, IT Act S.139)
                  </span>
                </label>
                <input
                  type="date"
                  value={addForm.due_date}
                  onChange={(e) =>
                    handleAddFormChange("due_date", e.target.value)
                  }
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {addError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {addError}
                </p>
              )}
            </div>

            <div className="px-6 py-4 border-t border-[#F1F5F9] flex gap-3 justify-end">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm font-medium text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-[#F8FAFC] transition-colors"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0F172A]/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-[#F1F5F9]">
              <h3 className="text-base font-semibold text-[#0F172A]">
                Mark ITR as Filed
              </h3>
              <button
                onClick={() => setFiledModal(null)}
                className="text-[#94A3B8] hover:text-[#475569] transition-colors"
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
                  This records an already-filed return. PracticeSync does NOT
                  auto-submit to the Income Tax Portal. Verify the
                  acknowledgement number before saving.
                </p>
              </div>

              <div className="text-sm text-[#334155] bg-[#F8FAFC] rounded-lg px-4 py-3">
                <p className="font-medium">
                  {filedModal.entry.clients?.client_name ?? "Client"}
                </p>
                <p className="text-xs text-[#94A3B8] mt-0.5 font-mono">
                  {filedModal.entry.clients?.pan ?? ""} ·{" "}
                  {filedModal.entry.compliance_type}
                </p>
              </div>

              {/* Acknowledgement Number */}
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
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
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm font-mono text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {/* Filing Date */}
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">
                  Date of Filing <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={filedForm.filed_date}
                  onChange={(e) =>
                    setFiledForm((p) => ({ ...p, filed_date: e.target.value }))
                  }
                  className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              {filedError && (
                <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">
                  {filedError}
                </p>
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

      {/* ================================================================== */}
      {/* MODAL: Bulk Mark as Filed (batch reference-entry)                  */}
      {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT                            */}
      {/* ================================================================== */}
      {bulkFiledSelection && (
        <BulkMarkFiledModal
          selected={bulkFiledSelection}
          onClose={() => setBulkFiledSelection(null)}
          onFiled={loadData}
        />
      )}
    </div>
  );
}
