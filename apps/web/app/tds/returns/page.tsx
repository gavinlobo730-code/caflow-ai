"use client";

/**
 * TDS Returns — 24Q/26Q filing review, CA approval, and JSON download.
 *
 * IT Act Section 192 — Salary TDS (Form 24Q)
 * IT Act Section 194 — Non-salary TDS (Form 26Q)
 * IT Act Section 203 — TDS Certificates (Form 16/16A)
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
 */

import { useState, useEffect } from "react";
import {
  FileText, CheckCircle, AlertTriangle, Download,
  Info, X,
} from "lucide-react";
import Link from "next/link";
import { getSupabaseClient } from "@/lib/supabase/client";
import {
  getTDSDeductions, getTDSChallans,
  compute26Q, compute24Q, approveTDSReturn, markTDSFiled,
  saveTDSReturn, downloadTDSJSON, currentFinancialYear, currentQuarter,
  type TDSReturnPayload, type TDSReturnStatus, type TDSQuarter, type TDSReturnType,
} from "@/lib/data/tds";

function r(paise: number) {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

const STATUS_CONFIG: Record<TDSReturnStatus, { label: string; color: string }> = {
  pending:     { label: "Pending",     color: "bg-[#F1F5F9] text-[#334155]" },
  prepared:    { label: "Prepared",    color: "bg-blue-100 text-blue-700" },
  ca_approved: { label: "CA Approved", color: "bg-green-100 text-green-700" },
  filed:       { label: "Filed",       color: "bg-emerald-100 text-emerald-700" },
  revised:     { label: "Revised",     color: "bg-amber-100 text-amber-700" },
};

const QUARTERS: TDSQuarter[] = ["Q1", "Q2", "Q3", "Q4"];
const QUARTER_LABELS: Record<TDSQuarter, string> = {
  Q1: "Q1 (Apr–Jun)",
  Q2: "Q2 (Jul–Sep)",
  Q3: "Q3 (Oct–Dec)",
  Q4: "Q4 (Jan–Mar)",
};

export default function TDSReturnsPage() {
  const [clients, setClients] = useState<{ id: string; name: string; tan?: string }[]>([]);
  const [clientId, setClientId] = useState("");
  const [returnType, setReturnType] = useState<TDSReturnType>("26Q");
  const [financialYear, setFinancialYear] = useState(currentFinancialYear());
  const [quarter, setQuarter] = useState<TDSQuarter>(currentQuarter());

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TDSReturnPayload | null>(null);
  const [returnId, setReturnId] = useState<string | null>(null);
  const [filingStatus, setFilingStatus] = useState<TDSReturnStatus>("pending");
  const [error, setError] = useState<string | null>(null);

  const [approving, setApproving] = useState(false);
  const [showFiledModal, setShowFiledModal] = useState(false);
  const [prn, setPrn] = useState("");
  const [ackNumber, setAckNumber] = useState("");

  const [tab, setTab] = useState<"summary" | "deductees" | "challans" | "json">("summary");

  useEffect(() => {
    const sb = getSupabaseClient();
    sb.from("clients")
      .select("id,name")
      .eq("status", "active")
      .order("name")
      .then(({ data }) => setClients((data ?? []) as { id: string; name: string }[]));
  }, []);

  async function handleCompute() {
    if (!clientId) { setError("Select a client"); return; }
    setLoading(true); setError(null); setResult(null);
    try {
      // Fetch raw deductions and challans from Supabase
      const deductions = await getTDSDeductions(clientId, financialYear, quarter);
      const challans = await getTDSChallans(clientId, quarter);

      if (deductions.length === 0) {
        setError("No TDS deductions found for this period. Add deductions from the TDS Deductions tab.");
        return;
      }

      // Build deductee records
      const deductees = deductions.map(d => ({
        deductee_name: String(d.deductee_name ?? d.party_name ?? ""),
        deductee_pan: String(d.deductee_pan ?? d.party_pan ?? "PANNOTAVBL"),
        section: String(d.section ?? ""),
        nature_of_payment: String(d.nature_of_payment ?? ""),
        payment_date: String(d.transaction_date ?? d.payment_date ?? ""),
        payment_amount_paise: Number(d.payment_amount_paise ?? d.taxable_amount_paise ?? 0),
        tds_rate_pct: Number(d.tds_rate_pct ?? d.tds_rate ?? 0),
        tds_deducted_paise: Number(d.tds_paise ?? 0),
        tds_deposited_paise: Number(d.tds_paise ?? 0),
        challan_no: String(d.challan_no ?? ""),
        bsr_code: String(d.bsr_code ?? ""),
        challan_date: String(d.challan_date ?? d.transaction_date ?? ""),
        is_lower_deduction: Boolean(d.is_lower_deduction ?? false),
      }));

      const challanRecords = challans.map(c => ({
        challan_no: String(c.challan_no ?? ""),
        bsr_code: String(c.bsr_code ?? ""),
        payment_date: String(c.payment_date ?? ""),
        tds_paise: Number(c.tds_paise ?? 0),
        surcharge_paise: Number(c.surcharge_paise ?? 0),
        interest_paise: Number(c.interest_paise ?? 0),
        total_paise: Number(c.total_paise ?? c.tds_paise ?? 0),
        bank_name: String(c.bank_name ?? ""),
        section: String(c.section ?? ""),
      }));

      // Fetch TAN from client's compliance data (best-effort)
      const tan = "MUMB00000A"; // placeholder — must be configured per client
      const deductorName = clients.find(c => c.id === clientId)?.name ?? "";

      const req = {
        client_id: clientId,
        tan,
        deductor_name: deductorName,
        deductor_pan: "AAAAA0000A",
        deductor_address: "Address not configured",
        financial_year: financialYear,
        quarter,
        deductees,
        challans: challanRecords,
      };

      let payload: TDSReturnPayload;
      if (returnType === "24Q") {
        payload = await compute24Q(req);
      } else {
        payload = await compute26Q(req);
      }

      const rid = await saveTDSReturn(clientId, payload, "prepared");
      setResult(payload);
      setReturnId(rid);
      setFilingStatus("prepared");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Computation failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleApprove() {
    if (!returnId) return;
    setApproving(true);
    try {
      await approveTDSReturn(returnId);
      setFilingStatus("ca_approved");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval failed");
    } finally {
      setApproving(false);
    }
  }

  async function handleMarkFiled() {
    if (!returnId || !prn) return;
    try {
      await markTDSFiled(returnId, prn, ackNumber);
      setFilingStatus("filed");
      setShowFiledModal(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to mark as filed");
    }
  }

  const statusCfg = filingStatus ? STATUS_CONFIG[filingStatus] : STATUS_CONFIG.pending;

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/tds" className="text-[#94A3B8] hover:text-[#475569] text-sm">← TDS</Link>
        <h1 className="text-xl font-bold text-[#0F172A]">TDS Returns — 24Q / 26Q</h1>
      </div>

      {/* CA Review Banner */}
      <div className="flex items-start gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
        <AlertTriangle size={16} className="text-amber-600 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-800">
          <strong>CA Review Required.</strong> Review all figures before filing. Do not submit to TRACES without explicit CA approval. Download JSON for manual submission via TRACES portal.
        </p>
      </div>

      {/* Selector */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Client *</label>
            <select value={clientId} onChange={e => setClientId(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
              <option value="">Select client…</option>
              {clients.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Return Type</label>
            <select value={returnType} onChange={e => setReturnType(e.target.value as TDSReturnType)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
              <option value="26Q">26Q — Non-salary (194 series)</option>
              <option value="24Q">24Q — Salary (192)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Financial Year</label>
            <select value={financialYear} onChange={e => setFinancialYear(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
              <option value="2025-26">2025-26</option>
              <option value="2024-25">2024-25</option>
              <option value="2023-24">2023-24</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[#334155] mb-1">Quarter</label>
            <select value={quarter} onChange={e => setQuarter(e.target.value as TDSQuarter)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500">
              {QUARTERS.map(q => <option key={q} value={q}>{QUARTER_LABELS[q]}</option>)}
            </select>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button onClick={handleCompute} disabled={loading || !clientId}
            className="flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
            {loading ? "Computing…" : `Compute ${returnType}`}
          </button>
          {result && (
            <span className={`px-2.5 py-1 rounded-full text-xs font-medium ${statusCfg.color}`}>
              {statusCfg.label}
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
          <X size={15} className="shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Validation errors */}
          {result.validation_errors.length > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-xl p-4 space-y-1">
              <p className="text-sm font-semibold text-red-700 flex items-center gap-2">
                <AlertTriangle size={14} /> {result.validation_errors.length} Validation Error(s)
              </p>
              {result.validation_errors.map((e, i) => (
                <p key={i} className="text-xs text-red-600 pl-5">• {e}</p>
              ))}
            </div>
          )}

          {result.warnings.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-1">
              <p className="text-sm font-semibold text-amber-700 flex items-center gap-2">
                <Info size={14} /> {result.warnings.length} Warning(s)
              </p>
              {result.warnings.map((w, i) => (
                <p key={i} className="text-xs text-amber-700 pl-5">• {w}</p>
              ))}
            </div>
          )}

          {/* Tabs */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="flex border-b border-[#E2E8F0]">
              {(["summary", "deductees", "challans", "json"] as const).map(t => (
                <button key={t} onClick={() => setTab(t)}
                  className={`px-4 py-3 text-sm font-medium capitalize transition-colors ${
                    tab === t ? "border-b-2 border-blue-600 text-blue-600" : "text-[#64748B] hover:text-[#334155]"
                  }`}>
                  {t}
                </button>
              ))}
            </div>

            <div className="p-4">
              {tab === "summary" && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-[#F8FAFC] rounded-xl p-4 text-center">
                      <p className="text-xs text-[#64748B] mb-1">Total Payment</p>
                      <p className="text-lg font-bold text-[#0F172A]">
                        {r(result.total_payment_paise ?? result.total_salary_paise ?? 0)}
                      </p>
                    </div>
                    <div className="bg-blue-50 rounded-xl p-4 text-center">
                      <p className="text-xs text-blue-600 mb-1">TDS Deducted</p>
                      <p className="text-lg font-bold text-blue-900">{r(result.total_tds_deducted_paise)}</p>
                    </div>
                    <div className="bg-green-50 rounded-xl p-4 text-center">
                      <p className="text-xs text-green-600 mb-1">TDS Deposited</p>
                      <p className="text-lg font-bold text-green-900">{r(result.total_tds_deposited_paise)}</p>
                    </div>
                    <div className="bg-[#F8FAFC] rounded-xl p-4 text-center">
                      <p className="text-xs text-[#64748B] mb-1">Deductees</p>
                      <p className="text-lg font-bold text-[#0F172A]">{result.deductee_count}</p>
                    </div>
                  </div>
                  <div className="text-xs text-[#64748B] space-y-1">
                    <p>Form: <strong>{result.form}</strong></p>
                    <p>TAN: <strong className="font-mono">{result.tan}</strong></p>
                    <p>Period: <strong>{result.financial_year} — {result.quarter} (ends {result.quarter_end_date})</strong></p>
                    <p>Deductor: <strong>{result.deductor_name}</strong></p>
                  </div>
                </div>
              )}

              {tab === "deductees" && (
                <div className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                      <tr>
                        <th className="text-left px-3 py-2 text-[#475569]">Name</th>
                        <th className="text-left px-3 py-2 text-[#475569] font-mono">PAN</th>
                        <th className="text-left px-3 py-2 text-[#475569]">Section</th>
                        <th className="text-right px-3 py-2 text-[#475569]">Payment</th>
                        <th className="text-right px-3 py-2 text-[#475569]">Rate</th>
                        <th className="text-right px-3 py-2 text-[#475569]">TDS Deducted</th>
                        <th className="text-right px-3 py-2 text-[#475569]">TDS Deposited</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F1F5F9]">
                      {result.deductees.map((d, i) => (
                        <tr key={i} className="bg-white hover:bg-[#F8FAFC]">
                          <td className="px-3 py-2">{d.deductee_name}</td>
                          <td className="px-3 py-2 font-mono">{d.deductee_pan}</td>
                          <td className="px-3 py-2">
                            <span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded text-xs">{d.section}</span>
                          </td>
                          <td className="px-3 py-2 text-right">{r(d.payment_amount_paise)}</td>
                          <td className="px-3 py-2 text-right">{d.tds_rate_pct}%</td>
                          <td className="px-3 py-2 text-right font-semibold">{r(d.tds_deducted_paise)}</td>
                          <td className="px-3 py-2 text-right text-green-700">{r(d.tds_deposited_paise)}</td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot className="bg-[#F8FAFC] border-t border-[#E2E8F0] font-semibold">
                      <tr>
                        <td colSpan={3} className="px-3 py-2">Total</td>
                        <td className="px-3 py-2 text-right">{r(result.total_payment_paise ?? result.total_salary_paise ?? 0)}</td>
                        <td />
                        <td className="px-3 py-2 text-right text-blue-700">{r(result.total_tds_deducted_paise)}</td>
                        <td className="px-3 py-2 text-right text-green-700">{r(result.total_tds_deposited_paise)}</td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}

              {tab === "challans" && (
                result.challans.length > 0 ? (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr>
                          <th className="text-left px-3 py-2 text-[#475569]">Challan No</th>
                          <th className="text-left px-3 py-2 text-[#475569]">BSR Code</th>
                          <th className="text-left px-3 py-2 text-[#475569]">Date</th>
                          <th className="text-right px-3 py-2 text-[#475569]">TDS</th>
                          <th className="text-right px-3 py-2 text-[#475569]">Interest</th>
                          <th className="text-right px-3 py-2 text-[#475569]">Total</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F1F5F9]">
                        {result.challans.map((c, i) => (
                          <tr key={i} className="bg-white">
                            <td className="px-3 py-2 font-mono">{c.challan_no}</td>
                            <td className="px-3 py-2 font-mono">{c.bsr_code}</td>
                            <td className="px-3 py-2">{c.payment_date}</td>
                            <td className="px-3 py-2 text-right">{r(c.tds_paise)}</td>
                            <td className="px-3 py-2 text-right">{r(c.interest_paise ?? 0)}</td>
                            <td className="px-3 py-2 text-right font-semibold">{r(c.total_paise)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="text-sm text-[#64748B] text-center py-8">No challans linked to this period.</p>
                )
              )}

              {tab === "json" && (
                <pre className="text-xs bg-gray-900 text-green-400 rounded-lg p-4 overflow-auto max-h-80 font-mono">
                  {JSON.stringify(result, null, 2)}
                </pre>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex flex-wrap gap-3">
            {(filingStatus === "prepared") && (
              <button onClick={handleApprove} disabled={approving || result.validation_errors.length > 0}
                className="flex items-center gap-2 bg-green-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-green-700 disabled:opacity-50">
                <CheckCircle size={15} />
                {approving ? "Approving…" : "CA Approve"}
              </button>
            )}
            {(filingStatus === "ca_approved" || filingStatus === "filed") && (
              <button onClick={() => result && downloadTDSJSON(result)}
                className="flex items-center gap-2 bg-white border border-gray-300 text-[#334155] px-4 py-2 rounded-lg text-sm font-medium hover:bg-[#F8FAFC]">
                <Download size={15} />
                Download JSON (for TRACES)
              </button>
            )}
            {filingStatus === "ca_approved" && (
              <button onClick={() => setShowFiledModal(true)}
                className="flex items-center gap-2 bg-emerald-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-emerald-700">
                <FileText size={15} />
                Mark as Filed
              </button>
            )}
          </div>
        </div>
      )}

      {/* Mark as Filed Modal */}
      {showFiledModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div className="absolute inset-0 bg-black/40" onClick={() => setShowFiledModal(false)} />
          <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4">
            <h3 className="font-semibold text-[#0F172A]">Mark {returnType} as Filed</h3>
            <p className="text-sm text-[#64748B]">Enter the details from TRACES after successful submission.</p>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">PRN (Provisional Receipt Number) *</label>
              <input value={prn} onChange={e => setPrn(e.target.value.toUpperCase())}
                placeholder="Enter PRN from TRACES"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-[#334155] mb-1">Acknowledgement Number</label>
              <input value={ackNumber} onChange={e => setAckNumber(e.target.value)}
                placeholder="Optional acknowledgement number"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono outline-none focus:border-blue-500" />
            </div>
            <div className="flex gap-3 pt-1">
              <button onClick={() => setShowFiledModal(false)}
                className="flex-1 rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-[#334155] hover:bg-[#F8FAFC]">
                Cancel
              </button>
              <button onClick={handleMarkFiled} disabled={!prn}
                className="flex-1 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50">
                Confirm Filed
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
