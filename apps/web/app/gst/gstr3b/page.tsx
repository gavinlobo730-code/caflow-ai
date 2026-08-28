"use client";

/**
 * GSTR-3B Review UI — CA review, approval, and JSON download for portal upload.
 *
 * CGST Act Section 39 — Monthly summary return, due 20th of following month.
 * CGST Rule 36(4) — ITC restricted to 105% of eligible GSTR-2A credit.
 * CGST Act Section 49(5) — IGST ITC cross-utilisation sequence.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to any government portal.
 * The Download JSON button produces a file for manual upload to gst.gov.in.
 */

import { useState, useEffect } from "react";
import {
  Calculator,
  CheckCircle,
  AlertTriangle,
  Download,
  FileCheck,
  ChevronRight,
  ArrowLeft,
  Clock,
  Info,
  X,
} from "lucide-react";
import Link from "next/link";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import {
  computeGSTR3B,
  approveGSTR3B,
  markGSTR3BFiled,
  downloadGSTR3BJSON,
  getGSTR3BReturn,
  fetchRule37Report,
  toPeriod,
  type GSTR3BComputeResult,
  type GSTReturnStatus,
  type Rule37Report,
} from "@/lib/data/gst";
import { periodEndDate, splitRule37Bills } from "@/lib/gst/rule37Period";

// ── Helpers ───────────────────────────────────────────────────────────────────

function r(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function buildPeriodOptions(): { value: string; label: string }[] {
  const opts: { value: string; label: string }[] = [];
  const now = new Date();
  for (let i = 11; i >= 0; i--) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    opts.push({
      value: `${yyyy}-${mm}`,
      label: d.toLocaleDateString("en-IN", { month: "long", year: "numeric" }),
    });
  }
  return opts.reverse();
}

const PERIOD_OPTIONS = buildPeriodOptions();

