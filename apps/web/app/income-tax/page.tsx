"use client";

/**
 * Income Tax / ITR Tracking Module
 *
 * THE DUE DATE IS NOT DECIDED HERE. Explanation 2 to IT Act §139(1) is applied
 * by apps/api — services/compliance_obligation_service.itr_due_date_for_client,
 * reached through GET /api/compliance/itr-due-date — and this page displays
 * what comes back, including whether the backend could settle it at all.
 *
 * It used to decide it, and got it wrong for every company:
 *
 *     const AUDIT_ENTITY_TYPES = new Set(["private_limited","public_limited", …]);
 *     isAuditCase(t) -> AUDIT_ENTITY_TYPES.has(t?.toLowerCase() ?? "")
 *
 * `clients.entity_type` is constrained by migration 001's CHECK to title case
 * WITH A SPACE — 'Private Limited' — and ClientFormModal.tsx writes exactly
 * that. toLowerCase() gives 'private limited', which is not 'private_limited',
 * so the lookup missed on precisely the two multi-word values, which are
 * precisely the companies. Every Private Limited and Public Limited client was
 * given 31 July where Explanation 2(a)(i) fixes 31 October unconditionally.
 * The same table also asserted that every LLP, partnership firm and trust is an
 * audit case, which no fact in this product establishes — and that direction
 * costs §234A interest, a §234F fee and the §80 carry-forward.
 *
 * CLAUDE.md: zero business logic in the frontend. A statutory rule kept in two
 * places drifts, and only one of the two is law.
 *
 * IT Act Section 208 — Advance tax installments.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 * All filing actions require explicit CA confirmation. Never auto-submit to Income Tax Portal.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
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
import { getFirmId } from "@/lib/data/getFirmId";
import { request, type ApiResp } from "@/lib/api";
import { getClients } from "@/lib/data/clients";
import { formatDate } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";
import { DataTable } from "@/components/ui/data-table";
import type { BulkAction, Column, FilterDef } from "@/lib/table/types";
import { todayLocalISO, daysBetweenLocalISO, currentFinancialYearLabel } from "@/lib/dateMath";
import { useToast } from "@/components/ui/use-toast";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { Callout, GapList } from "@/components/ui/callout";
import { YearPicker } from "@/components/ui/year-picker";

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

/**
 * THE YEAR ON THIS PAGE IS A FINANCIAL YEAR, and it was labelled "Assessment
 * Year" while behaving as one — which was the second half of the same bug.
 *
 * FY_PERIOD (below) maps "2025-26" to 1 Apr 2025 – 31 Mar 2026, which is the
 * FINANCIAL year, and that pair is what is written to compliance_calendar's
 * period_start / period_end. fyFromPeriodStart reads the same label back off a
 * stored row, and routers/compliance.py's seeder writes the same pair. Only the
 * deleted DUE_DATE_* tables read the label the other way, giving 31 July 2025
 * for a period that ends in March 2026 — a return quoted a year before the year
 * it reports on had finished. The backend computes from the period, so the date
 * and the period now agree; the label is corrected to match them.
 */
// FROM THE CLOCK, NOT A LITERAL. This list ended at a year that is now in the
// past, so the current financial year could not be selected at all — broken on
// 1 April with nothing saying so. `financialYearChoicesAround` is the one
// helper (lib/dates/periods.ts); see
// scripts/a-financial-year-choice-comes-from-the-clock.test.ts.
const FINANCIAL_YEARS = financialYearChoicesAround(null);
type FY = (typeof FINANCIAL_YEARS)[number];

const FY_PERIOD: Record<FY, { start: string; end: string }> = {
  "2024-25": { start: "2024-04-01", end: "2025-03-31" },
  "2025-26": { start: "2025-04-01", end: "2026-03-31" },
  "2026-27": { start: "2026-04-01", end: "2027-03-31" },
};

/** What the backend says about one client's ITR due date for one FY.
 *  `decided` false means `due_date` is the EARLIER of the two statutory dates
 *  and `statutory_gaps` names the question nobody has answered. */
