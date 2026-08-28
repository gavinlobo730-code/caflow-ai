"use client";

/**
 * GSTR-1 Review UI — Invoice classification review, CA approval, JSON download.
 *
 * CGST Act Section 37 — Details of outward supplies, due 11th of following month.
 * CGST Rule 59(2) — B2CS/B2CL classification thresholds.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to any government portal.
 * The Download JSON button produces a file for manual upload to gst.gov.in.
 */

import { useState, useEffect } from "react";
import {
  FileText,
  CheckCircle,
  AlertTriangle,
  Download,
  FileCheck,
  ArrowLeft,
  Info,
  X,
  Building2,
  Globe,
  Users,
  ReceiptText,
} from "lucide-react";
import Link from "next/link";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { formatPaise } from "@/lib/services/formatting";
import { getSupabaseClient } from "@/lib/supabase/client";
import {
  buildGSTR1,
  approveGSTR1,
  markGSTR1Filed,
  downloadGSTR1JSON,
  toPeriod,
  type GSTR1BuildResult,
  type GSTReturnStatus,
} from "@/lib/data/gst";

// ── Helpers ───────────────────────────────────────────────────────────────────

function r(rupees: number): string {
  return "₹" + rupees.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// The from-books totals arrive in paise. Kept as a SEPARATE function from r()
// above rather than converting at the call site: two units behind one formatter
// name is how a GST figure silently ends up 100x out.
const p = formatPaise;

function buildPeriodOptions() {
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

type ActiveTab = "summary" | "b2b" | "b2cs" | "b2cl" | "cdnr" | "exp" | "hsn" | "json";

// ── Component ─────────────────────────────────────────────────────────────────

export default function GSTR1Page() {
  const [clients, setClients] = useState<{ id: string; name: string; gstin: string | null }[]>([]);
  const [clientId, setClientId] = useState("");
  const [yearMonth, setYearMonth] = useState(PERIOD_OPTIONS[1]?.value ?? "");

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GSTR1BuildResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filingStatus, setFilingStatus] = useState<GSTReturnStatus | null>(null);

  const [activeTab, setActiveTab] = useState<ActiveTab>("summary");

  // CA Approve
  const [approving, setApproving] = useState(false);

  // Mark as Filed modal
  const [showFiledModal, setShowFiledModal] = useState(false);
  const [arn, setArn] = useState("");

  useEffect(() => {
    const sb = getSupabaseClient();
    sb.from("clients")
      .select("id,name:client_name,gstin")
      .eq("status", "active")
      .order("client_name")
      .then(({ data }) => setClients((data ?? []) as { id: string; name: string; gstin: string | null }[]));
  }, []);

  async function handleBuild() {
    if (!clientId || !yearMonth) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await buildGSTR1(clientId, yearMonth);
      setResult(res);
      // from-books raises on anything it will not compute, so a returned
      // result is a validated one; a failure lands in catch below.
      setFilingStatus("validated");
      setActiveTab("summary");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Build failed");
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
      await approveGSTR1(clientId, toPeriod(yearMonth), user?.id ?? "");
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
      await markGSTR1Filed(clientId, toPeriod(yearMonth), arn.trim());
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
    downloadGSTR1JSON(result.payload, toPeriod(yearMonth), gstin);
  }

  const payload = result?.payload as Record<string, unknown> | undefined;
  const statusCfg = filingStatus ? STATUS_CONFIG[filingStatus] : null;
  const b2b = (payload?.b2b ?? []) as unknown[];
  const b2cs = (payload?.b2cs ?? []) as Record<string, unknown>[];
  const b2cl = (payload?.b2cl ?? []) as unknown[];
  const cdnr = (payload?.cdnr ?? []) as unknown[];
  const exp = (payload?.exp ?? []) as unknown[];
  const hsn = ((payload?.hsn as Record<string, unknown>)?.data ?? []) as Record<string, unknown>[];

  const TABS: { key: ActiveTab; label: string; count?: number }[] = [
    { key: "summary", label: "Summary" },
    { key: "b2b",     label: "B2B",      count: (b2b as { inv?: unknown[] }[]).reduce((n, g) => n + (g.inv?.length ?? 0), 0) },
    { key: "b2cs",    label: "B2CS",     count: b2cs.length },
    { key: "b2cl",    label: "B2CL",     count: (b2cl as { inv?: unknown[] }[]).reduce((n, g) => n + (g.inv?.length ?? 0), 0) },
    { key: "cdnr",    label: "CDNR",     count: (cdnr as { nt?: unknown[] }[]).reduce((n, g) => n + (g.nt?.length ?? 0), 0) },
    { key: "exp",     label: "Exports",  count: (exp as { inv?: unknown[] }[]).reduce((n, g) => n + (g.inv?.length ?? 0), 0) },
    { key: "hsn",     label: "HSN",      count: hsn.length },
    { key: "json",    label: "JSON" },
  ];

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/gst" className="text-[#94A3B8] hover:text-[#475569]">
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-2xl font-bold text-[#0F172A]">GSTR-1 Review</h1>
          <p className="text-sm text-[#64748B] mt-0.5">
            CGST Act Section 37 — Details of outward supplies. Due 11th of following month.
          </p>
        </div>
      </div>

      {/* CA Review Banner */}
      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-2">
        <Info className="w-4 h-4 text-amber-600 mt-0.5 shrink-0" />
        <p className="text-sm text-amber-800">
          <strong>CA Review Required.</strong> Verify invoice classifications and tax amounts before downloading.
          Maximum 5 MB / 19,000 line items per JSON upload to gst.gov.in.
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
                onChange={(id) => { setClientId(id); setResult(null); setError(null); }}
                ariaLabel="Client"
                placeholder="— Select client —"
              />
            </div>
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
          onClick={handleBuild}
          disabled={!clientId || !yearMonth || loading}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-sm font-medium rounded-lg transition-colors"
        >
          <FileText className="w-4 h-4" />
          {loading ? "Building…" : "Build GSTR-1"}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
          {error}
        </div>
      )}

      {result && (
        <>
          {/* Status + Actions row */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3 flex-wrap">
              {statusCfg && (
                <span className={`text-xs font-semibold px-2.5 py-1 rounded-full ${statusCfg.color}`}>
                  {statusCfg.label}
                </span>
              )}
              <span className="text-sm text-[#475569]">
                <strong>{result.invoice_count}</strong> invoices
                · Taxable <strong>{p(result.taxable_total_paise)}</strong>
                · Tax <strong>{p(result.tax_total_paise)}</strong>
              </span>
              {result.validation_warnings.length > 0 && (
                <span className="flex items-center gap-1 text-xs text-amber-600">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  {result.validation_warnings.length} warning{result.validation_warnings.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              {(filingStatus === "ca_approved" || filingStatus === "submitted") && (
                <button
                  onClick={handleDownload}
                  className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  <Download className="w-4 h-4" />
                  Download JSON
                </button>
              )}
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

          {/* The hard-errors panel lived here. From-books validates before it
              computes and raises 422, so an error never arrives as part of a
              result — it surfaces through the page's error banner instead. */}

          {/* Tabs */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="flex border-b border-[#E2E8F0] overflow-x-auto">
              {TABS.map(tab => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-1.5 px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors border-b-2 ${
                    activeTab === tab.key
                      ? "border-blue-600 text-blue-600"
                      : "border-transparent text-[#64748B] hover:text-[#334155]"
                  }`}
                >
                  {tab.label}
                  {tab.count !== undefined && tab.count > 0 && (
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      activeTab === tab.key ? "bg-blue-100 text-blue-700" : "bg-[#F1F5F9] text-[#64748B]"
                    }`}>
                      {tab.count}
                    </span>
                  )}
                </button>
              ))}
            </div>

            <div className="p-0">
              {/* Summary tab */}
              {activeTab === "summary" && (
                <div className="p-5 space-y-4">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                    {[
                      { icon: Building2, label: "B2B Invoices",    value: result.summary.counts.b2b ?? 0,                    color: "text-blue-600" },
                      { icon: Users,     label: "B2CS Groups",     value: result.summary.counts.b2cs_rate_groups ?? 0,       color: "text-blue-600" },
                      { icon: Globe,     label: "B2CL Invoices",   value: result.summary.counts.b2cl ?? 0,                   color: "text-purple-600" },
                      { icon: ReceiptText, label: "Credit Notes",  value: (result.summary.counts.credit_notes_registered ?? 0) + (result.summary.counts.credit_notes_unregistered ?? 0), color: "text-orange-600" },
                    ].map(item => (
                      <div key={item.label} className="bg-[#F8FAFC] rounded-lg p-4">
                        <item.icon className={`w-5 h-5 ${item.color} mb-2`} />
                        <p className="text-2xl font-bold text-[#0F172A]">{item.value}</p>
                        <p className="text-xs text-[#64748B] mt-0.5">{item.label}</p>
                      </div>
                    ))}
                  </div>
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-xs text-[#64748B] border-b border-[#F1F5F9]">
                        <th className="text-left py-2 font-medium">Tax Type</th>
                        <th className="text-right py-2 font-medium">Amount</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#F8FAFC]">
                      {[
                        { label: "Taxable Value", value: result.summary.totals_rupees.taxable ?? 0 },
                        { label: "CGST",  value: result.summary.totals_rupees.cgst ?? 0 },
                        { label: "SGST",  value: result.summary.totals_rupees.sgst ?? 0 },
                        { label: "IGST",  value: result.summary.totals_rupees.igst ?? 0 },
                      ].map(row => (
                        <tr key={row.label} className="hover:bg-[#F8FAFC]">
                          <td className="py-2.5 text-[#334155]">{row.label}</td>
                          <td className="py-2.5 text-right font-mono text-[#0F172A]">{r(row.value)}</td>
                        </tr>
                      ))}
                      <tr className="font-semibold bg-blue-50">
                        <td className="py-2.5 text-blue-800">Total Tax</td>
                        <td className="py-2.5 text-right font-mono text-blue-900">{p(result.tax_total_paise)}</td>
                      </tr>
                    </tbody>
                  </table>
                  {result.validation_warnings.length > 0 && (
                    <div className="mt-4">
                      <h4 className="text-xs font-semibold text-amber-700 mb-2 flex items-center gap-1">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        Warnings
                      </h4>
                      <ul className="space-y-1.5">
                        {result.validation_warnings.map((w, i) => (
                          <li key={i} className="text-xs text-amber-700">
                            {w.invoice_ref && <span className="font-mono mr-1">[{w.invoice_ref}]</span>}
                            {w.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}

              {/* B2B tab */}
              {activeTab === "b2b" && (
                <div className="overflow-x-auto">
                  {(b2b as { ctin: string; inv: Record<string, unknown>[] }[]).length === 0 ? (
                    <p className="p-6 text-sm text-[#94A3B8] text-center">No B2B invoices for this period.</p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr className="text-xs text-[#64748B]">
                          <th className="text-left px-4 py-2.5 font-medium">Receiver GSTIN</th>
                          <th className="text-left px-4 py-2.5 font-medium">Invoice No.</th>
                          <th className="text-left px-4 py-2.5 font-medium">Date</th>
                          <th className="text-left px-4 py-2.5 font-medium">POS</th>
                          <th className="text-right px-4 py-2.5 font-medium">Taxable</th>
                          <th className="text-right px-4 py-2.5 font-medium">Rate%</th>
                          <th className="text-right px-4 py-2.5 font-medium">Tax</th>
                          <th className="text-center px-4 py-2.5 font-medium">RCM</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {(b2b as { ctin: string; inv: Record<string, unknown>[] }[]).flatMap(g =>
                          g.inv.map((inv, i) => {
                            const itm = ((inv.itms as Record<string, unknown>[])?.[0]?.itm_det as Record<string, unknown>) ?? {};
                            const taxTotal = ((itm.iamt as number) ?? 0) + ((itm.camt as number) ?? 0) + ((itm.samt as number) ?? 0);
                            return (
                              <tr key={`${g.ctin}-${i}`} className="hover:bg-[#F8FAFC]">
                                <td className="px-4 py-2.5 font-mono text-xs text-[#475569]">{g.ctin}</td>
                                <td className="px-4 py-2.5 font-mono text-xs text-[#1E293B]">{inv.inum as string}</td>
                                <td className="px-4 py-2.5 text-xs text-[#475569]">{inv.idt as string}</td>
                                <td className="px-4 py-2.5 text-xs text-[#475569]">{inv.pos as string}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(itm.txval as number ?? 0)}</td>
                                <td className="px-4 py-2.5 text-right text-xs text-[#64748B]">{itm.rt as number ?? 0}%</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(taxTotal)}</td>
                                <td className="px-4 py-2.5 text-center text-xs">{inv.rchrg as string}</td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* B2CS tab */}
              {activeTab === "b2cs" && (
                <div className="overflow-x-auto">
                  {b2cs.length === 0 ? (
                    <p className="p-6 text-sm text-[#94A3B8] text-center">No B2CS entries for this period.</p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr className="text-xs text-[#64748B]">
                          <th className="text-left px-4 py-2.5 font-medium">Supply Type</th>
                          <th className="text-left px-4 py-2.5 font-medium">Rate%</th>
                          <th className="text-left px-4 py-2.5 font-medium">POS</th>
                          <th className="text-right px-4 py-2.5 font-medium">Taxable</th>
                          <th className="text-right px-4 py-2.5 font-medium">IGST</th>
                          <th className="text-right px-4 py-2.5 font-medium">CGST</th>
                          <th className="text-right px-4 py-2.5 font-medium">SGST</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {b2cs.map((row, i) => {
                          // "sply_ty" is the GSTN key. "sply_tp" was this
                          // codebase's misspelling, and a GSTR-1 saved before
                          // the fix still carries it — so a stored return
                          // renders instead of showing a blank chip.
                          const supplyType = (row.sply_ty ?? row.sply_tp) as string | undefined;
                          return (
                          <tr key={i} className="hover:bg-[#F8FAFC]">
                            <td className="px-4 py-2.5">
                              <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                supplyType === "INTER" ? "bg-blue-100 text-blue-700" : "bg-[#F1F5F9] text-[#475569]"
                              }`}>
                                {supplyType ?? "—"}
                              </span>
                            </td>
                            <td className="px-4 py-2.5 text-sm text-[#475569]">{row.rt as number}%</td>
                            <td className="px-4 py-2.5 text-sm text-[#475569]">{row.pos as string}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-sm">{r(row.txval as number)}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-sm">{r(row.iamt as number)}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-sm">{r(row.camt as number)}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-sm">{r(row.samt as number)}</td>
                          </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* B2CL tab */}
              {activeTab === "b2cl" && (
                <div className="overflow-x-auto">
                  {(b2cl as { pos: string; inv: Record<string, unknown>[] }[]).length === 0 ? (
                    <p className="p-6 text-sm text-[#94A3B8] text-center">
                      No B2CL invoices. B2CL applies to inter-state unregistered invoices above ₹2.5L (CGST Rule 59(2)).
                    </p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr className="text-xs text-[#64748B]">
                          <th className="text-left px-4 py-2.5 font-medium">POS</th>
                          <th className="text-left px-4 py-2.5 font-medium">Invoice No.</th>
                          <th className="text-left px-4 py-2.5 font-medium">Date</th>
                          <th className="text-right px-4 py-2.5 font-medium">Invoice Value</th>
                          <th className="text-right px-4 py-2.5 font-medium">Taxable</th>
                          <th className="text-right px-4 py-2.5 font-medium">Rate%</th>
                          <th className="text-right px-4 py-2.5 font-medium">IGST</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {(b2cl as { pos: string; inv: Record<string, unknown>[] }[]).flatMap(g =>
                          g.inv.map((inv, i) => {
                            const itm = ((inv.itms as Record<string, unknown>[])?.[0]?.itm_det as Record<string, unknown>) ?? {};
                            return (
                              <tr key={`${g.pos}-${i}`} className="hover:bg-[#F8FAFC]">
                                <td className="px-4 py-2.5 text-xs text-[#475569]">{g.pos}</td>
                                <td className="px-4 py-2.5 font-mono text-xs text-[#1E293B]">{inv.inum as string}</td>
                                <td className="px-4 py-2.5 text-xs text-[#475569]">{inv.idt as string}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(inv.val as number)}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(itm.txval as number ?? 0)}</td>
                                <td className="px-4 py-2.5 text-right text-xs text-[#64748B]">{itm.rt as number ?? 0}%</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(itm.iamt as number ?? 0)}</td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* CDNR tab */}
              {activeTab === "cdnr" && (
                <div className="overflow-x-auto">
                  {(cdnr as { ctin: string; nt: Record<string, unknown>[] }[]).length === 0 ? (
                    <p className="p-6 text-sm text-[#94A3B8] text-center">No credit/debit notes to registered buyers.</p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr className="text-xs text-[#64748B]">
                          <th className="text-left px-4 py-2.5 font-medium">Receiver GSTIN</th>
                          <th className="text-left px-4 py-2.5 font-medium">Type</th>
                          <th className="text-left px-4 py-2.5 font-medium">Note No.</th>
                          <th className="text-left px-4 py-2.5 font-medium">Date</th>
                          <th className="text-right px-4 py-2.5 font-medium">Note Value</th>
                          <th className="text-right px-4 py-2.5 font-medium">Taxable</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {(cdnr as { ctin: string; nt: Record<string, unknown>[] }[]).flatMap(g =>
                          g.nt.map((nt, i) => {
                            const itm = ((nt.itms as Record<string, unknown>[])?.[0]?.itm_det as Record<string, unknown>) ?? {};
                            return (
                              <tr key={`${g.ctin}-${i}`} className="hover:bg-[#F8FAFC]">
                                <td className="px-4 py-2.5 font-mono text-xs text-[#475569]">{g.ctin}</td>
                                <td className="px-4 py-2.5">
                                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                    nt.ntty === "C" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"
                                  }`}>
                                    {nt.ntty === "C" ? "Credit" : "Debit"}
                                  </span>
                                </td>
                                <td className="px-4 py-2.5 font-mono text-xs text-[#1E293B]">{nt.nt_num as string}</td>
                                <td className="px-4 py-2.5 text-xs text-[#475569]">{nt.nt_dt as string}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(nt.val as number)}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(itm.txval as number ?? 0)}</td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* Exports tab */}
              {activeTab === "exp" && (
                <div className="overflow-x-auto">
                  {(exp as { exp_typ: string; inv: Record<string, unknown>[] }[]).length === 0 ? (
                    <p className="p-6 text-sm text-[#94A3B8] text-center">No export invoices for this period.</p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr className="text-xs text-[#64748B]">
                          <th className="text-left px-4 py-2.5 font-medium">Type</th>
                          <th className="text-left px-4 py-2.5 font-medium">Invoice No.</th>
                          <th className="text-left px-4 py-2.5 font-medium">Date</th>
                          <th className="text-right px-4 py-2.5 font-medium">Invoice Value</th>
                          <th className="text-right px-4 py-2.5 font-medium">Taxable</th>
                          <th className="text-right px-4 py-2.5 font-medium">IGST</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {(exp as { exp_typ: string; inv: Record<string, unknown>[] }[]).flatMap(g =>
                          g.inv.map((inv, i) => {
                            const itm = ((inv.itms as Record<string, unknown>[])?.[0]?.itm_det as Record<string, unknown>) ?? {};
                            return (
                              <tr key={`${g.exp_typ}-${i}`} className="hover:bg-[#F8FAFC]">
                                <td className="px-4 py-2.5">
                                  <span className="text-xs px-2 py-0.5 rounded-full bg-teal-100 text-teal-700 font-medium">
                                    {g.exp_typ}
                                  </span>
                                </td>
                                <td className="px-4 py-2.5 font-mono text-xs text-[#1E293B]">{inv.inum as string}</td>
                                <td className="px-4 py-2.5 text-xs text-[#475569]">{inv.idt as string}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(inv.val as number)}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(itm.txval as number ?? 0)}</td>
                                <td className="px-4 py-2.5 text-right font-mono text-xs">{r(itm.iamt as number ?? 0)}</td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* HSN tab */}
              {activeTab === "hsn" && (
                <div className="overflow-x-auto">
                  {hsn.length === 0 ? (
                    <p className="p-6 text-sm text-[#94A3B8] text-center">
                      No HSN summary. Add HSN/SAC codes to invoice line items for Table 12.
                    </p>
                  ) : (
                    <table className="w-full text-sm">
                      <thead className="bg-[#F8FAFC] border-b border-[#E2E8F0]">
                        <tr className="text-xs text-[#64748B]">
                          <th className="text-left px-4 py-2.5 font-medium">HSN/SAC</th>
                          <th className="text-left px-4 py-2.5 font-medium">Description</th>
                          <th className="text-right px-4 py-2.5 font-medium">Qty</th>
                          <th className="text-right px-4 py-2.5 font-medium">Taxable</th>
                          <th className="text-right px-4 py-2.5 font-medium">IGST</th>
                          <th className="text-right px-4 py-2.5 font-medium">CGST</th>
                          <th className="text-right px-4 py-2.5 font-medium">SGST</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-[#F8FAFC]">
                        {hsn.map((row, i) => (
                          <tr key={i} className="hover:bg-[#F8FAFC]">
                            <td className="px-4 py-2.5 font-mono text-xs font-semibold text-[#334155]">{row.hsn_sc as string}</td>
                            <td className="px-4 py-2.5 text-xs text-[#475569]">{row.desc as string}</td>
                            <td className="px-4 py-2.5 text-right text-xs text-[#64748B]">{(row.qty as number).toFixed(2)} {row.uqc as string}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs">{r(row.txval as number)}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs">{r(row.iamt as number)}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs">{r(row.camt as number)}</td>
                            <td className="px-4 py-2.5 text-right font-mono text-xs">{r(row.samt as number)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* JSON Preview tab */}
              {activeTab === "json" && (
                <div>
                  <div className="px-4 py-3 bg-[#F8FAFC] border-b border-[#F1F5F9] flex items-center justify-between">
                    <p className="text-xs text-[#64748B]">
                      GSTN-compatible payload. This JSON is uploaded to gst.gov.in after CA approval.
                      Max 5 MB / 19,000 line items per upload.
                    </p>
                  </div>
                  <pre className="p-5 text-xs font-mono text-[#475569] overflow-auto max-h-96 bg-[#F8FAFC]">
                    {JSON.stringify(result.payload, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Mark as Filed modal */}
      {showFiledModal && (
        <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="font-semibold text-[#0F172A]">Mark GSTR-1 as Filed</h3>
              <button onClick={() => { setShowFiledModal(false); setArn(""); }}>
                <X className="w-5 h-5 text-[#94A3B8] hover:text-[#475569]" />
              </button>
            </div>
            <p className="text-sm text-[#475569] mb-4">
              After uploading the JSON to <strong>gst.gov.in</strong> and receiving the ARN,
              enter it below to record the filing in PracticeSync.
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
