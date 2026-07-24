"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Users, Plus, Play, CheckCircle,
  FileText, TrendingUp, IndianRupee, Download, Upload,
  Building2, CreditCard,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getFirmId } from "@/lib/data/getFirmId";
import { supabase, getSupabaseClient } from "@/lib/supabase/client";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import CsvImportModal, { type ImportRow } from "@/components/CsvImportModal";
import { buildEmployees, EMPLOYEE_IMPORT_COLUMNS } from "@/lib/imports/mappers";
import { downloadCsv } from "@/components/ui/data-table";
import { toCsv } from "@/lib/table/process";

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

type Tab = "dashboard" | "employees" | "structures" | "runs" | "statutory" | "reports";

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
  status: "draft" | "review" | "finalized";
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
  pf_total_paise: number;
  esi_total_paise: number;
  pt_total_paise: number;
  tds_24q_paise: number;
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
    const [r, e] = await Promise.all([
      db.from("payroll_runs").select("*").eq("client_id", clientId).order("month", { ascending: false }),
      db.from("payroll_employees").select("*").eq("client_id", clientId).eq("status", "active").order("name"),
    ]);
    if (r.error || e.error) { setLoadFailed(true); setLoading(false); return; }
    setRuns((r.data as PayrollRun[]) ?? []);
    setEmployees((e.data as Employee[]) ?? []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="p-6 space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-[#F1F5F9] rounded-xl animate-pulse" />)}</div>;

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
  const [form, setForm] = useState({ name: "", aadhaar: "", designation: "", department: "", basic_paise: "", hra_percent: "40", pf_applicable: true, esi_applicable: true, pt_applicable: false });
  const [aadhaarError, setAadhaarError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // M17: distinguish a failed roster fetch from a client with no employees.
  const [loadFailed, setLoadFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    const res = await apiFetch<Employee[]>(`/api/payroll/employees?client_id=${clientId}`).catch(() => null);
    if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setLoading(false); return; }
    setEmployees(res.data || []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  /** Bulk-import employees through the EXISTING /api/payroll/employees endpoint. */
  async function handleImport(rows: ImportRow[]): Promise<{ imported: number; errors: string[] }> {
    const { records, errors } = buildEmployees(rows, clientId, firmId);
    let imported = 0;
    for (const emp of records) {
      // Responses follow the { success, data, error } contract.
      const res = await apiFetch<unknown>("/api/payroll/employees", {
        method: "POST",
        body: JSON.stringify(emp),
      }).catch(() => null) as { success?: boolean; error?: string | null } | null;
      if (res && res.success !== false) imported++;
      else errors.push(`Employee "${emp.name}": ${res?.error ?? "request failed"}`);
    }
    if (imported > 0) await load();
    return { imported, errors };
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
    setSaveError(null);
    setSaving(true);
    const res = await apiFetch("/api/payroll/employees", {
      method: "POST",
      body: JSON.stringify({
        client_id: clientId,
        firm_id: firmId,
        ...rest,
        aadhaar_last4: aadhaarDigits ? aadhaarDigits.slice(-4) : undefined,
        basic_paise: Math.round(parseFloat(form.basic_paise) * 100),
        hra_percent: parseFloat(form.hra_percent),
      }),
    }).catch(() => null) as { success?: boolean; error?: string | null } | null;
    setSaving(false);
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
    setForm({ name: "", aadhaar: "", designation: "", department: "", basic_paise: "", hra_percent: "40", pf_applicable: true, esi_applicable: true, pt_applicable: false });
  }

  if (loading) return <div className="p-6 space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-12 bg-[#F1F5F9] rounded-lg animate-pulse" />)}</div>;

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
  const [finalizeError, setFinalizeError] = useState<string | null>(null);

  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadFailed(false);
    const res = await apiFetch<PayrollRun[]>(`/api/payroll/runs?client_id=${clientId}`).catch(() => null);
    if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setLoading(false); return; }
    setRuns(res.data || []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function createRun() {
    setCreating(true);
    setCreateError(null);
    const res = await apiFetch("/api/payroll/runs", { method: "POST", body: JSON.stringify({ client_id: clientId, firm_id: firmId, month }) })
      .catch(() => null) as { success?: boolean; error?: string | null } | null;
    setCreating(false);
    // task #229: previously discarded — a duplicate-run 409 or RBAC/guardrail
    // rejection produced silent no-op with zero explanation of why nothing
    // happened.
    if (!res || res.success === false) {
      setCreateError(res?.error ?? "Could not create the payroll run — the request failed.");
      return;
    }
    await load();
  }

  async function finalizeRun(runId: string) {
    setFinalizing(runId);
    setFinalizeError(null);
    const res = await apiFetch(`/api/payroll/runs/${runId}/finalize`, { method: "POST", body: JSON.stringify({}) })
      .catch(() => null) as { success?: boolean; error?: string | null } | null;
    setFinalizing(null);
    // task #229: finalize posts a real, immutable GL journal — a silently
    // discarded failure (empty run, journal-posting error, already
    // finalized) left the CA with no idea the run was still a draft.
    if (!res || res.success === false) {
      setFinalizeError(res?.error ?? "Could not finalize the payroll run — the request failed.");
      return;
    }
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

  if (loading) return <div className="p-6"><div className="h-32 bg-[#F1F5F9] rounded-xl animate-pulse" /></div>;

  return (
    <div className="p-5 space-y-4">
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
      </div>

      {finalizeError && <p className="text-xs text-red-600 bg-red-50 rounded px-3 py-2">{finalizeError}</p>}

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
                {r.status !== "finalized" && (
                  <button onClick={() => finalizeRun(r.id)} disabled={finalizing === r.id}
                    className="flex items-center gap-1 text-[11px] px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50">
                    <CheckCircle size={11} /> {finalizing === r.id ? "Finalizing…" : "Finalize"}
                  </button>
                )}
                {r.status === "finalized" && (
                  <span className="text-[11px] text-emerald-600 flex items-center gap-1"><CheckCircle size={11} /> Finalized</span>
                )}
              </div>
            </div>

            {selectedRun === r.id && (
              <div className="border-t border-[#F1F5F9] px-4 py-3">
                {loadingSlips ? (
                  <div className="space-y-2">{[...Array(3)].map((_, i) => <div key={i} className="h-8 bg-[#F1F5F9] rounded animate-pulse" />)}</div>
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
    const res = await apiFetch<StatutoryData>(`/api/payroll/reports/statutory-summary?client_id=${clientId}&month=${month}`).catch(() => null);
    if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setData(null); setLoading(false); return; }
    setData(res.data);
    setLoading(false);
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
            { label: "PF Challan (Employer + Employee)", amount: data.pf_total_paise, due: "15th of following month", color: "blue" },
            { label: "ESI Challan (Employer + Employee)", amount: data.esi_total_paise, due: "15th of following month", color: "green" },
            { label: "PT Challan", amount: data.pt_total_paise, due: "varies by state", color: "amber" },
            { label: "TDS — 24Q", amount: data.tds_24q_paise, due: "7th of following month", color: "red" },
          ].map(({ label, amount, due, color }) => (
            <div key={label} className="bg-white rounded-xl border border-[#E2E8F0] p-4">
              <p className="text-[11px] font-semibold text-[#64748B]">{label}</p>
              <p className={`text-2xl font-bold mt-1 text-${color}-600`}>{fmt(amount ?? 0)}</p>
              <p className="text-[10px] text-[#94A3B8] mt-1">Due: {due}</p>
            </div>
          ))}
        </div>
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
  const [tab, setTab] = useState<Tab>("dashboard");
  const [firmId, setFirmId] = useState<string>("");

  useEffect(() => { getFirmId().then(setFirmId).catch(() => {}); }, []);

  const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
    { id: "dashboard",  label: "Dashboard",       icon: TrendingUp },
    { id: "employees",  label: "Employees",        icon: Users },
    { id: "structures", label: "Salary Structures", icon: Building2 },
    { id: "runs",       label: "Payroll Runs",     icon: Play },
    { id: "statutory",  label: "Statutory",        icon: FileText },
    { id: "reports",    label: "Reports",          icon: Download },
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
        {tab === "dashboard"  && <DashboardTab clientId={clientId} />}
        {tab === "employees"  && <EmployeesTab clientId={clientId} firmId={firmId} />}
        {tab === "structures" && <SalaryStructuresTab clientId={clientId} firmId={firmId} />}
        {tab === "runs"       && <RunsTab clientId={clientId} firmId={firmId} />}
        {tab === "statutory"  && <StatutoryTab clientId={clientId} />}
        {tab === "reports"    && <ReportsTab clientId={clientId} />}
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
    const res = await apiFetch<SalaryStructure[]>(`/api/payroll/salary-structures?client_id=${clientId}`).catch(() => null);
    if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setLoading(false); return; }
    setStructures(res.data || []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function addStructure() {
    setSaving(true);
    setSaveError(null);
    const res = await apiFetch("/api/payroll/salary-structures", {
      method: "POST",
      body: JSON.stringify({ client_id: clientId, firm_id: firmId, ...form, basic_percent: parseFloat(form.basic_percent), hra_percent: parseFloat(form.hra_percent) }),
    }).catch(() => null) as { success?: boolean; error?: string | null } | null;
    setSaving(false);
    // task #229: previously discarded — a rejected structure looked identical
    // to a saved one, and the modal closed as if it had worked.
    if (!res || res.success === false) {
      setSaveError(res?.error ?? "Could not save the salary structure — the request failed.");
      return;
    }
    await load();
    setShowAdd(false);
  }

  if (loading) return <div className="p-6"><div className="h-32 bg-[#F1F5F9] rounded-xl animate-pulse" /></div>;

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

  async function load() {
    setLoading(true);
    setLoadFailed(false);
    const res = await apiFetch<SalaryRegister>(`/api/payroll/reports/salary-register?client_id=${clientId}&month=${month}`).catch(() => null);
    if (!res || (res as { success?: boolean }).success === false) { setLoadFailed(true); setData(null); setLoading(false); return; }
    setData(res.data);
    setLoading(false);
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center gap-3">
        <input type="month" value={month} onChange={e => setMonth(e.target.value)}
          className="border border-[#E2E8F0] rounded-lg px-3 py-1.5 text-[13px] outline-none focus:border-blue-400" />
        <button onClick={load} disabled={loading} className="px-4 py-1.5 bg-blue-600 text-white text-[12px] rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {loading ? "Loading…" : "Load Salary Register"}
        </button>
      </div>
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
