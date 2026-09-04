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
import { ArrowLeft, Save, Upload, Download, Edit2, Check, X } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { api } from "@/lib/api";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
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
