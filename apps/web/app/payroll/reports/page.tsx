"use client";

/**
 * Payroll Reports — PracticeSync AI
 *
 * IT Act Section 192 (TDS on Salary), EPF Act, ESI Act
 * All monetary values stored and computed in integer paise.
 * IT Act Section 234B/234C: interest on under-payment of advance tax / TDS.
 *
 * Reports:
 *  1. Payslip Summary   — one payroll run (a client, a month), and the
 *                        month-end pack: the salary register and every
 *                        payslip in one zip, both built by the server
 *  2. Year-to-Date      — month-by-month breakdown per employee (Form 16 prep)
 *  3. Cost to Company   — Gross + Employer PF + Employer ESI per employee
 *  4. TDS Projection    — month-by-month TDS plan to avoid 234B/234C interest
 *  5. Year End Summary  — annual totals for Form 24Q reconciliation
 *  6. Statutory Dues Calendar — all PF/ESI/PT/TDS due dates for a financial year
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft, Download, AlertCircle, AlertTriangle, CheckCircle, Clock,
  BarChart2, CalendarDays, TrendingUp, Users, IndianRupee, FileText,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { getSupabaseClient } from "@/lib/supabase/client";
import { useSlips } from "@/lib/payroll/useSlips";
import { employerCostOf } from "@/lib/payroll/types";
import type {
  Employee, EmployeeYearTotals, PayrollRun, PayrollSlip,
} from "@/lib/payroll/types";
import { getFirmId } from "@/lib/data/getFirmId";
import { toLocalISO, dueDateUrgency, fromLocalISO } from "@/lib/dateMath";
import { monthlyTdsPaiseNewRegime } from "@/lib/services/payrollTdsEstimate";
import { api, type PayrollDepositDueDates_FY } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────

type DueCategory = "PF" | "ESI" | "PT" | "TDS";
type DueStatus = "overdue" | "due-soon" | "upcoming";

type StatutoryDueRow = {
  id: string;
  label: string;
  description: string;
  dueDate: string; // display string
  dueDateObj: Date;
  portal: string;
  status: DueStatus;
  category: DueCategory;
};

// ── Paise helpers ─────────────────────────────────────────────────────────

/** Format integer paise as ₹X,XX,XXX.XX using Indian numbering */
function fmtPaise(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  return `₹${rupees.toLocaleString("en-IN")}.${p.toString().padStart(2, "0")}`;
}

function downloadCsv(content: string, filename: string): void {
  // BOM so Excel opens as UTF-8 instead of mangling ₹ into "â‚¹".
  const blob = new Blob(["\uFEFF" + content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Financial Year helpers ────────────────────────────────────────────────

/** Returns e.g. "2025-26" for a given start year */
function fyLabel(year: number): string {
  return `${year}-${String(year + 1).slice(2)}`;
}

/** Returns start year of a FY string like "2025-26" */
function fyStartYear(fy: string): number {
  return parseInt(fy.split("-")[0], 10);
}

/** Returns ordered months ["YYYY-MM", ...] for a financial year (Apr–Mar) */
function fyMonths(fy: string): string[] {
  const start = fyStartYear(fy);
  const months: string[] = [];
  for (let m = 4; m <= 12; m++) {
    months.push(`${start}-${String(m).padStart(2, "0")}`);
  }
  for (let m = 1; m <= 3; m++) {
    months.push(`${start + 1}-${String(m).padStart(2, "0")}`);
  }
  return months;
}

/** Detect the financial year string for a "YYYY-MM" month string */
function fyForMonth(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const start = m >= 4 ? y : y - 1;
  return fyLabel(start);
}

/** Current financial year */
function currentFy(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1; // 1-indexed
  return fyLabel(m >= 4 ? y : y - 1);
}

/** Month display name e.g. "Apr 2025" */
function monthLabel(yyyyMm: string): string {
  const [y, m] = yyyyMm.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-IN", { month: "short", year: "numeric" });
}

// ── Statutory Dues Calendar helpers ──────────────────────────────────────

// This was byte-identical to app/payroll/page.tsx's getDueDateStatus. The rule
// now lives once, in lib/dateMath.dueDateUrgency.
function dueDateStatus(due: Date, today: Date): DueStatus {
  return dueDateUrgency(toLocalISO(due), toLocalISO(today));
}

/**
 * The statutory due dates for one financial year.
 *
 * THE DATES THE ENGINE OWNS NOW COME FROM IT (PAY-19). The monthly deposits
 * (EPF para 38(1), ESI reg. 31, TDS Rule 30(2)) and the four quarterly TDS
 * return dates (Rule 31A(2)) are served by
 * GET /api/compliance/payroll-deposit-due-dates/fy, from
 * services/compliance_engine.py — the single source CLAUDE.md names for every
 * due date in this product.
 *
 * WHAT THIS FUNCTION USED TO DO AND NO LONGER DOES:
 *
 *   * it INVENTED a monthly Professional Tax row for every month of the year,
 *     dated the last day of the month and described as "Maharashtra: ₹200 if
 *     > ₹10,000" — for every client, whatever state its employees are in. The
 *     engine deliberately has no PT date: it is fixed by each state, there is
 *     no single rule, and this app models the slabs for four states of
 *     twenty-two. It is reported as a named gap instead, because a calendar
 *     with a silently missing row cannot be told from one whose client has no
 *     PT liability.
 *
 *   * it OMITTED the ESI deposit (the 15th) and the monthly salary TDS deposit
 *     (the 7th; 30 April for March) — the two that attract interest.
 *     §201(1A)(ii) runs 1.5% a month from the date of DEDUCTION.
 *
 * What is still built here is the HALF-YEARLY ESI RETURN (11 Nov / 11 May).
 * The engine does not model it, and whether it still exists could not be
 * settled from primary sources in this environment — so it is kept and marked
 * rather than deleted on unconfirmed evidence: removing a real deadline costs
 * a penalty, showing a stale one costs a phone call.
 */
function buildStatutoryCalendar(
  fy: string,
  today: Date,
  served: PayrollDepositDueDates_FY | null,
): StatutoryDueRow[] {
  const start = fyStartYear(fy);
  const rows: StatutoryDueRow[] = [];

  // ESI — half-yearly
  const esiDue1 = new Date(start, 10, 11); // Nov 11 — Apr-Sep period
  rows.push({
    id: `esi-${start}-h1`,
    label: `ESI Return — Apr–Sep ${start}`,
    description: "Half-yearly ESI return — ESIC Portal (ESI Act; employees ≤ ₹21,000/month)",
    dueDate: esiDue1.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }),
    dueDateObj: esiDue1,
    portal: "ESIC Portal",
    status: dueDateStatus(esiDue1, today),
    category: "ESI",
  });
  const esiDue2 = new Date(start + 1, 4, 11); // May 11 — Oct-Mar period
  rows.push({
    id: `esi-${start}-h2`,
    label: `ESI Return — Oct ${start}–Mar ${start + 1}`,
    description: "Half-yearly ESI return — ESIC Portal (ESI Act; employees ≤ ₹21,000/month)",
    dueDate: esiDue2.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }),
    dueDateObj: esiDue2,
    portal: "ESIC Portal",
    status: dueDateStatus(esiDue2, today),
    category: "ESI",
  });

  // ── Everything the engine owns ──────────────────────────────────────────
  for (const m of served?.months ?? []) {
    const periodLabel = new Date(m.year, m.month - 1, 1)
      .toLocaleString("en-IN", { month: "short", year: "numeric" });
    for (const d of m.deposits) {
      const due = fromLocalISO(d.due_date);
      if (!due) continue;
      rows.push({
        id: `deposit-${m.year}-${m.month}-${d.label}`,
        label: `${d.label} — ${periodLabel}`,
        description: `${d.statute} — ${d.authority}`,
        dueDate: due.toLocaleDateString("en-IN",
          { day: "numeric", month: "short", year: "numeric" }),
        dueDateObj: due,
        portal: d.authority,
        status: dueDateStatus(due, today),
        category: d.label.startsWith("EPF") ? "PF"
          : d.label.startsWith("ESI") ? "ESI" : "TDS",
      });
    }
  }
  for (const r of served?.returns ?? []) {
    const due = fromLocalISO(r.due_date);
    if (!due) continue;
    rows.push({
      id: `return-${r.quarter}`,
      label: `${r.label} — FY ${fy}`,
      description: `${r.statute} — quarterly TDS return on salary`,
      dueDate: due.toLocaleDateString("en-IN",
        { day: "numeric", month: "short", year: "numeric" }),
      dueDateObj: due,
      portal: "e-filing portal (incometax.gov.in)",
      status: dueDateStatus(due, today),
      category: "TDS",
    });
  }

  rows.sort((a, b) => a.dueDateObj.getTime() - b.dueDateObj.getTime());
  return rows;
}