type ItrDueDate = {
  due_date: string;
  is_audit: boolean;
  decided: boolean;
  basis: string;
  statutory_gaps: string[];
};

/** Derive the financial-year label (e.g. "2025-26") from a period's start. */
function fyFromPeriodStart(periodStart: string): string {
  const year = parseInt(periodStart.slice(0, 4));
  const month = parseInt(periodStart.slice(5, 7));
  const fyStart = month >= 4 ? year : year - 1;
  return `${fyStart}-${String(fyStart + 1).slice(-2)}`;
}

const STATUS_STYLES: Record<string, string> = {
  pending: "bg-state-attention-surface text-state-attention",
  overdue: "bg-state-problem-surface text-state-problem",
  filed: "bg-state-ready-surface text-state-ready",
  in_progress: "bg-state-working-surface text-state-working",
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

/** One §211 instalment, as GET /api/income-tax/financial-years returns it. */
type AdvanceTaxInstalment = {
  due_date: string;              // ISO, derived from the FY by the engine
  cumulative_percentage: number; // 15 / 45 / 75 / 100
  installment: string;
};

const ORDINALS = ["1st", "2nd", "3rd", "4th"];

// ---------------------------------------------------------------------------
// getFirmId helper (same pattern as compliance.ts)
// ---------------------------------------------------------------------------


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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 backdrop-blur-sm p-4">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg">
        <div className="flex items-center justify-between px-6 py-5 border-b border-ps-muted">
          <h3 className="text-base font-semibold text-ps-ink">
            Mark {pending.length} ITR Filing{pending.length === 1 ? "" : "s"} as Filed
          </h3>
          <button
            onClick={onClose}
            className="text-ps-hint hover:text-ps-label transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4">
          {/* Warning banner — CA Review */}
          <div className="bg-state-attention-surface border border-state-attention-border rounded-lg px-4 py-3">
            <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">
              CA Confirmation Required
            </p>
            <p className="text-xs text-state-attention mt-1">
              This records already-filed returns. PracticeSync does NOT
              auto-submit to the Income Tax Portal. Verify every
              acknowledgement number before saving.
            </p>
          </div>

          {/* Shared Filed Date — applied to every row below on submit */}
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1.5">
              Date of Filing <span className="text-red-500">*</span>
              <span className="ml-1 text-ps-hint font-normal">
                (applied to all rows below)
              </span>
            </label>
            <input
              type="date"
              value={filedDate}
              onChange={(e) => setFiledDate(e.target.value)}
              className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
            />
          </div>

          {/* Per-row Acknowledgement Number (ARN) entry */}
          <div>
            <label className="block text-xs font-medium text-ps-body mb-1.5">
              Acknowledgement Number (ARN) — one per filing{" "}
              <span className="text-red-500">*</span>
            </label>
            <div className="max-h-[45vh] overflow-y-auto rounded-lg border border-ps-muted">
              {pending.map((entry) => {
                const isDone = succeededIds.has(entry.id);
                const rowError = rowErrors[entry.id];
                return (
                  <div
                    key={entry.id}
                    className="flex items-center gap-3 px-4 py-3 border-b border-ps-muted last:border-0 bg-white"
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-ps-ink truncate">
                        {entry.clients?.client_name ?? "Client"}
                      </p>
                      <p className="text-xs text-ps-hint mt-0.5 font-mono">
                        {entry.compliance_type} · FY {fyFromPeriodStart(entry.period_start)}
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
                          className={`w-full border rounded-lg px-2.5 py-1.5 text-xs font-mono text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand ${
                            rowError ? "border-red-400" : "border-ps-border"
                          }`}
                        />
                        {rowError && (
                          <p className="text-3xs text-red-600 mt-1">{rowError}</p>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {error && <Callout tone="problem">{error}</Callout>}
        </div>

        <div className="px-6 py-4 border-t border-ps-muted flex gap-3 justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-ps-body bg-ps-muted rounded-lg hover:bg-ps-bg transition-colors"
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
    financial_year: "2025-26" as FY,
    due_date: "",
  });
  const [addLoading, setAddLoading] = useState(false);
  const [addError, setAddError] = useState<string | null>(null);
  // What the backend said about this client + FY. Null until a client is
  // chosen; the Due Date field stays empty until then, because there is no
  // honest date to pre-fill without knowing the assessee.
  const [dueDate, setDueDate] = useState<ItrDueDate | null>(null);
  const [dueDateLoading, setDueDateLoading] = useState(false);
  const [dueDateError, setDueDateError] = useState<string | null>(null);
  const dueDateSeq = useRef(0);

  // Mark as Filed modal
  const [filedModal, setFiledModal] = useState<{ entry: ITREntry } | null>(null);
  const [filedForm, setFiledForm] = useState({ arn: "", filed_date: "" });
  const [filedLoading, setFiledLoading] = useState(false);
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = addLoading || filedLoading;
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

  // §211's INSTALMENT DATES, FROM THE ENGINE (IT-33). This panel carried four
  // hardcoded strings — "15 Jun 2025" through "15 Mar 2026" — under a heading
  // that hardcoded "FY 2025-26", so on any date in the following financial
  // year the first panel of the module showed four elapsed instalments for the
  // wrong year. `compliance_engine.advance_tax_due_dates` has always derived
  // them from the FY; nothing called it from here.
  //
  // The FY comes with them, from the server: `current_fy` is IST
  // (core.ist_clock), and a browser in another zone flips the financial year
  // on 31 March.
  const [advanceTax, setAdvanceTax] = useState<AdvanceTaxInstalment[]>([]);
  const [advanceTaxFy, setAdvanceTaxFy] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await request("/api/income-tax/financial-years") as ApiResp<{
          current_fy?: string;
          current_fy_advance_tax?: AdvanceTaxInstalment[];
        }>;
        if (cancelled || !res.success || !res.data) return;
        setAdvanceTax(res.data.current_fy_advance_tax ?? []);
        setAdvanceTaxFy(res.data.current_fy ?? null);
      } catch {
        // The panel says the dates are unavailable rather than showing last
        // year's — which is the whole point of taking them off the literal.
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ---------------------------------------------------------------------------
  // Derived stats
  // ---------------------------------------------------------------------------

  const today = todayLocalISO();
  // FROM THE CLOCK, not a literal (IT-33). This was "2025-26" and it is the
  // heading over the ITR status card, so on 11 September 2026 the card counted
  // THIS year's entries under LAST year's name — a wrong label on the one
  // figure the page exists to show, wrong from 1 April with nothing to say so.
  const currentFY = currentFinancialYearLabel();

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

  /**
   * Ask apps/api for the due date. Explanation 2 to §139(1) turns on facts the
   * browser does not hold — whether the client is a company, whether its
   * accounts are required to be audited — and the answer comes back with
   * `decided` saying whether the backend could settle it, so an ASSUMED date is
   * shown as assumed rather than pre-filled as fact.
   */
  const resolveDueDate = useCallback(async (clientId: string, fy: FY) => {
    // Changing the client twice quickly starts two lookups, and the first can
    // land last. Only the newest answer is allowed to reach the form — a stale
    // reply would put one client's due date against another's name.
    const seq = ++dueDateSeq.current;
    if (!clientId) {
      setDueDate(null);
      setDueDateError(null);
      setDueDateLoading(false);
      return;
    }
    setDueDateLoading(true);
    setDueDateError(null);
    try {
      const res = await request<ApiResp<ItrDueDate>>(
        `/api/compliance/itr-due-date?client_id=${encodeURIComponent(clientId)}` +
          `&financial_year=${encodeURIComponent(fy)}`
      );
      if (seq !== dueDateSeq.current) return;
      setDueDate(res.data);
      setAddForm((prev) => ({ ...prev, due_date: res.data.due_date }));
    } catch (err) {
      if (seq !== dueDateSeq.current) return;
      // The field is left as the CA typed it and no date is invented. A guess
      // here is what this whole change removed.
      setDueDate(null);
      setDueDateError(
        err instanceof Error ? err.message : "Could not compute the due date"
      );
    } finally {
      if (seq === dueDateSeq.current) setDueDateLoading(false);
    }
  }, []);

  function handleAddFormChange(
    field: keyof typeof addForm,
    value: string
  ) {
    setAddForm((prev) => ({ ...prev, [field]: value }));
    if (field === "client_id" || field === "financial_year") {
      const clientId = field === "client_id" ? value : addForm.client_id;
      const fy = (field === "financial_year" ? value : addForm.financial_year) as FY;
      void resolveDueDate(clientId, fy);
    }
  }

  async function handleAddSubmit() {
    if (!addForm.client_id) {
      setAddError("Please select a client");
      return;
    }
    setAddLoading(true);
    setAddError(null);
    try {
      if (!addForm.due_date) {
        setAddError("No due date yet — pick a client so the due date can be computed.");
        return;
      }
      const firmId = await getFirmId();
      const fy = addForm.financial_year as FY;
      const period = FY_PERIOD[fy];

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
      setAddForm({ client_id: "", itr_form: "ITR-1", financial_year: "2025-26", due_date: "" });
      setDueDate(null);
      setDueDateError(null);
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
      render: (e) => <span className="font-medium text-ps-ink">{e.clients?.client_name ?? "—"}</span>,
    },
    {
      key: "pan", header: "PAN", searchable: true, sortable: true,
      accessor: (e) => e.clients?.pan ?? "",
      render: (e) => (
        <span className="font-mono text-xs text-ps-label bg-ps-bg px-1.5 py-0.5 rounded">
          {e.clients?.pan ?? "—"}
        </span>
      ),
    },
    {
      key: "entity_type", header: "Entity", sortable: true,
      accessor: (e) => (e.clients?.entity_type ?? "").replace(/_/g, " "),
      render: (e) => (
        <span className="text-ps-label text-xs capitalize">
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
      key: "fy", header: "FY", sortable: true,
      accessor: (e) => fyFromPeriodStart(e.period_start),
      render: (e) => <span className="text-ps-label text-xs">{fyFromPeriodStart(e.period_start)}</span>,
    },
    {
      key: "due_date", header: "Due Date", sortable: true,
      accessor: (e) => e.due_date,
      render: (e) => <span className="text-ps-label text-xs">{formatDate(e.due_date)}</span>,
    },
    {
      key: "status", header: "Status", sortable: true,
      accessor: (e) => effectiveStatusOf(e),
      render: (e) => {
        const s = effectiveStatusOf(e);
        return (
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[s] ?? "bg-ps-muted text-ps-label"}`}>
            {STATUS_LABELS[s] ?? s}
          </span>
        );
      },
    },
    {
      key: "arn_number", header: "ARN / Ack No",
      accessor: (e) => e.arn_number ?? "",
      render: (e) => (
        <span className="text-xs font-mono text-ps-label">
          {e.arn_number ?? <span className="text-ps-disabled">—</span>}
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
        key: "fy", label: "Financial Year", type: "select",
        accessor: (e) => fyFromPeriodStart(e.period_start),
        options: [...FINANCIAL_YEARS].map((fy) => ({ value: fy, label: fy })),
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
    <div className="p-6 max-w-ps-data mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ps-ink">Income Tax</h1>
          <p className="text-sm text-ps-label mt-0.5">
            ITR Tracking — IT Act Section 139
          </p>
          {/* Sub-navigation */}
          <div className="flex gap-2 mt-3">
            <a href="/income-tax/capital-gains" className="text-xs font-medium text-blue-600 hover:text-blue-800 border border-blue-200 bg-blue-50 px-2.5 py-1 rounded-lg hover:bg-blue-100 transition-colors">
              Capital Gains Calculator
            </a>
            <a href="/income-tax/advance-tax" className="text-xs font-medium text-ps-label hover:text-ps-body border border-ps-border px-2.5 py-1 rounded-lg hover:bg-ps-bg transition-colors">
              Advance Tax
            </a>
            <a href="/income-tax/notices" className="text-xs font-medium text-ps-label hover:text-ps-body border border-ps-border px-2.5 py-1 rounded-lg hover:bg-ps-bg transition-colors">
              Notices
            </a>
            <a href="/income-tax/deductions" className="text-xs font-medium text-ps-label hover:text-ps-body border border-ps-border px-2.5 py-1 rounded-lg hover:bg-ps-bg transition-colors">
              Deductions
            </a>
            <a href="/income-tax/tax-audit" className="text-xs font-medium text-ps-label hover:text-ps-body border border-ps-border px-2.5 py-1 rounded-lg hover:bg-ps-bg transition-colors">
              Tax Audit
            </a>
            {/* IT Act §32 — per BLOCK, which is a different system from the
                Schedule II charge in the fixed-asset register, and usually the
                largest single line in the book-to-tax bridge. */}
            <a href="/income-tax/section-32" className="text-xs font-medium text-ps-label hover:text-ps-body border border-ps-border px-2.5 py-1 rounded-lg hover:bg-ps-bg transition-colors">
              Depreciation §32
            </a>
            {/* …and the statement the two depreciation systems meet in. The
                bridge engine and its endpoint existed with no caller at all,
                so a CA could record §32 blocks and never see what they did to
                taxable income. */}
            <a href="/income-tax/book-to-tax" className="text-xs font-medium text-ps-label hover:text-ps-body border border-ps-border px-2.5 py-1 rounded-lg hover:bg-ps-bg transition-colors">
              Book-to-tax bridge
            </a>
          </div>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
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
      <div className="flex gap-1 border-b border-ps-muted">
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab
                ? "border-brand text-blue-700"
                : "border-transparent text-ps-label hover:text-ps-body"
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
          <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-ps-ink">
                ITR Status — FY {currentFY}
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
                    <span className="text-xs text-ps-hint">
                      Filed {entry.filed_date ? formatDate(entry.filed_date) : ""}
                    </span>
                  )
                }
              />
            </div>
          </div>

          {/* ITR Form Guide — collapsible */}
          <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
            <button
              onClick={() => setShowGuide((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-4 text-sm font-semibold text-ps-ink hover:bg-ps-bg/50 transition-colors"
            >
              <span className="flex items-center gap-2">
                <FileText className="w-4 h-4 text-ps-hint" />
                ITR Form Guide
              </span>
              {showGuide ? (
                <ChevronUp className="w-4 h-4 text-ps-hint" />
              ) : (
                <ChevronDown className="w-4 h-4 text-ps-hint" />
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
                    className="flex items-start gap-3 p-3 bg-ps-bg rounded-lg"
                  >
                    <span className="text-xs font-bold text-blue-700 bg-blue-100 px-2 py-0.5 rounded shrink-0">
                      {form}
                    </span>
                    <div>
                      <p className="text-xs font-medium text-ps-body">{desc}</p>
                      <p className="text-xs text-ps-hint mt-0.5">{tag}</p>
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
          <div className="bg-white rounded-xl border border-ps-muted overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-ps-ink">
                Advance Tax Installments{advanceTaxFy ? ` — FY ${advanceTaxFy}` : ""}
              </h2>
              <p className="text-xs text-ps-hint mt-0.5">
                IT Act Section 208 — applicable when tax liability ≥ ₹10,000
              </p>
            </div>
            <div className="divide-y divide-ps-bg">
              {advanceTax.length === 0 ? (
                <p className="px-5 py-6 text-sm text-ps-hint">
                  Instalment dates unavailable — the server could not be
                  reached. They are not shown from a stored list, because a
                  stored list is last year&apos;s.
                </p>
              ) : (
                advanceTax.map((inst, i) => {
                  const dueDate = inst.due_date;
                  const isPast = dueDate < today;
                  const isUpcoming =
                    !isPast && (daysBetweenLocalISO(today, dueDate) ?? 999) <= 30;
                  // §211's table is CUMULATIVE — 15/45/75/100. What each
                  // instalment adds is the step, so the fourth is 25%, not
                  // 100%. Derived here rather than carried, so the two figures
                  // cannot disagree.
                  const step =
                    inst.cumulative_percentage -
                    (i === 0 ? 0 : advanceTax[i - 1].cumulative_percentage);

                  return (
                    <div key={dueDate} className="flex items-center gap-4 px-5 py-4">
                      <div className="flex items-center justify-center w-10 h-10 bg-blue-50 rounded-full shrink-0">
                        <IndianRupee className="w-5 h-5 text-blue-600" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-ps-ink">
                          {ORDINALS[i] ?? `${i + 1}th`} Installment
                        </p>
                        <p className="text-xs text-ps-hint mt-0.5">
                          Due: {formatDate(dueDate)} · Cumulative{" "}
                          {inst.cumulative_percentage}% of estimated tax
                        </p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-sm font-semibold text-ps-body">{step}%</p>
                        <p className="text-xs text-ps-hint mt-0.5">of estimated tax</p>
                      </div>
                      <span
                        className={`text-xs px-2.5 py-1 rounded-full font-medium shrink-0 ${
                          isPast
                            ? "bg-ps-muted text-ps-label"
                            : isUpcoming
                            ? "bg-state-attention-surface text-state-attention"
                            : "bg-blue-50 text-blue-600"
                        }`}
                      >
                        {isPast ? "Due passed" : isUpcoming ? "Upcoming" : "Scheduled"}
                      </span>
                    </div>
                  );
                })
              )}
            </div>
          </div>

          <div className="bg-blue-50 border border-blue-200 rounded-xl px-5 py-4 flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-semibold text-blue-800 uppercase tracking-wide mb-1">
                Advance Tax Calculator
              </p>
              <p className="text-sm text-blue-700">
                Calculate exact advance tax instalments, apply the slab rates
                for the year, and compute Section 234A, 234B and 234C interest
                on late filing and shortfalls — per client.
              </p>
            </div>
            <Link
              href="/income-tax/advance-tax"
              className="shrink-0 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
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
            className="shrink-0 px-4 py-2 bg-brand text-white text-sm font-medium rounded-lg hover:bg-brand-dark transition-colors"
          >
            Open AIS Tool →
          </Link>
        </div>
        <div className="bg-state-attention-surface border border-state-attention-border rounded-xl px-5 py-4 flex items-center justify-between gap-4">
          <div>
            <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide mb-1">
              IT Notice Tracker
            </p>
            <p className="text-sm text-state-attention">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-ps-muted">
              <h3 className="text-base font-semibold text-ps-ink">
                Add ITR Deadline
              </h3>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-ps-hint hover:text-ps-label transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Client */}
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1.5">
                  Client <span className="text-red-500">*</span>
                </label>
                <select
                  value={addForm.client_id}
                  onChange={(e) => handleAddFormChange("client_id", e.target.value)}
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
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
                <label className="block text-xs font-medium text-ps-body mb-1.5">
                  ITR Form
                </label>
                <select
                  value={addForm.itr_form}
                  onChange={(e) =>
                    handleAddFormChange("itr_form", e.target.value)
                  }
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
                >
                  {ITR_FORMS.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </div>

              {/* Financial Year — the period the return reports on. The label
                  used to read "Assessment Year" while mapping to 1 Apr–31 Mar,
                  which is the FY; see FY_PERIOD. */}
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1.5">
                  Financial Year
                  <span className="ml-1 text-ps-hint font-normal">
                    (the year the return reports on)
                  </span>
                </label>
                <YearPicker value={addForm.financial_year}
                onChange={v => handleAddFormChange("financial_year", v)} />
              </div>

              {/* Due Date — computed by apps/api, editable */}
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1.5">
                  Due Date
                  <span className="ml-1 text-ps-hint font-normal">
                    (IT Act §139(1), Explanation 2 — computed for this client)
                  </span>
                </label>
                <input
                  type="date"
                  value={addForm.due_date}
                  onChange={(e) =>
                    handleAddFormChange("due_date", e.target.value)
                  }
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
                />

                {dueDateLoading && (
                  <p className="mt-1.5 text-xs text-ps-hint">
                    Computing the due date…
                  </p>
                )}

                {!dueDateLoading && !dueDate && !dueDateError && (
                  <p className="mt-1.5 text-xs text-ps-hint">
                    Pick a client — the due date depends on the assessee, not on
                    the year alone.
                  </p>
                )}

                {dueDateError && (
                  <p role="alert" className="mt-1.5 text-xs text-state-problem bg-state-problem-surface px-3 py-2 rounded-lg">
                    {dueDateError} — enter the date yourself and check it against
                    §139(1).
                  </p>
                )}

                {/* A DECIDED date says which clause it rests on. An ASSUMED one
                    says so first, and says what would settle it — the backend
                    returns the earlier of the two dates in that case, so the
                    CA is chased early rather than told a date that has passed. */}
                {dueDate && !dueDateLoading && (
                  dueDate.decided ? (
                    <p className="mt-1.5 text-xs text-ps-label">
                      {dueDate.basis}
                    </p>
                  ) : (
                    <GapList className="mt-1.5" gaps={dueDate.statutory_gaps}
                             tone="attention" title="Assumed — please confirm before saving." />
                  )
                )}
              </div>

              {addError && <Callout tone="problem">{addError}</Callout>}
            </div>

            <div className="px-6 py-4 border-t border-ps-muted flex gap-3 justify-end">
              <button
                onClick={() => setShowAddModal(false)}
                className="px-4 py-2 text-sm font-medium text-ps-body bg-ps-muted rounded-lg hover:bg-ps-bg transition-colors"
              >
                Cancel
              </button>
              {/* Also waits on the due-date lookup: saving mid-fetch would
                  either store a blank date or store the one left over from the
                  previously-selected client. */}
              <button
                onClick={handleAddSubmit}
                disabled={actionInFlight || dueDateLoading}
                className="px-4 py-2 text-sm font-medium text-white bg-brand rounded-lg hover:bg-brand-dark disabled:opacity-50 transition-colors"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-brand-dark/60 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="flex items-center justify-between px-6 py-5 border-b border-ps-muted">
              <h3 className="text-base font-semibold text-ps-ink">
                Mark ITR as Filed
              </h3>
              <button
                onClick={() => setFiledModal(null)}
                className="text-ps-hint hover:text-ps-label transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="px-6 py-5 space-y-4">
              {/* Warning banner — CA Review */}
              <div className="bg-state-attention-surface border border-state-attention-border rounded-lg px-4 py-3">
                <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">
                  CA Confirmation Required
                </p>
                <p className="text-xs text-state-attention mt-1">
                  This records an already-filed return. PracticeSync does NOT
                  auto-submit to the Income Tax Portal. Verify the
                  acknowledgement number before saving.
                </p>
              </div>

              <div className="text-sm text-ps-body bg-ps-bg rounded-lg px-4 py-3">
                <p className="font-medium">
                  {filedModal.entry.clients?.client_name ?? "Client"}
                </p>
                <p className="text-xs text-ps-hint mt-0.5 font-mono">
                  {filedModal.entry.clients?.pan ?? ""} ·{" "}
                  {filedModal.entry.compliance_type}
                </p>
              </div>

              {/* Acknowledgement Number */}
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1.5">
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
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm font-mono text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>

              {/* Filing Date */}
              <div>
                <label className="block text-xs font-medium text-ps-body mb-1.5">
                  Date of Filing <span className="text-red-500">*</span>
                </label>
                <input
                  type="date"
                  value={filedForm.filed_date}
                  onChange={(e) =>
                    setFiledForm((p) => ({ ...p, filed_date: e.target.value }))
                  }
                  className="w-full border border-ps-border rounded-lg px-3 py-2 text-sm text-ps-ink focus:outline-none focus:ring-2 focus:ring-brand"
                />
              </div>

              {filedError && <Callout tone="problem">{filedError}</Callout>}
            </div>

            <div className="px-6 py-4 border-t border-ps-muted flex gap-3 justify-end">
              <button
                onClick={() => setFiledModal(null)}
                className="px-4 py-2 text-sm font-medium text-ps-body bg-ps-muted rounded-lg hover:bg-ps-bg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleMarkFiled}
                disabled={actionInFlight}
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
