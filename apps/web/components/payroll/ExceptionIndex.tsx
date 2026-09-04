"use client";

/** The exception index — the roster's statutory gaps, before a file is built.
 *
 *  Moved out of /payroll when the roster became its own screen (People). The
 *  design puts it there: it is a fact about PEOPLE, not about a month, and a
 *  CA chasing a missing UAN is doing roster work rather than payroll work. */

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { api, type ApiResp } from "@/lib/api";
import { apiErr } from "@/components/payroll/shared";

type PayrollException = {
  kind: string;
  employee_id: string | null;
  employee: string;
  client_id: string;
  client_name: string;
  blocks: string;
  note: string;
};

const EXCEPTION_LABEL: Record<string, string> = {
  uan: "UAN missing or malformed",
  esic_ip: "ESIC IP number missing",
  pan: "PAN missing or invalid",
  date_of_birth: "Date of birth missing (old regime)",
  bank: "Bank details missing or invalid",
  pt_state: "Professional tax state not modelled",
};

export function ExceptionIndexTab() {
  const [rows, setRows] = useState<PayrollException[]>([]);
  const [summary, setSummary] = useState<Record<string, number>>({});
  const [checked, setChecked] = useState(0);
  const [loading, setLoading] = useState(true);
  // A failed read must not render as "nothing to fix" — that is the M17
  // mistake, and here it would read as a clean roster.
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.payroll.payrollEmployeeExceptions() as ApiResp<{
        exceptions: PayrollException[];
        summary: Record<string, number>;
        employees_checked: number;
      }>;
      if (!res?.data) { setError("Could not read the roster."); return; }
      setRows(res.data.exceptions ?? []);
      setSummary(res.data.summary ?? {});
      setChecked(res.data.employees_checked ?? 0);
    } catch (e) {
      setError(apiErr(e, "Could not read the roster."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-row items-start justify-between flex-wrap gap-3">
          <div>
            <CardTitle className="text-base">Exceptions</CardTitle>
            <p className="text-xs text-[#64748B] mt-0.5">
              What is missing from the employee master that a statutory output
              will refuse. Nothing here stops a run — these people are still
              paid; what they are missing is the means to be reported.
            </p>
          </div>
          <Button size="sm" variant="outline" onClick={load} disabled={loading}>
            {loading ? "Checking…" : "Re-check"}
          </Button>
        </div>
        {!loading && !error && (
          <p className="text-xs text-[#475569] mt-3">
            {/* The denominator: "14 need a UAN" means something different out of
                20 than out of 400. */}
            {rows.length === 0
              ? `Nothing outstanding across ${checked} active employee(s).`
              : `${rows.length} gap(s) across ${checked} active employee(s).`}
          </p>
        )}
        {Object.keys(summary).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3">
            {Object.entries(summary).map(([kind, n]) => (
              <span key={kind} className="text-[11px] px-2 py-0.5 rounded bg-amber-50 text-amber-800">
                {EXCEPTION_LABEL[kind] ?? kind}: {n}
              </span>
            ))}
          </div>
        )}
      </CardHeader>
      <CardContent className="p-0">
        {loading ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">Checking the roster…</p>
        ) : error ? (
          <div className="p-8 text-center">
            <p className="text-sm text-red-600 font-medium mb-2">{error}</p>
            <Button size="sm" variant="outline" onClick={load}>Retry</Button>
          </div>
        ) : rows.length === 0 ? (
          <p className="text-center text-[#94A3B8] py-12 text-sm">
            Every active employee has what the statutory outputs need.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs font-medium text-[#64748B] uppercase tracking-wide bg-[#F8FAFC]">
                  <th className="text-left py-3 px-4">Employee</th>
                  <th className="text-left py-3 px-4">Client</th>
                  <th className="text-left py-3 px-4">Blocks</th>
                  <th className="text-left py-3 px-4">What is missing</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.employee_id ?? r.employee}-${r.kind}-${i}`} className="border-b hover:bg-[#F8FAFC] align-top">
                    <td className="py-3 px-4 font-medium text-[#0F172A]">{r.employee}</td>
                    <td className="py-3 px-4 text-[#475569]">{r.client_name || "—"}</td>
                    <td className="py-3 px-4">
                      <span className="inline-block px-2 py-0.5 rounded text-xs bg-amber-100 text-amber-800">
                        {r.blocks}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-xs text-[#475569] max-w-xl">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}