const STATUS_CONFIG: Record<GSTReturnStatus, { label: string; color: string }> = {
  draft:       { label: "Draft",       color: "bg-[#F1F5F9] text-[#334155]" },
  validated:   { label: "Validated",   color: "bg-blue-100 text-blue-700" },
  ca_approved: { label: "CA Approved", color: "bg-green-100 text-green-700" },
  submitted:   { label: "Filed",       color: "bg-emerald-100 text-emerald-700" },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function GSTR3BPage() {
  const [clients, setClients] = useState<{ id: string; name: string; gstin: string | null }[]>([]);
  const [clientId, setClientId] = useState("");
  const [yearMonth, setYearMonth] = useState(PERIOD_OPTIONS[1]?.value ?? "");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GSTR3BComputeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // CA Approve
  const [approving, setApproving] = useState(false);

  // Rule 37: reported alongside the return, never folded into it. See the
  // panel below for why the two must stay separate.
  const [rule37, setRule37] = useState<Rule37Report | null>(null);
  const [rule37Error, setRule37Error] = useState<string | null>(null);

  // Mark as Filed modal
  const [showFiledModal, setShowFiledModal] = useState(false);
  const [arn, setArn] = useState("");
  const [filingStatus, setFilingStatus] = useState<GSTReturnStatus | null>(null);

  useEffect(() => {
    const sb = getSupabaseClient();
    sb.from("clients")
      .select("id,name:client_name,gstin")
      .eq("status", "active")
      .order("client_name")
      .then(({ data }) => setClients((data ?? []) as { id: string; name: string; gstin: string | null }[]));
  }, []);

  async function handleCompute() {
    if (!clientId || !yearMonth) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setRule37(null);
    setRule37Error(null);
    try {
      const res = await computeGSTR3B(clientId, yearMonth);
      setResult(res);
      const period = toPeriod(yearMonth);
      const saved = await getGSTR3BReturn(clientId, period);
      setFilingStatus((saved?.status as GSTReturnStatus) ?? "draft");
      // Asked as at the PERIOD END, not today: a bill that crosses 180 days
      // next week belongs in next month's return, not this one. Failing this
      // must not fail the return — the figures above stand on their own.
      try {
        setRule37(await fetchRule37Report(clientId, periodEndDate(yearMonth)));
      } catch (e) {
        setRule37Error(e instanceof Error ? e.message : "Could not check Rule 37");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Computation failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove() {
    if (!clientId || !yearMonth || !result) return;
    setApproving(true);
    try {
      const sb = getSupabaseClient();
      const { data: { user } } = await sb.auth.getUser();
      await approveGSTR3B(clientId, toPeriod(yearMonth), user?.id ?? "");
      setFilingStatus("ca_approved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  }

  async function handleMarkFiled() {
    if (!clientId || !yearMonth || !arn.trim()) return;
    try {
      await markGSTR3BFiled(clientId, toPeriod(yearMonth), arn.trim());
      setFilingStatus("submitted");
      setShowFiledModal(false);
      setArn("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to mark as filed");
    }
  }

  function handleDownload() {
    if (!result || !clientId) return;
    const client = clients.find(c => c.id === clientId);
    const gstin = client?.gstin ?? "UNKNOWN";
    downloadGSTR3BJSON(result.payload, toPeriod(yearMonth), gstin);
  }

  const w = result?.working;
  const statusCfg = filingStatus ? STATUS_CONFIG[filingStatus] : null;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/gst" className="text-[#94A3B8] hover:text-[#475569]">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-[#0F172A]">GSTR-3B Review</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            CGST Act Section 39 — Monthly summary return. Due 20th of following month.
          </p>
        </div>
      </div>

      {/* CA Review Banner */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
        <Info className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-800">
          <strong>CA Review Required.</strong> Verify all figures before downloading JSON for portal upload.
          Do not upload to gst.gov.in without CA approval.
        </p>
      </div>

      {/* Selection */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-5 space-y-4">
        <h2 className="font-semibold text-[#1E293B]">Select Client & Period</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-[#334155] mb-1">Client</label>
            <div className="w-full">
              <ClientLookup
                clients={clients}
                value={clientId}
                onChange={(id) => { setClientId(id); setResult(null); setError(null); setRule37(null); }}
                ariaLabel="Client"
                placeholder="— Select client —"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-[#334155] mb-1">Period</label>
            <select
              value={yearMonth}
              onChange={e => { setYearMonth(e.target.value); setResult(null); setError(null); setRule37(null); }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              {PERIOD_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>
        <button
          onClick={handleCompute}
          disabled={!clientId || !yearMonth || loading}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <Calculator className="w-4 h-4" />
          {loading ? "Computing…" : "Compute GSTR-3B"}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && w && (
        <>
          {/* Status row */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {statusCfg && (
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${statusCfg.color}`}>
                  {statusCfg.label}
                </span>
              )}
              {result.validation_warnings.length > 0 && (
                <span className="flex items-center gap-1 text-xs text-amber-600">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {result.validation_warnings.length} warning{result.validation_warnings.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {filingStatus === "ca_approved" || filingStatus === "submitted" ? (
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  <Download className="w-4 h-4" />
                  Download JSON
                </button>
              ) : null}
              {filingStatus === "ca_approved" && (
                <button
                  onClick={() => setShowFiledModal(true)}
                  className="flex items-center gap-2 px-4 py-2 bg-[#F1F5F9] hover:bg-[#F8FAFC] text-[#334155] text-sm font-medium rounded-lg transition-colors"
                >
                  <FileCheck className="w-4 h-4" />
                  Mark as Filed
                </button>
              )}
              {(filingStatus === "draft" || filingStatus === "validated") && (
                <button
                  onClick={handleApprove}
                  disabled={approving}
                  className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  <CheckCircle className="w-4 h-4" />
                  {approving ? "Approving…" : "CA Approve"}
                </button>
              )}
            </div>
          </div>

          {/* Table 3.1 — Outward Taxable Supplies */}
          <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
              <h3 className="font-semibold text-[#1E293B] text-sm">
                Table 3.1 — Outward Taxable Supplies
              </h3>
              <p className="text-xs text-[#64748B] mt-0.5">Net of credit notes. CGST Act Section 37.</p>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[#64748B] uppercase border-b border-[#F1F5F9]">
                  <th className="text-left px-5 py-2.5 font-medium">Supply Type</th>
                  <th className="text-right px-5 py-2.5 font-medium">IGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">CGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">SGST</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">Taxable supplies (B2B + B2C + B2CL)</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.outward.taxable_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.outward.taxable_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.outward.taxable_sgst_paise)}</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">Zero-rated supplies (Exports / SEZ)</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B]">{r(w.outward.zero_rated_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">Nil-rated / Exempt</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B]">{r(w.outward.nil_exempt_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                </tr>
                <tr className="bg-blue-50 font-semibold">
                  <td className="px-5 py-3 text-blue-800">Total Output Tax</td>
                  <td className="px-5 py-3 text-right font-mono text-blue-900">{r(w.outward.taxable_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-blue-900">{r(w.outward.taxable_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-blue-900">{r(w.outward.taxable_sgst_paise)}</td>
                </tr>
              </tbody>
            </table>
          </section>

          {/* Table 4 — ITC, in the layout the portal has used since 01-09-2022 */}
          <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
              <h3 className="font-semibold text-[#1E293B] text-sm">Table 4 — Input Tax Credit</h3>
              <p className="text-xs text-[#64748B] mt-0.5">
                Notification 14/2022 with Circular 170/02/2022-GST. 4(A) is gross — the portal
                populates it from GSTR-2B — and the reversals are declared separately in 4(B).
              </p>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[#64748B] uppercase border-b border-[#F1F5F9]">
                  <th className="text-left px-5 py-2.5 font-medium">Row</th>
                  <th className="text-right px-5 py-2.5 font-medium">IGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">CGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">SGST</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">
                    4(A) ITC available
                    <span className="block text-xs text-[#94A3B8]">All credit availed, including credit reversed below</span>
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.itc.avail_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.itc.avail_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.itc.avail_sgst_paise)}</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#475569] text-xs">
                    4(B)(1) Reversed — permanent
                    <span className="block text-[#94A3B8]">Rules 38, 42 and 43, and Section 17(5) blocked credit</span>
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc_reversal.permanent_paise.igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc_reversal.permanent_paise.cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc_reversal.permanent_paise.sgst_paise)}</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#475569] text-xs">
                    4(B)(2) Reversed — reclaimable later
                    <span className="block text-[#94A3B8]">Rule 37 / 37A and Section 16(2)(b), (c). Comes back through 4(A)(5)</span>
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc_reversal.reclaimable_paise.igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc_reversal.reclaimable_paise.cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc_reversal.reclaimable_paise.sgst_paise)}</td>
                </tr>
                <tr className="bg-green-50 font-semibold">
                  <td className="px-5 py-3 text-green-800">4(C) Net ITC available</td>
                  <td className="px-5 py-3 text-right font-mono text-green-900">{r(w.itc.net_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-green-900">{r(w.itc.net_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-green-900">{r(w.itc.net_sgst_paise)}</td>
                </tr>
              </tbody>
            </table>
            {w.itc_reversal.reasons.length > 0 && (
              <div className="px-5 py-3 border-t border-[#F1F5F9] bg-[#FCFCFD]">
                <p className="text-xs font-medium text-[#475569] mb-1.5">What is in 4(B)</p>
                <ul className="space-y-1">
                  {w.itc_reversal.reasons.map((x, i) => (
                    <li key={i} className="text-xs text-[#64748B] flex items-baseline justify-between gap-4">
                      <span>
                        {x.reason}
                        <span className="ml-2 text-[#94A3B8]">
                          {x.reclaimable ? "4(B)(2)" : "4(B)(1)"}
                        </span>
                      </span>
                      <span className="font-mono shrink-0">
                        {r(x.igst_paise + x.cgst_paise + x.sgst_paise + x.cess_paise)}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {/* Table 6 — Net Tax Payable */}
          <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
              <h3 className="font-semibold text-[#1E293B] text-sm">Table 6 — Net Tax Payable</h3>
              <p className="text-xs text-[#64748B] mt-0.5">CGST Act Section 49: IGST ITC cross-utilised against CGST/SGST if excess.</p>
            </div>
            <div className="grid grid-cols-4 divide-x divide-[#F1F5F9] text-center">
              {[
                { label: "IGST", value: w.net_payable.igst_paise, color: "text-blue-700" },
                { label: "CGST", value: w.net_payable.cgst_paise, color: "text-blue-600" },
                { label: "SGST", value: w.net_payable.sgst_paise, color: "text-purple-700" },
                { label: "Total", value: w.net_payable.total_paise, color: "text-red-700 font-bold" },
              ].map(item => (
                <div key={item.label} className="px-4 py-5">
                  <p className="text-xs text-[#64748B] font-medium mb-1">{item.label}</p>
                  <p className={`text-lg font-semibold font-mono ${item.color}`}>{r(item.value)}</p>
                </div>
              ))}
            </div>
          </section>

          {/* Rule 37 — reported beside the return, never folded into it */}
          {(rule37 || rule37Error) && (() => {
            if (rule37Error) {
              return (
                <section className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl p-4 text-sm text-[#64748B]">
                  <strong className="text-[#334155]">Rule 37 not checked.</strong>{" "}
                  {rule37Error} The figures above are unaffected, but this return has not been
                  checked for suppliers unpaid past 180 days.
                </section>
              );
            }
            // Rule 37(1) puts each reversal in ONE specific return. The bills
            // whose period is this one are what THIS 3B has to carry; earlier
            // ones belonged to a return that has already been filed, and are
            // listed separately rather than silently added here.
            const { due, earlier: overdueEarlier } =
              splitRule37Bills(rule37!.bills, toPeriod(yearMonth));
            const dueTotal = due.reduce((t, b) => t + b.reversal.total_paise, 0);
            const earlierTotal = overdueEarlier.reduce((t, b) => t + b.reversal.total_paise, 0);

            if (due.length === 0 && overdueEarlier.length === 0) {
              return (
                <section className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl p-4 flex items-start gap-2">
                  <CheckCircle className="w-4 h-4 text-[#94A3B8] mt-0.5 shrink-0" />
                  <p className="text-sm text-[#64748B]">
                    <strong className="text-[#334155]">No Rule 37 reversal due.</strong>{" "}
                    No purchase bill was 180 days unpaid as at {periodEndDate(yearMonth)}.
                  </p>
                </section>
              );
            }

            return (
              <section className="bg-amber-50 border border-amber-200 rounded-xl overflow-hidden">
                <div className="px-5 py-3 border-b border-amber-200 flex items-start gap-2">
                  <Clock className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
                  <div>
                    <h3 className="font-semibold text-amber-900 text-sm">
                      Rule 37 — credit to reverse in this return
                    </h3>
                    <p className="text-xs text-amber-800 mt-0.5">
                      CGST Act Section 16(2) second proviso and Rule 37: credit on a bill the
                      supplier has not been paid for within 180 days is reversed, in Table 4(B)(2).
                      It is reclaimed when the supplier is paid.
                    </p>
                  </div>
                </div>

                {due.length > 0 && (
                  <div className="px-5 py-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <p className="text-sm text-amber-900">
                        <strong>{due.length}</strong> bill{due.length !== 1 ? "s" : ""} crossed 180 days
                        for this period
                      </p>
                      <p className="font-mono font-semibold text-amber-900">{r(dueTotal)}</p>
                    </div>
                    <ul className="space-y-1.5">
                      {due.map(b => (
                        <li key={b.bill_id} className="text-xs text-amber-800 flex items-baseline justify-between gap-4">
                          <span>
                            <span className="font-mono">{b.bill_no ?? b.bill_id.slice(0, 8)}</span>
                            <span className="text-amber-700 ml-2">
                              {b.bill_date} · {b.days_outstanding} days · {r(b.unpaid_paise)} unpaid
                            </span>
                          </span>
                          <span className="font-mono shrink-0">{r(b.reversal.total_paise)}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {overdueEarlier.length > 0 && (
                  <div className="px-5 py-3 border-t border-amber-200 text-xs text-amber-800">
                    <strong>{overdueEarlier.length}</strong> more bill
                    {overdueEarlier.length !== 1 ? "s" : ""} ({r(earlierTotal)}) crossed 180 days in an
                    earlier period. Rule 37(1) puts those in the return for the period after the one
                    the 180 days expired in — check they were reversed then.
                  </div>
                )}

                <div className="px-5 py-3 bg-amber-100/60 border-t border-amber-200 text-xs text-amber-900">
                  <strong>Not included in Table 4(B) above.</strong> PracticeSync computes this return
                  from posted books, and no journal has been posted for these reversals — so adding
                  them here would put the return out of step with the ledger and the reconciliation
                  would flag it. Post the reversal journal, then recompute and it will appear in
                  4(B)(2) on its own.
                </div>
              </section>
            );
          })()}

          {/* Validation warnings */}
          {result.validation_warnings.length > 0 && (
            <section className="bg-amber-50 border border-amber-200 rounded-xl p-5">
              <h3 className="font-semibold text-amber-800 text-sm mb-3 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                Validation Warnings ({result.validation_warnings.length})
              </h3>
              <ul className="space-y-2">
                {result.validation_warnings.map((w, i) => (
                  <li key={i} className="text-sm text-amber-700 flex items-start gap-2">
                    <ChevronRight className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                    <span>
                      {w.invoice_ref && <span className="font-mono mr-1">[{w.invoice_ref}]</span>}
                      {w.message}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* JSON preview */}
          <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
              <h3 className="font-semibold text-[#1E293B] text-sm">GSTN Payload Preview</h3>
              <p className="text-xs text-[#64748B] mt-0.5">
                This is the JSON that will be uploaded to gst.gov.in after CA approval.
              </p>
            </div>
            <pre className="p-5 text-xs font-mono text-[#475569] overflow-auto max-h-80 bg-[#F8FAFC]">
              {JSON.stringify(result.payload, null, 2)}
            </pre>
          </section>
        </>
      )}

      {/* Mark as Filed modal */}
      {showFiledModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-[#0F172A]">Mark GSTR-3B as Filed</h3>
              <button onClick={() => { setShowFiledModal(false); setArn(""); }}>
                <X className="w-5 h-5 text-[#94A3B8] hover:text-[#475569]" />
              </button>
            </div>
            <p className="text-sm text-[#475569] mb-4">
              After uploading the JSON to <strong>gst.gov.in</strong> and receiving the Acknowledgment
              Reference Number (ARN), enter it below to record the filing in PracticeSync.
            </p>
            <div className="mb-4">
              <label className="block text-sm font-medium text-[#334155] mb-1">
                ARN (Acknowledgment Reference Number)
              </label>
              <input
                type="text"
                value={arn}
                onChange={e => setArn(e.target.value)}
                placeholder="e.g. AA270525XXXXXXXXXX"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => { setShowFiledModal(false); setArn(""); }}
                className="px-4 py-2 text-sm text-[#475569] hover:text-[#1E293B] border border-gray-300 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleMarkFiled}
                disabled={!arn.trim()}
                className="px-4 py-2 text-sm font-medium bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 text-white rounded-lg"
              >
                Confirm Filed
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
