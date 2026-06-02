"use client";

/**
 * Payroll Module — IT Act Section 192 (TDS on Salary), ESI Act, EPF Act
 * All monetary values stored and computed in integer paise.
 */

import { useState, useEffect, useCallback } from "react";
import { Users, Play, FileText, Shield, Plus, X, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ── Types ──────────────────────────────────────────────────────────────────

type Client = { id: string; client_name: string };

type Employee = {
  id: string;
  firm_id: string;
  client_id: string;
  name: string;
  pan: string;
  designation: string;
  basic_paise: number;
  hra_percent: number;
  da_percent: number;
  other_allowances_paise: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
};

type PayrollRun = {
  id: string;
  firm_id: string;
  client_id: string;
  month: string;
  status: string;
  generated_at: string;
};

type PayrollSlip = {
  id: string;
  run_id: string;
  employee_id: string;
  gross_paise: number;
  pf_employee_paise: number;
  esi_employee_paise: number;
  pt_paise: number;
  tds_paise: number;
  net_paise: number;
  employee?: Employee;
  run?: PayrollRun;
};

// ── Paise helpers ─────────────────────────────────────────────────────────

function fmtRs(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  return `₹${rupees.toLocaleString("en-IN")}.${p.toString().padStart(2, "0")}`;
}

function rsToP(rs: number): number {
  return Math.round(rs * 100);
}

/**
 * Compute payroll for one employee — all integer paise arithmetic.
 * IT Act Section 192: TDS on salary via new-regime basic slab rates.
 * ESI Act: employee 0.75%, employer 3.25% of gross (gross <= Rs 21,000/month).
 * EPF Act: PF employee 12% of basic, capped Rs 1,800/month.
 */
function computeSlip(emp: Employee, ptState: string): {
  gross: number; pf: number; esi: number; pt: number; tds: number; net: number;
} {
  const basic = emp.basic_paise;
  const hra = Math.round(basic * emp.hra_percent / 100);
  const da = Math.round(basic * emp.da_percent / 100);
  const gross = basic + hra + da + emp.other_allowances_paise;

  // PF: 12% of basic, max Rs 1,800/month (EPF Act)
  let pf = 0;
  if (emp.pf_applicable) {
    pf = Math.min(Math.round(basic * 12 / 100), 180000);
  }

  // ESI: 0.75% of gross if gross <= Rs 21,000/month (ESI Act)
  let esi = 0;
  if (emp.esi_applicable && gross <= 2100000) {
    esi = Math.round(gross * 75 / 10000); // 0.75%
  }

  // Professional Tax by state
  let pt = 0;
  if (ptState === "MH" && gross > 1000000) {
    pt = 20000; // Rs 200 in paise
  } else if (ptState === "KA" && gross > 1500000) {
    pt = 20000;
  } else if (ptState === "WB" && gross > 1000000) {
    pt = 20000;
  } else if (ptState === "TN" && gross > 2100000) {
    pt = 20800;
  }

  // TDS estimate — IT Act Section 192, new regime slabs (FY 2024-25)
  const annualGross = gross * 12;
  let annualTax = 0;
  if (annualGross > 1500000) {
    annualTax = Math.round((annualGross - 1500000) * 30 / 100) + 12500 * 100;
  } else if (annualGross > 1250000) {
    annualTax = Math.round((annualGross - 1250000) * 25 / 100) + 7500 * 100;
  } else if (annualGross > 1000000) {
    annualTax = Math.round((annualGross - 1000000) * 20 / 100) + 5000 * 100;
  } else if (annualGross > 750000) {
    annualTax = Math.round((annualGross - 750000) * 15 / 100) + 2500 * 100;
  } else if (annualGross > 500000) {
    annualTax = Math.round((annualGross - 500000) * 10 / 100);
  }
  const tds = annualGross <= 700000 ? 0 : Math.round(annualTax / 12);

  const net = gross - pf - esi - pt - tds;
  return { gross, pf, esi, pt, tds, net };
}

const PT_STATES = [
  { code: "MH", label: "Maharashtra — Rs 200/month if > Rs 10,000" },
  { code: "KA", label: "Karnataka — Rs 200/month if > Rs 15,000" },
  { code: "WB", label: "West Bengal — Rs 200/month if > Rs 10,000" },
  { code: "TN", label: "Tamil Nadu — Rs 208/month if > Rs 21,000" },
  { code: "NONE", label: "No Professional Tax" },
];

const INSTALL_SQL = `-- Run in Supabase SQL editor:
CREATE TABLE IF NOT EXISTS payroll_employees (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  client_id UUID NOT NULL,
  name TEXT NOT NULL,
  pan TEXT,
  designation TEXT,
  basic_paise BIGINT NOT NULL DEFAULT 0,
  hra_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
  da_percent NUMERIC(5,2) NOT NULL DEFAULT 0,
  other_allowances_paise BIGINT NOT NULL DEFAULT 0,
  pf_applicable BOOLEAN NOT NULL DEFAULT false,
  esi_applicable BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payroll_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  client_id UUID NOT NULL,
  month TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  generated_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS payroll_slips (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id UUID NOT NULL REFERENCES payroll_runs(id),
  employee_id UUID NOT NULL REFERENCES payroll_employees(id),
  gross_paise BIGINT NOT NULL,
  pf_employee_paise BIGINT NOT NULL DEFAULT 0,
  esi_employee_paise BIGINT NOT NULL DEFAULT 0,
  pt_paise BIGINT NOT NULL DEFAULT 0,
  tds_paise BIGINT NOT NULL DEFAULT 0,
  net_paise BIGINT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);`;

// ── Add Employee Modal ────────────────────────────────────────────────────

function AddEmployeeModal({
  clients,
  firmId,
  onClose,
  onSaved,
}: {
  clients: Client[];
  firmId: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    client_id: clients[0]?.id ?? "",
    name: "",
    pan: "",
    designation: "",
    basic_rs: "",
    hra_percent: "40",
    da_percent: "10",
    other_rs: "0",
    pf_applicable: false,
    esi_applicable: false,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  async function save() {
    if (!form.name || !form.basic_rs) { setErr("Name and Basic Salary are required."); return; }
    setSaving(true);
    const sb = getSupabaseClient();
    const { error } = await sb.from("payroll_employees").insert({
      firm_id: firmId,
      client_id: form.client_id,
      name: form.name,
      pan: form.pan.toUpperCase(),
      designation: form.designation,
      basic_paise: rsToP(parseFloat(form.basic_rs) || 0),
      hra_percent: parseFloat(form.hra_percent) || 0,
      da_percent: parseFloat(form.da_percent) || 0,
      other_allowances_paise: rsToP(parseFloat(form.other_rs) || 0),
      pf_applicable: form.pf_applicable,
      esi_applicable: form.esi_applicable,
    });
    setSaving(false);
    if (error) { setErr(error.message); return; }
    onSaved();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold text-gray-900">Add Employee</h2>
          <button onClick={onClose}><X size={16} /></button>
        </div>
        {err && <p className="text-red-600 text-sm mb-3">{err}</p>}
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
            <select className="w-full border rounded-lg px-3 py-2 text-sm" value={form.client_id} onChange={e => setForm(f => ({ ...f, client_id: e.target.value }))}>
              {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Name *</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">PAN</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm uppercase" value={form.pan} onChange={e => setForm(f => ({ ...f, pan: e.target.value }))} maxLength={10} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Designation</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={form.designation} onChange={e => setForm(f => ({ ...f, designation: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Basic Salary (Rs/month) *</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.basic_rs} onChange={e => setForm(f => ({ ...f, basic_rs: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">HRA %</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.hra_percent} onChange={e => setForm(f => ({ ...f, hra_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">DA %</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.da_percent} onChange={e => setForm(f => ({ ...f, da_percent: e.target.value }))} />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Other Allowances (Rs)</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={form.other_rs} onChange={e => setForm(f => ({ ...f, other_rs: e.target.value }))} />
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="pf" checked={form.pf_applicable} onChange={e => setForm(f => ({ ...f, pf_applicable: e.target.checked }))} />
            <label htmlFor="pf" className="text-sm text-gray-700">PF Applicable (12% of basic)</label>
          </div>
          <div className="flex items-center gap-2">
            <input type="checkbox" id="esi" checked={form.esi_applicable} onChange={e => setForm(f => ({ ...f, esi_applicable: e.target.checked }))} />
            <label htmlFor="esi" className="text-sm text-gray-700">ESI Applicable (if &le; Rs 21,000)</label>
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-5">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={save} disabled={saving}>{saving ? "Saving..." : "Add Employee"}</Button>
        </div>
      </div>
    </div>
  );
}

// ── Payslip Modal ─────────────────────────────────────────────────────────

function PayslipModal({ slip, onClose }: { slip: PayrollSlip; onClose: () => void }) {
  const emp = slip.employee!;
  const run = slip.run!;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex justify-between items-center mb-4">
          <h2 className="font-semibold">Payslip</h2>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={() => window.print()}>Print</Button>
            <button onClick={onClose}><X size={16} /></button>
          </div>
        </div>
        <div className="border-b pb-3 mb-3">
          <h3 className="font-bold text-lg text-gray-900">{emp.name}</h3>
          <p className="text-sm text-gray-600">{emp.designation} {emp.pan ? `• ${emp.pan}` : ""}</p>
          <p className="text-sm text-gray-600">Month: {run.month}</p>
        </div>
        <table className="w-full text-sm">
          <tbody>
            <tr className="border-b">
              <td className="py-1 text-gray-600">Gross Salary</td>
              <td className="py-1 text-right font-medium">{fmtRs(slip.gross_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-gray-600">PF Deduction (12% of Basic)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.pf_employee_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-gray-600">ESI Deduction (0.75%)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.esi_employee_paise)}</td>
            </tr>
            <tr>
              <td className="py-1 text-gray-600">Professional Tax</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.pt_paise)}</td>
            </tr>
            <tr className="border-b">
              <td className="py-1 text-gray-600">TDS on Salary (IT Act Sec 192)</td>
              <td className="py-1 text-right text-red-600">- {fmtRs(slip.tds_paise)}</td>
            </tr>
            <tr className="font-bold">
              <td className="py-2 text-gray-900">Net Pay</td>
              <td className="py-2 text-right text-green-700">{fmtRs(slip.net_paise)}</td>
            </tr>
          </tbody>
        </table>
        <p className="text-[10px] text-gray-400 mt-4 text-center">Generated by CAflow AI</p>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function PayrollPage() {
  const [firmId, setFirmId] = useState<string | null>(null);
  const [tablesError, setTablesError] = useState(false);
  const [clients, setClients] = useState<Client[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [runs, setRuns] = useState<PayrollRun[]>([]);
  const [slips, setSlips] = useState<PayrollSlip[]>([]);
  const [loading, setLoading] = useState(true);

  const [runClientId, setRunClientId] = useState("");
  const [runMonth, setRunMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [ptState, setPtState] = useState("MH");
  const [runEmployees, setRunEmployees] = useState<Employee[]>([]);
  const [generating, setGenerating] = useState(false);

  const [statMonth, setStatMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [statClientId, setStatClientId] = useState("");
  const [statSlips, setStatSlips] = useState<PayrollSlip[]>([]);

  const [showAdd, setShowAdd] = useState(false);
  const [viewSlip, setViewSlip] = useState<PayrollSlip | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fid = await getFirmId();
      setFirmId(fid);
      const sb = getSupabaseClient();
      const [clientsRes, empRes, runsRes] = await Promise.all([
        sb.from("clients").select("id, client_name").eq("firm_id", fid),
        sb.from("payroll_employees").select("*").eq("firm_id", fid),
        sb.from("payroll_runs").select("*").eq("firm_id", fid).order("generated_at", { ascending: false }),
      ]);
      if (empRes.error?.message?.includes("does not exist")) {
        setTablesError(true);
        setLoading(false);
        return;
      }
      setClients(clientsRes.data ?? []);
      setEmployees(empRes.data ?? []);
      setRuns(runsRes.data ?? []);

      if (runsRes.data && runsRes.data.length > 0) {
        const runIds = runsRes.data.map(r => r.id);
        const slipsRes = await sb.from("payroll_slips").select("*").in("run_id", runIds);
        const rawSlips: PayrollSlip[] = slipsRes.data ?? [];
        const enriched = rawSlips.map(s => ({
          ...s,
          employee: (empRes.data ?? []).find((e: Employee) => e.id === s.employee_id),
          run: runsRes.data!.find(r => r.id === s.run_id),
        }));
        setSlips(enriched);
      }
    } catch { /* not authenticated */ }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (runClientId) {
      setRunEmployees(employees.filter(e => e.client_id === runClientId));
    }
  }, [runClientId, employees]);

  useEffect(() => {
    if (clients.length > 0 && !runClientId) {
      setRunClientId(clients[0].id);
      setStatClientId(clients[0].id);
    }
  }, [clients, runClientId]);

  useEffect(() => {
    if (statClientId) {
      const monthRuns = runs.filter(r => r.client_id === statClientId && r.month === statMonth);
      const runIds = monthRuns.map(r => r.id);
      setStatSlips(slips.filter(s => runIds.includes(s.run_id)));
    }
  }, [statClientId, statMonth, runs, slips]);

  async function generatePayslips() {
    if (!firmId || !runClientId || runEmployees.length === 0) return;
    setGenerating(true);
    const sb = getSupabaseClient();
    const { data: run, error: runErr } = await sb.from("payroll_runs").insert({
      firm_id: firmId,
      client_id: runClientId,
      month: runMonth,
      status: "generated",
    }).select().single();
    if (runErr || !run) { setGenerating(false); return; }

    const slipRows = runEmployees.map(emp => {
      const calc = computeSlip(emp, ptState);
      return {
        run_id: run.id,
        employee_id: emp.id,
        gross_paise: calc.gross,
        pf_employee_paise: calc.pf,
        esi_employee_paise: calc.esi,
        pt_paise: calc.pt,
        tds_paise: calc.tds,
        net_paise: calc.net,
      };
    });
    await sb.from("payroll_slips").insert(slipRows);
    setGenerating(false);
    load();
  }

  if (loading) {
    return <div className="min-h-screen bg-gray-50 flex items-center justify-center"><p className="text-gray-500">Loading payroll...</p></div>;
  }

  if (tablesError) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <Card className="max-w-2xl mx-auto">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle size={18} className="text-amber-500" />
              Install Payroll Tables
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-gray-600 mb-4">The payroll tables do not exist yet. Run this SQL in your Supabase dashboard:</p>
            <pre className="bg-gray-900 text-green-400 p-4 rounded-lg text-xs overflow-auto whitespace-pre-wrap">{INSTALL_SQL}</pre>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      {showAdd && firmId && (
        <AddEmployeeModal
          clients={clients}
          firmId={firmId}
          onClose={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load(); }}
        />
      )}
      {viewSlip && <PayslipModal slip={viewSlip} onClose={() => setViewSlip(null)} />}

      <div className="max-w-6xl mx-auto">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Payroll</h1>
          <p className="text-sm text-gray-500 mt-0.5">IT Act Section 192 &middot; EPF Act &middot; ESI Act</p>
        </div>

        <Tabs defaultValue="employees">
          <TabsList className="mb-6">
            <TabsTrigger value="employees" className="flex items-center gap-1.5"><Users size={14} />Employees</TabsTrigger>
            <TabsTrigger value="monthly" className="flex items-center gap-1.5"><Play size={14} />Monthly Run</TabsTrigger>
            <TabsTrigger value="payslips" className="flex items-center gap-1.5"><FileText size={14} />Payslips</TabsTrigger>
            <TabsTrigger value="statutory" className="flex items-center gap-1.5"><Shield size={14} />Statutory</TabsTrigger>
          </TabsList>

          {/* EMPLOYEES TAB */}
          <TabsContent value="employees">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <CardTitle>Employees</CardTitle>
                <Button size="sm" onClick={() => setShowAdd(true)} className="flex items-center gap-1.5">
                  <Plus size={14} />Add Employee
                </Button>
              </CardHeader>
              <CardContent>
                {employees.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <Users size={32} className="mx-auto mb-3 opacity-30" />
                    <p>No employees yet. Click &quot;Add Employee&quot; to get started.</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-gray-500 uppercase tracking-wide">
                          <th className="text-left py-3 px-4">Name</th>
                          <th className="text-left py-3 px-4">PAN</th>
                          <th className="text-left py-3 px-4">Designation</th>
                          <th className="text-right py-3 px-4">Monthly CTC</th>
                          <th className="text-center py-3 px-4">PF</th>
                          <th className="text-center py-3 px-4">ESI</th>
                        </tr>
                      </thead>
                      <tbody>
                        {employees.map(emp => {
                          const gross = emp.basic_paise
                            + Math.round(emp.basic_paise * emp.hra_percent / 100)
                            + Math.round(emp.basic_paise * emp.da_percent / 100)
                            + emp.other_allowances_paise;
                          return (
                            <tr key={emp.id} className="border-b hover:bg-gray-50">
                              <td className="py-3 px-4 font-medium">{emp.name}</td>
                              <td className="py-3 px-4 font-mono text-xs">{emp.pan || "—"}</td>
                              <td className="py-3 px-4 text-gray-600">{emp.designation || "—"}</td>
                              <td className="py-3 px-4 text-right font-mono">{fmtRs(gross)}</td>
                              <td className="py-3 px-4 text-center">
                                <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${emp.pf_applicable ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                                  {emp.pf_applicable ? "Yes" : "No"}
                                </span>
                              </td>
                              <td className="py-3 px-4 text-center">
                                <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${emp.esi_applicable ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
                                  {emp.esi_applicable ? "Yes" : "No"}
                                </span>
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

          {/* MONTHLY RUN TAB */}
          <TabsContent value="monthly">
            <Card className="mb-4">
              <CardContent className="pt-5">
                <div className="flex flex-wrap gap-4 items-end">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
                    <select className="border rounded-lg px-3 py-2 text-sm" value={runClientId} onChange={e => setRunClientId(e.target.value)}>
                      {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Month</label>
                    <input type="month" className="border rounded-lg px-3 py-2 text-sm" value={runMonth} onChange={e => setRunMonth(e.target.value)} />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">PT State</label>
                    <select className="border rounded-lg px-3 py-2 text-sm" value={ptState} onChange={e => setPtState(e.target.value)}>
                      {PT_STATES.map(s => <option key={s.code} value={s.code}>{s.label}</option>)}
                    </select>
                  </div>
                  <Button
                    onClick={generatePayslips}
                    disabled={generating || runEmployees.length === 0}
                    className="flex items-center gap-1.5"
                  >
                    <Play size={14} />{generating ? "Generating..." : "Generate Payslips"}
                  </Button>
                </div>
              </CardContent>
            </Card>
            {runEmployees.length === 0 ? (
              <Card><CardContent className="py-12 text-center text-gray-400">No employees for this client.</CardContent></Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-gray-500 uppercase tracking-wide">
                          <th className="text-left py-3 px-4">Employee</th>
                          <th className="text-right py-3 px-4">Gross</th>
                          <th className="text-right py-3 px-4">PF Emp</th>
                          <th className="text-right py-3 px-4">ESI Emp</th>
                          <th className="text-right py-3 px-4">PT</th>
                          <th className="text-right py-3 px-4">TDS (Sec 192)</th>
                          <th className="text-right py-3 px-4">Net Pay</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runEmployees.map(emp => {
                          const c = computeSlip(emp, ptState);
                          return (
                            <tr key={emp.id} className="border-b hover:bg-gray-50">
                              <td className="py-3 px-4 font-medium">{emp.name}</td>
                              <td className="py-3 px-4 text-right font-mono">{fmtRs(c.gross)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.pf)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.esi)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.pt)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(c.tds)}</td>
                              <td className="py-3 px-4 text-right font-mono font-semibold text-green-700">{fmtRs(c.net)}</td>
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

          {/* PAYSLIPS TAB */}
          <TabsContent value="payslips">
            <Card>
              <CardHeader><CardTitle>Generated Payslips</CardTitle></CardHeader>
              <CardContent>
                {slips.length === 0 ? (
                  <div className="text-center py-12 text-gray-400">
                    <FileText size={32} className="mx-auto mb-3 opacity-30" />
                    <p>No payslips generated yet. Run a Monthly Run to generate payslips.</p>
                  </div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-gray-500 uppercase tracking-wide">
                          <th className="text-left py-3 px-4">Employee</th>
                          <th className="text-left py-3 px-4">Month</th>
                          <th className="text-right py-3 px-4">Gross</th>
                          <th className="text-right py-3 px-4">Deductions</th>
                          <th className="text-right py-3 px-4">Net Pay</th>
                          <th className="py-3 px-4"></th>
                        </tr>
                      </thead>
                      <tbody>
                        {slips.map(s => {
                          const deductions = s.pf_employee_paise + s.esi_employee_paise + s.pt_paise + s.tds_paise;
                          return (
                            <tr key={s.id} className="border-b hover:bg-gray-50">
                              <td className="py-3 px-4 font-medium">{s.employee?.name ?? "—"}</td>
                              <td className="py-3 px-4 text-gray-600">{s.run?.month ?? "—"}</td>
                              <td className="py-3 px-4 text-right font-mono">{fmtRs(s.gross_paise)}</td>
                              <td className="py-3 px-4 text-right font-mono text-red-600">{fmtRs(deductions)}</td>
                              <td className="py-3 px-4 text-right font-mono font-semibold text-green-700">{fmtRs(s.net_paise)}</td>
                              <td className="py-3 px-4">
                                <Button size="sm" variant="outline" onClick={() => setViewSlip(s)}>View</Button>
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

          {/* STATUTORY TAB */}
          <TabsContent value="statutory">
            <Card className="mb-4">
              <CardContent className="pt-5">
                <div className="flex gap-4 items-end">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
                    <select className="border rounded-lg px-3 py-2 text-sm" value={statClientId} onChange={e => setStatClientId(e.target.value)}>
                      {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">Month</label>
                    <input type="month" className="border rounded-lg px-3 py-2 text-sm" value={statMonth} onChange={e => setStatMonth(e.target.value)} />
                  </div>
                </div>
              </CardContent>
            </Card>
            {statSlips.length === 0 ? (
              <Card><CardContent className="py-12 text-center text-gray-400">No payroll runs for selected month/client.</CardContent></Card>
            ) : (() => {
              const emps = statSlips.map(s => s.employee).filter(Boolean) as Employee[];
              let totalPfEmp = 0, totalPfEmployer = 0, totalEsiEmp = 0, totalEsiEmployer = 0, totalPt = 0, totalTds = 0;
              statSlips.forEach((s, i) => {
                const emp = emps[i];
                totalPfEmp += s.pf_employee_paise;
                totalPfEmployer += emp ? Math.min(Math.round(emp.basic_paise * 12 / 100), 180000) : 0;
                totalEsiEmp += s.esi_employee_paise;
                totalEsiEmployer += (emp && emp.esi_applicable && s.gross_paise <= 2100000)
                  ? Math.round(s.gross_paise * 325 / 10000) : 0;
                totalPt += s.pt_paise;
                totalTds += s.tds_paise;
              });
              const edli = Math.round(totalPfEmployer * 5 / 1000);
              return (
                <Card>
                  <CardHeader><CardTitle>Statutory Contributions — {statMonth}</CardTitle></CardHeader>
                  <CardContent>
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-xs font-medium text-gray-500 uppercase">
                          <th className="text-left py-2">Component</th>
                          <th className="text-right py-2">Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr className="border-b"><td className="py-2">PF Employee Contribution (12% of Basic)</td><td className="py-2 text-right font-mono">{fmtRs(totalPfEmp)}</td></tr>
                        <tr className="border-b"><td className="py-2">PF Employer Contribution (12% of Basic)</td><td className="py-2 text-right font-mono">{fmtRs(totalPfEmployer)}</td></tr>
                        <tr className="border-b"><td className="py-2">EDLI (0.5% of Basic)</td><td className="py-2 text-right font-mono">{fmtRs(edli)}</td></tr>
                        <tr className="border-b"><td className="py-2">ESI Employee (0.75% of Gross)</td><td className="py-2 text-right font-mono">{fmtRs(totalEsiEmp)}</td></tr>
                        <tr className="border-b"><td className="py-2">ESI Employer (3.25% of Gross)</td><td className="py-2 text-right font-mono">{fmtRs(totalEsiEmployer)}</td></tr>
                        <tr className="border-b"><td className="py-2">Professional Tax</td><td className="py-2 text-right font-mono">{fmtRs(totalPt)}</td></tr>
                        <tr className="font-bold"><td className="py-2">TDS on Salary (IT Act Sec 192)</td><td className="py-2 text-right font-mono">{fmtRs(totalTds)}</td></tr>
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              );
            })()}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
