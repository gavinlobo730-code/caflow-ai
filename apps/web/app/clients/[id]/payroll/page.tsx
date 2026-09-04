"use client";

import { paiseFromRupeeInput, bpsFromPercentInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import {
  Users, Plus, Play, CheckCircle,
  FileText, TrendingUp, IndianRupee, Download, Upload,
  CreditCard, Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getFirmId } from "@/lib/data/getFirmId";
import { supabase, getSupabaseClient } from "@/lib/supabase/client";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { EMPLOYEE_IMPORT_COLUMNS } from "@/lib/imports/mappers";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";
import { api } from "@/lib/api";
import { DisburseModal } from "@/components/payroll/DisburseModal";
import { MetricCardSkeleton, StatementSkeleton, TransactionListSkeleton, TableSkeleton, CardGridSkeleton, Skeleton } from "@/components/ui/skeleton";
import FilingDemoWizard, { fetchFilingDemoCapabilities } from "@/components/FilingDemoWizard";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// R2.10 fix: this helper never attached the caller's auth token, so every
// call 401'd against a real (non-mock) backend — this whole page could never
// have worked in production. Mirrors lib/api/index.ts's request() helper.
async function apiFetch<T>(path: string, options?: RequestInit): Promise<{ data: T }> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${API}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options?.headers ?? {}),
    },
  });
  return res.json();
}

/** THE CLIENT MONTH, IN FOUR VERBS (docs/architecture/10-payroll.md).
 *
 *  The tabs used to name NOUNS — Employees, Salary Structures, Payroll Runs,
 *  Statutory, Reports — which describe the tables behind them rather than the
 *  job in front of them. A CA on the 3rd is not looking for "Payroll Runs";
 *  they are closing inputs, approving a register, releasing it, and handing the
 *  outputs over. Four verbs, in the order the month is actually done.
 *
 *  `setup` is deliberately NOT a verb and sits after them: the client's
 *  statutory registrations are a fact about the client, not a step in a month.
 */
type Tab = "inputs" | "register" | "release" | "outputs" | "setup";

/** The server refuses a shorter reason and so does migration 328's CHECK. Not a
 *  quality bar — a floor under "ok", "-" and ".", which is what a required
 *  free-text field collects when nothing asks for more. */
const OVERRIDE_REASON_MIN = 20;

function fmt(paise: number) {
  return "₹" + Math.floor(paise / 100).toLocaleString("en-IN");
}

