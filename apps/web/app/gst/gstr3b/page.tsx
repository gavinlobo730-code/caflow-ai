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
  Info,
  X,
} from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import {
  computeGSTR3B,
  approveGSTR3B,
  markGSTR3BFiled,
  downloadGSTR3BJSON,
  getGSTR3BReturn,
  toPeriod,
  type GSTR3BComputeResult,
  type GSTReturnStatus,
} from "@/lib/data/gst";

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

  // Mark as Filed modal
  const [showFiledModal, setShowFiledModal] = useState(false);
  const [arn, setArn] = useState("");
  const [filingStatus, setFilingStatus] = useState<GSTReturnStatus | null>(null);

  useEffect(() => {
    const sb = getSupabaseClient();
    sb.from("clients")
      .select("id,name,gstin")
      .eq("status", "active")
      .order("name")
      .then(({ data }) => setClients((data ?? []) as { id: string; name: string; gstin: string | null }[]));
  }, []);

  async function handleCompute() {
    if (!clientId || !yearMonth) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await computeGSTR3B(clientId, yearMonth);
      setResult(res);
      const period = toPeriod(yearMonth);
      const saved = await getGSTR3BReturn(clientId, period);
      setFilingStatus((saved?.status as GSTReturnStatus) ?? "draft");
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
            <select
              value={clientId}
              onChange={e => { setClientId(e.target.value); setResult(null); setError(null); }}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">— Select client —</option>
              {clients.map(c => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.gstin ? ` (${c.gstin})` : " (no GSTIN)"}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-[#334155] mb-1">Period</label>
            <select
              value={yearMonth}
              onChange={e => { setYearMonth(e.target.value); setResult(null); setError(null); }}
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

          {/* Table 4 — ITC Available */}
          <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0] flex items-center justify-between">
              <div>
                <h3 className="font-semibold text-[#1E293B] text-sm">Table 4 — ITC Available</h3>
                <p className="text-xs text-[#64748B] mt-0.5">CGST Rule 36(4): capped at 105% of GSTR-2A credit.</p>
              </div>
              {w.itc.rule_36_4_cap_applied && (
                <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full font-medium">
                  Rule 36(4) cap applied
                </span>
              )}
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[#64748B] uppercase border-b border-[#F1F5F9]">
                  <th className="text-left px-5 py-2.5 font-medium">ITC Component</th>
                  <th className="text-right px-5 py-2.5 font-medium">IGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">CGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">SGST</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#475569] text-xs">As per books (purchase register)</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc.book_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc.book_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc.book_sgst_paise)}</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#475569] text-xs">As per GSTR-2A (supplier-filed)</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc.gstr2a_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc.gstr2a_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.itc.gstr2a_sgst_paise)}</td>
                </tr>
                <tr className="bg-green-50 font-semibold">
                  <td className="px-5 py-3 text-green-800">Eligible ITC (after Rule 36(4))</td>
                  <td className="px-5 py-3 text-right font-mono text-green-900">{r(w.itc.eligible_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-green-900">{r(w.itc.eligible_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-green-900">{r(w.itc.eligible_sgst_paise)}</td>
                </tr>
              </tbody>
            </table>
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
