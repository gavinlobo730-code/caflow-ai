"use client";

/**
 * Statutory Deductions — PF / ESIC / Gratuity
 *
 * PF: Employees' Provident Funds and Misc. Provisions Act 1952
 * ESIC: Employees' State Insurance Act 1948
 * Gratuity: Payment of Gratuity Act 1972, Section 4
 *
 * All monetary values in integer paise — never float.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, Download, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ── Types ──────────────────────────────────────────────────────────────────

type Client = { id: string; client_name: string };

type Employee = {
  id: string;
  client_id: string;
  name: string;
  designation: string;
  basic_paise: number;
  hra_percent: number;
  da_percent: number;
  other_allowances_paise: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
  date_of_joining?: string; // ISO date string for gratuity calculation
};

type StatutoryRow = {
  emp: Employee;
  basicPaise: number;
  grossPaise: number;
  employeePF: number;
  employerEPF: number;
  employerEPS: number;
  totalEmployerPF: number;
  employeeESIC: number;
  employerESIC: number;
  gratuityPaise: number;
  yearsOfService: number;
};

// ── PF Calculation ─────────────────────────────────────────────────────────
// Provident Fund per Employees' Provident Funds and Misc. Provisions Act 1952
// Employee contribution: 12% of Basic salary (capped at Rs 15,000 basic = Rs 1,800 max employee PF)
// Employer contribution: 12% of Basic (3.67% to EPF, 8.33% to EPS)

const PF_WAGE_CEILING_PAISE = 1500000; // Rs 15,000 in paise

function calcPF(basicPaise: number, applicable: boolean): {
  employeePF: number; employerEPF: number; employerEPS: number; total: number;
} {
  if (!applicable) return { employeePF: 0, employerEPF: 0, employerEPS: 0, total: 0 };
  const pfBasis = Math.min(basicPaise, PF_WAGE_CEILING_PAISE);
  const employeePF = Math.round(pfBasis * 12 / 100);      // 12% employee
  const employerEPF = Math.round(pfBasis * 367 / 10000);  // 3.67% to EPF
  const employerEPS = Math.round(pfBasis * 833 / 10000);  // 8.33% to EPS
  const total = employeePF + employerEPF + employerEPS;
  return { employeePF, employerEPF, employerEPS, total };
}

// ── ESIC Calculation ───────────────────────────────────────────────────────
// ESIC per Employees' State Insurance Act 1948
// Applicable if gross salary <= Rs 21,000/month
// Employee: 0.75% of gross, Employer: 3.25% of gross

const ESIC_CEILING_PAISE = 2100000; // Rs 21,000 in paise

function calcESIC(grossPaise: number, applicable: boolean): {
  employeeESIC: number; employerESIC: number;
} {
  if (!applicable || grossPaise > ESIC_CEILING_PAISE) {
    return { employeeESIC: 0, employerESIC: 0 };
  }
  const employeeESIC = Math.round(grossPaise * 75 / 10000);   // 0.75%
  const employerESIC = Math.round(grossPaise * 325 / 10000);  // 3.25%
  return { employeeESIC, employerESIC };
}

// ── Gratuity Calculation ───────────────────────────────────────────────────
// Gratuity per Payment of Gratuity Act 1972, Section 4
// Applicable after 5 years of continuous service
// Gratuity = (Last drawn salary / 26) * 15 * years of service
// Max gratuity = Rs 20 lakh (2000000 rupees)

const GRATUITY_MAX_PAISE = 200000000; // Rs 20,00,000 in paise
const GRATUITY_MIN_SERVICE_YEARS = 5;

function calcGratuity(basicPaise: number, dateOfJoining: string | undefined, asOfMonth: number, asOfYear: number): {
  gratuityPaise: number; yearsOfService: number;
} {
  if (!dateOfJoining) return { gratuityPaise: 0, yearsOfService: 0 };
  const joinDate = new Date(dateOfJoining);
  const asOf = new Date(asOfYear, asOfMonth - 1, 1);
  const diffMs = asOf.getTime() - joinDate.getTime();
  const yearsOfService = Math.floor(diffMs / (1000 * 60 * 60 * 24 * 365.25));
  if (yearsOfService < GRATUITY_MIN_SERVICE_YEARS) return { gratuityPaise: 0, yearsOfService };
  const dailyWagePaise = Math.round(basicPaise / 26); // 26 working days per month
  const gratuityPaise = Math.min(
    Math.round(dailyWagePaise * 15 * yearsOfService),
    GRATUITY_MAX_PAISE,
  );
  return { gratuityPaise, yearsOfService };
}

// ── Format helpers ─────────────────────────────────────────────────────────

function fmtRs(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  return `₹${rupees.toLocaleString("en-IN")}.${p.toString().padStart(2, "0")}`;
}

function downloadCSV(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function StatutoryPage() {
  const today = new Date();
  const [clients, setClients] = useState<Client[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [loading, setLoading] = useState(true);

  const [selectedClientId, setSelectedClientId] = useState("");
  const [selMonth, setSelMonth] = useState(today.getMonth() + 1);
  const [selYear, setSelYear] = useState(today.getFullYear());
  const [showChallan, setShowChallan] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const fid = await getFirmId();
      const sb = getSupabaseClient();
      const [clientsRes, empRes] = await Promise.all([
        sb.from("clients").select("id, client_name").eq("firm_id", fid),
        sb.from("payroll_employees").select("*").eq("firm_id", fid),
      ]);
      const cls: Client[] = clientsRes.data ?? [];
      const emps: Employee[] = empRes.data ?? [];
      setClients(cls);
      setEmployees(emps);
      if (cls.length > 0) setSelectedClientId(cls[0].id);
    } catch {
      // not authenticated
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const clientEmployees = employees.filter(e => e.client_id === selectedClientId);

  const rows: StatutoryRow[] = clientEmployees.map(emp => {
    const basicPaise = emp.basic_paise;
    const hraPaise = Math.round(basicPaise * emp.hra_percent / 100);
    const daPaise = Math.round(basicPaise * emp.da_percent / 100);
    const grossPaise = basicPaise + hraPaise + daPaise + emp.other_allowances_paise;

    const pf = calcPF(basicPaise, emp.pf_applicable);
    const esic = calcESIC(grossPaise, emp.esi_applicable);
    const gratuity = calcGratuity(basicPaise, emp.date_of_joining, selMonth, selYear);

    return {
      emp,
      basicPaise,
      grossPaise,
      employeePF: pf.employeePF,
      employerEPF: pf.employerEPF,
      employerEPS: pf.employerEPS,
      totalEmployerPF: pf.employerEPF + pf.employerEPS,
      employeeESIC: esic.employeeESIC,
      employerESIC: esic.employerESIC,
      gratuityPaise: gratuity.gratuityPaise,
      yearsOfService: gratuity.yearsOfService,
    };
  });

  // Challan summary totals
  const totalEmpPF = rows.reduce((s, r) => s + r.employeePF, 0);
  const totalEmprPF = rows.reduce((s, r) => s + r.totalEmployerPF, 0);
  const totalPF = totalEmpPF + totalEmprPF;
  const totalEmpESIC = rows.reduce((s, r) => s + r.employeeESIC, 0);
  const totalEmprESIC = rows.reduce((s, r) => s + r.employerESIC, 0);
  const totalESIC = totalEmpESIC + totalEmprESIC;
  const totalGratuity = rows.reduce((s, r) => s + r.gratuityPaise, 0);

  const MONTHS = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December",
  ];

  function handleExport() {
    const header = "Employee,Designation,Basic,Gross,Emp PF,Empr EPF,Empr EPS,Emp ESIC,Empr ESIC,Gratuity Liability,Years of Service";
    const dataRows = rows.map(r => [
      `"${r.emp.name}"`,
      `"${r.emp.designation || ""}"`,
      (r.basicPaise / 100).toFixed(2),
      (r.grossPaise / 100).toFixed(2),
      (r.employeePF / 100).toFixed(2),
      (r.employerEPF / 100).toFixed(2),
      (r.employerEPS / 100).toFixed(2),
      (r.employeeESIC / 100).toFixed(2),
      (r.employerESIC / 100).toFixed(2),
      (r.gratuityPaise / 100).toFixed(2),
      r.yearsOfService,
    ].join(","));
    const footer = [
      '"TOTAL","","","",',
      `${(totalEmpPF / 100).toFixed(2)},`,
      `${(totalEmprPF / 100).toFixed(2)},`,
      `"",`,
      `${(totalEmpESIC / 100).toFixed(2)},`,
      `${(totalEmprESIC / 100).toFixed(2)},`,
      `${(totalGratuity / 100).toFixed(2)},`,
      `""`,
    ].join("");
    const content = [
      `# Statutory Summary — ${MONTHS[selMonth - 1]} ${selYear}`,
      `# PF: Employees' Provident Funds and Misc. Provisions Act 1952`,
      `# ESIC: Employees' State Insurance Act 1948`,
      `# Gratuity: Payment of Gratuity Act 1972 Section 4`,
      `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT`,
      header,
      ...dataRows,
      footer,
    ].join("\n");
    downloadCSV(content, `Statutory_${selYear}_${String(selMonth).padStart(2, "0")}.csv`);
  }

  if (loading) {
    return <div className="min-h-screen bg-[#F8FAFC] flex items-center justify-center"><p className="text-[#64748B]">Loading...</p></div>;
  }

  return (
    <div className="min-h-screen bg-[#F8FAFC] p-8">
      <div className="max-w-7xl mx-auto">
        <div className="mb-6 flex items-center gap-3">
          <Link href="/payroll">
            <Button variant="outline" size="sm" className="flex items-center gap-1.5">
              <ArrowLeft size={14} />Back to Payroll
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-[#0F172A]">Statutory Deductions</h1>
            <p className="text-sm text-[#64748B] mt-0.5">
              PF (EPF Act 1952) &middot; ESIC (ESI Act 1948) &middot; Gratuity (Gratuity Act 1972 Sec 4)
            </p>
          </div>
        </div>

        {/* Filters */}
        <Card className="mb-4">
          <CardContent className="pt-5">
            <div className="flex flex-wrap gap-4 items-end justify-between">
              <div className="flex flex-wrap gap-4 items-end">
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                  <select
                    className="border rounded-lg px-3 py-2 text-sm"
                    value={selectedClientId}
                    onChange={e => setSelectedClientId(e.target.value)}
                  >
                    {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Month</label>
                  <select
                    className="border rounded-lg px-3 py-2 text-sm"
                    value={selMonth}
                    onChange={e => setSelMonth(Number(e.target.value))}
                  >
                    {MONTHS.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Year</label>
                  <input
                    type="number"
                    className="border rounded-lg px-3 py-2 text-sm w-24"
                    value={selYear}
                    onChange={e => setSelYear(Number(e.target.value))}
                    min={2020}
                    max={2099}
                  />
                </div>
              </div>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  onClick={() => setShowChallan(v => !v)}
                  className="flex items-center gap-1.5"
                >
                  {showChallan ? "Hide" : "Generate"} Challan Summary
                </Button>
                <Button onClick={handleExport} className="flex items-center gap-1.5">
                  <Download size={14} />Export CSV
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* CA Review notice */}
        <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg mb-4">
          <AlertCircle size={15} className="text-amber-600 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-amber-800">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            <strong>CA Review Required.</strong> PF and ESIC challans must be reviewed and submitted
            by a qualified Chartered Accountant. This page is for calculation reference only.
            Gratuity is a liability estimate — actual payment subject to eligibility verification.
          </p>
        </div>

        {/* Challan Summary */}
        {showChallan && (
          <Card className="mb-4 border-blue-500/20 bg-blue-500/[0.08]">
            <CardHeader>
              <CardTitle className="text-base text-indigo-900">
                Challan Summary — {MONTHS[selMonth - 1]} {selYear}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                <div className="bg-white rounded-lg p-4 border border-blue-500/20">
                  <p className="text-xs font-semibold uppercase text-blue-600 mb-3">PF Challan (EPF Act 1952)</p>
                  <table className="w-full text-sm">
                    <tbody>
                      <tr><td className="py-1 text-[#475569]">Employee PF (12%)</td><td className="text-right font-mono">{fmtRs(totalEmpPF)}</td></tr>
                      <tr><td className="py-1 text-[#475569]">Employer EPF (3.67%)</td><td className="text-right font-mono">{fmtRs(rows.reduce((s, r) => s + r.employerEPF, 0))}</td></tr>
                      <tr><td className="py-1 text-[#475569]">Employer EPS (8.33%)</td><td className="text-right font-mono">{fmtRs(rows.reduce((s, r) => s + r.employerEPS, 0))}</td></tr>
                      <tr className="border-t font-bold"><td className="py-2">Total PF Payable</td><td className="text-right font-mono text-blue-600">{fmtRs(totalPF)}</td></tr>
                    </tbody>
                  </table>
                </div>
                <div className="bg-white rounded-lg p-4 border border-green-100">
                  <p className="text-xs font-semibold uppercase text-green-600 mb-3">ESIC Challan (ESI Act 1948)</p>
                  <table className="w-full text-sm">
                    <tbody>
                      <tr><td className="py-1 text-[#475569]">Employee ESIC (0.75%)</td><td className="text-right font-mono">{fmtRs(totalEmpESIC)}</td></tr>
                      <tr><td className="py-1 text-[#475569]">Employer ESIC (3.25%)</td><td className="text-right font-mono">{fmtRs(totalEmprESIC)}</td></tr>
                      <tr className="border-t font-bold"><td className="py-2">Total ESIC Payable</td><td className="text-right font-mono text-green-700">{fmtRs(totalESIC)}</td></tr>
                    </tbody>
                  </table>
                  <p className="text-xs text-[#94A3B8] mt-2">Applicable for employees with gross &le; ₹21,000/month</p>
                </div>
                <div className="bg-white rounded-lg p-4 border border-orange-100">
                  <p className="text-xs font-semibold uppercase text-orange-600 mb-3">Gratuity Liability (Gratuity Act 1972)</p>
                  <table className="w-full text-sm">
                    <tbody>
                      <tr><td className="py-1 text-[#475569]">Eligible Employees</td><td className="text-right font-mono">{rows.filter(r => r.yearsOfService >= 5).length}</td></tr>
                      <tr className="border-t font-bold"><td className="py-2">Total Gratuity Liability</td><td className="text-right font-mono text-orange-700">{fmtRs(totalGratuity)}</td></tr>
                    </tbody>
                  </table>
                  <p className="text-xs text-[#94A3B8] mt-2">Applicable after 5 years of continuous service. Max ₹20 lakh.</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Employee-wise statutory table */}
        {clientEmployees.length === 0 ? (
          <Card><CardContent className="py-12 text-center text-[#94A3B8]">No employees for this client.</CardContent></Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Employee-wise Statutory Deductions</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide">
                      <th className="text-left py-3 px-4">Employee</th>
                      <th className="text-right py-3 px-3">Basic</th>
                      <th className="text-right py-3 px-3">Gross</th>
                      <th className="text-right py-3 px-3">Emp PF</th>
                      <th className="text-right py-3 px-3">Empr PF</th>
                      <th className="text-right py-3 px-3">Emp ESIC</th>
                      <th className="text-right py-3 px-3">Empr ESIC</th>
                      <th className="text-right py-3 px-3">Gratuity</th>
                      <th className="text-center py-3 px-3">Service Yrs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(r => (
                      <tr key={r.emp.id} className="border-b hover:bg-[#F8FAFC]">
                        <td className="py-3 px-4">
                          <div className="font-medium text-[#0F172A]">{r.emp.name}</div>
                          {r.emp.designation && <div className="text-xs text-[#64748B]">{r.emp.designation}</div>}
                          <div className="flex gap-1 mt-0.5">
                            {r.emp.pf_applicable && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">PF</span>
                            )}
                            {r.emp.esi_applicable && r.grossPaise <= ESIC_CEILING_PAISE && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">ESIC</span>
                            )}
                          </div>
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs">{fmtRs(r.basicPaise)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs">{fmtRs(r.grossPaise)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-red-600">
                          {r.employeePF > 0 ? fmtRs(r.employeePF) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-orange-600">
                          {r.totalEmployerPF > 0 ? fmtRs(r.totalEmployerPF) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-red-600">
                          {r.employeeESIC > 0 ? fmtRs(r.employeeESIC) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-orange-600">
                          {r.employerESIC > 0 ? fmtRs(r.employerESIC) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-purple-700">
                          {r.gratuityPaise > 0 ? fmtRs(r.gratuityPaise) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-center text-xs">
                          {r.yearsOfService > 0 ? (
                            <span className={r.yearsOfService >= 5 ? "text-green-700 font-medium" : "text-[#64748B]"}>
                              {r.yearsOfService}y
                            </span>
                          ) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {rows.length > 1 && (
                    <tfoot>
                      <tr className="border-t-2 font-bold bg-[#F8FAFC]">
                        <td className="py-3 px-4 text-[#334155]">Total</td>
                        <td className="py-3 px-3 text-right font-mono text-xs">{fmtRs(rows.reduce((s, r) => s + r.basicPaise, 0))}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs">{fmtRs(rows.reduce((s, r) => s + r.grossPaise, 0))}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-red-600">{fmtRs(totalEmpPF)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-orange-600">{fmtRs(totalEmprPF)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-red-600">{fmtRs(totalEmpESIC)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-orange-600">{fmtRs(totalEmprESIC)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-purple-700">{fmtRs(totalGratuity)}</td>
                        <td></td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
              <div className="p-4 border-t">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs text-[#64748B]">
                  <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                    <p className="font-medium text-[#334155] mb-1">PF Calculation (EPF Act 1952)</p>
                    <p>Employee: 12% of basic (capped at ₹15,000 basic). Employer: 3.67% EPF + 8.33% EPS. Basic ceiling ₹15,000/month.</p>
                  </div>
                  <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                    <p className="font-medium text-[#334155] mb-1">ESIC (ESI Act 1948)</p>
                    <p>Employee: 0.75% of gross. Employer: 3.25% of gross. Applicable only if gross salary ≤ ₹21,000/month.</p>
                  </div>
                  <div className="p-3 bg-[#F8FAFC] rounded-lg border border-[#F1F5F9]">
                    <p className="font-medium text-[#334155] mb-1">Gratuity (Gratuity Act 1972 Sec 4)</p>
                    <p>= (Basic/26) × 15 × years. Applicable after 5 years continuous service. Maximum ₹20 lakh. Requires date of joining in employee record.</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
