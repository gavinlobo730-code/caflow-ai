"use client";

/**
 * Attendance & Leave Management — PracticeSync AI
 * All leave/attendance data stored per employee per month/year.
 *
 * LOP (Loss of Pay) = Working Days - Days Present - CL - SL - EL, and the
 * SERVER is the authority on it (domain/payroll/attendance.py). This page no
 * longer writes public.attendance directly, for two reasons:
 *
 *   1. calcLOP below floors the remainder at zero, so 26 days present plus
 *      four days' casual leave in a 26-day month became "no loss of pay" and a
 *      full month's salary. The endpoint refuses that row instead; the floor
 *      survives here only to render the same number for a row that IS valid,
 *      and a negative remainder is now shown as the contradiction it is.
 *
 *   2. Save used to upsert `Object.values(attendance)` — the whole editor,
 *      which seeds a default 26/26 row for every employee that has none. One
 *      press therefore asserted a confident full month for the entire firm's
 *      roster, and payroll_slips.attendance_entered (migration 324) then read
 *      true for everybody. Only TOUCHED employees are sent now.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, Save, Upload, Download, Edit2, Check, X, Plus, Trash2, AlertTriangle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { api } from "@/lib/api";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { formatPaise } from "@/lib/services/formatting";
import type { Column } from "@/lib/table/types";

// ── Types ──────────────────────────────────────────────────────────────────

type Employee = {
  id: string;
  name: string;
  designation: string;
  /** The endpoint is client-scoped, as the rest of the app is; this page is
   *  the firm-wide rail, so a save fans out one request per client. */
  client_id: string;
};

type AttendanceRow = {
  employee_id: string;
  working_days: number;
  days_present: number;
  casual_leaves: number;
  sick_leaves: number;
  earned_leaves: number;
};

/** One extra amount paid in this month that is NOT a monthly rate.
 *
 *  The three booleans are three different Acts asking three different
 *  questions, and the browser must never guess any of them — the server
 *  proposes them (GET /one-time-earnings/defaults) and the row records what
 *  was saved:
 *
 *    pf_wages   EPF Act s.2(b) — bonus and commission are NOT basic wages;
 *               arrears of basic and DA are.
 *    esi_wages  ESI Act s.2(22) — additional remuneration paid at intervals
 *               NOT EXCEEDING TWO MONTHS. An interval test, not a name test.
 *    taxable    IT Act s.17(1)(iv). False only for a real reimbursement.
 *
 *  `amount_rs` is the typed string, kept as typed. It becomes paise through
 *  paiseFromRupeeInput, which REFUSES anything that is not an amount —
 *  parseFloat("1,25,000") is 1, and a CA types amounts that way.
 */
type EarningRow = {
  key: string;
  employee_id: string;
  kind: string;
  label: string;
  amount_rs: string;
  pf_wages: boolean;
  esi_wages: boolean;
  taxable: boolean;
  payment_interval_months: number | null;
  /** The sentence the server returns where a saved row disagrees with the
   *  statutory default. Shown, never enforced — a CA may know something the
   *  default cannot, but a disagreement in what the ECR is built from should
   *  not be silent. */
  divergence?: string | null;
};

const EARNING_KINDS = [
  { value: "incentive",     label: "Incentive" },
  { value: "bonus",         label: "Bonus" },
  { value: "ex_gratia",     label: "Ex-gratia" },
  { value: "arrears",       label: "Arrears" },
  { value: "commission",    label: "Commission" },
  { value: "reimbursement", label: "Reimbursement" },
  { value: "other",         label: "Other" },
];

type LeaveBalance = {
  id?: string;
  employee_id: string;
  year: number;
  casual_leave_balance: number;
  sick_leave_balance: number;
  earned_leave_balance: number;
  // Used — derived from attendance records
  casual_used?: number;
  sick_used?: number;
  earned_used?: number;
};

const ATTENDANCE_IMPORT_COLUMNS = [
  { key: "employee_name",  label: "Employee Name",   required: true,  hint: "Must match existing employee" },
  { key: "working_days",   label: "Working Days",    required: true,  hint: "e.g. 26" },
  { key: "days_present",   label: "Days Present",    required: true,  hint: "e.g. 24" },
  { key: "casual_leaves",  label: "Casual Leaves",   required: false, hint: "e.g. 1" },
  { key: "sick_leaves",    label: "Sick Leaves",     required: false, hint: "e.g. 0" },
  { key: "earned_leaves",  label: "Earned Leaves",   required: false, hint: "e.g. 1" },
];

type AttendanceExportRow = {
  name: string;
  designation: string;
  working_days: number;
  days_present: number;
  casual_leaves: number;
  sick_leaves: number;
  earned_leaves: number;
  lop: number;
  net_pay_days: number;
};

const ATTENDANCE_EXPORT_COLUMNS: Column<AttendanceExportRow>[] = [
  { key: "name",           header: "Employee",       accessor: (r) => r.name },
  { key: "designation",    header: "Designation",    accessor: (r) => r.designation },
  { key: "working_days",   header: "Working Days",   accessor: (r) => r.working_days },
  { key: "days_present",   header: "Days Present",   accessor: (r) => r.days_present },
  { key: "casual_leaves",  header: "CL",             accessor: (r) => r.casual_leaves },
  { key: "sick_leaves",    header: "SL",             accessor: (r) => r.sick_leaves },
  { key: "earned_leaves",  header: "EL",             accessor: (r) => r.earned_leaves },
  { key: "lop",            header: "LOP",            accessor: (r) => r.lop },
  { key: "net_pay_days",   header: "Net Pay Days",   accessor: (r) => r.net_pay_days },
];

