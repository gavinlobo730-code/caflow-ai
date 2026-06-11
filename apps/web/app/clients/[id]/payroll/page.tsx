"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Users, Plus, Play, CheckCircle, AlertCircle, ChevronDown,
  FileText, TrendingUp, IndianRupee, Download, RefreshCw,
  Building2, CreditCard, User
} from "lucide-react";
import { cn } from "@/lib/utils";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { useClientNav } from "@/lib/workspace/ClientNavContext";
import { api } from "@/lib/api";

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

// ─── Dashboard Tab ────────────────────────────────────────────────────────────

function DashboardTab({ clientId }: { clientId: string }) {
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get(`/api/payroll/runs?client_id=${clientId}`).catch(() => ({ data: [] })),
      api.get(`/api/payroll/employees?client_id=${clientId}`).catch(() => ({ data: [] })),
    ]).then(([r, e]) => {
      setRuns(r.data || []);
      setEmployees(e.data || []);
      setLoading(false);
    });
  }, [clientId]);

  if (loading) return <div className="p-6 space-y-3">{[...Array(4)].map((_, i) => <div key={i} className="h-20 bg-[#F1F5F9] rounded-xl animate-pulse" />)}</div>;

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

function EmployeesTab({ clientId, firmId }: { clientId: string; firmId: string }) {
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", designation: "", department: "", basic_paise: "", hra_percent: "40", pf_applicable: true, esi_applicable: true, pt_applicable: false });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const res = await api.get(`/api/payroll/employees?client_id=${clientId}`).catch(() => ({ data: [] }));
    setEmployees(res.data || []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function addEmployee() {
    if (!form.name || !form.basic_paise) return;
    setSaving(true);
    await api.post("/api/payroll/employees", {
      client_id: clientId,
      firm_id: firmId,
      ...form,
      basic_paise: Math.round(parseFloat(form.basic_paise) * 100),
      hra_percent: parseFloat(form.hra_percent),
    }).catch(() => null);
    await load();
    setShowAdd(false);
    setForm({ name: "", designation: "", department: "", basic_paise: "", hra_percent: "40", pf_applicable: true, esi_applicable: true, pt_applicable: false });
    setSaving(false);
  }

  if (loading) return <div className="p-6 space-y-2">{[...Array(5)].map((_, i) => <div key={i} className="h-12 bg-[#F1F5F9] rounded-lg animate-pulse" />)}</div>;

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-semibold text-[#1E293B]">{employees.length} active employees</p>
        <button onClick={() => setShowAdd(!showAdd)} className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-[12px] font-medium rounded-lg hover:bg-blue-700 transition-colors">
          <Plus size={13} /> Add Employee
        </button>
      </div>

      {showAdd && (
        <div className="bg-[#F8FAFC] rounded-xl border border-[#E2E8F0] p-4 space-y-3">
          <p className="text-[12px] font-semibold text-[#1E293B]">New Employee</p>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name *" value={form.name} onChange={v => setForm(f => ({...f, name: v}))} placeholder="Employee name" />
            <Field label="Designation" value={form.designation} onChange={v => setForm(f => ({...f, designation: v}))} placeholder="e.g. Manager" />
            <Field label="Department" value={form.department} onChange={v => setForm(f => ({...f, department: v}))} placeholder="e.g. Accounts" />
            <Field label="Basic Salary (₹/month) *" value={form.basic_paise} onChange={v => setForm(f => ({...f, basic_paise: v}))} placeholder="e.g. 25000" type="number" />
            <Field label="HRA %" value={form.hra_percent} onChange={v => setForm(f => ({...f, hra_percent: v}))} placeholder="40" type="number" />
          </div>
          <div className="flex items-center gap-4">
            {(["pf_applicable", "esi_applicable", "pt_applicable"] as const).map(k => (
              <label key={k} className="flex items-center gap-1.5 text-[12px] text-[#64748B] cursor-pointer">
                <input type="checkbox" checked={form[k]} onChange={e => setForm(f => ({...f, [k]: e.target.checked}))} className="rounded" />
                {k === "pf_applicable" ? "PF" : k === "esi_applicable" ? "ESI" : "PT"}
              </label>
            ))}
          </div>
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

  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);

  const load = useCallback(async () => {
    const res = await api.get(`/api/payroll/runs?client_id=${clientId}`).catch(() => ({ data: [] }));
    setRuns(res.data || []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function createRun() {
    setCreating(true);
    await api.post("/api/payroll/runs", { client_id: clientId, firm_id: firmId, month }).catch(() => null);
    await load();
    setCreating(false);
  }

  async function finalizeRun(runId: string) {
    setFinalizing(runId);
    await api.post(`/api/payroll/runs/${runId}/finalize`, {}).catch(() => null);
    await load();
    setFinalizing(null);
  }

  async function loadSlips(runId: string) {
    if (selectedRun === runId) { setSelectedRun(null); return; }
    setSelectedRun(runId);
    setLoadingSlips(true);
    const res = await api.get(`/api/payroll/runs/${runId}/slips`).catch(() => ({ data: [] }));
    setSlips(res.data || []);
    setLoadingSlips(false);
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
      </div>

      <div className="space-y-2">
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
      </div>
    </div>
  );
}

// ─── Statutory Tab ────────────────────────────────────────────────────────────

function StatutoryTab({ clientId }: { clientId: string }) {
  const now = new Date();
  const defaultMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const [month, setMonth] = useState(defaultMonth);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    const res = await api.get(`/api/payroll/reports/statutory-summary?client_id=${clientId}&month=${month}`).catch(() => ({ data: null }));
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
              <p className={`text-2xl font-bold mt-1 text-${color}-600`}>{fmt(amount || 0)}</p>
              <p className="text-[10px] text-[#94A3B8] mt-1">Due: {due}</p>
            </div>
          ))}
        </div>
      )}

      {!data && !loading && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] p-8 text-center text-[#94A3B8] text-sm">
          Select a month and click Load to view statutory dues
        </div>
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
  const [structures, setStructures] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ name: "", basic_percent: "40", hra_percent: "20", pf_applicable: true, esi_applicable: true });
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    const res = await api.get(`/api/payroll/salary-structures?client_id=${clientId}`).catch(() => ({ data: [] }));
    setStructures(res.data || []);
    setLoading(false);
  }, [clientId]);

  useEffect(() => { load(); }, [load]);

  async function addStructure() {
    setSaving(true);
    await api.post("/api/payroll/salary-structures", { client_id: clientId, firm_id: firmId, ...form, basic_percent: parseFloat(form.basic_percent), hra_percent: parseFloat(form.hra_percent) }).catch(() => null);
    await load();
    setShowAdd(false);
    setSaving(false);
  }

  if (loading) return <div className="p-6"><div className="h-32 bg-[#F1F5F9] rounded-xl animate-pulse" /></div>;

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
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    const res = await api.get(`/api/payroll/reports/salary-register?client_id=${clientId}&month=${month}`).catch(() => ({ data: null }));
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
      {data?.slips?.length > 0 && (
        <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
          <div className="px-4 py-3 border-b border-[#F1F5F9] flex items-center justify-between">
            <p className="text-[12px] font-semibold text-[#1E293B]">Salary Register — {fmtMonth(month)}</p>
            <span className="text-[11px] text-[#94A3B8]">{data.slips.length} employees</span>
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
              {data.slips.map((s: Slip) => (
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
      {data && !data.slips?.length && <p className="text-center text-sm text-[#94A3B8] py-8">No salary data for {fmtMonth(month)}</p>}
    </div>
  );
}