function fmtMonth(m: string) {
  const [y, mo] = m.split("-");
  return new Date(parseInt(y), parseInt(mo) - 1).toLocaleString("en-IN", { month: "long", year: "numeric" });
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Employee {
  id: string;
  name: string;
  pan?: string;
  aadhaar_last4?: string;
  designation?: string;
  department?: string;
  basic_paise: number;
  hra_percent: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
  pt_applicable: boolean;
  status: string;
  joining_date?: string;
}

interface PayrollRun {
  id: string;
  month: string;
  // 'paid' since migration 225 (salary disbursement) — a paid run has had
  // its accrual AND disbursement journals posted and is just as terminal
  // as a finalized one.
  status: "draft" | "review" | "finalized" | "paid";
  headcount: number;
  total_gross_paise: number;
  total_net_paise: number;
  total_pf_paise: number;
  total_esi_paise: number;
  total_tds_paise: number;
  finalized_at?: string;
}

interface Slip {
  id: string;
  employee_id: string;
  gross_paise: number;
  net_paise: number;
  pf_employee_paise: number;
  esi_employee_paise: number;
  pt_paise: number;
  tds_paise: number;
  payroll_employees?: { name: string; pan?: string; designation?: string };
}

interface SalaryStructure {
  id: string;
  name: string;
  basic_percent: number;
  hra_percent: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
}

interface StatutoryData {
  /** The 12% either side. NOT what is remitted — see pf_challan_total_paise. */
  pf_total_paise: number;
  edli_paise?: number;
  pf_admin_paise?: number;
  /** Contributions + EDLI + admin charge: the figure on the EPFO challan. */
  pf_challan_total_paise?: number;
  esi_total_paise: number;
  pt_total_paise: number;
  tds_24q_paise: number;
  one_time_paise?: number;
  gross_paise?: number;
  status?: string;
}

interface SalaryRegister {
  slips: Slip[];
}

// ─── Dashboard Tab ────────────────────────────────────────────────────────────

function DashboardTab({ clientId }: { clientId: string }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  // M17: a failed Supabase read must not fall through to ₹0 stat cards /
  // "No payroll runs yet" — that is indistinguishable from a client that
  // genuinely has no payroll. Track the failure and surface a retry instead.
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    const db = getSupabaseClient();
    setLoading(true);
    setLoadFailed(false);
    // Direct Supabase reads (not api/payroll/runs + api/payroll/employees) —
    // these are plain client-scoped selects with no server-side computation,
    // so routing them through the FastAPI backend only adds a cold-start hit.
    // Mirrors routers/payroll.py's list_runs (order by month desc) and
    // list_employees (eq status=active, order by name).
    try {
      const [r, e] = await Promise.all([
        db.from("payroll_runs").select("*").eq("client_id", clientId).order("month", { ascending: false }),
        db.from("payroll_employees").select("*").eq("client_id", clientId).eq("status", "active").order("name"),
      ]);
      if (r.error || e.error) { setLoadFailed(true); return; }
      setRuns((r.data as PayrollRun[]) ?? []);
      setEmployees((e.data as Employee[]) ?? []);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return (
    <div className="p-6 space-y-3">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => <MetricCardSkeleton key={i} />)}
      </div>
      <StatementSkeleton sections={1} rowsPerSection={3} />
      <TransactionListSkeleton rows={6} />
    </div>
  );

  if (loadFailed) return (
    <div className="p-5">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
        <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load the payroll dashboard — the request failed or timed out.</p>
        <button onClick={() => load()} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
      </div>
    </div>
  );

  const latest = runs[0];

  return (
    <div className="p-5 space-y-5">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard icon={<Users size={14} className="text-blue-600" />} label="Active Employees" value={employees.length} />
        <StatCard icon={<IndianRupee size={14} className="text-emerald-600" />} label="Last Month Gross" value={latest ? fmt(latest.total_gross_paise) : "—"} />
        <StatCard icon={<CreditCard size={14} className="text-violet-600" />} label="Last Month Net" value={latest ? fmt(latest.total_net_paise) : "—"} />
        <StatCard icon={<FileText size={14} className="text-amber-600" />} label="Runs This Year" value={runs.length} />
      </div>

      {latest && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-[#94A3B8] mb-3">Latest Run — {fmtMonth(latest.month)}</p>
          <div className="grid grid-cols-3 gap-4">
            <SummaryRow label="Gross Payroll" value={fmt(latest.total_gross_paise)} />
            <SummaryRow label="PF (both sides)" value={fmt(latest.total_pf_paise)} />
            <SummaryRow label="TDS (24Q)" value={fmt(latest.total_tds_paise)} />
          </div>
          <div className="mt-3 flex items-center gap-2">
            <StatusBadge status={latest.status} />
            <span className="text-[11px] text-[#94A3B8]">{latest.headcount} employees</span>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-[#94A3B8] mb-3">Payroll History</p>
        {runs.length === 0 ? (
          <p className="text-sm text-[#94A3B8]">No payroll runs yet. Create your first run from the Payroll Runs tab.</p>
        ) : (
          <div className="space-y-2">
            {runs.slice(0, 6).map(r => (
              <div key={r.id} className="flex items-center justify-between py-2 border-b border-[#F1F5F9] last:border-0">
                <div>
                  <p className="text-sm font-medium text-[#1E293B]">{fmtMonth(r.month)}</p>
                  <p className="text-[11px] text-[#94A3B8]">{r.headcount} employees</p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-semibold text-[#1E293B]">{fmt(r.total_gross_paise)}</p>
                  <StatusBadge status={r.status} />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Employees Tab ────────────────────────────────────────────────────────────

const EMPLOYEE_EXPORT_COLUMNS: { key: string; header: string; accessor: (row: Employee) => unknown }[] = [
  { key: "name", header: "Name", accessor: (e) => e.name },
  { key: "pan", header: "PAN", accessor: (e) => e.pan ?? "" },
  { key: "designation", header: "Designation", accessor: (e) => e.designation ?? "" },
  { key: "department", header: "Department", accessor: (e) => e.department ?? "" },
  { key: "basic", header: "Basic Salary (₹)", accessor: (e) => (e.basic_paise / 100).toFixed(2) },
  { key: "hra_percent", header: "HRA %", accessor: (e) => e.hra_percent },
  { key: "pf_applicable", header: "PF Applicable", accessor: (e) => (e.pf_applicable ? "Yes" : "No") },
  { key: "esi_applicable", header: "ESI Applicable", accessor: (e) => (e.esi_applicable ? "Yes" : "No") },
  { key: "pt_applicable", header: "PT Applicable", accessor: (e) => (e.pt_applicable ? "Yes" : "No") },
  { key: "status", header: "Status", accessor: (e) => e.status },
];

function EmployeesTab({ clientId, firmId }: { clientId: string; firmId: string }) {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [form, setForm] = useState({ name: "", employee_code: "", date_of_birth: "", aadhaar: "", designation: "", department: "", basic_paise: "", hra_percent: "40", pf_applicable: true, esi_applicable: true, pt_applicable: false });
  const [aadhaarError, setAadhaarError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // M17: distinguish a failed roster fetch from a client with no employees.
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const res = await apiFetch<Employee[]>(`/api/payroll/employees?client_id=${clientId}`);
      if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); return; }
      setEmployees(res.data || []);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  /** The whole file, in ONE request, decided by the server.
   *
   *  This used to validate in the browser (`buildEmployees`) and POST
   *  /employees once per row. It accepted PART of a file — thirty-one of fifty
   *  employees landed and there was no list of the nineteen — and re-importing
   *  the corrected file made a second copy of the thirty-one, because nothing
   *  identified an employee across two imports.
   *
   *  Now: whole-file validation, whole-file refusal, and idempotent on
   *  `employee_code` (migration 333), so "fix the spreadsheet and upload it
   *  again" is actually the answer to a refusal.
   */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[]; skipped?: number; skippedDetail?: string[] }> {
    try {
      const res = await api.payroll.importEmployees(clientId, rows);
      const data = res?.data;
      await load();
      return {
        imported: data?.created ?? 0,
        errors: [],
        // Updates are not "skipped" — they are the idempotency working — but
        // this is the field the shared modal has for "something happened that
        // was not a create", and saying nothing would make a corrected
        // re-import of twenty people read as importing zero.
        skipped: data?.updated ?? 0,
        skippedDetail: (data?.updated ?? 0) > 0
          ? [`${data?.updated} existing employee(s) updated from their employee code`]
          : undefined,
      };
    } catch (err) {
      // NOTHING was written — the endpoint refuses the file as a whole. The
      // message carries the offending rows; lib/api's errorMessage keeps them.
      return { imported: 0, errors: [err instanceof Error ? err.message : "Import failed"] };
    }
  }

  async function addEmployee() {
    if (!form.name || !form.basic_paise) return;
    // Aadhaar: keep only the last 4 digits; never send the full number.
    const { aadhaar, ...rest } = form;
    const aadhaarDigits = aadhaar.replace(/\D/g, "");
    if (aadhaarDigits && aadhaarDigits.length !== 12) {
      setAadhaarError("Aadhaar must be 12 digits");
      return;
    }
    setAadhaarError(null);
    // basic_paise is the payload key; the field holds RUPEES. Read wrong, it is
    // the base for PF, HRA, gratuity and every month's withholding thereafter.
    const basic = paiseFromRupeeInput(form.basic_paise);
    if (basic === null) {
      setSaveError("Basic salary must be an amount in rupees, e.g. 50000 or "
                   + "50000.50 — without commas.");
      return;
    }
    // The percentage beside it was still parseFloat. HRA is a salary head:
    // it feeds the s.192 projection, s.10(13A) and Annexure II, so a comma
    // that reads as 1% where the CA meant 10% is money.
    const hraBps = bpsFromPercentInput(form.hra_percent);
    if (hraBps === null) {
      setSaveError("HRA % must be a plain percentage, e.g. 40 or 40.5 — without commas.");
      return;
    }
    setSaveError(null);
    setSaving(true);
    try {
      const res = await apiFetch("/api/payroll/employees", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          firm_id: firmId,
          ...rest,
          // Empty strings, not omissions: '' would hit migration 333's
          // not-blank CHECK on the code, and Postgres will not read '' as a
          // date. Both columns mean "unknown" when NULL.
          employee_code: rest.employee_code?.trim() || undefined,
          date_of_birth: rest.date_of_birth || undefined,
          aadhaar_last4: aadhaarDigits ? aadhaarDigits.slice(-4) : undefined,
          basic_paise: basic,
          hra_percent: hraBps / 100,
        }),
      }) as { success?: boolean; error?: string | null } | null;
      // task #229: this previously discarded the response and unconditionally
      // closed the modal + reset the form — a rejected employee (RBAC, bad PAN,
      // internal-client guardrail) looked identical to a successful add, and
      // the employee was silently absent from every subsequent payroll run.
      if (!res || res.success === false) {
        setSaveError(res?.error ?? "Could not add employee — the request failed.");
        return;
      }
      await load();
      setShowAdd(false);
      setForm({ name: "", employee_code: "", date_of_birth: "", aadhaar: "", designation: "", department: "", basic_paise: "", hra_percent: "40", pf_applicable: true, esi_applicable: true, pt_applicable: false });
    } catch {
      // Replaces a .catch(() => null) on the request alone, which left the
      // reload after it unguarded.
      setSaveError("Could not add employee — the request failed.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="p-6"><TableSkeleton cols={7} rows={5} /></div>;

  if (loadFailed) return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
        <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load employees — the request failed or timed out.</p>
        <button onClick={() => load()} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
      </div>
    </div>
  );

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-[#1E293B]">{employees.length} active employees</p>
        <div className="flex gap-2">
          <button onClick={() => setShowImport(true)} className="flex items-center gap-1.5 px-3 py-1.5 border border-[#E2E8F0] text-[#475569] text-[12px] font-medium rounded-lg hover:bg-[#F1F5F9] transition-colors">
            <Upload size={13} /> Import
          </button>
          <button onClick={() => downloadCsv("employees.csv", toCsv(employees, EMPLOYEE_EXPORT_COLUMNS))} disabled={employees.length === 0} className="flex items-center gap-1.5 px-3 py-1.5 border border-[#E2E8F0] text-[#475569] text-[12px] font-medium rounded-lg hover:bg-[#F1F5F9] transition-colors disabled:opacity-50">
            <Download size={13} /> Export
          </button>
          <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700 transition-colors">
            <Plus size={13} /> Add Employee
          </button>
        </div>
      </div>

      {showImport && (
        <CsvImportModal
          title="Import Employees"
          columns={EMPLOYEE_IMPORT_COLUMNS}
          templateFilename="employees-template.csv"
          onImport={handleImport}
          onClose={() => setShowImport(false)}
        />
      )}

      {showAdd && (
        <div className="bg-[#F8FAFC] rounded-xl border border-[#E2E8F0] p-4 space-y-3">
          <p className="text-[12px] font-semibold text-[#1E293B]">New Employee</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name *" value={form.name} onChange={v => setForm(f => ({...f, name: v}))} placeholder="Employee name" />
            <div>
              <Field label="Employee Code" value={form.employee_code} onChange={v => setForm(f => ({...f, employee_code: v}))} placeholder="e.g. EMP001" />
              <p className="text-[10px] text-[#94A3B8] mt-0.5">Your own code. A bulk import that repeats it updates this employee instead of adding a second one.</p>
            </div>
            <div>
              <Field label="Date of Birth" value={form.date_of_birth} onChange={v => setForm(f => ({...f, date_of_birth: v}))} placeholder="YYYY-MM-DD" type="date" />
              {/* Not demographics. Part III of the First Schedule widens the
                  OLD-regime nil band at 60 and again at 80, and without this
                  every employee is withheld on the general ladder. */}
              <p className="text-[10px] text-[#94A3B8] mt-0.5">Decides the old-regime slab at 60 and 80. Leave blank if unknown — the run will say so.</p>
            </div>
            <Field label="Designation" value={form.designation} onChange={v => setForm(f => ({...f, designation: v}))} placeholder="e.g. Manager" />
            <Field label="Department" value={form.department} onChange={v => setForm(f => ({...f, department: v}))} placeholder="e.g. Accounts" />
            <Field label="Basic Salary (₹/month) *" value={form.basic_paise} onChange={v => setForm(f => ({...f, basic_paise: v}))} placeholder="e.g. 25000" type="number" />
            <Field label="HRA %" value={form.hra_percent} onChange={v => setForm(f => ({...f, hra_percent: v}))} placeholder="40" type="number" />
            <div>
              <Field label="Aadhaar" value={form.aadhaar} onChange={v => setForm(f => ({...f, aadhaar: v}))} placeholder="12-digit Aadhaar" />
              <p className="text-[10px] text-[#94A3B8] mt-0.5">Only the last 4 digits are stored.</p>
              {aadhaarError && <p className="text-[10px] text-red-500 mt-0.5">{aadhaarError}</p>}
            </div>
          </div>
          <div className="flex items-center gap-4">
            {(["pf_applicable", "esi_applicable", "pt_applicable"] as const).map(k => (
              <label key={k} className="flex items-center gap-1.5 text-[12px] text-[#64748B] cursor-pointer">
                <input type="checkbox" checked={form[k]} onChange={e => setForm(f => ({...f, [k]: e.target.checked}))} className="rounded" />
                {k === "pf_applicable" ? "PF" : k === "esi_applicable" ? "ESI" : "PT"}
              </label>
            ))}
          </div>
          {saveError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{saveError}</p>}
          <div className="flex gap-2">
            <button onClick={addEmployee} disabled={saving} className="px-4 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700 disabled:opacity-50">
              {saving ? "Saving…" : "Add Employee"}
            </button>
            <button onClick={() => setShowAdd(false)} className="px-4 py-1.5 text-[12px] text-[#64748B] border border-[#E2E8F0] rounded-lg hover:bg-[#F1F5F9]">Cancel</button>
          </div>
        </div>
      )}

      <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[#F1F5F9] bg-[#F8FAFC]">
              {["Name", "Designation", "Department", "Basic", "PF", "ESI", "Status"].map(h => (
                <th key={h} className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-[#94A3B8]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#F1F5F9]">
            {employees.length === 0 ? (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-[#94A3B8] text-sm">No employees yet</td></tr>
            ) : employees.map(e => (
              <tr key={e.id} className="hover:bg-[#F8FAFC] transition-colors">
                <td className="px-4 py-3 font-medium text-[#1E293B]">{e.name}</td>
                <td className="px-4 py-3 text-[#64748B]">{e.designation || "—"}</td>
                <td className="px-4 py-3 text-[#64748B]">{e.department || "—"}</td>
                <td className="px-4 py-3 font-mono text-[#1E293B]">{fmt(e.basic_paise)}</td>
                <td className="px-4 py-3">{e.pf_applicable ? <span className="text-[10px] px-1.5 py-0.5 bg-green-50 text-green-600 rounded">Yes</span> : <span className="text-[10px] text-[#94A3B8]">No</span>}</td>
                <td className="px-4 py-3">{e.esi_applicable ? <span className="text-[10px] px-1.5 py-0.5 bg-green-50 text-green-600 rounded">Yes</span> : <span className="text-[10px] text-[#94A3B8]">No</span>}</td>
                <td className="px-4 py-3"><span className={cn("text-[10px] px-1.5 py-0.5 rounded font-medium", e.status === "active" ? "bg-emerald-50 text-emerald-600" : "bg-red-50 text-red-600")}>{e.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Payroll Runs Tab ─────────────────────────────────────────────────────────

function RunsTab({ clientId, firmId }: { clientId: string; firmId: string }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [slips, setSlips] = useState<Slip[]>([]);
  const [loadingSlips, setLoadingSlips] = useState(false);
  const [finalizing, setFinalizing] = useState<string | null>(null);
  // M17: a failed runs/slips fetch must not render as "No payroll runs yet" /
  // an empty slip table — both look identical to genuinely having no data.
  const [loadFailed, setLoadFailed] = useState(false);
  const [slipsFailed, setSlipsFailed] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  /** Sentences the server composed about what this run could NOT establish —
   *  attendance nobody entered, a state PT slab we do not model. Rendered
   *  verbatim; see createRun. */
  const [runGaps, setRunGaps] = useState<string[]>([]);
  const [finalizeError, setFinalizeError] = useState<string | null>(null);
  /** The run whose finalise was refused, and what stood. Null when nothing is
   *  blocked — a separate state from finalizeError because a block is not a
   *  failure and is answered differently. */
  const [blockedRun, setBlockedRun] = useState<
    { runId: string; gaps: string[]; message: string } | null>(null);
  const [overrideReason, setOverrideReason] = useState("");

  // The generic filing walk-throughs (services/filing_demo/pf_ecr and .../esi).
  // Offered only where the server says the demo exists — the dead-control rule.
  // ONE demo slot for both flows, so the PF and ESI wizards can never be open
  // at the same time.
  const [demoFlows, setDemoFlows] = useState<string[]>([]);
  const [demo, setDemo] = useState<{ flow: "pf" | "esi"; runId: string } | null>(null);

  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const res = await apiFetch<PayrollRun[]>(`/api/payroll/runs?client_id=${clientId}`);
      if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); return; }
      setRuns(res.data || []);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    let cancelled = false;
    fetchFilingDemoCapabilities().then((c) => {
      if (!cancelled) setDemoFlows(c.enabled ? c.flows : []);
    });
    return () => { cancelled = true; };
  }, []);

  async function createRun() {
    setCreating(true);
    setCreateError(null);
    setRunGaps([]);
    const res = await apiFetch("/api/payroll/runs", { method: "POST", body: JSON.stringify({ client_id: clientId, firm_id: firmId, month }) })
      .catch(() => null) as {
        success?: boolean; error?: string | null;
        data?: { statutory_gaps?: string[]; attendance_gaps?: string[] };
      } | null;
    setCreating(false);
    // task #229: previously discarded — a duplicate-run 409 or RBAC/guardrail
    // rejection produced silent no-op with zero explanation of why nothing
    // happened.
    if (!res || res.success === false) {
      setCreateError(res?.error ?? "Could not create the payroll run — the request failed.");
      return;
    }
    // The run has ALWAYS come back with statutory_gaps and this page has always
    // thrown them away: `res.data` was never read, so a deduction the engine
    // refused to guess at reached nobody. A named gap that only exists in a
    // response body is an omitted statutory deduction with extra steps.
    //
    // Both lists are sentences composed by apps/api. The page prints them and
    // decides nothing about them.
    setRunGaps([...(res.data?.attendance_gaps ?? []), ...(res.data?.statutory_gaps ?? [])]);
    await load();
  }

  /** Finalize, and handle the block.
   *
   *  Migration 328: a run with an unresolved statutory or attendance gap is
   *  REFUSED, because finalising posts a real, immutable general-ledger
   *  journal — the gaps stopped being advice at exactly that moment. The
   *  server names them; a Partner may go ahead with a written reason, which is
   *  recorded on the transition log beside the gaps that stood.
   *
   *  `overrideReason` is passed explicitly rather than read from state so the
   *  retry cannot race the textarea.
   */
  async function finalizeRun(runId: string, overrideReason?: string) {
    setFinalizing(runId);
    setFinalizeError(null);
    const res = await apiFetch(`/api/payroll/runs/${runId}/finalize`, {
      method: "POST",
      body: JSON.stringify(overrideReason ? { override_reason: overrideReason } : {}),
    }).catch(() => null) as {
      success?: boolean; error?: string | null;
      detail?: string | { message?: string; gaps?: string[] };
      data?: { overridden_gaps?: string[] };
    } | null;
    setFinalizing(null);

    // task #229: finalize posts a real, immutable GL journal — a silently
    // discarded failure (empty run, journal-posting error, already
    // finalized) left the CA with no idea the run was still a draft.
    if (!res || res.success === false) {
      const detail = res?.detail;
      if (detail && typeof detail === "object" && Array.isArray(detail.gaps)) {
        // The block, not a failure. Show what stood and offer the override —
        // and do NOT clear it into a generic error, because the sentences are
        // the whole point of having collected them.
        setBlockedRun({ runId, gaps: detail.gaps, message: detail.message ?? "" });
        setOverrideReason("");
        return;
      }
      setFinalizeError(
        (typeof detail === "string" ? detail : null)
        ?? res?.error
        ?? "Could not finalize the payroll run — the request failed.");
      return;
    }
    setBlockedRun(null);
    setOverrideReason("");
    await load();
  }

  async function fetchSlips(runId: string) {
    setLoadingSlips(true);
    setSlipsFailed(false);
    const res = await apiFetch<Slip[]>(`/api/payroll/runs/${runId}/slips`).catch(() => null);
    if (!res || (res as { success?: boolean }).success === false) { setSlipsFailed(true); setSlips([]); setLoadingSlips(false); return; }
    setSlips(res.data || []);
    setLoadingSlips(false);
  }

  function loadSlips(runId: string) {
    if (selectedRun === runId) { setSelectedRun(null); return; }
    setSelectedRun(runId);
    fetchSlips(runId);
  }

  if (loading) return (
    <div className="p-5 space-y-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
        <Skeleton className="h-2.5 w-24 mb-3" />
        <div className="flex items-end gap-3">
          <Skeleton className="h-9 w-40 rounded-lg" />
          <Skeleton className="h-9 w-32 rounded-lg" />
        </div>
      </div>
      <TransactionListSkeleton rows={3} />
    </div>
  );

  return (
    <div className="p-5 space-y-4">
      {demo && (
        <FilingDemoWizard
          flow={demo.flow}
          clientId={clientId}
          refData={{ run_id: demo.runId }}
          onClose={() => setDemo(null)}
        />
      )}
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
        <p className="text-[12px] font-semibold text-[#1E293B] mb-3">Create New Run</p>
        <div className="flex items-end gap-3">
          <div>
            <label className="block text-[11px] text-[#64748B] mb-1">Month</label>
            <input type="month" value={month} onChange={e => setMonth(e.target.value)}
              className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-[13px] text-[#1E293B] outline-none focus:border-blue-400" />
          </div>
          <button onClick={createRun} disabled={creating}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50">
            <Play size={12} /> {creating ? "Computing…" : "Compute & Draft"}
          </button>
        </div>
        {createError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2 mt-3">{createError}</p>}
        {runGaps.length > 0 && (
          <div className="mt-3 rounded border border-amber-200 bg-amber-50 px-3 py-2">
            <p className="text-xs font-medium text-amber-900">
              This run computed, but {runGaps.length} thing{runGaps.length === 1 ? "" : "s"} could not be established:
            </p>
            <ul className="mt-1 space-y-0.5">
              {runGaps.map((g, i) => (
                <li key={i} className="text-[11px] text-amber-800">· {g}</li>
              ))}
            </ul>
            <p className="text-[11px] text-amber-700 mt-1.5">
              The run is a draft — nothing is posted or paid. Fix these and create it again,
              or finalise it if the figures are right.
            </p>
          </div>
        )}
      </div>

      {finalizeError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{finalizeError}</p>}

      {/* The block. Migration 328: finalising posts a journal that cannot be
          changed afterwards, so a run with an unresolved gap is refused rather
          than warned about. The gaps are NAMED — a count would send the CA back
          to the draft to work out which. */}
      {blockedRun && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 space-y-2">
          <p className="text-xs font-semibold text-amber-900">
            {blockedRun.message || "This run has things it could not establish."}
          </p>
          <ul className="space-y-0.5">
            {blockedRun.gaps.map((g, i) => (
              <li key={i} className="text-[11px] text-amber-900">· {g}</li>
            ))}
          </ul>
          <div>
            <label className="block text-[11px] font-medium text-amber-900 mb-1">
              Releasing anyway? Say why — this goes on the release log beside these
              items and is what a reviewer reads months later.
            </label>
            <textarea
              value={overrideReason}
              onChange={e => setOverrideReason(e.target.value)}
              rows={2}
              placeholder="e.g. Client confirmed by email on the 3rd that nobody was on leave."
              className="w-full border border-amber-300 rounded-lg px-2.5 py-1.5 text-[12px] text-[#1E293B] outline-none focus:border-amber-500 bg-white"
            />
            <p className="text-[10px] text-amber-700 mt-0.5">
              {overrideReason.trim().length}/{OVERRIDE_REASON_MIN} characters
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => finalizeRun(blockedRun.runId, overrideReason.trim())}
              disabled={overrideReason.trim().length < OVERRIDE_REASON_MIN
                        || finalizing === blockedRun.runId}
              className="text-[11px] px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-40"
            >
              {finalizing === blockedRun.runId ? "Finalizing…" : "Finalize anyway"}
            </button>
            <button
              onClick={() => { setBlockedRun(null); setOverrideReason(""); }}
              className="text-[11px] px-3 py-1.5 border border-amber-300 text-amber-900 rounded-lg hover:bg-amber-100"
            >
              Go back and fix them
            </button>
          </div>
        </div>
      )}

      <div className="space-y-2">
        {loadFailed ? (
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
            <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load payroll runs — the request failed or timed out.</p>
            <button onClick={() => load()} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
          </div>
        ) : (
        <>
        {runs.length === 0 && (
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center text-[#94A3B8] text-sm">No payroll runs yet</div>
        )}
        {runs.map(r => (
          <div key={r.id} className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-3">
                <StatusBadge status={r.status} />
                <div>
                  <p className="text-sm font-semibold text-[#1E293B]">{fmtMonth(r.month)}</p>
                  <p className="text-[11px] text-[#94A3B8]">{r.headcount} employees · Gross {fmt(r.total_gross_paise)}</p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button onClick={() => loadSlips(r.id)} className="text-[11px] text-blue-600 hover:text-blue-800 px-2 py-1 rounded hover:bg-blue-50">
                  {selectedRun === r.id ? "Hide Slips" : "View Slips"}
                </button>
                {r.status !== "finalized" && r.status !== "paid" && (
                  <button onClick={() => finalizeRun(r.id)} disabled={finalizing === r.id}
                    className="flex items-center gap-1 text-[11px] px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50">
                    <CheckCircle size={11} /> {finalizing === r.id ? "Finalizing…" : "Finalize"}
                  </button>
                )}
                {(r.status === "finalized" || r.status === "paid") && (
                  <span className="text-[11px] text-emerald-600 flex items-center gap-1"><CheckCircle size={11} /> {r.status === "paid" ? "Paid" : "Finalized"}</span>
                )}
                {/* The statutory walk-throughs — only on a settled run, and
                    only where the server says the demo exists (dead-control
                    rule). Both buttons share ONE demo slot, so the two
                    wizards can never be open at once. */}
                {(r.status === "finalized" || r.status === "paid") && demoFlows.includes("pf") && (
                  <button onClick={() => setDemo({ flow: "pf", runId: r.id })}
                    className="text-[11px] px-2.5 py-1.5 border border-amber-300 rounded-lg hover:bg-amber-50 text-amber-800">
                    PF ECR (demo)
                  </button>
                )}
                {(r.status === "finalized" || r.status === "paid") && demoFlows.includes("esi") && (
                  <button onClick={() => setDemo({ flow: "esi", runId: r.id })}
                    className="text-[11px] px-2.5 py-1.5 border border-amber-300 rounded-lg hover:bg-amber-50 text-amber-800">
                    ESI (demo)
                  </button>
                )}
              </div>
            </div>

            {selectedRun === r.id && (
              <div className="border-t border-[#F1F5F9] px-4 py-3">
                {loadingSlips ? (
                  <TableSkeleton cols={7} rows={3} bare />
                ) : slipsFailed ? (
                  <div className="text-center py-6">
                    <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load slips — the request failed or timed out.</p>
                    <button onClick={() => fetchSlips(r.id)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
                  </div>
                ) : (
                  <table className="w-full text-[11px]">
                    <thead>
                      <tr className="border-b border-[#F1F5F9]">
                        {["Employee", "Gross", "PF (Emp)", "ESI (Emp)", "PT", "TDS", "Net"].map(h => (
                          <th key={h} className="py-1.5 px-2 text-left text-[10px] font-semibold text-[#94A3B8]">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {slips.map(s => (
                        <tr key={s.id} className="hover:bg-[#F8FAFC]">
                          <td className="py-1.5 px-2 text-[#1E293B] font-medium">{s.payroll_employees?.name}</td>
                          <td className="py-1.5 px-2 font-mono text-[#1E293B]">{fmt(s.gross_paise)}</td>
                          <td className="py-1.5 px-2 font-mono text-[#64748B]">{fmt(s.pf_employee_paise)}</td>
                          <td className="py-1.5 px-2 font-mono text-[#64748B]">{fmt(s.esi_employee_paise)}</td>
                          <td className="py-1.5 px-2 font-mono text-[#64748B]">{fmt(s.pt_paise)}</td>
                          <td className="py-1.5 px-2 font-mono text-amber-600">{fmt(s.tds_paise)}</td>
                          <td className="py-1.5 px-2 font-mono font-semibold text-emerald-600">{fmt(s.net_paise)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t-2 border-[#E2E8F0] font-semibold">
                        <td className="py-1.5 px-2 text-[#1E293B] text-[10px]">TOTAL</td>
                        <td className="py-1.5 px-2 font-mono text-[#1E293B]">{fmt(r.total_gross_paise)}</td>
                        <td colSpan={4} />
                        <td className="py-1.5 px-2 font-mono text-emerald-600">{fmt(r.total_net_paise)}</td>
                      </tr>
                    </tfoot>
                  </table>
                )}
              </div>
            )}
          </div>
        ))}
        </>
        )}
      </div>
    </div>
  );
}

// ─── Statutory Tab ────────────────────────────────────────────────────────────

function StatutoryTab({ clientId }: { clientId: string }) {
  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);
  const [data, setData] = useState<StatutoryData | null>(null);
  const [loading, setLoading] = useState(false);
  // M17: a failed statutory-summary fetch must not render as the "click Load"
  // prompt — PF/ESI/PT/TDS dues would look un-run when the fetch actually failed.
  const [loadFailed, setLoadFailed] = useState(false);

  async function load() {
    setLoading(true);
    setLoadFailed(false);
    try {
      const res = await apiFetch<StatutoryData>(`/api/payroll/reports/statutory-summary?client_id=${clientId}&month=${month}`);
      if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setData(null); return; }
      setData(res.data);
    } catch {
      setLoadFailed(true); setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center gap-3">
        <input type="month" value={month} onChange={e => setMonth(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-[13px] outline-none focus:border-blue-400" />
        <button onClick={load} disabled={loading} className="px-4 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {loading ? "Loading…" : "Load"}
        </button>
      </div>

      {data && (
        <div className="grid grid-cols-2 gap-3">
          {[
            // The PF card shows the CHALLAN, not the contributions. EDLI and the
            // admin charge are remitted on the same challan, and a card headed
            // "PF Challan" showing only the 12% either side was about 1% of PF
            // wages short of what the CA was about to pay — with no line to
            // explain the gap. The two are named underneath so the total can be
            // taken apart again.
            {
              label: "PF Challan (Employer + Employee)",
              amount: data.pf_challan_total_paise ?? data.pf_total_paise,
              due: "15th of following month", color: "blue",
              detail: `Contributions ${fmt(data.pf_total_paise ?? 0)} · EDLI ${fmt(data.edli_paise ?? 0)} · Admin ${fmt(data.pf_admin_paise ?? 0)}`,
            },
            { label: "ESI Challan (Employer + Employee)", amount: data.esi_total_paise, due: "15th of following month", color: "green", detail: "" },
            { label: "PT Challan", amount: data.pt_total_paise, due: "varies by state", color: "amber", detail: "" },
            { label: "TDS — 24Q", amount: data.tds_24q_paise, due: "7th of following month", color: "red", detail: "" },
          ].map(({ label, amount, due, color, detail }) => (
            <div key={label} className="bg-white rounded-xl border border-[#E2E8F0] p-4">
              <p className="text-[11px] font-semibold text-[#64748B]">{label}</p>
              <p className={`text-2xl font-bold mt-1 text-${color}-600`}>{fmt(amount ?? 0)}</p>
              {detail && <p className="text-[10px] text-[#94A3B8] mt-1 font-mono">{detail}</p>}
              <p className="text-[10px] text-[#94A3B8] mt-1">Due: {due}</p>
            </div>
          ))}
        </div>
      )}

      {data && (data.one_time_paise ?? 0) !== 0 && (
        <p className="text-[11px] text-[#64748B]">
          {fmt(data.one_time_paise ?? 0)} of the gross this month was one-time
          earnings — a bonus, arrears or a reimbursement — not the recurring
          salary bill. It is the usual reason a month&apos;s challans jump.
        </p>
      )}

      {!data && !loading && (
        loadFailed ? (
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
            <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load statutory dues — the request failed or timed out.</p>
            <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center text-[#94A3B8] text-sm">
            Select a month and click Load to view statutory dues
          </div>
        )
      )}
    </div>
  );
}


// ─── Release — lock, pay, reverse. One lifecycle, one place. ─────────────────
//
// WHAT WAS MISSING, AND WHY IT MATTERED
//
// Finalising posts a real, immutable general-ledger journal, and DISBURSING
// posts the payment. Until now the client workspace could finalise but not
// disburse and not reverse — those two lived only on the firm rail, behind a
// client dropdown. So the CA locked the month in one place and paid it in
// another, and the one action that undoes a release was on neither screen the
// month was worked from.
//
// Reverse is present but never primary, and it demands a reason: it writes two
// reversing journals and reopens the run, which is a correction to the books
// rather than an edit.

function ReleaseTab({ clientId }: { clientId: string }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [disburseRun, setDisburseRun] = useState<PayrollRun | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setLoadFailed(false);
    try {
      const res = await apiFetch<PayrollRun[]>(`/api/payroll/runs?client_id=${clientId}`);
      if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); return; }
      setRuns(res.data || []);
    } catch { setLoadFailed(true); } finally { setLoading(false); }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function reverse(run: PayrollRun) {
    // A reason, because a reversal is answered for later. The server records it
    // on the transition log; asking here means the CA writes it while they know
    // why rather than reconstructing it in June.
    const reason = prompt(
      `Reverse payroll for ${run.month}?\n\n`
      + "This posts reversing journals for the accrual and, if paid, the "
      + "disbursement, then reopens the run for editing. Say why:");
    if (reason === null) return;
    if (reason.trim().length < 10) {
      setMsg({ kind: "err", text: "A reversal needs a reason of at least ten characters." });
      return;
    }
    setBusy(run.id); setMsg(null);
    try {
      const res = await api.payroll.reverseRun(run.id) as { success?: boolean; error?: string | null };
      if (res?.success === false) { setMsg({ kind: "err", text: res.error ?? "Could not reverse the run." }); return; }
      setMsg({ kind: "ok", text: `Payroll for ${run.month} reversed and reopened.` });
      await load();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Could not reverse the run." });
    } finally { setBusy(null); }
  }

  if (loading) return <div className="p-5"><TransactionListSkeleton rows={3} /></div>;

  return (
    <div className="p-5 space-y-4">
      {msg && (
        <p className={`text-[12px] px-3 py-2 rounded-lg ${msg.kind === "ok" ? "bg-green-50 text-green-700" : "bg-red-50 text-red-600"}`}>
          {msg.text}
        </p>
      )}

      {loadFailed ? (
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load the runs.</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      ) : runs.length === 0 ? (
        <p className="text-center text-sm text-[#94A3B8] py-10">
          No payroll runs yet. Compute one under Register first.
        </p>
      ) : (
        <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="bg-[#F8FAFC] border-b border-[#F1F5F9] text-[10px] font-semibold text-[#94A3B8] uppercase">
                <th className="px-3 py-2 text-left">Month</th>
                <th className="px-3 py-2 text-left">State</th>
                <th className="px-3 py-2 text-right">Net pay</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {runs.map((r) => {
                const paid = r.status === "paid";
                const finalized = r.status === "finalized";
                return (
                  <tr key={r.id}>
                    <td className="px-3 py-2 font-medium text-[#1E293B]">{fmtMonth(r.month)}</td>
                    <td className="px-3 py-2">
                      <span className={`px-2 py-0.5 rounded text-[11px] ${
                        paid ? "bg-green-100 text-green-700"
                        : finalized ? "bg-emerald-100 text-emerald-700"
                        : "bg-blue-100 text-blue-700"}`}>
                        {paid ? "Paid" : finalized ? "Finalised" : "Draft"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono">
                      {r.total_net_paise != null ? fmt(r.total_net_paise) : "—"}
                    </td>
                    <td className="px-3 py-2 text-right space-x-2 whitespace-nowrap">
                      {finalized && (
                        <button onClick={() => setDisburseRun(r)} disabled={busy === r.id}
                          className="px-3 py-1 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50">
                          Record payment
                        </button>
                      )}
                      {(finalized || paid) && (
                        // Never primary. It is a correction to posted books.
                        <button onClick={() => reverse(r)} disabled={busy === r.id}
                          className="px-3 py-1 border border-[#E2E8F0] rounded-lg text-[#64748B] hover:bg-red-50 hover:text-red-600 disabled:opacity-50">
                          {busy === r.id ? "Reversing…" : "Reverse"}
                        </button>
                      )}
                      {!finalized && !paid && (
                        <span className="text-[11px] text-[#94A3B8]">Finalise it under Register</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {disburseRun && (
        <DisburseModal
          run={{ ...disburseRun, client_id: clientId }}
          onClose={() => setDisburseRun(null)}
          onDone={(text: string) => { setDisburseRun(null); setMsg({ kind: "ok", text }); load(); }}
        />
      )}
    </div>
  );
}

// ─── Outputs — this client-month's shelf, every file server-built ────────────
//
// Each of these existed and could only be reached from the firm rail, behind a
// client dropdown — on a different screen from the month they describe. The ECR
// and the ESIC return REFUSE a run that is not finalised, because both report
// contributions actually made; the button says so rather than spending a round
// trip to be told.

function OutputsTab({ clientId }: { clientId: string }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [runId, setRunId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "warn" | "err"; text: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch<PayrollRun[]>(`/api/payroll/runs?client_id=${clientId}`);
        const list = res?.data ?? [];
        setRuns(list);
        setRunId(list[0]?.id ?? "");
      } catch { /* the empty state below says it */ } finally { setLoading(false); }
    })();
  }, [clientId]);

  const run = runs.find((r) => r.id === runId);
  const released = !!run && (run.status === "finalized" || run.status === "paid");

  async function go(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key); setMsg(null);
    try { await fn(); setMsg({ kind: "ok", text: ok }); }
    catch (e) { setMsg({ kind: "err", text: e instanceof Error ? e.message : "That did not work." }); }
    finally { setBusy(null); }
  }

  /** The ECR and the ESIC return come back as TEXT with `problems` and
   *  `filable` — a CA has to see which members the file cannot carry BEFORE
   *  the portal rejects the batch. */
  async function statutoryFile(kind: "ecr" | "esic") {
    if (!run) return;
    setBusy(kind); setMsg(null);
    try {
      const res = (await (kind === "ecr" ? api.payroll.runEcr(run.id) : api.payroll.runEsic(run.id))) as {
        data?: { filename?: string; lines?: string; csv?: string; problems?: string[]; filable?: boolean };
      };
      const d = res?.data;
      const problems = d?.problems ?? [];
      const label = kind === "ecr" ? "ECR" : "ESIC return";
      if (!d?.filable) {
        setMsg({ kind: "warn", text: problems.length
          ? `${label} blocked — ${problems.join(" · ")}`
          : `No member of this run carries a ${kind === "ecr" ? "PF" : "ESI"} contribution, so there is no ${label} to build.` });
        return;
      }
      const content = kind === "ecr" ? d.lines : d.csv;
      if (!content) { setMsg({ kind: "err", text: "The server returned an empty file." }); return; }
      // Both go to a government portal. Neither gets a BOM — extra bytes break
      // the parse on upload.
      const blob = new Blob([content], { type: kind === "ecr" ? "text/plain" : "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = d.filename ?? `${label.replace(/\s/g, "_")}_${run.month}.${kind === "ecr" ? "txt" : "csv"}`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg({ kind: "ok", text: `${label} downloaded.` });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "That did not work." });
    } finally { setBusy(null); }
  }

  if (loading) return <div className="p-5"><TransactionListSkeleton rows={3} /></div>;
  if (runs.length === 0) {
    return <p className="p-5 text-center text-sm text-[#94A3B8] py-10">
      No payroll runs yet. Compute one under Register first.
    </p>;
  }

  const items: { key: string; label: string; hint: string; run: () => void; ready: boolean }[] = [
    { key: "payslips", label: "Payslips (zip)", ready: true,
      hint: "Every payslip in this run, one PDF per employee.",
      run: () => go("payslips", async () => {
        const problems = await api.payroll.downloadRunPayslips(run!.id, run!.month);
        if (problems.length) setMsg({ kind: "warn", text: `The zip is missing ${problems.length} payslip(s): ${problems.join("; ")}` });
      }, "Payslips downloaded.") },
    { key: "register", label: "Salary register (CSV)", ready: true,
      hint: "Twenty-eight columns in the document's order — the sheet that goes to the client and into the audit file.",
      run: () => go("register", () => api.payroll.downloadSalaryRegister(clientId, run!.month), "Register downloaded.") },
    { key: "ecr", label: "EPFO ECR", ready: released,
      hint: released ? "The UAN-based text file for unifiedportal-emp.epfindia.gov.in."
                     : "Needs a finalised run — the ECR reports contributions actually made.",
      run: () => statutoryFile("ecr") },
    { key: "esic", label: "ESIC contribution file", ready: released,
      hint: released ? "The IP-number CSV for the ESIC portal."
                     : "Needs a finalised run — it reports contributions actually made.",
      run: () => statutoryFile("esic") },
    { key: "24q", label: "Form 24Q working paper", ready: true,
      hint: "The quarter's deductee rows. A working paper, not a return — CA review required, nothing is filed.",
      run: () => go("24q", () => {
        const [y, m] = run!.month.split("-").map(Number);
        const quarter = m >= 4 && m <= 6 ? "Q1" : m >= 7 && m <= 9 ? "Q2" : m >= 10 && m <= 12 ? "Q3" : "Q4";
        const fyStart = m >= 4 ? y : y - 1;
        return api.payroll.download24QWorkingPaper(clientId, `${fyStart}-${String(fyStart + 1).slice(2)}`, quarter);
      }, "24Q working paper downloaded.") },
  ];

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <label className="text-[11px] text-[#64748B]">Month</label>
        <select value={runId} onChange={(e) => { setRunId(e.target.value); setMsg(null); }}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-[13px] outline-none focus:border-blue-400">
          {runs.map((r) => <option key={r.id} value={r.id}>{fmtMonth(r.month)} · {r.status}</option>)}
        </select>
      </div>

      {msg && (
        <p className={`text-[12px] px-3 py-2 rounded-lg ${
          msg.kind === "ok" ? "bg-green-50 text-green-700"
          : msg.kind === "warn" ? "bg-amber-50 text-amber-800"
          : "bg-red-50 text-red-600"}`}>{msg.text}</p>
      )}

      <div className="grid grid-cols-2 gap-3">
        {items.map((it) => (
          <div key={it.key} className="bg-white rounded-xl border border-[#E2E8F0] p-4">
            <p className="text-[12px] font-semibold text-[#1E293B]">{it.label}</p>
            <p className="text-[10px] text-[#94A3B8] mt-1 min-h-[28px]">{it.hint}</p>
            <button onClick={it.run} disabled={!it.ready || busy !== null}
              className="mt-2 px-3 py-1.5 text-[12px] border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-40">
              {busy === it.key ? "Building…" : it.ready ? "Download" : "Not yet"}
            </button>
          </div>
        ))}
      </div>

      {/* Both belong on the shelf. The statutory summary is the figure a CA
          reconciles the challans against before paying them, and the register
          is the month read employee by employee — the Reports tab that used to
          hold it was a noun for the same thing. */}
      <StatutoryTab clientId={clientId} />
      <ReportsTab clientId={clientId} />
    </div>
  );
}

// ─── Setup Tab — the client's own statutory registrations ─────────────────────
//
// Migration 325. Three finished returns — the ECR, the ESIC contribution file
// and Form 24Q — are returns BY AN ESTABLISHMENT, and until this screen existed
// there was nowhere to record the number that identifies it. A CA retyped the
// 24Q deductor block by hand every quarter, for every client.
//
// The field LIST comes from the API, not from here. If the form held its own
// copy the two would drift, and a registration added to the table would be
// invisible until somebody remembered this file.

type IdentityField = { name: string; label: string; used_for: string };
type IdentityValues = Record<string, string | null>;
type PTRegistration = { state: string; ptrc_number?: string | null; ptec_number?: string | null };

function StatutoryIdentityTab({ clientId }: { clientId: string }) {
  const [fields, setFields] = useState<IdentityField[]>([]);
  const [values, setValues] = useState<IdentityValues>({});
  const [pt, setPt] = useState<PTRegistration[]>([]);
  const [loading, setLoading] = useState(true);
  // A failed load must not render as "this client has no registrations" — that
  // is the same mistake the 26/26 attendance default made, in the UI.
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [ptForm, setPtForm] = useState({ state: "", ptrc_number: "", ptec_number: "" });

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const res = await apiFetch<{ identity: IdentityValues; pt_registrations: PTRegistration[]; fields: IdentityField[] }>(
        `/api/payroll/statutory-identity?client_id=${clientId}`);
      if (!res?.data) { setLoadFailed(true); return; }
      setFields(res.data.fields ?? []);
      setValues(res.data.identity ?? {});
      setPt(res.data.pt_registrations ?? []);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  /** One field at a time, and only the field that changed.
   *
   *  The endpoint is PATCH-shaped on purpose: sending the whole object back
   *  would clear anything this form has not loaded, and a form that clears a
   *  TAN because somebody edited the LIN is the silent-write failure the whole
   *  table exists to end. */
  async function saveField(name: string, raw: string) {
    setSaving(name); setSaveError(null); setSaved(null);
    try {
      const res = await apiFetch<{ identity: IdentityValues }>("/api/payroll/statutory-identity", {
        method: "PUT",
        body: JSON.stringify({ client_id: clientId, [name]: raw }),
      });
      const body = res as unknown as { success?: boolean; error?: string; detail?: string };
      if (body?.success === false || !res?.data) {
        // The server's own sentence, which names WHY a TAN was refused. A
        // generic "couldn't save" would hide the only useful part.
        setSaveError(body?.error || body?.detail || "Couldn't save — the request failed.");
        return;
      }
      setValues(res.data.identity ?? {});
      setSaved(name);
    } catch {
      setSaveError("Couldn't save — the request failed or timed out.");
    } finally {
      setSaving(null);
    }
  }

  async function savePt() {
    const state = ptForm.state.trim().toUpperCase();
    if (!/^[A-Z]{2}$/.test(state)) {
      setSaveError('State must be the two-letter code, e.g. "MH" or "KA".');
      return;
    }
    if (!ptForm.ptrc_number.trim() && !ptForm.ptec_number.trim()) {
      setSaveError("Enter a PTRC or a PTEC number.");
      return;
    }
    setSaving("pt"); setSaveError(null);
    try {
      const res = await apiFetch<PTRegistration>("/api/payroll/statutory-identity/pt", {
        method: "PUT",
        body: JSON.stringify({
          client_id: clientId, state,
          ptrc_number: ptForm.ptrc_number.trim(),
          ptec_number: ptForm.ptec_number.trim(),
        }),
      });
      const body = res as unknown as { success?: boolean; error?: string; detail?: string };
      if (body?.success === false) {
        setSaveError(body?.error || body?.detail || "Couldn't save the registration.");
        return;
      }
      setPtForm({ state: "", ptrc_number: "", ptec_number: "" });
      await load();
    } catch {
      setSaveError("Couldn't save — the request failed or timed out.");
    } finally {
      setSaving(null);
    }
  }

  async function removePt(state: string) {
    setSaving("pt"); setSaveError(null);
    try {
      await apiFetch(`/api/payroll/statutory-identity/pt?client_id=${clientId}&state=${state}`,
                     { method: "DELETE" });
      await load();
    } catch {
      setSaveError("Couldn't remove the registration.");
    } finally {
      setSaving(null);
    }
  }

  if (loading) return <div className="p-5"><CardGridSkeleton count={4} /></div>;

  if (loadFailed) {
    return (
      <div className="p-5">
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">
            Couldn&apos;t load this client&apos;s registrations — the request failed.
          </p>
          <p className="text-xs text-[#64748B] mb-3">
            This is not the same as having none recorded, so nothing is shown either way.
          </p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
        <h2 className="text-[13px] font-semibold text-[#0F172A]">Statutory registrations</h2>
        <p className="text-[11px] text-[#64748B] mt-0.5">
          The numbers this client&apos;s own returns are filed under. Form 24Q carries the TAN;
          the EPFO and ESIC portals take the establishment from the login, so those two are
          shown beside the file rather than in it.
        </p>
      </div>

      {saveError && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-[12px] text-red-700">{saveError}</div>
      )}

      <div className="bg-white rounded-xl border border-[#E2E8F0] divide-y divide-[#F1F5F9]">
        {fields.map(f => (
          <IdentityRow
            key={f.name}
            field={f}
            value={values[f.name] ?? ""}
            saving={saving === f.name}
            justSaved={saved === f.name}
            onSave={v => saveField(f.name, v)}
          />
        ))}
      </div>

      {/* ── Professional tax, one registration per state ─────────────────── */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-3">
        <div>
          <h2 className="text-[13px] font-semibold text-[#0F172A]">Professional tax registrations</h2>
          <p className="text-[11px] text-[#64748B] mt-0.5">
            One per state — PT is a state levy under Article 276(2). The PTRC is the
            employer&apos;s authority to <em>deduct</em> from employees and deposit; the PTEC is the
            entity&apos;s own enrolment. A payroll run reports any state it deducts in with no PTRC here.
          </p>
        </div>

        {pt.length > 0 && (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-[10px] text-[#94A3B8] border-b border-[#F1F5F9]">
                <th className="py-1.5">State</th><th>PTRC</th><th>PTEC</th><th></th>
              </tr>
            </thead>
            <tbody>
              {pt.map(r => (
                <tr key={r.state} className="border-b border-[#F8FAFC]">
                  <td className="py-1.5 font-medium text-[#1E293B]">{r.state}</td>
                  <td className="text-[#334155]">{r.ptrc_number || <span className="text-[#94A3B8]">—</span>}</td>
                  <td className="text-[#334155]">{r.ptec_number || <span className="text-[#94A3B8]">—</span>}</td>
                  <td className="text-right">
                    <button onClick={() => removePt(r.state)} disabled={saving === "pt"}
                      className="text-[11px] text-red-600 hover:underline disabled:opacity-50">Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="grid grid-cols-4 gap-2 items-end">
          <Field label="State code" value={ptForm.state} placeholder="MH"
            onChange={v => setPtForm({ ...ptForm, state: v.toUpperCase().slice(0, 2) })} />
          <Field label="PTRC number" value={ptForm.ptrc_number} placeholder="27123456789P"
            onChange={v => setPtForm({ ...ptForm, ptrc_number: v })} />
          <Field label="PTEC number" value={ptForm.ptec_number} placeholder="optional"
            onChange={v => setPtForm({ ...ptForm, ptec_number: v })} />
          <button onClick={savePt} disabled={saving === "pt"}
            className="px-4 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700 disabled:opacity-50">
            {saving === "pt" ? "Saving…" : "Add"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** One registration, edited and saved on its own.
 *
 *  Deliberately not part of a single Save-all button: the endpoint writes only
 *  the field it is sent, and a form that posted every field would clear the
 *  ones this screen happened not to load. */
function IdentityRow({ field, value, saving, justSaved, onSave }: {
  field: IdentityField; value: string; saving: boolean; justSaved: boolean;
  onSave: (v: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => { setDraft(value); }, [value]);
  const dirty = draft !== value;

  return (
    <div className="p-3 flex items-end gap-3">
      <div className="flex-1">
        <label className="block text-[11px] font-medium text-[#334155]">{field.label}</label>
        <p className="text-[10px] text-[#94A3B8] mb-1">{field.used_for}</p>
        <input
          value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder="Not recorded"
          className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] text-[#1E293B] outline-none focus:border-blue-400"
        />
      </div>
      <button onClick={() => onSave(draft)} disabled={saving || !dirty}
        className="px-3 py-1.5 text-[12px] rounded-lg border border-[#E2E8F0] text-[#334155] hover:bg-[#F8FAFC] disabled:opacity-40 shrink-0">
        {saving ? "Saving…" : justSaved && !dirty ? "Saved" : "Save"}
      </button>
    </div>
  );
}

// ─── Shared Components ────────────────────────────────────────────────────────

function StatCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
      <div className="flex items-center gap-1.5 mb-1">{icon}<span className="text-[10px] text-[#94A3B8]">{label}</span></div>
      <p className="text-2xl font-bold text-[#1E293B]">{value}</p>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] text-[#94A3B8]">{label}</p>
      <p className="text-sm font-semibold text-[#1E293B]">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    draft:     "bg-[#F1F5F9] text-[#64748B]",
    review:    "bg-amber-50 text-amber-600",
    finalized: "bg-emerald-50 text-emerald-600",
    paid:      "bg-sky-50 text-sky-600",
  };
  return <span className={cn("text-[10px] font-medium px-1.5 py-0.5 rounded capitalize", map[status] || map.draft)}>{status}</span>;
}

function Field({ label, value, onChange, placeholder, type = "text" }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string }) {
  return (
    <div>
      <label className="block text-[11px] text-[#64748B] mb-0.5">{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full border border-[#E2E8F0] rounded-lg px-2.5 py-1.5 text-[12px] text-[#1E293B] outline-none focus:border-blue-400" />
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PayrollPage() {
  const { clientId } = useClientNav();
  const [tab, setTab] = useState<Tab>("inputs");
  const [firmId, setFirmId] = useState<string>("");

  useEffect(() => { getFirmId().then(setFirmId).catch(() => {}); }, []);

  const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: "inputs",   label: "Inputs",   icon: Users },
    { id: "register", label: "Register", icon: Play },
    { id: "release",  label: "Release",  icon: TrendingUp },
    { id: "outputs",  label: "Outputs",  icon: Download },
    { id: "setup",    label: "Setup",    icon: Settings },
  ];

  return (
    <div className="flex flex-col h-full bg-[#F8FAFC]">
      {/* Header */}
      <div className="bg-white border-b border-[#E2E8F0] px-5 py-4 shrink-0">
        <div className="flex items-center gap-2 mb-3">
          <Users size={16} className="text-blue-600" />
          <h1 className="text-[15px] font-semibold text-[#0F172A]">Payroll</h1>
        </div>
        <div className="flex items-center gap-0.5">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg transition-colors",
                tab === t.id ? "bg-blue-600 text-white" : "text-[#64748B] hover:text-[#1E293B] hover:bg-[#F1F5F9]"
              )}
            >
              <t.icon size={12} />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {/* INPUTS — who is paid this month, and on what terms. The overview
            leads, because a month starts by looking at what changed. */}
        {tab === "inputs" && (
          <div className="space-y-6">
            <DashboardTab clientId={clientId} />
            <EmployeesTab clientId={clientId} firmId={firmId} />
            <SalaryStructuresTab clientId={clientId} firmId={firmId} />
          </div>
        )}
        {/* REGISTER — compute the month and read it employee by employee. */}
        {tab === "register" && <RunsTab clientId={clientId} firmId={firmId} />}
        {/* RELEASE — lock, pay, and (rarely) reverse. One lifecycle, one place. */}
        {tab === "release"  && <ReleaseTab clientId={clientId} />}
        {/* OUTPUTS — this client-month's shelf, every file server-built. */}
        {tab === "outputs"  && <OutputsTab clientId={clientId} />}
        {tab === "setup"    && <StatutoryIdentityTab clientId={clientId} />}
      </div>
    </div>
  );
}

// ─── Salary Structures Tab ────────────────────────────────────────────────────

function SalaryStructuresTab({ clientId, firmId }: { clientId: string; firmId: string }) {
  const [structures, setStructures] = useState<SalaryStructure[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", basic_percent: "40", hra_percent: "20", pf_applicable: true, esi_applicable: true });
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  // M17: distinguish a failed fetch from a client with no salary structures.
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    try {
      const res = await apiFetch<SalaryStructure[]>(`/api/payroll/salary-structures?client_id=${clientId}`);
      if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); return; }
      setStructures(res.data || []);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function addStructure() {
    // A structure's percentages are applied to every employee it is put on, so
    // one that parsed wrong is wrong for a whole client's roster, every month.
    const basicBps = bpsFromPercentInput(form.basic_percent);
    const hraBps = bpsFromPercentInput(form.hra_percent);
    if (basicBps === null || hraBps === null) {
      setSaveError("Basic % and HRA % must be plain percentages, e.g. 50 or 40.5 — without commas.");
      return;
    }
    setSaving(true);
    setSaveError(null);
    try {
      const res = await apiFetch("/api/payroll/salary-structures", {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, firm_id: firmId, ...form,
                               basic_percent: basicBps / 100, hra_percent: hraBps / 100 }),
      }) as { success?: boolean; error?: string | null } | null;
      // task #229: previously discarded — a rejected structure looked identical
      // to a saved one, and the modal closed as if it had worked.
      if (!res || res.success === false) {
        setSaveError(res?.error ?? "Could not save the salary structure — the request failed.");
        return;
      }
      await load();
      setShowAdd(false);
    } catch {
      setSaveError("Could not save the salary structure — the request failed.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="p-6"><CardGridSkeleton count={4} /></div>;

  if (loadFailed) return (
    <div className="p-6">
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
        <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load salary structures — the request failed or timed out.</p>
        <button onClick={() => load()} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
      </div>
    </div>
  );

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-[#1E293B]">Reusable Salary Templates</p>
        <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700">
          <Plus size={13} /> Add Structure
        </button>
      </div>
      {showAdd && (
        <div className="bg-[#F8FAFC] rounded-xl border border-[#E2E8F0] p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Structure Name *" value={form.name} onChange={v => setForm(f => ({...f, name: v}))} placeholder="e.g. Standard Grade A" />
            <Field label="Basic %" value={form.basic_percent} onChange={v => setForm(f => ({...f, basic_percent: v}))} type="number" />
            <Field label="HRA %" value={form.hra_percent} onChange={v => setForm(f => ({...f, hra_percent: v}))} type="number" />
          </div>
          <div className="flex items-center gap-4">
            {(["pf_applicable", "esi_applicable"] as const).map(k => (
              <label key={k} className="flex items-center gap-1.5 text-[12px] text-[#64748B] cursor-pointer">
                <input type="checkbox" checked={form[k]} onChange={e => setForm(f => ({...f, [k]: e.target.checked}))} />
                {k === "pf_applicable" ? "PF" : "ESI"}
              </label>
            ))}
          </div>
          {saveError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{saveError}</p>}
          <div className="flex gap-2">
            <button onClick={addStructure} disabled={saving} className="px-4 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700 disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
            <button onClick={() => setShowAdd(false)} className="px-4 py-1.5 text-[12px] text-[#64748B] border border-[#E2E8F0] rounded-lg">Cancel</button>
          </div>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {structures.length === 0 && <p className="col-span-2 text-sm text-[#94A3B8] text-center py-8">No structures yet</p>}
        {structures.map(s => (
          <div key={s.id} className="bg-white rounded-xl border border-[#E2E8F0] p-4">
            <p className="font-semibold text-[13px] text-[#1E293B]">{s.name}</p>
            <div className="mt-2 space-y-1 text-[11px] text-[#64748B]">
              <p>Basic {s.basic_percent}% · HRA {s.hra_percent}%</p>
              <p>{s.pf_applicable ? "PF ✓" : "PF ✗"} · {s.esi_applicable ? "ESI ✓" : "ESI ✗"}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Reports Tab ──────────────────────────────────────────────────────────────

function ReportsTab({ clientId }: { clientId: string }) {
  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);
  const [data, setData] = useState<SalaryRegister | null>(null);
  const [loading, setLoading] = useState(false);
  // M17: a failed salary-register fetch must not render blank — that reads as
  // "no salary data" when the request actually failed.
  const [loadFailed, setLoadFailed] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setLoadFailed(false);
    try {
      const res = await apiFetch<SalaryRegister>(`/api/payroll/reports/salary-register?client_id=${clientId}&month=${month}`);
      if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setData(null); return; }
      setData(res.data);
    } catch {
      setLoadFailed(true); setData(null);
    } finally {
      setLoading(false);
    }
  }

  // The file is built by the SERVER, from the full slip row. This screen shows
  // eight columns; the register a CA hands over has twenty-eight — attendance,
  // employer contributions, EDLI, the admin charge and one-time earnings among
  // them. Exporting what is on screen would produce a document that does not
  // reconcile to the bank advice.
  async function downloadRegister(): Promise<void> {
    setDownloading(true); setDownloadError(null);
    try {
      await api.payroll.downloadSalaryRegister(clientId, month);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Could not build the register");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center gap-3">
        <input type="month" value={month} onChange={e => setMonth(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-[13px] outline-none focus:border-blue-400" />
        <button onClick={load} disabled={loading} className="px-4 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {loading ? "Loading…" : "Load Salary Register"}
        </button>
        <button onClick={downloadRegister} disabled={downloading}
          className="px-4 py-1.5 border border-[#E2E8F0] text-[12px] rounded-lg hover:bg-[#F8FAFC] text-[#334155] disabled:opacity-50">
          {downloading ? "Building…" : "Download CSV"}
        </button>
      </div>
      {downloadError && <p className="text-[11px] text-red-600">{downloadError}</p>}
      {(data?.slips?.length ?? 0) > 0 && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#F1F5F9] flex items-center justify-between">
            <p className="text-[12px] font-semibold text-[#1E293B]">Salary Register — {fmtMonth(month)}</p>
            <span className="text-[11px] text-[#94A3B8]">{data!.slips.length} employees</span>
          </div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className="bg-[#F8FAFC] border-b border-[#F1F5F9]">
                {["Employee", "PAN", "Gross", "PF", "ESI", "PT", "TDS", "Net"].map(h => (
                  <th key={h} className="px-3 py-2 text-left text-[10px] font-semibold text-[#94A3B8]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F8FAFC]">
              {data!.slips.map((s) => (
                <tr key={s.id}>
                  <td className="px-3 py-2 text-[#1E293B] font-medium">{s.payroll_employees?.name}</td>
                  <td className="px-3 py-2 font-mono text-[#94A3B8]">{s.payroll_employees?.pan || "—"}</td>
                  <td className="px-3 py-2 font-mono">{fmt(s.gross_paise)}</td>
                  <td className="px-3 py-2 font-mono text-[#64748B]">{fmt(s.pf_employee_paise)}</td>
                  <td className="px-3 py-2 font-mono text-[#64748B]">{fmt(s.esi_employee_paise)}</td>
                  <td className="px-3 py-2 font-mono text-[#64748B]">{fmt(s.pt_paise)}</td>
                  <td className="px-3 py-2 font-mono text-amber-600">{fmt(s.tds_paise)}</td>
                  <td className="px-3 py-2 font-mono font-semibold text-emerald-600">{fmt(s.net_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {loadFailed && !loading && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center">
          <p className="text-sm text-red-600 font-medium mb-2">Couldn&apos;t load the salary register — the request failed or timed out.</p>
          <button onClick={load} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">Retry</button>
        </div>
      )}
      {data && !data.slips?.length && <p className="text-center text-sm text-[#94A3B8] py-8">No salary data for {fmtMonth(month)}</p>}
    </div>
  );
}
