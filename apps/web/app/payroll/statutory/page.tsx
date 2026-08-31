"use client";

/**
 * Statutory Deductions — PF / ESIC / Gratuity
 *
 * THIS PAGE COMPUTES NOTHING, AND THAT IS THE POINT.
 *
 * It used to carry its own calcPF, calcESIC and calcGratuity in TypeScript,
 * with its own copies of the ₹15,000 and ₹21,000 ceilings, against CLAUDE.md's
 * rule that computation lives in apps/api. All three had drifted from the
 * backend, each in a different direction:
 *
 *   - PF was computed on BASIC ALONE. EPF Act §6 says basic wages plus dearness
 *     allowance. Every employee with a DA component had their PF understated.
 *   - the employer's 12% was split as a flat 3.67% / 8.33%. EPS is capped at
 *     8.33% of the ceiling (₹1,250), so above the ceiling that split is simply
 *     not what happens — and eps_eligible was not considered at all, so a member
 *     excluded by GSR 609(E) was shown a pension contribution they do not get.
 *   - ESIC ignored Rule 50's contribution periods.
 *   - gratuity read `emp.date_of_joining`, WHICH IS NOT A COLUMN — it is
 *     joining_date. The page selected "*", so PostgREST returned rows without
 *     that key instead of erroring, and gratuity displayed as ZERO FOR EVERY
 *     EMPLOYEE, silently, for as long as this page has existed.
 *
 * Everything now comes from GET /api/payroll/statutory-summary, which has the
 * tests. All monetary values are integer paise on the wire.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ArrowLeft, Download, AlertCircle } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { api, type StatutoryRow, type StatutorySummary } from "@/lib/api";

type Client = { id: string; client_name: string };

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function fmtRs(paise: number): string {
  const rupees = Math.floor(paise / 100);
  const p = paise % 100;
  const formatted = new Intl.NumberFormat("en-IN").format(rupees);
  return p > 0 ? `₹${formatted}.${String(p).padStart(2, "0")}` : `₹${formatted}`;
}

function downloadCSV(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function StatutoryPage() {
  const now = new Date();
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [selMonth, setSelMonth] = useState(now.getMonth() + 1);
  const [selYear, setSelYear] = useState(now.getFullYear());
  const [summary, setSummary] = useState<StatutorySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [showChallan, setShowChallan] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const sb = getSupabaseClient();
        const fid = await getFirmId();
        if (!fid) return;
        const { data } = await sb.from("clients")
          .select("id, client_name").eq("firm_id", fid).order("client_name");
        setClients(data ?? []);
      } catch (e) {
        console.error("load clients:", e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const load = useCallback(async () => {
    if (!selectedClientId) { setSummary(null); return; }
    setLoading(true);
    setLoadFailed(false);
    try {
      const month = `${selYear}-${String(selMonth).padStart(2, "0")}`;
      const res = await api.payroll.statutoryPosition(selectedClientId, month);
      setSummary(res?.data ?? null);
    } catch (e) {
      console.error("load statutory summary:", e);
      setLoadFailed(true);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, [selectedClientId, selMonth, selYear]);

  useEffect(() => { void load(); }, [load]);

  const rows: StatutoryRow[] = summary?.rows ?? [];
  const t = summary?.totals ?? {};
  const totalEmpPF = t.pf_employee_paise ?? 0;
  const totalEmprPF = t.pf_employer_paise ?? 0;
  const totalEmpESIC = t.esi_employee_paise ?? 0;
  const totalEmprESIC = t.esi_employer_paise ?? 0;
  const totalGratuity = t.gratuity_paise ?? 0;

  function handleExport() {
    const header = "Employee,Basic,DA,Gross,Emp PF,Empr EPF,Empr EPS,EDLI,Admin,Emp ESIC,Empr ESIC,Gratuity,Service Yrs";
    const dataRows = rows.map((r) => [
      `"${r.name ?? ""}"`,
      (r.basic_paise / 100).toFixed(2),
      (r.da_paise / 100).toFixed(2),
      (r.gross_paise / 100).toFixed(2),
      (r.pf_employee_paise / 100).toFixed(2),
      (r.pf_employer_epf_paise / 100).toFixed(2),
      (r.pf_employer_eps_paise / 100).toFixed(2),
      (r.edli_paise / 100).toFixed(2),
      (r.pf_admin_paise / 100).toFixed(2),
      (r.esi_employee_paise / 100).toFixed(2),
      (r.esi_employer_paise / 100).toFixed(2),
      (r.gratuity_payable_paise / 100).toFixed(2),
      r.gratuity_years,
    ].join(","));
    const content = [
      `# Statutory Summary — ${MONTHS[selMonth - 1]} ${selYear}`,
      `# PF: Employees' Provident Funds and Misc. Provisions Act 1952`,
      `# ESIC: Employees' State Insurance Act 1948`,
      `# Gratuity: Payment of Gratuity Act 1972 Section 4`,
      `# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT`,
      header,
      ...dataRows,
    ].join("\n");
    downloadCSV(content, `Statutory_${selYear}_${String(selMonth).padStart(2, "0")}.csv`);
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

        <Card className="mb-4">
          <CardContent className="pt-5">
            <div className="flex flex-wrap gap-4 items-end justify-between">
              <div className="flex flex-wrap gap-4 items-end">
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Client</label>
                  <ClientLookup clients={clients} value={selectedClientId}
                    onChange={setSelectedClientId} ariaLabel="Client"
                    placeholder="Select client…" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Month</label>
                  <select className="border rounded-lg px-3 py-2 text-sm" value={selMonth}
                    onChange={(e) => setSelMonth(Number(e.target.value))}>
                    {MONTHS.map((m, i) => <option key={i + 1} value={i + 1}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-[#334155] mb-1">Year</label>
                  <input type="number" className="border rounded-lg px-3 py-2 text-sm w-24"
                    value={selYear} onChange={(e) => setSelYear(Number(e.target.value))}
                    min={2020} max={2099} />
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setShowChallan((v) => !v)}>
                  {showChallan ? "Hide" : "Generate"} Challan Summary
                </Button>
                <Button onClick={handleExport} disabled={!rows.length}
                        className="flex items-center gap-1.5">
                  <Download size={14} />Export CSV
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="flex items-start gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg mb-4">
          <AlertCircle size={15} className="text-amber-600 mt-0.5 flex-shrink-0" />
          <p className="text-xs text-amber-800">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            <strong>CA Review Required.</strong> PF and ESIC challans must be reviewed and
            submitted by a qualified Chartered Accountant. Gratuity here is what would be
            payable if the employee left at the end of the selected month — a provision,
            not an instruction to pay.
          </p>
        </div>

        {/* Anything the backend could not compute, named. A missing joining
            date used to look identical to no entitlement. */}
        {(summary?.gaps?.length ?? 0) > 0 && (
          <div className="mb-4 space-y-1.5 p-3 bg-[#FFFBEB] border border-[#FDE68A] rounded-lg">
            {summary!.gaps.map((g, i) => (
              <p key={i} className="text-xs text-[#78350F]">{g}</p>
            ))}
          </div>
        )}

        {loading && (
          <Card><CardContent className="py-12 text-center text-[#64748B]">Loading…</CardContent></Card>
        )}

        {!loading && loadFailed && (
          <Card><CardContent className="py-12 text-center">
            <p className="text-sm text-red-600 font-medium mb-2">
              Couldn&apos;t load statutory data — the request failed or timed out.
            </p>
            <button onClick={() => void load()}
              className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg hover:bg-[#F8FAFC] text-[#334155]">
              Retry
            </button>
          </CardContent></Card>
        )}

        {!loading && !loadFailed && showChallan && rows.length > 0 && (
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
                  <table className="w-full text-sm"><tbody>
                    <tr><td className="py-1 text-[#475569]">Employee PF</td><td className="text-right font-mono">{fmtRs(totalEmpPF)}</td></tr>
                    <tr><td className="py-1 text-[#475569]">Employer EPF</td><td className="text-right font-mono">{fmtRs(t.pf_employer_epf_paise ?? 0)}</td></tr>
                    <tr><td className="py-1 text-[#475569]">Employer EPS</td><td className="text-right font-mono">{fmtRs(t.pf_employer_eps_paise ?? 0)}</td></tr>
                    <tr><td className="py-1 text-[#475569]">EDLI</td><td className="text-right font-mono">{fmtRs(t.edli_paise ?? 0)}</td></tr>
                    <tr><td className="py-1 text-[#475569]">Admin charges</td><td className="text-right font-mono">{fmtRs(t.pf_admin_paise ?? 0)}</td></tr>
                    <tr className="border-t font-bold"><td className="py-2">Total PF Payable</td>
                      <td className="text-right font-mono text-blue-600">
                        {fmtRs(totalEmpPF + totalEmprPF + (t.edli_paise ?? 0) + (t.pf_admin_paise ?? 0))}
                      </td></tr>
                  </tbody></table>
                  <p className="text-xs text-[#94A3B8] mt-2">
                    EDLI and admin charges are employer costs outside the 12%. The admin
                    minimum of ₹500 is per establishment, so it is applied to this total
                    and never to one payslip.
                  </p>
                </div>
                <div className="bg-white rounded-lg p-4 border border-green-100">
                  <p className="text-xs font-semibold uppercase text-green-600 mb-3">ESIC Challan (ESI Act 1948)</p>
                  <table className="w-full text-sm"><tbody>
                    <tr><td className="py-1 text-[#475569]">Employee ESIC (0.75%)</td><td className="text-right font-mono">{fmtRs(totalEmpESIC)}</td></tr>
                    <tr><td className="py-1 text-[#475569]">Employer ESIC (3.25%)</td><td className="text-right font-mono">{fmtRs(totalEmprESIC)}</td></tr>
                    <tr className="border-t font-bold"><td className="py-2">Total ESIC Payable</td>
                      <td className="text-right font-mono text-green-700">{fmtRs(totalEmpESIC + totalEmprESIC)}</td></tr>
                  </tbody></table>
                  <p className="text-xs text-[#94A3B8] mt-2">
                    Someone whose wages cross ₹21,000 part way through a contribution
                    period stays in the scheme until that period ends (Rule 50).
                  </p>
                </div>
                <div className="bg-white rounded-lg p-4 border border-orange-100">
                  <p className="text-xs font-semibold uppercase text-orange-600 mb-3">Gratuity Liability (Gratuity Act 1972)</p>
                  <table className="w-full text-sm"><tbody>
                    <tr><td className="py-1 text-[#475569]">Eligible employees</td>
                      <td className="text-right font-mono">{rows.filter((r) => r.gratuity_eligible).length}</td></tr>
                    <tr className="border-t font-bold"><td className="py-2">Total gratuity liability</td>
                      <td className="text-right font-mono text-orange-700">{fmtRs(totalGratuity)}</td></tr>
                  </tbody></table>
                  <p className="text-xs text-[#94A3B8] mt-2">
                    Fifteen days&apos; wages per completed year on basic + DA, divided by 26.
                    Five years&apos; service, except on death or disablement. Ceiling ₹20 lakh.
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {!loading && !loadFailed && selectedClientId && rows.length === 0 && (
          <Card><CardContent className="py-12 text-center text-[#94A3B8]">
            No active employees for this client.
          </CardContent></Card>
        )}

        {!loading && !loadFailed && rows.length > 0 && (
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
                      <th className="text-right py-3 px-3">Basic + DA</th>
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
                    {rows.map((r) => (
                      <tr key={r.employee_id} className="border-b hover:bg-[#F8FAFC]">
                        <td className="py-3 px-4">
                          <div className="font-medium text-[#0F172A]">{r.name}</div>
                          <div className="flex gap-1 mt-0.5">
                            {r.pf_applicable && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-100 text-blue-700">PF</span>
                            )}
                            {r.esi_applicable && r.esi_employee_paise > 0 && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-100 text-green-700">ESIC</span>
                            )}
                            {r.pf_applicable && !r.eps_eligible && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#F1F5F9] text-[#475569]"
                                    title="Excluded from EPS by GSR 609(E) — the whole employer 12% goes to EPF">
                                No EPS
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs">{fmtRs(r.basic_paise + r.da_paise)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs">{fmtRs(r.gross_paise)}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-red-600">
                          {r.pf_employee_paise > 0 ? fmtRs(r.pf_employee_paise) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-orange-600">
                          {r.pf_employer_paise > 0 ? fmtRs(r.pf_employer_paise) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-red-600">
                          {r.esi_employee_paise > 0 ? fmtRs(r.esi_employee_paise) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-orange-600">
                          {r.esi_employer_paise > 0 ? fmtRs(r.esi_employer_paise) : <span className="text-[#CBD5E1]">—</span>}
                        </td>
                        <td className="py-3 px-3 text-right font-mono text-xs text-purple-700">
                          {r.gratuity_payable_paise > 0
                            ? fmtRs(r.gratuity_payable_paise)
                            : <span className="text-[#CBD5E1]" title={r.gratuity_reasons[0] ?? ""}>—</span>}
                        </td>
                        <td className="py-3 px-3 text-center text-xs">
                          {r.joining_date
                            ? <span className={r.gratuity_eligible ? "text-green-700 font-medium" : "text-[#64748B]"}>
                                {r.gratuity_years}y
                              </span>
                            : <span className="text-[#CBD5E1]" title="No joining date on record">—</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  {rows.length > 1 && (
                    <tfoot>
                      <tr className="border-t-2 font-bold bg-[#F8FAFC]">
                        <td className="py-3 px-4 text-[#334155]">Total</td>
                        <td className="py-3 px-3 text-right font-mono text-xs">
                          {fmtRs(rows.reduce((s, r) => s + r.basic_paise + r.da_paise, 0))}</td>
                        <td className="py-3 px-3 text-right font-mono text-xs">
                          {fmtRs(rows.reduce((s, r) => s + r.gross_paise, 0))}</td>
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
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
