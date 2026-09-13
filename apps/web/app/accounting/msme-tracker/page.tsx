"use client";

/**
 * IT Act §43B(h) — a sum payable to a micro or small enterprise, paid late.
 *
 * WHAT THIS SCREEN USED TO BE (PUR-15)
 *     It asked the CA to type every bill in again — supplier, invoice number,
 *     invoice date, amount, whether the agreement was written, payment date —
 *     into `msme_payments` over PostgREST, and then computed the whole
 *     statutory rule in TypeScript. Three defects in one screen: the figure
 *     was a re-keying of data the books already hold and drifted the moment a
 *     bill was corrected; `rbac()` never ran on the write; and a §43B(h)
 *     disallowance was being decided in the browser.
 *
 *     Its rule was wrong in the direction that matters, too. It read the
 *     agreement type per ROW and defaulted the limit to 15 or 45 off that,
 *     but nothing anywhere recorded which suppliers actually have a written
 *     agreement — so the number depended on what somebody picked in a dropdown
 *     for that one invoice.
 *
 * WHAT IT IS NOW
 *     A rendering of GET /api/income-tax/msme-43bh, which derives the working
 *     from `purchase_bills`, their payment allocations and
 *     `vendors.msme_status`. This file computes nothing: no due dates, no
 *     limits, no disallowance. `domain/income_tax/section_43b_h.py` is the
 *     rule and says what it refuses to decide.
 *
 *     `msme_payments` is no longer read or written. Dropping the table is a
 *     migration and an owner decision; not reading it is neither.
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft, AlertTriangle, CheckCircle, Info, Download } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/services/formatting";
import { getClients } from "@/lib/data/clients";
import { financialYearChoicesAround } from "@/lib/dates/periods";
import { api, type MSME43BHWorking } from "@/lib/api";
import * as XLSX from "xlsx";
import type { Client } from "@/lib/types";

export default function MSME43BHPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  // Derived from the clock, never listed — a hardcoded year list is a control
  // that goes stale on 1 April and then offers a year already past.
  const fyChoices = useMemo(() => financialYearChoicesAround(), []);
  const [fy, setFy] = useState(fyChoices[0]);
  const [working, setWorking] = useState<MSME43BHWorking | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { getClients().then(setClients).catch(() => setClients([])); }, []);

  const load = useCallback(async () => {
    if (!clientId || !fy) { setWorking(null); return; }
    setLoading(true);
    setError(null);
    try {
      const r = await api.incomeTax.msme43bh(clientId, fy);
      if (!r.success) { setWorking(null); setError(r.error ?? "Could not compute the §43B(h) working"); return; }
      setWorking(r.data);
    } catch (e) {
      setWorking(null);
      setError(e instanceof Error ? e.message : "Could not compute the §43B(h) working");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy]);

  useEffect(() => { load(); }, [load]);

  const rows = working?.bills ?? [];

  function exportExcel() {
    if (!working) return;
    const sheet = working.bills.map(b => ({
      Supplier: b.vendor_name,
      "Bill No": b.bill_no ?? "",
      "Bill Date": b.bill_date ?? "",
      "MSMED s.15 limit (days)": b.limit_days ?? "",
      "Due by": b.due_by ?? "",
      "Invoice total (Rs)": (b.total_paise / 100).toFixed(2),
      "Deduction claimed (Rs)": (b.deductible_paise / 100).toFixed(2),
      "Paid in time (Rs)": (b.paid_in_time_paise / 100).toFixed(2),
      "Paid late (Rs)": (b.paid_late_paise / 100).toFixed(2),
      "Still unpaid (Rs)": (b.unpaid_paise / 100).toFixed(2),
      "Disallowed this year (Rs)": (b.disallowed_paise / 100).toFixed(2),
      Basis: b.reason,
    }));
    const ws = XLSX.utils.json_to_sheet(sheet);
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, "43B(h)");
    XLSX.writeFile(wb, `msme_43bh_${working.financial_year}.xlsx`);
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">MSME §43B(h)</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            Sums payable to micro and small enterprises beyond the MSMED §15 limit,
            read from the purchase ledger
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={exportExcel} disabled={rows.length === 0}>
          <Download size={14} className="mr-1" /> Export
        </Button>
      </div>

      <div className="flex flex-wrap gap-3">
        <div className="min-w-[240px]">
          <ClientLookup
            clients={clients}
            value={clientId}
            onChange={(id) => setClientId(id)}
            ariaLabel="Client"
            placeholder="Select a client"
          />
        </div>
        <select
          aria-label="Financial year"
          className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500"
          value={fy}
          onChange={e => setFy(e.target.value)}
        >
          {fyChoices.map(y => <option key={y} value={y}>FY {y}</option>)}
        </select>
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>}

      {!clientId && (
        <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-5 py-4 text-sm text-[#64748B]">
          §43B(h) is a figure in one client&apos;s tax computation. Pick a client.
        </div>
      )}

      {working && !working.applicable && (
        <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-5 py-4 text-sm text-[#64748B]">
          {working.caveats[0]}
        </div>
      )}

      {working?.applicable && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className={`rounded-xl px-5 py-4 border ${working.disallowed_paise > 0
              ? "bg-red-50 border-red-200" : "bg-[#F8FAFC] border-[#E2E8F0]"}`}>
              <p className="text-xs text-[#64748B]">Added back to taxable income, FY {working.financial_year}</p>
              <p className={`text-2xl font-bold tabular-nums mt-1 ${working.disallowed_paise > 0
                ? "text-red-700" : "text-[#0F172A]"}`}>
                {formatPaise(working.disallowed_paise)}
              </p>
              <p className="text-xs text-[#64748B] mt-1">
                Bills that accrued this year and were not paid within their own MSMED §15 limit.
              </p>
            </div>
            <div className="rounded-xl px-5 py-4 border bg-[#F8FAFC] border-[#E2E8F0]">
              <p className="text-xs text-[#64748B]">Allowed back this year, on payment</p>
              <p className="text-2xl font-bold tabular-nums mt-1 text-[#0F172A]">
                {formatPaise(working.allowed_on_payment_paise)}
              </p>
              <p className="text-xs text-[#64748B] mt-1">
                Earlier years&apos; bills that were disallowed then and were actually paid during
                this year.
              </p>
            </div>
          </div>

          {working.gaps.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4">
              <div className="flex items-start gap-2">
                <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-amber-900">
                    {working.gaps.length} supplier{working.gaps.length !== 1 ? "s are" : " is"} not
                    in this working, and should be
                  </p>
                  {working.gaps.map((g, i) => (
                    <p key={i} className="text-xs text-amber-800">• {g}</p>
                  ))}
                  <p className="text-[11px] text-amber-700 pt-1">
                    Record it on the client&apos;s Schedule III ageing screen, then recompute.
                  </p>
                </div>
              </div>
            </div>
          )}

          <div className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl px-5 py-4 space-y-1.5">
            <div className="flex items-start gap-2">
              <Info size={15} className="text-[#94A3B8] shrink-0 mt-0.5" />
              <div className="space-y-1.5">
                {working.caveats.map((c, i) => (
                  <p key={i} className="text-xs text-[#64748B]">{c}</p>
                ))}
                <p className="text-[11px] text-[#94A3B8]">{working.source}</p>
              </div>
            </div>
          </div>

          <Card>
            {loading ? (
              <TableSkeleton cols={8} bare />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[980px]">
                  <thead>
                    <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                      <th className="px-5 py-3 text-left">Supplier</th>
                      <th className="px-3 py-3 text-left">Bill</th>
                      <th className="px-3 py-3 text-left">Bill date</th>
                      <th className="px-3 py-3 text-left">§15 limit</th>
                      <th className="px-3 py-3 text-left">Due by</th>
                      <th className="px-3 py-3 text-right">Deduction</th>
                      <th className="px-3 py-3 text-right">Unpaid</th>
                      <th className="px-5 py-3 text-right">Disallowed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {rows.length === 0 && (
                      <tr><td colSpan={8} className="text-center text-[#94A3B8] py-8 text-sm">
                        No purchase bills for this client.
                      </td></tr>
                    )}
                    {rows.map(b => (
                      <tr key={b.bill_id} className={b.disallowed_paise > 0 ? "bg-red-50/40" : ""}>
                        <td className="px-5 py-3 text-sm font-medium text-[#0F172A]">{b.vendor_name}</td>
                        <td className="px-3 py-3 text-xs font-mono text-[#64748B]">{b.bill_no ?? "—"}</td>
                        <td className="px-3 py-3 text-xs text-[#475569]">{b.bill_date ?? "—"}</td>
                        <td className="px-3 py-3 text-xs text-[#475569]" title={b.limit_source}>
                          {b.limit_days == null ? "—" : `${b.limit_days} days`}
                        </td>
                        <td className="px-3 py-3 text-xs text-[#475569]">{b.due_by ?? "—"}</td>
                        <td className="px-3 py-3 text-sm tabular-nums text-right">{formatPaise(b.deductible_paise)}</td>
                        <td className="px-3 py-3 text-sm tabular-nums text-right">{formatPaise(b.unpaid_paise)}</td>
                        <td className="px-5 py-3 text-sm tabular-nums text-right font-medium">
                          {b.disallowed_paise > 0
                            ? <span className="text-red-700">{formatPaise(b.disallowed_paise)}</span>
                            : <span className="inline-flex items-center gap-1 text-[#94A3B8]" title={b.reason}>
                                <CheckCircle size={12} /> —
                              </span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