// ── Helpers ────────────────────────────────────────────────────────────────

/** The remainder BEFORE the floor. Negative means the days entered add up to
 *  more than the month contains, which is a contradiction the CA has to
 *  resolve — the server refuses such a row. calcLOP's `Math.max(0, …)` used to
 *  hide it, and hiding it paid a full month. */
function rawLOP(row: AttendanceRow): number {
  return row.working_days - row.days_present - row.casual_leaves - row.sick_leaves - row.earned_leaves;
}

function calcLOP(row: AttendanceRow): number {
  return Math.max(0, rawLOP(row));
}

function calcNetPayDays(row: AttendanceRow): number {
  return Math.max(0, row.working_days - calcLOP(row));
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function AttendancePage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  // M17: a swallowed load failure previously rendered as an empty roster; the
  // leave-balance loader further fabricated default 12/12/15 allocations as if
  // real on a failed query. Track both failures and offer a retry instead.
  const [loadFailed, setLoadFailed] = useState(false);
  const [leaveLoadFailed, setLeaveLoadFailed] = useState(false);

  // Attendance tab state
  const today = new Date();
  const [attMonth, setAttMonth] = useState(today.getMonth() + 1); // 1-12
  const [attYear, setAttYear] = useState(today.getFullYear());
  const [attendance, setAttendance] = useState<Record<string, AttendanceRow>>({});
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [showImport, setShowImport] = useState(false);

  // Leave balance tab state
  const [leaveYear, setLeaveYear] = useState(today.getFullYear());
  const [leaveBalances, setLeaveBalances] = useState<LeaveBalance[]>([]);
  /** Employees who genuinely HAVE a row for this month. Not the same as the
   *  editor having values for them — the editor seeds a 26/26 default for
   *  everybody, which is exactly what used to get written. */
  const [entered, setEntered] = useState<Set<string>>(new Set());
  /** Employees the CA actually edited. Only these are sent. */
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [editingLeave, setEditingLeave] = useState<string | null>(null);
  const [editLeaveForm, setEditLeaveForm] = useState<Partial<LeaveBalance>>({});

  // ── One-time and variable earnings (migration 331) ───────────────────────
  // Kept per client, because that is the grain the endpoint works at and the
  // grain a payroll month has. The firm rail edits one client at a time here.
  const [earnClient, setEarnClient] = useState<string>("");
  /** client_id → client_name, so the picker names a client rather than a UUID. */
  const [clientNames, setClientNames] = useState<Record<string, string>>({});
  const [earnings, setEarnings] = useState<EarningRow[]>([]);
  const [earnLocked, setEarnLocked] = useState(false);
  const [earnSaving, setEarnSaving] = useState(false);
  const [earnMsg, setEarnMsg] = useState("");
  const [earnLoading, setEarnLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();

      // Load employees from payroll_employees table
      const empRes = await sb.from("payroll_employees").select("id, name, designation, client_id").eq("firm_id", fid);
      if (empRes.error) throw empRes.error;
      const emps: Employee[] = empRes.data ?? [];
      setEmployees(emps);

      // Names for the clients this firm actually runs payroll for. Firm-scoped
      // like every other read on this page — RLS is the control here, but the
      // filter is the primary one and omitting it is what CLAUDE.md forbids.
      const cliRes = await sb.from("clients").select("id, client_name").eq("firm_id", fid);
      setClientNames(Object.fromEntries(
        (cliRes.data ?? []).map((c: { id: string; client_name: string }) =>
          [c.id, c.client_name])));

      // Load attendance for selected month/year
      const attRes = await sb.from("attendance").select("*")
        .eq("firm_id", fid)
        .eq("month", attMonth)
        .eq("year", attYear);
      if (attRes.error) throw attRes.error;

      const attMap: Record<string, AttendanceRow> = {};
      // The editor still seeds a default so the inputs have something to show.
      // What changed is that the seed is no longer indistinguishable from a
      // saved row: `entered` records which employees actually have one, and
      // only `touched` rows are ever sent.
      const have = new Set<string>();
      for (const emp of emps) {
        const existing = (attRes.data ?? []).find((a: AttendanceRow & { employee_id: string }) => a.employee_id === emp.id);
        if (existing) have.add(emp.id);
        attMap[emp.id] = existing
          ? {
              employee_id: emp.id,
              working_days: existing.working_days,
              days_present: existing.days_present,
              casual_leaves: existing.casual_leaves,
              sick_leaves: existing.sick_leaves,
              earned_leaves: existing.earned_leaves,
            }
          : {
              employee_id: emp.id,
              working_days: 26,
              days_present: 26,
              casual_leaves: 0,
              sick_leaves: 0,
              earned_leaves: 0,
            };
      }
      setAttendance(attMap);
      setEntered(have);
      setTouched(new Set());
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [attMonth, attYear]);

  const loadLeaveBalances = useCallback(async () => {
    if (!firmId) return;
    setLeaveLoadFailed(false);
    const sb = getSupabaseClient();

    const [lbRes, attRes] = await Promise.all([
      sb.from("leave_balances").select("*").eq("firm_id", firmId).eq("year", leaveYear),
      sb.from("attendance").select("employee_id, casual_leaves, sick_leaves, earned_leaves")
        .eq("firm_id", firmId)
        .eq("year", leaveYear),
    ]);

    // A failed query must NOT fall through to the employees.map below, which
    // would fabricate default 12/12/15 allocations as if they were real records.
    if (lbRes.error || attRes.error) { setLeaveLoadFailed(true); setLeaveBalances([]); return; }

    // Aggregate used leaves per employee across all months
    const usedMap: Record<string, { casual: number; sick: number; earned: number }> = {};
    for (const row of attRes.data ?? []) {
      if (!usedMap[row.employee_id]) usedMap[row.employee_id] = { casual: 0, sick: 0, earned: 0 };
      usedMap[row.employee_id].casual += row.casual_leaves ?? 0;
      usedMap[row.employee_id].sick += row.sick_leaves ?? 0;
      usedMap[row.employee_id].earned += row.earned_leaves ?? 0;
    }

    const balances: LeaveBalance[] = employees.map(emp => {
      const existing = (lbRes.data ?? []).find((lb: { employee_id: string }) => lb.employee_id === emp.id);
      const used = usedMap[emp.id] ?? { casual: 0, sick: 0, earned: 0 };
      return {
        id: existing?.id,
        employee_id: emp.id,
        year: leaveYear,
        casual_leave_balance: existing?.casual_leave_balance ?? 12,
        sick_leave_balance: existing?.sick_leave_balance ?? 12,
        earned_leave_balance: existing?.earned_leave_balance ?? 15,
        casual_used: used.casual,
        sick_used: used.sick,
        earned_used: used.earned,
      };
    });
    setLeaveBalances(balances);
  }, [firmId, leaveYear, employees]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (firmId && employees.length > 0) loadLeaveBalances(); }, [loadLeaveBalances, firmId, employees]);

  // ── One-time and variable earnings ──────────────────────────────────────

  const loadEarnings = useCallback(async () => {
    if (!earnClient) { setEarnings([]); setEarnLocked(false); return; }
    const month = `${attYear}-${String(attMonth).padStart(2, "0")}`;
    setEarnLoading(true);
    try {
      const res = await api.payroll.getOneTimeEarnings(earnClient, month) as {
        data?: {
          locked?: boolean;
          rows?: Array<{
            id: string; employee_id: string; kind: string; label: string | null;
            amount_paise: number; pf_wages: boolean; esi_wages: boolean;
            taxable: boolean; payment_interval_months: number | null;
            divergence?: string | null;
          }>;
        };
      };
      setEarnLocked(Boolean(res?.data?.locked));
      setEarnings((res?.data?.rows ?? []).map(r => ({
        key: r.id,
        employee_id: r.employee_id,
        kind: r.kind,
        label: r.label ?? "",
        // Round-tripped through the same string form the CA types, so editing
        // an existing row and saving it back cannot change the amount.
        amount_rs: (r.amount_paise / 100).toFixed(2),
        pf_wages: r.pf_wages,
        esi_wages: r.esi_wages,
        taxable: r.taxable,
        payment_interval_months: r.payment_interval_months,
        divergence: r.divergence ?? null,
      })));
    } catch {
      setEarnMsg("Could not load this month's earnings.");
    } finally {
      setEarnLoading(false);
    }
  }, [earnClient, attMonth, attYear]);

  useEffect(() => { loadEarnings(); }, [loadEarnings]);

  /** Ask the server what the three Acts say about this kind and interval.
   *
   *  The browser does not decide any of it. "Is a quarterly incentive ESI
   *  wages" is ESI Act s.2(22) and the answer moves with the INTERVAL, which
   *  is exactly the kind of rule that drifts the moment it exists twice.
   */
  async function applyStatutoryDefaults(key: string, kind: string, interval: number | null) {
    try {
      const res = await api.payroll.oneTimeEarningDefaults(kind, interval) as {
        data?: { pf_wages: boolean; esi_wages: boolean; taxable: boolean; reason: string };
      };
      const d = res?.data;
      if (!d) return;
      setEarnings(prev => prev.map(r => r.key === key
        ? { ...r, pf_wages: d.pf_wages, esi_wages: d.esi_wages, taxable: d.taxable,
            divergence: null }
        : r));
    } catch {
      /* The row keeps whatever it had; the CA can still set the three by hand,
         and the server refuses a row that has not answered them. */
    }
  }

  function addEarning() {
    const emp = employees.find(e => e.client_id === earnClient);
    setEarnings(prev => [...prev, {
      key: `new-${prev.length}-${Date.now()}`,
      employee_id: emp?.id ?? "",
      kind: "bonus",
      label: "",
      amount_rs: "",
      // Seeded from the statute for a bonus paid once, then re-asked whenever
      // the kind or interval changes.
      pf_wages: false, esi_wages: false, taxable: true,
      payment_interval_months: null,
    }]);
  }

  function updateEarning(key: string, patch: Partial<EarningRow>) {
    setEarnings(prev => prev.map(r => (r.key === key ? { ...r, ...patch } : r)));
  }

  /** Save the month's earnings for this client.
   *
   *  Every employee currently shown is sent, including those whose rows were
   *  all removed — the endpoint REPLACES per employee, so an employee sent
   *  with no rows has theirs cleared. That is what makes "I deleted the
   *  duplicate bonus" expressible at all.
   *
   *  Amounts go through paiseFromRupeeInput, which returns null rather than
   *  coercing. A refused amount is named here rather than sent as NaN.
   */
  async function saveEarnings() {
    const month = `${attYear}-${String(attMonth).padStart(2, "0")}`;
    const rows: Array<Record<string, unknown>> = [];
    const bad: string[] = [];

    for (const r of earnings) {
      if (!r.employee_id) { bad.push("a row has no employee"); continue; }
      const paise = paiseFromRupeeInput(r.amount_rs);
      if (paise === null || paise === 0) {
        const who = employees.find(e => e.id === r.employee_id)?.name ?? "an employee";
        bad.push(`${who}: "${r.amount_rs}" is not an amount`);
        continue;
      }
      rows.push({
        employee_id: r.employee_id,
        kind: r.kind,
        label: r.label || null,
        amount_paise: paise,
        pf_wages: r.pf_wages,
        esi_wages: r.esi_wages,
        taxable: r.taxable,
        payment_interval_months: r.payment_interval_months,
      });
    }

    if (bad.length > 0) {
      setEarnMsg(`Not saved — ${bad.join("; ")}.`);
      return;
    }

    setEarnSaving(true);
    setEarnMsg("");
    try {
      const res = await api.payroll.saveOneTimeEarnings({
        client_id: earnClient, month, rows,
      }) as { success?: boolean; error?: string | null; detail?: string };
      if (res?.success === false) {
        setEarnMsg(res.error || res.detail || "Save refused.");
      } else {
        setEarnMsg(`Saved ${rows.length} earning(s) for ${month}.`);
        await loadEarnings();
      }
    } catch (e) {
      setEarnMsg(e instanceof Error ? e.message : "Save failed.");
    } finally {
      // In a finally, so a thrown save cannot leave the button spinning
      // forever — scripts/loading-flags.test.ts checks exactly this.
      setEarnSaving(false);
    }
  }

  function updateAtt(empId: string, field: keyof Omit<AttendanceRow, "employee_id">, value: number) {
    setAttendance(prev => ({
      ...prev,
      [empId]: { ...prev[empId], [field]: Math.max(0, value) },
    }));
    // Touching a row is what makes it savable. Without this the save would
    // have to guess, and the old guess was "everything".
    setTouched(prev => new Set(prev).add(empId));
  }

  /** Save ONLY the employees the CA touched, through the API.
   *
   *  What this replaces upserted `Object.values(attendance)` straight into
   *  PostgREST — the whole editor, including the 26/26 default seeded for
   *  every employee that had no row. One press wrote a confident full month
   *  for the entire firm, and payroll_slips.attendance_entered (migration 324)
   *  then read true for people nobody had looked at.
   *
   *  `lop_days` is deliberately NOT sent: the server derives it, and a sent
   *  value that contradicts the others is refused rather than corrected.
   *
   *  The endpoint is client-scoped, so a firm-wide edit fans out one request
   *  per client. Each is validated and refused whole, so a client whose rows
   *  do not add up is reported by name and nothing of that client's is
   *  written — the others still save, and the message says which failed.
   */
  async function saveAttendance() {
    const month = `${attYear}-${String(attMonth).padStart(2, "0")}`;
    const toSave = employees.filter(e => touched.has(e.id) && attendance[e.id]);
    if (toSave.length === 0) {
      setSaveMsg("Nothing to save — no attendance was changed.");
      setTimeout(() => setSaveMsg(""), 3000);
      return;
    }

    const byClient: Record<string, Employee[]> = {};
    for (const emp of toSave) {
      (byClient[emp.client_id] ??= []).push(emp);
    }

    setSaving(true);
    setSaveMsg("");
    let saved = 0;
    const failures: string[] = [];

    try {
    for (const [clientId, emps] of Object.entries(byClient)) {
      const rows = emps.map(emp => {
        const row = attendance[emp.id];
        return {
          employee_id: emp.id,
          working_days: row.working_days,
          days_present: row.days_present,
          casual_leaves: row.casual_leaves,
          sick_leaves: row.sick_leaves,
          earned_leaves: row.earned_leaves,
        };
      });
      try {
        const res = await api.payroll.saveAttendance({ client_id: clientId, month, rows }) as
          { success?: boolean; error?: string | null; detail?: string; data?: { saved?: number } };
        if (res?.success === false) {
          // The server's own sentence names the employee and the field. A
          // generic "couldn't save" would throw away the only useful part.
          failures.push(res.error || res.detail || "the request was refused");
        } else {
          saved += res?.data?.saved ?? rows.length;
        }
      } catch (e) {
        failures.push(e instanceof Error ? e.message : "the request failed");
      }
    }

    } finally {
      // In a finally, per scripts/loading-flags.test.ts: a flag left raised
      // leaves the Save button permanently disabled until the page reloads,
      // and here that would look exactly like a save in progress.
      setSaving(false);
    }

    setSaveMsg(failures.length
      ? `Error: ${failures.join(" ")}`
      : `Attendance saved for ${saved} employee${saved === 1 ? "" : "s"}.`);
    if (!failures.length) {
      await load();
      // A refusal has to stay on screen long enough to read and act on; a
      // success does not.
      setTimeout(() => setSaveMsg(""), 3000);
    }
  }

  async function saveLeaveBalance(lb: LeaveBalance) {
    if (!firmId) return;
    const sb = getSupabaseClient();
    await sb.from("leave_balances").upsert({
      firm_id: firmId,
      employee_id: lb.employee_id,
      year: lb.year,
      casual_leave_balance: lb.casual_leave_balance,
      sick_leave_balance: lb.sick_leave_balance,
      earned_leave_balance: lb.earned_leave_balance,
    }, { onConflict: "employee_id,year" });
    setEditingLeave(null);
    loadLeaveBalances();
  }

  const MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
  ];

  if (loading) {
    return <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading...</p></div>;
  }

  if (loadFailed) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center">
        <div className="text-center">
          <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load attendance data — the request failed or timed out.</p>
          <button onClick={() => load()} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      <div className="max-w-6xl mx-auto">
        <div className="mb-6 flex items-center gap-3">
          <Link href="/payroll">
            <Button variant="outline" size="sm" className="flex items-center gap-1.5">
              <ArrowLeft size={14} />Back to Payroll
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-[#0F172A]">Attendance &amp; Leave</h1>
            <p className="text-sm text-[#64748B] mt-0.5">Track monthly attendance and leave balances</p>
          </div>
        </div>

        <Tabs defaultValue="attendance">
          <TabsList className="mb-6">
            <TabsTrigger value="attendance">Attendance</TabsTrigger>
            <TabsTrigger value="leave-balance">Leave Balances</TabsTrigger>
            <TabsTrigger value="earnings">One-time Earnings</TabsTrigger>
          </TabsList>

          {/* ATTENDANCE TAB */}
          <TabsContent value="attendance">
            <Card className="mb-4">
              <CardContent className="pt-5">
                <div className="flex flex-wrap gap-4 items-end justify-between">
                  <div className="flex gap-4 items-end">
                    <div>
                      <label className="block text-xs font-medium text-[#334155] mb-1">Month</label>
                      <select
                        className="border rounded-lg px-3 py-2 text-sm"
                        value={attMonth}
                        onChange={e => setAttMonth(Number(e.target.value))}
                      >
                        {MONTHS.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-[#334155] mb-1">Year</label>
                      <input
                        type="number"
                        className="border rounded-lg px-3 py-2 text-sm w-24"
                        value={attYear}
                        onChange={e => setAttYear(Number(e.target.value))}
                        min={2020}
                        max={2099}
                      />
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => setShowImport(true)} className="flex items-center gap-1.5">
                      <Upload size={14} />Import CSV
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={employees.length === 0}
                      onClick={() => {
                        const exportRows: AttendanceExportRow[] = employees.map(emp => {
                          const row = attendance[emp.id] ?? {
                            employee_id: emp.id,
                            working_days: 26, days_present: 26,
                            casual_leaves: 0, sick_leaves: 0, earned_leaves: 0,
                          };
                          return {
                            name: emp.name,
                            designation: emp.designation,
                            working_days: row.working_days,
                            days_present: row.days_present,
                            casual_leaves: row.casual_leaves,
                            sick_leaves: row.sick_leaves,
                            earned_leaves: row.earned_leaves,
                            lop: calcLOP(row),
                            net_pay_days: calcNetPayDays(row),
                          };
                        });
                        downloadCsv(
                          `attendance-${attYear}-${String(attMonth).padStart(2, "0")}.csv`,
                          toCsv(exportRows, ATTENDANCE_EXPORT_COLUMNS),
                        );
                      }}
                      className="flex items-center gap-1.5"
                    >
                      <Download size={14} />Export
                    </Button>
                    <Button size="sm" onClick={saveAttendance} disabled={saving || touched.size === 0} className="flex items-center gap-1.5">
                      <Save size={14} />
                      {saving ? "Saving..."
                        : touched.size === 0 ? "Save Attendance"
                        : `Save ${touched.size} employee${touched.size === 1 ? "" : "s"}`}
                    </Button>
                  </div>
                </div>
                {saveMsg && (
                  <p className={`mt-3 text-sm font-medium ${saveMsg.startsWith("Error") ? "text-red-600" : "text-green-600"}`}>
                    {saveMsg}
                  </p>
                )}
              </CardContent>
            </Card>

            {employees.length === 0 ? (
              <Card><CardContent className="py-12 text-center text-[#94A3B8]">No employees found. Add employees in Payroll first.</CardContent></Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                          <th className="text-left py-3 px-4">Employee</th>
                          <th className="text-center py-3 px-3">Working Days</th>
                          <th className="text-center py-3 px-3">Days Present</th>
                          <th className="text-center py-3 px-3">CL</th>
                          <th className="text-center py-3 px-3">SL</th>
                          <th className="text-center py-3 px-3">EL</th>
                          <th className="text-center py-3 px-3">LOP (auto)</th>
                          <th className="text-center py-3 px-3">Net Pay Days</th>
                        </tr>
                      </thead>
                      <tbody>
                        {employees.map(emp => {
                          const row = attendance[emp.id] ?? {
                            employee_id: emp.id,
                            working_days: 26, days_present: 26,
                            casual_leaves: 0, sick_leaves: 0, earned_leaves: 0,
                          };
                          const remainder = rawLOP(row);
                          const lop = calcLOP(row);
                          const netDays = calcNetPayDays(row);
                          const isEntered = entered.has(emp.id);
                          const isTouched = touched.has(emp.id);
                          return (
                            <tr key={emp.id} className={`border-b hover:bg-[#F8FAFC] ${remainder < 0 ? "bg-red-50" : ""}`}>
                              <td className="py-3 px-4">
                                <div className="font-medium text-[#0F172A]">{emp.name}</div>
                                {emp.designation && <div className="text-xs text-[#64748B]">{emp.designation}</div>}
                                {/* The whole point of the fix, on the row. A seeded
                                    26/26 and a saved 26/26 used to look identical,
                                    and the old Save turned every one of the first
                                    kind into the second. */}
                                {!isEntered && !isTouched && (
                                  <div className="text-[10px] font-medium text-amber-600 mt-0.5">
                                    Not entered — the run will assume a full month
                                  </div>
                                )}
                                {isTouched && (
                                  <div className="text-[10px] font-medium text-blue-600 mt-0.5">
                                    Edited — will be saved
                                  </div>
                                )}
                              </td>
                              {(["working_days", "days_present", "casual_leaves", "sick_leaves", "earned_leaves"] as const).map(field => (
                                <td key={field} className="py-2 px-3 text-center">
                                  <input
                                    type="number"
                                    min={0}
                                    max={31}
                                    value={row[field]}
                                    onChange={e => updateAtt(emp.id, field, parseInt(e.target.value) || 0)}
                                    className="w-16 border rounded px-2 py-1 text-center text-sm"
                                  />
                                </td>
                              ))}
                              <td className="py-3 px-3 text-center">
                                {remainder < 0 ? (
                                  // Shown rather than floored. The server refuses
                                  // this row, and quietly displaying 0 would leave
                                  // the CA wondering why the save was rejected.
                                  <span className="text-[10px] font-medium text-red-700">
                                    {row.days_present + row.casual_leaves + row.sick_leaves + row.earned_leaves} days
                                    entered vs {row.working_days} working
                                  </span>
                                ) : (
                                  <span className={`font-semibold ${lop > 0 ? "text-red-600" : "text-[#94A3B8]"}`}>{lop}</span>
                                )}
                              </td>
                              <td className="py-3 px-3 text-center">
                                {remainder < 0
                                  ? <span className="text-[#94A3B8]">—</span>
                                  : <span className="font-semibold text-green-700">{netDays}</span>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </TabsContent>

          {/* LEAVE BALANCE TAB */}
          <TabsContent value="leave-balance">
            <Card className="mb-4">
              <CardContent className="pt-5">
                <div className="flex gap-4 items-end">
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Year</label>
                    <input
                      type="number"
                      className="border rounded-lg px-3 py-2 text-sm w-24"
                      value={leaveYear}
                      onChange={e => setLeaveYear(Number(e.target.value))}
                      min={2020}
                      max={2099}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-base">Leave Balances — {leaveYear}</CardTitle>
                <p className="text-xs text-[#64748B] mt-0.5">
                  Used leave is aggregated from attendance records. Edit the annual allocation per employee.
                </p>
              </CardHeader>
              <CardContent className="p-0">
                {leaveLoadFailed ? (
                  <div className="p-8 text-center">
                    <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load leave balances — the request failed or timed out.</p>
                    <button onClick={() => loadLeaveBalances()} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
                  </div>
                ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                        <th className="text-left py-3 px-4">Employee</th>
                        <th className="text-center py-3 px-3" colSpan={3}>Casual Leave</th>
                        <th className="text-center py-3 px-3" colSpan={3}>Sick Leave</th>
                        <th className="text-center py-3 px-3" colSpan={3}>Earned Leave</th>
                        <th className="py-3 px-4"></th>
                      </tr>
                      <tr className="border-b text-xs text-[#94A3B8]">
                        <th className="py-2 px-4"></th>
                        <th className="py-2 px-2 text-center font-normal">Allotted</th>
                        <th className="py-2 px-2 text-center font-normal">Used</th>
                        <th className="py-2 px-2 text-center font-normal">Rem.</th>
                        <th className="py-2 px-2 text-center font-normal">Allotted</th>
                        <th className="py-2 px-2 text-center font-normal">Used</th>
                        <th className="py-2 px-2 text-center font-normal">Rem.</th>
                        <th className="py-2 px-2 text-center font-normal">Allotted</th>
                        <th className="py-2 px-2 text-center font-normal">Used</th>
                        <th className="py-2 px-2 text-center font-normal">Rem.</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {leaveBalances.map(lb => {
                        const emp = employees.find(e => e.id === lb.employee_id);
                        const isEditing = editingLeave === lb.employee_id;
                        const form = isEditing ? editLeaveForm : lb;
                        const clRem = (form.casual_leave_balance ?? lb.casual_leave_balance) - (lb.casual_used ?? 0);
                        const slRem = (form.sick_leave_balance ?? lb.sick_leave_balance) - (lb.sick_used ?? 0);
                        const elRem = (form.earned_leave_balance ?? lb.earned_leave_balance) - (lb.earned_used ?? 0);
                        return (
                          <tr key={lb.employee_id} className="border-b hover:bg-[#F8FAFC]">
                            <td className="py-3 px-4 font-medium">{emp?.name ?? lb.employee_id}</td>
                            {/* CL */}
                            <td className="py-2 px-2 text-center">
                              {isEditing ? (
                                <input
                                  type="number" min={0}
                                  value={editLeaveForm.casual_leave_balance ?? lb.casual_leave_balance}
                                  onChange={e => setEditLeaveForm(f => ({ ...f, casual_leave_balance: parseInt(e.target.value) || 0 }))}
                                  className="w-14 border rounded px-2 py-1 text-center text-xs"
                                />
                              ) : <span>{lb.casual_leave_balance}</span>}
                            </td>
                            <td className="py-2 px-2 text-center text-[#64748B]">{lb.casual_used ?? 0}</td>
                            <td className="py-2 px-2 text-center">
                              <span className={clRem < 0 ? "text-red-600 font-semibold" : "text-green-700 font-semibold"}>{clRem}</span>
                            </td>
                            {/* SL */}
                            <td className="py-2 px-2 text-center">
                              {isEditing ? (
                                <input
                                  type="number" min={0}
                                  value={editLeaveForm.sick_leave_balance ?? lb.sick_leave_balance}
                                  onChange={e => setEditLeaveForm(f => ({ ...f, sick_leave_balance: parseInt(e.target.value) || 0 }))}
                                  className="w-14 border rounded px-2 py-1 text-center text-xs"
                                />
                              ) : <span>{lb.sick_leave_balance}</span>}
                            </td>
                            <td className="py-2 px-2 text-center text-[#64748B]">{lb.sick_used ?? 0}</td>
                            <td className="py-2 px-2 text-center">
                              <span className={slRem < 0 ? "text-red-600 font-semibold" : "text-green-700 font-semibold"}>{slRem}</span>
                            </td>
                            {/* EL */}
                            <td className="py-2 px-2 text-center">
                              {isEditing ? (
                                <input
                                  type="number" min={0}
                                  value={editLeaveForm.earned_leave_balance ?? lb.earned_leave_balance}
                                  onChange={e => setEditLeaveForm(f => ({ ...f, earned_leave_balance: parseInt(e.target.value) || 0 }))}
                                  className="w-14 border rounded px-2 py-1 text-center text-xs"
                                />
                              ) : <span>{lb.earned_leave_balance}</span>}
                            </td>
                            <td className="py-2 px-2 text-center text-[#64748B]">{lb.earned_used ?? 0}</td>
                            <td className="py-2 px-2 text-center">
                              <span className={elRem < 0 ? "text-red-600 font-semibold" : "text-green-700 font-semibold"}>{elRem}</span>
                            </td>
                            <td className="py-2 px-4">
                              {isEditing ? (
                                <div className="flex gap-1">
                                  <Button size="sm" onClick={() => saveLeaveBalance({ ...lb, ...editLeaveForm })} className="h-7 px-2">
                                    <Check size={13} />
                                  </Button>
                                  <Button size="sm" variant="outline" onClick={() => setEditingLeave(null)} className="h-7 px-2">
                                    <X size={13} />
                                  </Button>
                                </div>
                              ) : (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="h-7 px-2"
                                  onClick={() => {
                                    setEditingLeave(lb.employee_id);
                                    setEditLeaveForm({
                                      casual_leave_balance: lb.casual_leave_balance,
                                      sick_leave_balance: lb.sick_leave_balance,
                                      earned_leave_balance: lb.earned_leave_balance,
                                    });
                                  }}
                                >
                                  <Edit2 size={13} />
                                </Button>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>

          {/* ONE-TIME AND VARIABLE EARNINGS TAB (migration 331) */}
          <TabsContent value="earnings">
            <Card className="mb-4">
              <CardHeader>
                <CardTitle className="text-base">
                  One-time &amp; variable earnings — {MONTHS[attMonth - 1]} {attYear}
                </CardTitle>
                <p className="text-xs text-[#64748B] mt-1">
                  Incentive, bonus, ex-gratia, arrears. These are <strong>not</strong> prorated by
                  loss of pay — a decided amount is not a monthly rate. Each row states whether it
                  is PF wages (EPF Act s.2(b)), ESI wages (ESI Act s.2(22)) and salary
                  (IT Act s.17(1)); the answers differ between payments with the same name.
                </p>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-4 items-end mb-4">
                  <div>
                    <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                    <select
                      className="border rounded-lg px-3 py-2 text-sm min-w-[220px]"
                      value={earnClient}
                      onChange={e => setEarnClient(e.target.value)}
                    >
                      <option value="">Select a client…</option>
                      {Array.from(new Set(employees.map(e => e.client_id))).map(cid => (
                        <option key={cid} value={cid}>
                          {clientNames[cid] ?? cid}
                        </option>
                      ))}
                    </select>
                  </div>
                  <Button size="sm" variant="outline" onClick={addEarning}
                          disabled={!earnClient || earnLocked}
                          className="flex items-center gap-1.5">
                    <Plus size={14} />Add earning
                  </Button>
                  <Button size="sm" onClick={saveEarnings}
                          disabled={!earnClient || earnLocked || earnSaving}
                          className="flex items-center gap-1.5">
                    <Save size={14} />{earnSaving ? "Saving…" : "Save"}
                  </Button>
                  {earnMsg && <span className="text-sm text-[#334155]">{earnMsg}</span>}
                </div>

                {earnLocked && (
                  <div className="mb-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2
                                  text-sm text-amber-900 flex items-start gap-2">
                    <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                    <span>
                      This month&apos;s payroll is released. Its payslips already carry these
                      earnings, so changing them now would leave the inputs disagreeing with the
                      payslips, the ECR and the ledger. Reverse the run first.
                    </span>
                  </div>
                )}

                {!earnClient ? (
                  <p className="text-sm text-[#64748B]">Select a client to record earnings.</p>
                ) : earnLoading ? (
                  <p className="text-sm text-[#64748B]">Loading…</p>
                ) : earnings.length === 0 ? (
                  <p className="text-sm text-[#64748B]">
                    Nothing recorded for this month. That is a real answer, not a blank —
                    most months have none.
                  </p>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-xs text-[#64748B]">
                          <th className="py-2 pr-3">Employee</th>
                          <th className="py-2 pr-3">Kind</th>
                          <th className="py-2 pr-3">Description</th>
                          <th className="py-2 pr-3">Amount (₹)</th>
                          <th className="py-2 pr-3">Every (months)</th>
                          <th className="py-2 pr-3">PF wages</th>
                          <th className="py-2 pr-3">ESI wages</th>
                          <th className="py-2 pr-3">Salary</th>
                          <th className="py-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {earnings.map(r => (
                          <tr key={r.key} className="border-b align-top">
                            <td className="py-2 pr-3">
                              <select
                                className="border rounded px-2 py-1 text-sm"
                                value={r.employee_id}
                                disabled={earnLocked}
                                onChange={e => updateEarning(r.key, { employee_id: e.target.value })}
                              >
                                <option value="">—</option>
                                {employees.filter(e => e.client_id === earnClient).map(e => (
                                  <option key={e.id} value={e.id}>{e.name}</option>
                                ))}
                              </select>
                            </td>
                            <td className="py-2 pr-3">
                              <select
                                className="border rounded px-2 py-1 text-sm"
                                value={r.kind}
                                disabled={earnLocked}
                                onChange={e => {
                                  updateEarning(r.key, { kind: e.target.value });
                                  applyStatutoryDefaults(r.key, e.target.value,
                                                         r.payment_interval_months);
                                }}
                              >
                                {EARNING_KINDS.map(k => (
                                  <option key={k.value} value={k.value}>{k.label}</option>
                                ))}
                              </select>
                            </td>
                            <td className="py-2 pr-3">
                              <input
                                className="border rounded px-2 py-1 text-sm w-40"
                                value={r.label}
                                disabled={earnLocked}
                                placeholder="Diwali bonus"
                                onChange={e => updateEarning(r.key, { label: e.target.value })}
                              />
                            </td>
                            <td className="py-2 pr-3">
                              <input
                                className="border rounded px-2 py-1 text-sm w-28 text-right"
                                value={r.amount_rs}
                                disabled={earnLocked}
                                inputMode="decimal"
                                placeholder="50000"
                                onChange={e => updateEarning(r.key, { amount_rs: e.target.value })}
                              />
                              {/* Shown only once it parses. paiseFromRupeeInput
                                  returns null rather than coercing, so a half-typed
                                  amount simply shows nothing instead of a number
                                  that is not what was typed. */}
                              {paiseFromRupeeInput(r.amount_rs) !== null && (
                                <div className="text-[11px] text-[#64748B] text-right mt-0.5">
                                  {formatPaise(paiseFromRupeeInput(r.amount_rs) as number)}
                                </div>
                              )}
                            </td>
                            <td className="py-2 pr-3">
                              <input
                                type="number" min={1} max={12}
                                className="border rounded px-2 py-1 text-sm w-16"
                                value={r.payment_interval_months ?? ""}
                                disabled={earnLocked}
                                placeholder="—"
                                onChange={e => {
                                  const v = e.target.value === "" ? null : Number(e.target.value);
                                  updateEarning(r.key, { payment_interval_months: v });
                                  applyStatutoryDefaults(r.key, r.kind, v);
                                }}
                              />
                            </td>
                            {(["pf_wages", "esi_wages", "taxable"] as const).map(f => (
                              <td key={f} className="py-2 pr-3">
                                <input
                                  type="checkbox"
                                  checked={r[f]}
                                  disabled={earnLocked}
                                  onChange={e => updateEarning(r.key, { [f]: e.target.checked })}
                                />
                              </td>
                            ))}
                            <td className="py-2">
                              <button
                                className="text-[#64748B] hover:text-red-600 disabled:opacity-40"
                                disabled={earnLocked}
                                aria-label="Remove earning"
                                onClick={() => setEarnings(prev =>
                                  prev.filter(x => x.key !== r.key))}
                              >
                                <Trash2 size={14} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>

                    {earnings.some(r => r.divergence) && (
                      <div className="mt-4 space-y-1">
                        {earnings.filter(r => r.divergence).map(r => (
                          <p key={r.key} className="text-xs text-amber-800 flex items-start gap-1.5">
                            <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                            {r.divergence}
                          </p>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      </div>

      {showImport && firmId && (
        <CsvImportModal
          title="Import Attendance from CSV"
          columns={ATTENDANCE_IMPORT_COLUMNS}
          templateFilename="practicesync-attendance-template.xlsx"
          onClose={() => setShowImport(false)}
          onImport={async (rows: ImportRow[]) => {
            let imported = 0;
            const errors: string[] = [];
            for (const row of rows) {
              const emp = employees.find(e => e.name.toLowerCase() === row.employee_name?.toLowerCase());
              if (!emp) { errors.push(`Employee "${row.employee_name}" not found`); continue; }
              const empId = emp.id;
              // `|| 26` turned an unparseable working_days into a confident 26
              // and `|| 0` turned an unparseable leave count into no leave —
              // the same silent-default fault as the seeded row, one column
              // down. A number that is not a number rejects the ROW.
              const nums: Record<string, number> = {};
              let bad = false;
              for (const [field, fallback] of [["working_days", 26], ["days_present", 26],
                                               ["casual_leaves", 0], ["sick_leaves", 0],
                                               ["earned_leaves", 0]] as [string, number][]) {
                const raw = (row as Record<string, string | undefined>)[field];
                if (raw === undefined || raw === "") { nums[field] = fallback; continue; }
                const n = Number(raw.trim());
                if (!Number.isInteger(n) || n < 0) {
                  errors.push(`${emp.name}: ${field} "${raw}" is not a whole number of days`);
                  bad = true;
                  break;
                }
                nums[field] = n;
              }
              if (bad) continue;
              setAttendance(prev => ({
                ...prev,
                [empId]: {
                  employee_id: empId,
                  working_days: nums.working_days,
                  days_present: nums.days_present,
                  casual_leaves: nums.casual_leaves,
                  sick_leaves: nums.sick_leaves,
                  earned_leaves: nums.earned_leaves,
                },
              }));
              // An imported row is an entered row: it goes to the server on the
              // next Save, and nothing else would mark it.
              setTouched(prev => new Set(prev).add(empId));
              imported++;
            }
            return { imported, errors };
          }}
          validateRow={(row) => {
            const errs: string[] = [];
            if (!row.employee_name) errs.push("employee_name is required");
            if (row.working_days && isNaN(parseInt(row.working_days))) errs.push("working_days must be a number");
            if (row.days_present && isNaN(parseInt(row.days_present))) errs.push("days_present must be a number");
            return errs;
          }}
        />
      )}
    </div>
  );
}