// ── Status / Category Badges ──────────────────────────────────────────────

function StatusBadge({ status }: { status: DueStatus }) {
  if (status === "overdue") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">
        <AlertTriangle size={11} />Overdue
      </span>
    );
  }
  if (status === "due-soon") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
        <Clock size={11} />Due Soon
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-[#F1F5F9] text-[#475569]">
      <CheckCircle size={11} />Upcoming
    </span>
  );
}

function CategoryBadge({ category }: { category: DueCategory }) {
  const styles: Record<DueCategory, string> = {
    PF: "bg-blue-100 text-blue-700",
    ESI: "bg-purple-100 text-purple-700",
    PT: "bg-teal-100 text-teal-700",
    TDS: "bg-orange-100 text-orange-700",
  };
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ${styles[category]}`}>
      {category}
    </span>
  );
}

// ── 1. Payslip Summary ────────────────────────────────────────────────────

function PayslipSummaryTab({
  runs, employees, clientNames,
}: { runs: PayrollRun[]; employees: Employee[]; clientNames: Record<string, string> }) {
  // THE SELECTOR IS A RUN, NOT A MONTH. It used to be a month, and a firm that
  // runs payroll for two clients in August had both clients' employees in one
  // table under one TOTAL — a number that is nobody's payroll. A run is exactly
  // one client for exactly one month, which is also what a salary register and
  // a payslip pack are.
  const runOptions = [...runs].sort(
    (a, b) => b.month.localeCompare(a.month)
           || (clientNames[a.client_id] ?? "").localeCompare(clientNames[b.client_id] ?? ""),
  );
  const [selectedRunId, setSelectedRunId] = useState(runOptions[0]?.id ?? "");
  const [busy, setBusy] = useState<"" | "register" | "payslips">("");
  const [note, setNote] = useState<{ kind: "ok" | "warn" | "error"; text: string } | null>(null);

  const run = runs.find(r => r.id === selectedRunId);
  // ONE run's payslips, which is exactly the table below. This screen used to
  // hold every payslip in the firm and filter it here.
  const { slips: runSlips, loading: slipsLoading, error: slipsError } =
    useSlips(selectedRunId ? { run_id: selectedRunId } : null, employees, runs);

  const totals = runSlips.reduce(
    (acc, s) => ({
      gross: acc.gross + s.gross_paise,
      pf: acc.pf + s.pf_employee_paise,
      esi: acc.esi + s.esi_employee_paise,
      pt: acc.pt + s.pt_paise,
      tds: acc.tds + s.tds_paise,
      net: acc.net + s.net_paise,
    }),
    { gross: 0, pf: 0, esi: 0, pt: 0, tds: 0, net: 0 },
  );

  // Both files are built by the SERVER. The register used to be assembled here
  // out of `paise / 100`, from the eight columns this screen happened to load —
  // so it carried no attendance, no employer contributions and no one-time
  // earnings, and a CA reconciling it against the bank advice was reading a
  // different document from the one payroll actually paid.
  async function downloadRegister(): Promise<void> {
    if (!run) return;
    setBusy("register"); setNote(null);
    try {
      await api.payroll.downloadSalaryRegister(run.client_id, run.month);
    } catch (err) {
      setNote({ kind: "error", text: err instanceof Error ? err.message : "Could not build the register" });
    } finally {
      setBusy("");
    }
  }

  async function downloadPayslips(): Promise<void> {
    if (!run) return;
    setBusy("payslips"); setNote(null);
    try {
      const problems = await api.payroll.downloadRunPayslips(run.id, run.month);
      // A zip one file short is a trap nobody counts their way out of, so the
      // employees it could not render are said out loud rather than left to be
      // noticed.
      setNote(problems.length
        ? { kind: "warn", text: `The zip is missing ${problems.length} payslip${problems.length === 1 ? "" : "s"}: ${problems.join("; ")}` }
        : { kind: "ok", text: `${runSlips.length} payslips downloaded.` });
    } catch (err) {
      setNote({ kind: "error", text: err instanceof Error ? err.message : "Could not build the payslips" });
    } finally {
      setBusy("");
    }
  }

  return (
    <>
    <SliceState loading={slipsLoading} error={slipsError} />
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-row items-start justify-between flex-wrap gap-3">
          <div>
            <CardTitle className="text-base">Payslip Summary</CardTitle>
            <p className="text-xs text-[#64748B] mt-0.5">One client, one month — the month-end pack</p>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select
              className="border rounded-lg px-3 py-2 text-sm"
              value={selectedRunId}
              onChange={e => { setSelectedRunId(e.target.value); setNote(null); }}
            >
              {runOptions.length === 0 && <option value="">No payroll runs</option>}
              {runOptions.map(r => (
                <option key={r.id} value={r.id}>
                  {(clientNames[r.client_id] ?? "Client")} — {monthLabel(r.month)}
                </option>
              ))}
            </select>
            <Button
              size="sm" variant="outline" onClick={downloadRegister}
              disabled={!run || busy !== ""}
              className="flex items-center gap-1.5"
            >
              <Download size={13} />{busy === "register" ? "Building…" : "Salary register"}
            </Button>
            <Button
              size="sm" variant="outline" onClick={downloadPayslips}
              disabled={!run || runSlips.length === 0 || busy !== ""}
              className="flex items-center gap-1.5"
            >
              <FileText size={13} />{busy === "payslips" ? "Building…" : "Payslips (zip)"}
            </Button>
          </div>
        </div>
        {note && (
          <p className={`text-xs mt-3 ${
            note.kind === "error" ? "text-red-600"
            : note.kind === "warn" ? "text-amber-700"
            : "text-green-700"}`}>
            {note.text}
          </p>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {runSlips.length === 0 ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">
            {run ? `No payslips in the ${monthLabel(run.month)} run.` : "No payroll runs yet."}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Employee</th>
                  <th className="text-left py-3 px-4">PAN</th>
                  <th className="text-right py-3 px-4">Gross</th>
                  <th className="text-right py-3 px-4">PF</th>
                  <th className="text-right py-3 px-4">ESI</th>
                  <th className="text-right py-3 px-4">PT</th>
                  <th className="text-right py-3 px-4">TDS</th>
                  <th className="text-right py-3 px-4">Net Pay</th>
                </tr>
              </thead>
              <tbody>
                {runSlips.map(s => (
                  <tr key={s.id} className="border-b hover:bg-[#F8FAFC]">
                    <td className="py-3 px-4 font-medium">{s.employee?.name ?? "—"}</td>
                    <td className="py-3 px-4 font-mono text-xs text-[#64748B]">{s.employee?.pan || "—"}</td>
                    <td className="py-3 px-4 text-right font-mono">{fmtPaise(s.gross_paise)}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{fmtPaise(s.pf_employee_paise)}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{fmtPaise(s.esi_employee_paise)}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{fmtPaise(s.pt_paise)}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{fmtPaise(s.tds_paise)}</td>
                    <td className="py-3 px-4 text-right font-mono font-semibold text-green-700">{fmtPaise(s.net_paise)}</td>
                  </tr>
                ))}
                <tr className="bg-[#F8FAFC] font-semibold border-t-2 border-[#E2E8F0]">
                  <td className="py-3 px-4" colSpan={2}>Total ({runSlips.length} employees)</td>
                  <td className="py-3 px-4 text-right font-mono">{fmtPaise(totals.gross)}</td>
                  <td className="py-3 px-4 text-right font-mono text-red-700">{fmtPaise(totals.pf)}</td>
                  <td className="py-3 px-4 text-right font-mono text-red-700">{fmtPaise(totals.esi)}</td>
                  <td className="py-3 px-4 text-right font-mono text-red-700">{fmtPaise(totals.pt)}</td>
                  <td className="py-3 px-4 text-right font-mono text-red-700">{fmtPaise(totals.tds)}</td>
                  <td className="py-3 px-4 text-right font-mono text-green-800">{fmtPaise(totals.net)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
    </>
  );
}

// ── 2. Year-to-Date ───────────────────────────────────────────────────────

function YtdTab({ employees, runs, fyOptions }: {
  employees: Employee[]; runs: PayrollRun[]; fyOptions: string[];
}) {
  const [selectedFy, setSelectedFy] = useState(fyOptions[0] ?? currentFy());
  const [selectedEmpId, setSelectedEmpId] = useState(employees[0]?.id ?? "");

  const months = fyMonths(selectedFy);
  const emp = employees.find(e => e.id === selectedEmpId);
  // ONE employee, ONE year: twelve rows, twelve payslips.
  const { slips, loading: slipsLoading, error: slipsError } = useSlips(
    selectedEmpId ? { employee_id: selectedEmpId, financial_year: selectedFy } : null,
    employees, runs);

  type YtdRow = {
    month: string;
    gross: number;
    pf: number;
    esi: number;
    pt: number;
    tds: number;
    totalDeductions: number;
    net: number;
    ytdGross: number;
    ytdTds: number;
    ytdNet: number;
  };

  const rows: YtdRow[] = [];
  let ytdGross = 0;
  let ytdTds = 0;
  let ytdNet = 0;

  for (const month of months) {
    const slip = slips.find(s => s.employee_id === selectedEmpId && s.run?.month === month);
    const gross = slip?.gross_paise ?? 0;
    const pf = slip?.pf_employee_paise ?? 0;
    const esi = slip?.esi_employee_paise ?? 0;
    const pt = slip?.pt_paise ?? 0;
    const tds = slip?.tds_paise ?? 0;
    const net = slip?.net_paise ?? 0;
    ytdGross += gross;
    ytdTds += tds;
    ytdNet += net;
    rows.push({ month, gross, pf, esi, pt, tds, totalDeductions: pf + esi + pt + tds, net, ytdGross, ytdTds, ytdNet });
  }

  function exportCsv(): void {
    const header = "Month,Gross,PF,ESI,PT,TDS,Total Deductions,Net Pay,YTD Gross,YTD TDS,YTD Net";
    const csvRows = rows.map(r =>
      [
        `"${monthLabel(r.month)}"`,
        (r.gross / 100).toFixed(2),
        (r.pf / 100).toFixed(2),
        (r.esi / 100).toFixed(2),
        (r.pt / 100).toFixed(2),
        (r.tds / 100).toFixed(2),
        (r.totalDeductions / 100).toFixed(2),
        (r.net / 100).toFixed(2),
        (r.ytdGross / 100).toFixed(2),
        (r.ytdTds / 100).toFixed(2),
        (r.ytdNet / 100).toFixed(2),
      ].join(",")
    );
    downloadCsv([header, ...csvRows].join("\n"), `YTD_${emp?.name ?? "employee"}_FY${selectedFy}.csv`);
  }

  return (
    <>
    <SliceState loading={slipsLoading} error={slipsError} />
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div>
          <CardTitle className="text-base">Year-to-Date (YTD)</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">Month-by-month breakdown — used for Form 16 preparation (IT Act Section 203)</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <select
            className="border rounded-lg px-3 py-2 text-sm"
            value={selectedFy}
            onChange={e => setSelectedFy(e.target.value)}
          >
            {fyOptions.map(fy => <option key={fy} value={fy}>FY {fy}</option>)}
          </select>
          <select
            className="border rounded-lg px-3 py-2 text-sm"
            value={selectedEmpId}
            onChange={e => setSelectedEmpId(e.target.value)}
          >
            {employees.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <Button size="sm" variant="outline" onClick={exportCsv} className="flex items-center gap-1.5">
            <Download size={13} />Export CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {!emp ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">No employees found.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Month</th>
                  <th className="text-right py-3 px-4">Gross</th>
                  <th className="text-right py-3 px-4">PF</th>
                  <th className="text-right py-3 px-4">ESI</th>
                  <th className="text-right py-3 px-4">PT</th>
                  <th className="text-right py-3 px-4">TDS</th>
                  <th className="text-right py-3 px-4">Total Ded.</th>
                  <th className="text-right py-3 px-4">Net Pay</th>
                  <th className="text-right py-3 px-4 bg-blue-50">YTD Gross</th>
                  <th className="text-right py-3 px-4 bg-blue-50">YTD TDS</th>
                  <th className="text-right py-3 px-4 bg-blue-50">YTD Net</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr
                    key={r.month}
                    className={`border-b hover:bg-[#F8FAFC] ${r.gross === 0 ? "text-[#CBD5E1]" : ""}`}
                  >
                    <td className="py-3 px-4 font-medium text-[#334155]">{monthLabel(r.month)}</td>
                    <td className="py-3 px-4 text-right font-mono">{r.gross > 0 ? fmtPaise(r.gross) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{r.pf > 0 ? fmtPaise(r.pf) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{r.esi > 0 ? fmtPaise(r.esi) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{r.pt > 0 ? fmtPaise(r.pt) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-600">{r.tds > 0 ? fmtPaise(r.tds) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-700">{r.totalDeductions > 0 ? fmtPaise(r.totalDeductions) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono font-semibold text-green-700">{r.net > 0 ? fmtPaise(r.net) : "—"}</td>
                    <td className="py-3 px-4 text-right font-mono bg-blue-50/50 font-semibold text-[#1E293B]">{fmtPaise(r.ytdGross)}</td>
                    <td className="py-3 px-4 text-right font-mono bg-blue-50/50 text-red-700">{fmtPaise(r.ytdTds)}</td>
                    <td className="py-3 px-4 text-right font-mono bg-blue-50/50 text-green-700 font-semibold">{fmtPaise(r.ytdNet)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
    </>
  );
}

// ── 3. Cost to Company ────────────────────────────────────────────────────

type CtcRow = {
  slip: PayrollSlip;
  gross: number;
  employerPf: number;
  employerEsi: number;
  edli: number;
  admin: number;
  totalCtc: number;
};

/**
 * Cost to company, READ off the slip rather than re-derived (PAY-09).
 *
 * This used to compute employer PF as `min(basic x 12%, ₹1,800)` and employer
 * ESI as `gross x 3.25%` when this month's gross was under ₹21,000 — the four
 * exact drifts app/payroll/statutory/page.tsx was rewritten to remove, in a CSV
 * the CA hands to the client:
 *
 *   * the base is not the basic. The Code on Social Security s.2(88) wage base
 *     (migration 334) folds DA and the deemed-wages excess back in;
 *   * `eps_eligible` splits the employer's 12% between EPF and EPS, and
 *     GSR 609(E) excludes some employees from EPS altogether;
 *   * ESI's ceiling is fixed for the CONTRIBUTION PERIOD (Rule 50), not tested
 *     month by month — an employee who crosses ₹21,000 in October keeps
 *     contributing to 31 March;
 *   * EDLI and the admin charge are the employer's cost too (migration 329)
 *     and were simply absent.
 *
 * Measured on the finding: an employee on ₹10,000 basic + ₹8,000 special
 * allowance + ₹4,000 HRA has ₹1,800 employer PF plus ₹75 EDLI and ₹75 admin on
 * the stored slip, and this screen showed ₹1,200 — about ₹9,000 a year
 * understated, for an employee with no DA at all.
 */
function buildCtcRows(monthSlips: PayrollSlip[]): CtcRow[] {
  return monthSlips.map(s => {
    const cost = employerCostOf(s);
    return {
      slip: s,
      gross: s.gross_paise,
      employerPf: cost.pf,
      employerEsi: cost.esi,
      edli: cost.edli,
      admin: cost.admin,
      totalCtc: s.gross_paise + cost.total,
    };
  });
}

function CtcTab({ runs, employees }: { runs: PayrollRun[]; employees: Employee[] }) {
  const availableMonths = Array.from(new Set(runs.map(r => r.month))).sort().reverse();
  const [selectedMonth, setSelectedMonth] = useState(availableMonths[0] ?? "");

  // ONE month across the firm — one row per employee, which is the table.
  const { slips: monthSlips, loading: slipsLoading, error: slipsError } =
    useSlips(selectedMonth ? { month: selectedMonth } : null, employees, runs);
  const ctcRows = buildCtcRows(monthSlips);

  const totals = ctcRows.reduce(
    (acc, r) => ({
      gross: acc.gross + r.gross,
      employerPf: acc.employerPf + r.employerPf,
      employerEsi: acc.employerEsi + r.employerEsi,
      edli: acc.edli + r.edli,
      admin: acc.admin + r.admin,
      totalCtc: acc.totalCtc + r.totalCtc,
    }),
    { gross: 0, employerPf: 0, employerEsi: 0, edli: 0, admin: 0, totalCtc: 0 },
  );

  function exportCsv(): void {
    // The headers no longer quote a rate. "Employer PF (12%)" was a claim about
    // how the figure was reached, and it was not reached that way — the EPS
    // split and the s.2(88) base mean the stored figure is not 12% of anything
    // on this row. EDLI and the admin charge get their own columns because a
    // client reading a CTC needs to see what the employer actually bears.
    const header = "Employee,PAN,Gross Salary,Employer PF,Employer ESI,EDLI,PF Admin Charges,Total CTC";
    const rows = ctcRows.map(r => {
      const emp = r.slip.employee;
      return [
        `"${emp?.name ?? ""}"`, `"${emp?.pan ?? ""}"`,
        (r.gross / 100).toFixed(2),
        (r.employerPf / 100).toFixed(2),
        (r.employerEsi / 100).toFixed(2),
        (r.edli / 100).toFixed(2),
        (r.admin / 100).toFixed(2),
        (r.totalCtc / 100).toFixed(2),
      ].join(",");
    });
    const footer = [
      `"TOTAL"`, `""`,
      (totals.gross / 100).toFixed(2),
      (totals.employerPf / 100).toFixed(2),
      (totals.employerEsi / 100).toFixed(2),
      (totals.edli / 100).toFixed(2),
      (totals.admin / 100).toFixed(2),
      (totals.totalCtc / 100).toFixed(2),
    ].join(",");
    downloadCsv([header, ...rows, footer].join("\n"), `CTC_${selectedMonth}.csv`);
  }

  return (
    <>
    <SliceState loading={slipsLoading} error={slipsError} />
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div>
          <CardTitle className="text-base">Cost to Company (CTC)</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">Gross + Employer PF + ESI + EDLI + admin charges, as computed on each payslip — EPF Act, ESI Act, Code on Social Security s.2(88)</p>
          {/* THE ADMIN CHARGE IS FLOORED PER ESTABLISHMENT, NOT PER MEMBER.
              EPFO charges 0.5% of PF wages with a ₹500 monthly minimum for the
              whole establishment, and the floor is applied to the RUN
              (routers/payroll.py, `payroll_admin_charge`) — the slip carries
              only that member's share. So the column below totals to the sum of
              the shares, which is a LOWER BOUND on what is remitted: three
              members at ₹60 each owe ₹500, not ₹180. Said out loud rather than
              left for a CA to discover against the challan. */}
          <p className="text-[11px] text-amber-700 mt-1">
            Per-employee cost. The PF admin charge has a ₹500 per-establishment
            monthly floor, so the total below is the sum of member shares — the
            remittable challan figure is on the client&apos;s Statutory summary.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="border rounded-lg px-3 py-2 text-sm"
            value={selectedMonth}
            onChange={e => setSelectedMonth(e.target.value)}
          >
            {availableMonths.map(m => <option key={m} value={m}>{monthLabel(m)}</option>)}
          </select>
          <Button size="sm" variant="outline" onClick={exportCsv} disabled={ctcRows.length === 0} className="flex items-center gap-1.5">
            <Download size={13} />Export CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {ctcRows.length === 0 ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">No payroll data for {selectedMonth || "selected month"}.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Employee</th>
                  <th className="text-left py-3 px-4">PAN</th>
                  <th className="text-right py-3 px-4">Gross Salary</th>
                  <th className="text-right py-3 px-4">Employer PF</th>
                  <th className="text-right py-3 px-4">Employer ESI</th>
                  <th className="text-right py-3 px-4">EDLI</th>
                  <th className="text-right py-3 px-4">PF Admin</th>
                  <th className="text-right py-3 px-4 bg-blue-500/[0.08]">Total CTC</th>
                </tr>
              </thead>
              <tbody>
                {ctcRows.map(r => (
                  <tr key={r.slip.id} className="border-b hover:bg-[#F8FAFC]">
                    <td className="py-3 px-4 font-medium">{r.slip.employee?.name ?? "—"}</td>
                    <td className="py-3 px-4 font-mono text-xs text-[#64748B]">{r.slip.employee?.pan || "—"}</td>
                    <td className="py-3 px-4 text-right font-mono">{fmtPaise(r.gross)}</td>
                    <td className="py-3 px-4 text-right font-mono text-blue-600">+ {fmtPaise(r.employerPf)}</td>
                    <td className="py-3 px-4 text-right font-mono text-blue-600">+ {fmtPaise(r.employerEsi)}</td>
                    <td className="py-3 px-4 text-right font-mono text-blue-600">+ {fmtPaise(r.edli)}</td>
                    <td className="py-3 px-4 text-right font-mono text-blue-600">+ {fmtPaise(r.admin)}</td>
                    <td className="py-3 px-4 text-right font-mono font-bold text-blue-600 bg-blue-500/[0.08]/50">{fmtPaise(r.totalCtc)}</td>
                  </tr>
                ))}
                <tr className="bg-[#F8FAFC] font-semibold border-t-2 border-[#E2E8F0]">
                  <td className="py-3 px-4" colSpan={2}>Total ({ctcRows.length} employees)</td>
                  <td className="py-3 px-4 text-right font-mono">{fmtPaise(totals.gross)}</td>
                  <td className="py-3 px-4 text-right font-mono text-blue-700">+ {fmtPaise(totals.employerPf)}</td>
                  <td className="py-3 px-4 text-right font-mono text-blue-700">+ {fmtPaise(totals.employerEsi)}</td>
                  <td className="py-3 px-4 text-right font-mono text-blue-700">+ {fmtPaise(totals.edli)}</td>
                  <td className="py-3 px-4 text-right font-mono text-blue-700">+ {fmtPaise(totals.admin)}</td>
                  <td className="py-3 px-4 text-right font-mono text-indigo-800 bg-blue-500/[0.08]">{fmtPaise(totals.totalCtc)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
    </>
  );
}

// ── 4. TDS Projection ─────────────────────────────────────────────────────

function TdsProjectionTab({ employees, runs, fyOptions }: {
  employees: Employee[]; runs: PayrollRun[]; fyOptions: string[];
}) {
  const [selectedFy, setSelectedFy] = useState(fyOptions[0] ?? currentFy());
  const [selectedEmpId, setSelectedEmpId] = useState(employees[0]?.id ?? "");

  const months = fyMonths(selectedFy);
  const emp = employees.find(e => e.id === selectedEmpId);
  // ONE employee. The projection reads their most recent slip and the months
  // already paid this year; both are in this employee's own history.
  const { slips, loading: slipsLoading, error: slipsError } = useSlips(
    selectedEmpId ? { employee_id: selectedEmpId } : null, employees, runs);

  const recentSlip = slips
    .filter(s => s.employee_id === selectedEmpId)
    .sort((a, b) => (b.run?.month ?? "").localeCompare(a.run?.month ?? ""))
    .at(0);

  const estimatedMonthlyGross = recentSlip
    ? recentSlip.gross_paise
    : emp
    ? emp.basic_paise +
      Math.round((emp.basic_paise * emp.hra_percent) / 100) +
      Math.round((emp.basic_paise * emp.da_percent) / 100) +
      emp.other_allowances_paise
    : 0;

  const estimatedAnnualGross = estimatedMonthlyGross * 12;
  const estimatedAnnualTds = monthlyTdsPaiseNewRegime(estimatedAnnualGross) * 12;

  type ProjectionRow = {
    month: string;
    actualGross: number;
    actualTds: number;
    projectedTds: number;
    hasActual: boolean;
    cumulativeActual: number;
    cumulativeRemaining: number;
  };

  const projectionRows: ProjectionRow[] = [];
  let cumulativeActual = 0;

  const actualSlipsMap = new Map(
    slips
      .filter(s => s.employee_id === selectedEmpId)
      .map(s => [s.run?.month ?? "", s]),
  );

  for (const month of months) {
    const slip = actualSlipsMap.get(month);
    const hasActual = !!slip;
    const actualGross = slip?.gross_paise ?? 0;
    const actualTds = slip?.tds_paise ?? 0;
    const projectedTds = monthlyTdsPaiseNewRegime(estimatedAnnualGross);
    cumulativeActual += actualTds;
    const cumulativeRemaining = Math.max(0, estimatedAnnualTds - cumulativeActual);
    projectionRows.push({ month, actualGross, actualTds, projectedTds, hasActual, cumulativeActual, cumulativeRemaining });
  }

  const remainingMonths = projectionRows.filter(r => !r.hasActual).length;
  const suggestedMonthlyTds =
    remainingMonths > 0
      ? Math.round(Math.max(0, estimatedAnnualTds - cumulativeActual) / remainingMonths)
      : 0;

  return (
    <>
    <SliceState loading={slipsLoading} error={slipsError} />
    <div className="space-y-4">
      <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg">
        <AlertCircle size={15} className="text-amber-600 mt-0.5 flex-shrink-0" />
        <p className="text-xs text-amber-800">
          <strong>IT Act Section 234B/234C — CA Review Required.</strong> TDS projections are estimates
          based on current salary. Any change in salary, investments, or deductions will alter the
          tax liability. Review with the employee before each payroll run.
          Under-deduction may attract 234B/234C interest.
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div>
            <CardTitle className="text-base">TDS Projection</CardTitle>
            <p className="text-xs text-[#64748B] mt-0.5">Plan TDS deductions to avoid IT Act Section 234B/234C interest</p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <select
              className="border rounded-lg px-3 py-2 text-sm"
              value={selectedFy}
              onChange={e => setSelectedFy(e.target.value)}
            >
              {fyOptions.map(fy => <option key={fy} value={fy}>FY {fy}</option>)}
            </select>
            <select
              className="border rounded-lg px-3 py-2 text-sm"
              value={selectedEmpId}
              onChange={e => setSelectedEmpId(e.target.value)}
            >
              {employees.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
              <p className="text-xs text-[#64748B]">Est. Annual Gross</p>
              <p className="text-base font-bold text-[#0F172A] mt-0.5">{fmtPaise(estimatedAnnualGross)}</p>
            </div>
            <div className="p-3 bg-red-50 rounded-lg border border-red-100">
              <p className="text-xs text-[#64748B]">Est. Annual Tax</p>
              <p className="text-base font-bold text-red-700 mt-0.5">{fmtPaise(estimatedAnnualTds)}</p>
            </div>
            <div className="p-3 bg-green-50 rounded-lg border border-green-100">
              <p className="text-xs text-[#64748B]">TDS Deducted So Far</p>
              <p className="text-base font-bold text-green-700 mt-0.5">{fmtPaise(cumulativeActual)}</p>
            </div>
            <div className="p-3 bg-orange-50 rounded-lg border border-orange-100">
              <p className="text-xs text-[#64748B]">Suggested Monthly TDS</p>
              <p className="text-base font-bold text-orange-700 mt-0.5">
                {remainingMonths > 0 ? fmtPaise(suggestedMonthlyTds) : "—"}
              </p>
              {remainingMonths > 0 && <p className="text-[10px] text-orange-600">over {remainingMonths} remaining months</p>}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Month</th>
                  <th className="text-center py-3 px-4">Status</th>
                  <th className="text-right py-3 px-4">Actual Gross</th>
                  <th className="text-right py-3 px-4">Actual TDS</th>
                  <th className="text-right py-3 px-4">Projected TDS</th>
                  <th className="text-right py-3 px-4">Variance</th>
                  <th className="text-right py-3 px-4">Cumulative TDS</th>
                  <th className="text-right py-3 px-4">Remaining Tax</th>
                </tr>
              </thead>
              <tbody>
                {projectionRows.map(r => {
                  const variance = r.hasActual ? r.actualTds - r.projectedTds : 0;
                  const varianceColor = !r.hasActual ? "" : variance < 0 ? "text-red-600" : variance > 0 ? "text-green-600" : "text-[#64748B]";
                  return (
                    <tr
                      key={r.month}
                      className={`border-b hover:bg-[#F8FAFC] ${!r.hasActual ? "text-[#94A3B8]" : ""}`}
                    >
                      <td className="py-3 px-4 font-medium text-[#334155]">{monthLabel(r.month)}</td>
                      <td className="py-3 px-4 text-center">
                        {r.hasActual ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">
                            <CheckCircle size={10} />Processed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-[#F1F5F9] text-[#64748B]">
                            <Clock size={10} />Pending
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-4 text-right font-mono">{r.hasActual ? fmtPaise(r.actualGross) : "—"}</td>
                      <td className="py-3 px-4 text-right font-mono text-red-600">{r.hasActual ? fmtPaise(r.actualTds) : "—"}</td>
                      <td className="py-3 px-4 text-right font-mono text-[#64748B]">{fmtPaise(r.projectedTds)}</td>
                      <td className={`py-3 px-4 text-right font-mono ${varianceColor}`}>
                        {r.hasActual ? `${variance >= 0 ? "+" : ""}${fmtPaise(Math.abs(variance))}` : "—"}
                      </td>
                      <td className="py-3 px-4 text-right font-mono font-semibold text-[#334155]">{fmtPaise(r.cumulativeActual)}</td>
                      <td className="py-3 px-4 text-right font-mono text-orange-600">{fmtPaise(r.cumulativeRemaining)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-[#94A3B8] mt-3">
            * Projected TDS based on estimated annual income at current salary using FY 2025-26 new-regime slabs (IT Act Section 192).
            Rebate u/s 87A applied for taxable income ≤ ₹12,00,000 (Finance Act 2025). Consult employee&apos;s actual investment declarations for accuracy.
          </p>
        </CardContent>
      </Card>
    </div>
    </>
  );
}

// ── 5. Year End Summary ───────────────────────────────────────────────────

type EmpYearRow = {
  emp: Employee | undefined;
  gross: number;
  pf: number;
  esi: number;
  pt: number;
  tds: number;
  net: number;
};

// buildYearEndRows LIVED HERE. The grouping — one row per employee for a
// financial year — moved to services/payroll_report_service.employee_year_totals,
// because it was the one report whose ANSWER is smaller than the rows it read:
// a hundred employees over twelve months is 1,200 payslips to render a hundred
// lines, and that is proportional to payroll volume rather than to the table.

function YearEndSummaryTab({ fyOptions }: { fyOptions: string[] }) {
  const [selectedFy, setSelectedFy] = useState(fyOptions[0] ?? currentFy());

  // THE ONE TAB THAT HAS TO BE A SERVER AGGREGATE, and the distinction is
  // worth stating because the other four are the opposite case. A run's
  // payslips, a month's, one employee's twelve — each is a row set the same
  // size as the table it renders, so fetching the rows IS fetching the answer.
  // A firm's whole financial year is not: a hundred employees over twelve
  // months is 1,200 payslips to render a hundred rows.
  const [rows, setRows] = useState<EmployeeYearTotals[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedFy) { setRows([]); return; }
    let cancelled = false;
    setRowsLoading(true);
    setRowsError(null);
    api.payroll.yearEndSummary({ financial_year: selectedFy })
      .then(res => {
        if (cancelled) return;
        if (!res.success) throw new Error(res.error || "Could not load the year");
        setRows(res.data?.rows ?? []);
      })
      .catch(e => {
        if (cancelled) return;
        setRowsError(e instanceof Error ? e.message : "Could not load the year");
        setRows([]);
      })
      .finally(() => { if (!cancelled) setRowsLoading(false); });
    return () => { cancelled = true; };
  }, [selectedFy]);

  const empRows: EmpYearRow[] = rows.map(r => ({
    emp: r.employee ? ({ ...r.employee } as Employee) : undefined,
    gross: r.gross_paise, pf: r.pf_employee_paise, esi: r.esi_employee_paise,
    pt: r.pt_paise, tds: r.tds_paise, net: r.net_paise,
  }));

  const grandTotal = empRows.reduce(
    (acc, r) => ({
      gross: acc.gross + r.gross,
      pf: acc.pf + r.pf,
      esi: acc.esi + r.esi,
      pt: acc.pt + r.pt,
      tds: acc.tds + r.tds,
      net: acc.net + r.net,
    }),
    { gross: 0, pf: 0, esi: 0, pt: 0, tds: 0, net: 0 },
  );

  function exportCsv(): void {
    const header = "Employee,PAN,Total Gross Paid,Total PF Deducted,Total ESI Deducted,Total PT,Total TDS Deducted,Total Net Paid";
    const rows = empRows.map(r =>
      [
        `"${r.emp?.name ?? ""}"`, `"${r.emp?.pan ?? ""}"`,
        (r.gross / 100).toFixed(2),
        (r.pf / 100).toFixed(2),
        (r.esi / 100).toFixed(2),
        (r.pt / 100).toFixed(2),
        (r.tds / 100).toFixed(2),
        (r.net / 100).toFixed(2),
      ].join(",")
    );
    const footer = [
      `"GRAND TOTAL"`, `""`,
      (grandTotal.gross / 100).toFixed(2),
      (grandTotal.pf / 100).toFixed(2),
      (grandTotal.esi / 100).toFixed(2),
      (grandTotal.pt / 100).toFixed(2),
      (grandTotal.tds / 100).toFixed(2),
      (grandTotal.net / 100).toFixed(2),
    ].join(",");
    downloadCsv([header, ...rows, footer].join("\n"), `Year_End_Summary_FY_${selectedFy}.csv`);
  }

  return (
    <>
    <SliceState loading={rowsLoading} error={rowsError} />
    <Card>
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div>
          <CardTitle className="text-base">Year End Summary</CardTitle>
          <p className="text-xs text-[#64748B] mt-0.5">Annual totals per employee — for Form 24Q annual return &amp; employer reconciliation (IT Act Section 192)</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            className="border rounded-lg px-3 py-2 text-sm"
            value={selectedFy}
            onChange={e => setSelectedFy(e.target.value)}
          >
            {fyOptions.map(fy => <option key={fy} value={fy}>FY {fy}</option>)}
          </select>
          <Button size="sm" variant="outline" onClick={exportCsv} disabled={empRows.length === 0} className="flex items-center gap-1.5">
            <Download size={13} />Export CSV
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {empRows.length === 0 ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">No payroll data for FY {selectedFy}.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3 p-4 border-b">
              <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                <p className="text-xs text-[#64748B]">Total Gross Paid</p>
                <p className="text-lg font-bold text-[#0F172A] mt-0.5">{fmtPaise(grandTotal.gross)}</p>
              </div>
              <div className="p-3 bg-red-50 rounded-lg border border-red-100">
                <p className="text-xs text-[#64748B]">Total TDS Deducted</p>
                <p className="text-lg font-bold text-red-700 mt-0.5">{fmtPaise(grandTotal.tds)}</p>
              </div>
              <div className="p-3 bg-blue-50 rounded-lg border border-blue-100">
                <p className="text-xs text-[#64748B]">Total PF (Employee)</p>
                <p className="text-lg font-bold text-blue-700 mt-0.5">{fmtPaise(grandTotal.pf)}</p>
              </div>
              <div className="p-3 bg-purple-50 rounded-lg border border-purple-100">
                <p className="text-xs text-[#64748B]">Total ESI (Employee)</p>
                <p className="text-lg font-bold text-purple-700 mt-0.5">{fmtPaise(grandTotal.esi)}</p>
              </div>
              <div className="p-3 bg-teal-50 rounded-lg border border-teal-100">
                <p className="text-xs text-[#64748B]">Total Professional Tax</p>
                <p className="text-lg font-bold text-teal-700 mt-0.5">{fmtPaise(grandTotal.pt)}</p>
              </div>
              <div className="p-3 bg-green-50 rounded-lg border border-green-100">
                <p className="text-xs text-[#64748B]">Total Net Paid</p>
                <p className="text-lg font-bold text-green-700 mt-0.5">{fmtPaise(grandTotal.net)}</p>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                    <th className="text-left py-3 px-4">Employee</th>
                    <th className="text-left py-3 px-4">PAN</th>
                    <th className="text-right py-3 px-4">Total Gross</th>
                    <th className="text-right py-3 px-4">PF</th>
                    <th className="text-right py-3 px-4">ESI</th>
                    <th className="text-right py-3 px-4">PT</th>
                    <th className="text-right py-3 px-4">TDS (Sec 192)</th>
                    <th className="text-right py-3 px-4">Net Paid</th>
                  </tr>
                </thead>
                <tbody>
                  {empRows.map((r, idx) => (
                    <tr key={r.emp?.id ?? idx} className="border-b hover:bg-[#F8FAFC]">
                      <td className="py-3 px-4 font-medium">{r.emp?.name ?? "—"}</td>
                      <td className="py-3 px-4 font-mono text-xs text-[#64748B]">{r.emp?.pan || "—"}</td>
                      <td className="py-3 px-4 text-right font-mono">{fmtPaise(r.gross)}</td>
                      <td className="py-3 px-4 text-right font-mono text-blue-600">{fmtPaise(r.pf)}</td>
                      <td className="py-3 px-4 text-right font-mono text-purple-600">{fmtPaise(r.esi)}</td>
                      <td className="py-3 px-4 text-right font-mono text-teal-600">{fmtPaise(r.pt)}</td>
                      <td className="py-3 px-4 text-right font-mono text-red-600">{fmtPaise(r.tds)}</td>
                      <td className="py-3 px-4 text-right font-mono font-semibold text-green-700">{fmtPaise(r.net)}</td>
                    </tr>
                  ))}
                  <tr className="bg-[#F8FAFC] font-semibold border-t-2 border-[#E2E8F0]">
                    <td className="py-3 px-4" colSpan={2}>Grand Total ({empRows.length} employees)</td>
                    <td className="py-3 px-4 text-right font-mono">{fmtPaise(grandTotal.gross)}</td>
                    <td className="py-3 px-4 text-right font-mono text-blue-700">{fmtPaise(grandTotal.pf)}</td>
                    <td className="py-3 px-4 text-right font-mono text-purple-700">{fmtPaise(grandTotal.esi)}</td>
                    <td className="py-3 px-4 text-right font-mono text-teal-700">{fmtPaise(grandTotal.pt)}</td>
                    <td className="py-3 px-4 text-right font-mono text-red-700">{fmtPaise(grandTotal.tds)}</td>
                    <td className="py-3 px-4 text-right font-mono text-green-800">{fmtPaise(grandTotal.net)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </>
        )}
      </CardContent>
    </Card>
    </>
  );
}

// ── 6. Statutory Dues Calendar ────────────────────────────────────────────

type CategoryFilter = "ALL" | DueCategory;

function StatutoryDuesCalendarTab() {
  const today = new Date();
  const fyValue = currentFy();
  const start = fyStartYear(fyValue);
  const fyOptions = [fyLabel(start - 1), fyValue, fyLabel(start + 1)];

  const [selectedFy, setSelectedFy] = useState(fyValue);
  const [filterCategory, setFilterCategory] = useState<CategoryFilter>("ALL");

  // THE ENGINE'S DATES (PAY-19) — one call for the whole year. Until this,
  // every date on this calendar was computed in the browser, and three of them
  // were wrong: an invented monthly PT row, and the ESI and salary-TDS deposits
  // simply absent.
  const [servedDates, setServedDates] = useState<PayrollDepositDueDates_FY | null>(null);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.compliance.payrollDepositDueDatesForFy(selectedFy);
        if (!cancelled && res?.success && res.data) setServedDates(res.data);
      } catch {
        // The half-yearly ESI return is still built locally, so the calendar
        // shows what it can rather than nothing.
        if (!cancelled) setServedDates(null);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedFy]);

  const allRows = buildStatutoryCalendar(selectedFy, today, servedDates);
  const rows = filterCategory === "ALL" ? allRows : allRows.filter(r => r.category === filterCategory);

  const overdue = allRows.filter(r => r.status === "overdue").length;
  const dueSoon = allRows.filter(r => r.status === "due-soon").length;

  return (
    <div className="space-y-4">
      {(overdue > 0 || dueSoon > 0) && (
        <div className={`flex items-start gap-2 p-3 border rounded-lg ${overdue > 0 ? "bg-red-50 border-red-200" : "bg-amber-50 border-amber-200"}`}>
          <AlertTriangle size={15} className={`mt-0.5 flex-shrink-0 ${overdue > 0 ? "text-red-600" : "text-amber-600"}`} />
          <p className={`text-xs ${overdue > 0 ? "text-red-800" : "text-amber-800"}`}>
            {overdue > 0 && <><strong>{overdue} overdue filing(s)</strong> require immediate attention. </>}
            {dueSoon > 0 && <><strong>{dueSoon} filing(s)</strong> due within the next 7 days.</>}
          </p>
        </div>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between pb-3">
          <div>
            <CardTitle className="text-base">Statutory Dues Calendar</CardTitle>
            {/* The subtitle said "PT" and the calendar carried an INVENTED
                monthly PT row for every client (PAY-19). It no longer does —
                the date is per state and this app models four of twenty-two —
                and the gap below says so rather than the row going quiet. */}
            <p className="text-xs text-[#64748B] mt-0.5">EPF, ESI and salary-TDS deposits and the quarterly TDS returns — colour-coded by status</p>
            {(servedDates?.gaps ?? []).map(g => (
              <p key={g} className="text-xs text-amber-700 mt-1.5 max-w-2xl">{g}</p>
            ))}
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <select
              className="border rounded-lg px-3 py-2 text-sm"
              value={selectedFy}
              onChange={e => setSelectedFy(e.target.value)}
            >
              {fyOptions.map(fy => <option key={fy} value={fy}>FY {fy}</option>)}
            </select>
            <select
              className="border rounded-lg px-3 py-2 text-sm"
              value={filterCategory}
              onChange={e => setFilterCategory(e.target.value as CategoryFilter)}
            >
              <option value="ALL">All Categories</option>
              <option value="PF">PF Only</option>
              <option value="ESI">ESI Only</option>
              <option value="PT">PT Only</option>
              <option value="TDS">TDS Only</option>
            </select>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Filing</th>
                  <th className="text-left py-3 px-4">Category</th>
                  <th className="text-left py-3 px-4">Description</th>
                  <th className="text-left py-3 px-4">Portal</th>
                  <th className="text-right py-3 px-4">Due Date</th>
                  <th className="text-center py-3 px-4">Status</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => (
                  <tr
                    key={r.id}
                    className={`border-b ${
                      r.status === "overdue"
                        ? "bg-red-50 hover:bg-red-100"
                        : r.status === "due-soon"
                        ? "bg-amber-50 hover:bg-amber-100"
                        : "hover:bg-[#F8FAFC]"
                    }`}
                  >
                    <td className="py-3 px-4 font-medium text-[#0F172A]">{r.label}</td>
                    <td className="py-3 px-4"><CategoryBadge category={r.category} /></td>
                    <td className="py-3 px-4 text-xs text-[#64748B] max-w-xs">{r.description}</td>
                    <td className="py-3 px-4 text-xs text-[#64748B]">{r.portal}</td>
                    <td className="py-3 px-4 text-right font-mono text-xs font-medium">{r.dueDate}</td>
                    <td className="py-3 px-4 text-center"><StatusBadge status={r.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-[#94A3B8] p-4 border-t">
            Status computed from today&apos;s date. This calendar does not auto-track filed returns.
            Update your firm records after each submission. Due dates are general — verify state-specific PT deadlines.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

/** Whether the slice this tab asked for is still coming, or did not come.
 *
 *  Every tab renders one. A fetch that fails silently leaves an EMPTY TABLE
 *  under a heading naming a real employee and a real month, which reads as
 *  "this employee had no payroll" — a statement, and a false one. */
function SliceState({ loading, error }: { loading: boolean; error: string | null }) {
  if (error) {
    return (
      <p className="text-xs text-red-600 px-1 py-2">{error}</p>
    );
  }
  if (loading) {
    return <p className="text-xs text-[#94A3B8] px-1 py-2">Loading…</p>;
  }
  return null;
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function PayrollReportsPage() {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [fyOptions, setFyOptions] = useState<string[]>([]);
  const [clientNames, setClientNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const [empRes, runsRes, clientsRes] = await Promise.all([
        sb.from("payroll_employees").select("*").eq("firm_id", firmId),
        sb.from("payroll_runs").select("*").eq("firm_id", firmId).order("month", { ascending: false }),
        sb.from("clients").select("id, client_name").eq("firm_id", firmId),
      ]);
      if (empRes.error) throw new Error(empRes.error.message);
      if (runsRes.error) throw new Error(runsRes.error.message);
      // A missing client name is not worth failing the page for — the run is
      // still selectable, it just reads "Client — August 2026".
      setClientNames(Object.fromEntries(
        ((clientsRes.data ?? []) as { id: string; client_name: string }[])
          .map(c => [c.id, c.client_name]),
      ));

      const empList: Employee[] = empRes.data ?? [];
      const runList: PayrollRun[] = runsRes.data ?? [];
      setEmployees(empList);
      setRuns(runList);
      // The year picker's options come off the RUNS — one row per client-month
      // — where they used to be derived from every payslip in the firm. Same
      // answer, and it does not grow with the number of employees.
      setFyOptions(Array.from(new Set(runList.map(r => fyForMonth(r.month))))
        .sort().reverse());

      // EVERY PAYSLIP OF EVERY RUN used to be fetched here — every run's UUID
      // in one PostgREST in.() — before any tab had been chosen. Each tab now
      // asks for its own slice when it opens (lib/payroll/useSlips), and the
      // one tab whose answer is smaller than its rows asks the server to
      // aggregate. CLAUDE.md's reporting rule.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load payroll data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center">
        <p className="text-[#64748B]">Loading payroll reports...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] p-8">
        <div className="max-w-xl mx-auto">
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-start gap-3">
                <AlertCircle size={18} className="text-red-500 mt-0.5 flex-shrink-0" />
                <div>
                  <p className="font-medium text-[#0F172A]">Could not load payroll data</p>
                  <p className="text-sm text-[#475569] mt-1">{error}</p>
                  <p className="text-xs text-[#94A3B8] mt-2">
                    Make sure the payroll tables are installed. See the Payroll page for SQL setup instructions.
                  </p>
                </div>
              </div>
              <div className="mt-4">
                <Link href="/payroll">
                  <Button variant="outline" size="sm" className="flex items-center gap-1.5">
                    <ArrowLeft size={13} />Back to Payroll
                  </Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6 flex items-start justify-between flex-wrap gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Link href="/payroll">
                <Button variant="ghost" size="sm" className="flex items-center gap-1.5 text-[#64748B] hover:text-[#0F172A] -ml-2">
                  <ArrowLeft size={14} />Payroll
                </Button>
              </Link>
            </div>
            <h1 className="text-2xl font-bold text-[#0F172A] flex items-center gap-2">
              <BarChart2 size={22} className="text-blue-600" />
              Payroll Reports
            </h1>
            <p className="text-sm text-[#64748B] mt-0.5">
              IT Act Section 192 &middot; EPF Act &middot; ESI Act &middot; 234B/234C planning
            </p>
          </div>
        </div>

        <Tabs defaultValue="payslip-summary">
          <TabsList className="mb-6 flex-wrap h-auto gap-1">
            <TabsTrigger value="payslip-summary" className="flex items-center gap-1.5 text-xs">
              <FileText size={13} />Payslip Summary
            </TabsTrigger>
            <TabsTrigger value="ytd" className="flex items-center gap-1.5 text-xs">
              <TrendingUp size={13} />Year-to-Date
            </TabsTrigger>
            <TabsTrigger value="ctc" className="flex items-center gap-1.5 text-xs">
              <IndianRupee size={13} />Cost to Company
            </TabsTrigger>
            <TabsTrigger value="tds-projection" className="flex items-center gap-1.5 text-xs">
              <AlertCircle size={13} />TDS Projection
            </TabsTrigger>
            <TabsTrigger value="year-end" className="flex items-center gap-1.5 text-xs">
              <Users size={13} />Year End Summary
            </TabsTrigger>
            <TabsTrigger value="statutory-calendar" className="flex items-center gap-1.5 text-xs">
              <CalendarDays size={13} />Statutory Calendar
            </TabsTrigger>
          </TabsList>

          <TabsContent value="payslip-summary">
            <PayslipSummaryTab runs={runs} employees={employees} clientNames={clientNames} />
          </TabsContent>
          <TabsContent value="ytd">
            <YtdTab employees={employees} runs={runs} fyOptions={fyOptions} />
          </TabsContent>
          <TabsContent value="ctc">
            <CtcTab runs={runs} employees={employees} />
          </TabsContent>
          <TabsContent value="tds-projection">
            <TdsProjectionTab employees={employees} runs={runs} fyOptions={fyOptions} />
          </TabsContent>
          <TabsContent value="year-end">
            <YearEndSummaryTab fyOptions={fyOptions} />
          </TabsContent>
          <TabsContent value="statutory-calendar">
            <StatutoryDuesCalendarTab />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
