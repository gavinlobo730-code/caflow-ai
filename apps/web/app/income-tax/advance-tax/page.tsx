"use client";

/**
 * Advance Tax Tracker — IT Act Section 207/208/234C
 * Taxpayers with annual tax liability > ₹10,000 must pay advance tax in 4 instalments.
 * Due dates: 15 Jun (15%), 15 Sep (45%), 15 Dec (75%), 15 Mar (100%)
 *
 * R3.13a: all schedule/interest computation now happens on the backend
 * (domain/income_tax/advance_tax_interest_engine.py) — this page only
 * collects input and displays results. It previously computed Section 234C
 * interest itself with the wrong formula (actual payment-delay months, no
 * 12%/36% trigger tolerance — the Section 234B shape, not 234C's fixed
 * 3/3/3/1-month periods) and wrote straight to advance_tax_payments from
 * the browser.
 *
 * All monetary calculations use integer paise arithmetic (never floating point).
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Save, AlertTriangle, CheckCircle, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { formatPaise } from "@/lib/services/formatting";
import { getClients } from "@/lib/data/clients";
import {
  computeAdvanceTaxInterest, listAdvanceTaxPayments, saveAdvanceTaxPayments,
  type AdvanceTaxComputeResult, type AdvanceTaxInstallmentInput,
} from "@/lib/data/income-tax";
import type { Client } from "@/lib/types";
import { todayLocalISO } from "@/lib/dateMath";

const FY_OPTIONS = ["2026-27", "2025-26", "2024-25"];
const INSTALLMENT_LABELS: Record<number, string> = {
  1: "1st Installment (15 Jun)",
  2: "2nd Installment (15 Sep)",
  3: "3rd Installment (15 Dec)",
  4: "4th Installment (15 Mar)",
};

function rowStatus(dueDate: string, requiredPaise: number, paidPaise: number): "paid" | "overdue" | "upcoming" {
  if (paidPaise >= requiredPaise) return "paid";
  if (todayLocalISO() > dueDate) return "overdue";
  return "upcoming";
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AdvanceTaxPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [estimatedTaxRs, setEstimatedTaxRs] = useState("");
  const [editPaidRs, setEditPaidRs] = useState<Record<number, string>>({});
  const [editPaidDate, setEditPaidDate] = useState<Record<number, string>>({});
  const [editChallan, setEditChallan] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  const [result, setResult] = useState<AdvanceTaxComputeResult | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
  }, []);

  const loadData = useCallback(async () => {
    if (!clientId) return;
    setLoading(true);
    setError(null);
    try {
      const rows = await listAdvanceTaxPayments(clientId, fy);
      const paidRs: Record<number, string> = {};
      const paidDate: Record<number, string> = {};
      const challan: Record<number, string> = {};
      for (const n of [1, 2, 3, 4]) {
        const row = rows.find(r => r.installment_number === n);
        paidRs[n] = row && row.paid_amount_paise > 0 ? (row.paid_amount_paise / 100).toFixed(2) : "";
        paidDate[n] = row?.paid_date ?? "";
        challan[n] = row?.challan_number ?? "";
      }
      setEditPaidRs(paidRs);
      setEditPaidDate(paidDate);
      setEditChallan(challan);
      const withEstimate = rows.find(r => r.estimated_tax_paise > 0);
      if (withEstimate) setEstimatedTaxRs((withEstimate.estimated_tax_paise / 100).toFixed(2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [clientId, fy]);

  useEffect(() => { loadData(); }, [loadData]);

  // Every figure on this screen drives s.234B and s.234C interest, which is
  // charged per month on a shortfall — so an estimate read as ₹1 does not just
  // understate the tax, it manufactures interest.
  const estimatedTaxPaise = paiseFromRupeeInput(estimatedTaxRs || "0") ?? 0;
  const paidPaiseOf = (n: number | string) => paiseFromRupeeInput(editPaidRs[n as never] || "0");
  const badPaidInstalment = [1, 2, 3, 4].find((n) => paidPaiseOf(n) === null);

  // Server-side compute, debounced 400ms (matches the capital-gains
  // calculator's pattern) so every keystroke doesn't fire a request.
  useEffect(() => {
    if (badPaidInstalment !== undefined) {
      // An instalment that is not an amount stops the calculation and says so.
      // Computing on a coerced zero would report a shortfall — and s.234C
      // charges 1% a month on one — for tax the client has actually paid.
      setResult(null);
      setComputeError(`Instalment ${badPaidInstalment}: enter the amount paid in `
                      + "rupees, e.g. 125000 — without commas.");
      return;
    }
    if (estimatedTaxPaise <= 0) {
      setResult(null);
      setComputeError(null);
      return;
    }
    const timer = setTimeout(() => {
      const installments: AdvanceTaxInstallmentInput[] = [1, 2, 3, 4].map(n => ({
        installment_number: n as 1 | 2 | 3 | 4,
        paid_amount_paise: paidPaiseOf(n) as number,
        paid_date: editPaidDate[n] || null,
        challan_number: editChallan[n] || null,
      }));
      computeAdvanceTaxInterest({ fy, estimated_tax_paise: estimatedTaxPaise, installments })
        .then(r => { setResult(r); setComputeError(null); })
        .catch(e => { setResult(null); setComputeError(e instanceof Error ? e.message : "Failed to compute"); });
    }, 400);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fy, estimatedTaxPaise, editPaidRs, editPaidDate, editChallan]);

  async function handleSave() {
    if (!clientId || estimatedTaxPaise <= 0) {
      setError("Enter estimated annual tax first");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const installments: AdvanceTaxInstallmentInput[] = [1, 2, 3, 4].map(n => ({
        installment_number: n as 1 | 2 | 3 | 4,
        paid_amount_paise: paidPaiseOf(n) as number,
        paid_date: editPaidDate[n] || null,
        challan_number: editChallan[n] || null,
      }));
      await saveAdvanceTaxPayments({ client_id: clientId, fy, estimated_tax_paise: estimatedTaxPaise, installments });
      setSaveMsg("Saved");
      setTimeout(() => setSaveMsg(null), 3000);
      await loadData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  const totalPaid = [1, 2, 3, 4].reduce((s, n) => s + (paidPaiseOf(n) ?? 0), 0);
  const totalInterest = result?.total_interest_paise ?? 0;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-[#94A3B8] hover:text-[#475569]"><ChevronLeft size={18} /></Link>
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-[#0F172A]">Advance Tax Tracker</h1>
          <p className="text-sm text-[#64748B] mt-0.5">IT Act Section 207/208 — 4 installments per FY</p>
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="text-xs text-[#64748B]">Client</label>
          <div className="mt-1 min-w-[200px]">
            <ClientLookup
              clients={clients}
              value={clientId}
              onChange={setClientId}
              ariaLabel="Client"
              placeholder="Select client…"
            />
          </div>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Financial Year</label>
          <select value={fy} onChange={e => setFy(e.target.value)}
            className="block mt-1 border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500">
            {FY_OPTIONS.map(f => <option key={f} value={f}>FY {f}</option>)}
          </select>
        </div>
        <div>
          <label className="text-xs text-[#64748B]">Estimated Annual Tax (₹)</label>
          <input type="number" min="0" step="0.01" value={estimatedTaxRs}
            onChange={e => setEstimatedTaxRs(e.target.value)}
            className="block mt-1 border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 w-48"
            placeholder="Enter tax amount" />
        </div>
        <Button onClick={handleSave} disabled={saving || !clientId}>
          <Save size={14} className="mr-1" /> {saving ? "Saving…" : "Save"}
        </Button>
      </div>

      {error && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{error}</div>}
      {computeError && <div className="bg-red-50 text-red-700 rounded-lg px-5 py-4 text-sm">{computeError}</div>}
      {saveMsg && <div className="bg-green-50 text-green-700 rounded-lg px-5 py-2 text-sm">{saveMsg}</div>}

      {/* Summary */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        {[
          { label: "Estimated Tax", value: formatPaise(estimatedTaxPaise) },
          { label: "Total Paid", value: formatPaise(totalPaid) },
          { label: "Interest u/s 234C", value: formatPaise(totalInterest), red: totalInterest > 0 },
        ].map(s => (
          <Card key={s.label}>
            <CardContent className="pt-4 pb-3">
              <p className={`text-lg font-bold tabular-nums ${s.red ? "text-red-600" : "text-[#0F172A]"}`}>{s.value}</p>
              <p className="text-xs text-[#64748B] mt-0.5">{s.label}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Installment table */}
      <Card>
        {loading ? (
          <TableSkeleton cols={9} bare />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[#F1F5F9] text-xs text-[#94A3B8]">
                  <th className="px-5 py-3 text-left">Installment</th>
                  <th className="px-3 py-3 text-left">Due Date</th>
                  <th className="px-3 py-3 text-right">Required %</th>
                  <th className="px-3 py-3 text-right">Required Amount</th>
                  <th className="px-3 py-3 text-right">Paid Amount (₹)</th>
                  <th className="px-3 py-3 text-left">Paid Date</th>
                  <th className="px-3 py-3 text-left">Challan No.</th>
                  <th className="px-3 py-3 text-right">Interest 234C</th>
                  <th className="px-5 py-3 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                {[1, 2, 3, 4].map(n => {
                  const inst = result?.installments.find(i => i.installment_number === n);
                  const dueDate = inst?.due_date ?? "";
                  const requiredPercent = inst?.cumulative_required_percent ?? [15, 45, 75, 100][n - 1];
                  const requiredPaise = inst?.required_cumulative_paise ?? 0;
                  const interest = inst?.interest_paise ?? 0;
                  const paidPaise = paidPaiseOf(n) ?? 0;
                  const status = dueDate ? rowStatus(dueDate, requiredPaise, paidPaise) : "upcoming";

                  const statusEl = status === "paid"
                    ? <span className="inline-flex items-center gap-1 text-xs text-green-700 bg-green-50 px-2 py-0.5 rounded-full"><CheckCircle size={11} /> Paid</span>
                    : status === "overdue"
                    ? <span className="inline-flex items-center gap-1 text-xs text-red-700 bg-red-50 px-2 py-0.5 rounded-full"><AlertTriangle size={11} /> Overdue</span>
                    : <span className="inline-flex items-center gap-1 text-xs text-[#475569] bg-[#F1F5F9] px-2 py-0.5 rounded-full"><Clock size={11} /> Upcoming</span>;

                  return (
                    <tr key={n} className="hover:bg-[#F8FAFC]">
                      <td className="px-5 py-3 text-sm font-medium">{INSTALLMENT_LABELS[n]}</td>
                      <td className="px-3 py-3 text-xs text-[#475569]">{dueDate || "—"}</td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums">{requiredPercent}%</td>
                      <td className="px-3 py-3 text-sm text-right tabular-nums font-medium">{formatPaise(requiredPaise)}</td>
                      <td className="px-3 py-3">
                        <input type="number" min="0" step="0.01"
                          value={editPaidRs[n] ?? ""}
                          onChange={e => setEditPaidRs(prev => ({ ...prev, [n]: e.target.value }))}
                          className="w-28 border border-[#E2E8F0] rounded px-2 py-1 text-sm text-right outline-none focus:border-blue-500" />
                      </td>
                      <td className="px-3 py-3">
                        <input type="date"
                          value={editPaidDate[n] ?? ""}
                          onChange={e => setEditPaidDate(prev => ({ ...prev, [n]: e.target.value }))}
                          className="border border-[#E2E8F0] rounded px-2 py-1 text-xs outline-none focus:border-blue-500" />
                      </td>
                      <td className="px-3 py-3">
                        <input type="text"
                          value={editChallan[n] ?? ""}
                          onChange={e => setEditChallan(prev => ({ ...prev, [n]: e.target.value }))}
                          placeholder="BSR/challan"
                          className="w-32 border border-[#E2E8F0] rounded px-2 py-1 text-xs outline-none focus:border-blue-500" />
                      </td>
                      <td className={`px-3 py-3 text-sm text-right tabular-nums ${interest > 0 ? "text-red-600 font-semibold" : "text-[#94A3B8]"}`}>
                        {interest > 0 ? formatPaise(interest) : "—"}
                      </td>
                      <td className="px-5 py-3">{statusEl}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="text-xs text-[#94A3B8] text-center">
        Interest computed under IT Act Section 234C: a fixed 3-month period on the
        shortfall for instalments 1–3, 1 month for instalment 4 — not based on how
        late the payment actually was. CA Review Required before filing.
      </p>
    </div>
  );
}
