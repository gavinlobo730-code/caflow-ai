"use client";

/**
 * GSTR-3B Review UI — CA review, approval, and JSON download for portal upload.
 *
 * CGST Act Section 39 — Monthly summary return, due 20th of following month.
 * CGST Rule 36(4) — ITC restricted to 100% of the eligible GSTR-2B credit. The
 *   105% provisional buffer was withdrawn by Notification 40/2021-Central Tax
 *   w.e.f. 01-01-2022; domain/gst/gstr3b_computer._RULE_36_4_NUMERATOR is the
 *   authority and has said 100 all along.
 * CGST Act Section 49(5) — the four-step set-off: IGST credit to IGST then, with
 *   Rule 88A, to CGST and SGST; then CGST credit to CGST and to IGST (s.49(5)(b));
 *   then SGST credit to SGST and to IGST (s.49(5)(c)). Never CGST against SGST.
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
import { Gstr3bFindings } from "@/components/gst/Gstr3bFindings";
import { getSupabaseClient } from "@/lib/supabase/client";
import {
  computeGSTR3B,
  approveGSTR3B,
  markGSTR3BFiled,
  downloadGSTR3BJSON,
  getGSTR3BReturn,
  fetchRule37Report,
  fetchRule37AReport,
  fetchRule43Working,
  toPeriod,
  type GSTR3BComputeResult,
  type GSTReturnStatus,
  type Rule37Report,
  type Rule37AReport,
  type Rule43Working,
} from "@/lib/data/gst";
import { periodEndDate, splitRule37Bills } from "@/lib/gst/rule37Period";
import { financialYearOfMonth } from "@/lib/dates/periods";

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
  // One action at a time: every button that starts work waits for whichever
  // is already running. Guarding each on its own flag alone let two fire at
  // once, and the second could act on what the first was still changing.
  const actionInFlight = approving || loading;

  // Rule 37: reported alongside the return, never folded into it. See the
  // panel below for why the two must stay separate.
  const [rule37, setRule37] = useState<Rule37Report | null>(null);
  const [rule37Error, setRule37Error] = useState<string | null>(null);
  /* CGST Rule 37A — the SUPPLIER's default, not the recipient's. It is asked
     for the FINANCIAL YEAR the credit was availed in, because both of its
     deadlines hang off the end of that year and off no month at all. */
  const [rule37a, setRule37a] = useState<Rule37AReport | null>(null);
  const [rule37aError, setRule37aError] = useState<string | null>(null);

  // Rule 43: the capital-goods twin of Rule 37 above, and reported the same
  // way — beside the return, never folded into it, because no journal has been
  // posted for it either.
  const [rule43, setRule43] = useState<Rule43Working | null>(null);
  const [rule43Error, setRule43Error] = useState<string | null>(null);

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
    setRule37a(null);
    setRule37aError(null);
    setRule43(null);
    setRule43Error(null);
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
      // Rule 37A is asked for the FINANCIAL YEAR, not the month: the supplier
      // has until 30 September following the end of the availment year to file
      // their GSTR-3B, and the client until 30 November to reverse. Failing
      // must not fail the return, same as Rule 37 above.
      try {
        setRule37a(await fetchRule37AReport(
          clientId, financialYearOfMonth(yearMonth)));
      } catch (e) {
        setRule37aError(
          e instanceof Error ? e.message : "Could not check Rule 37A");
      }
      // Asked for the PERIOD, not a date: Rule 43 apportions per tax period,
      // and the sixty instalments are counted from the invoice month. Failing
      // must not fail the return, same as Rule 37 above.
      try {
        setRule43(await fetchRule43Working(clientId, period));
      } catch (e) {
        setRule43Error(e instanceof Error ? e.message : "Could not check Rule 43");
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
  // Is there a Table 11 part in 3.1(a) at all? Every head, because a period can
  // legitimately carry tax with a nil net value (11A at one rate adjusted by
  // 11B at another) and the note is worth showing whenever any of it is there.
  const a11 = w?.advances_11;
  const adv11 = (a11?.taxable_value_paise ?? 0) || (a11?.igst_paise ?? 0)
    || (a11?.cgst_paise ?? 0) || (a11?.sgst_paise ?? 0);
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
                onChange={(id) => { setClientId(id); setResult(null); setError(null); setRule37(null); setRule43(null); }}
                ariaLabel="Client"
                placeholder="— Select client —"
              />
            </div>
          </div>
          <div>
            <label className="block text-sm font-medium text-[#334155] mb-1">Period</label>
            <select
              value={yearMonth}
              onChange={e => { setYearMonth(e.target.value); setResult(null); setError(null); setRule37(null); setRule43(null); }}
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
          disabled={actionInFlight || !clientId || !yearMonth}
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
                  disabled={actionInFlight}
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
            {/* THE FORM HAS FIVE COLUMNS AND THIS TABLE HAD FOUR (GST-22).
                Without a taxable-value column there was nowhere to put the
                turnover, so the nil-rated/exempt row printed its VALUE under
                the heading "IGST" — a figure in the wrong unit under a
                statutory column name. 3.1(c) and 3.1(e) bear no tax at all;
                what they carry is the value, which is now where the portal
                puts it. */}
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-[#64748B] uppercase border-b border-[#F1F5F9]">
                  <th className="text-left px-5 py-2.5 font-medium">Supply Type</th>
                  <th className="text-right px-5 py-2.5 font-medium">Taxable value</th>
                  <th className="text-right px-5 py-2.5 font-medium">IGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">CGST</th>
                  <th className="text-right px-5 py-2.5 font-medium">SGST</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F8FAFC]">
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">
                    (a) Taxable supplies (B2B + B2C + B2CL)
                    {/* OF ROW (a), the part with no invoice behind it (GST-15):
                        GSTR-1 Table 11A received less 11B adjusted. A note under
                        the row, not a row of its own — it is already inside the
                        figures on this line, and a separate row would read as an
                        addition. Shown only when there is one: most clients have
                        no Table 11 at all (Notification 66/2017-Central Tax). */}
                    {adv11 !== 0 && (
                      <span className="block text-[10px] text-[#64748B] mt-0.5">
                        Includes {r(w.advances_11?.taxable_value_paise ?? 0)} of advances —
                        GSTR-1 Table 11A less 11B, taxable on receipt under CGST s.13(2).
                        Declared and payable here, but not in the general ledger: a receipt
                        posts no output-tax leg, so the books-to-ledger check excludes it.
                      </span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.outward.taxable_value_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.outward.taxable_igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.outward.taxable_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.outward.taxable_sgst_paise)}</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">
                    (b) Zero-rated supplies (Exports / SEZ)
                    {w.outward.zero_rated_igst_paise > 0 && (
                      <span className="block text-[10px] text-[#64748B] mt-0.5">
                        On payment of tax — CGST s.16(3)(b). Refundable under s.54.
                      </span>
                    )}
                  </td>
                  {/* The IGST column carried an em dash whatever the figure was.
                      An export under an LUT or bond (s.16(3)(a)) genuinely
                      carries nil, but one made ON PAYMENT OF TAX (s.16(3)(b))
                      carries real IGST that this return owes and s.54 refunds
                      later — and the em dash said otherwise. */}
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.outward.zero_rated_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#0F172A]">
                    {w.outward.zero_rated_igst_paise > 0 ? r(w.outward.zero_rated_igst_paise) : "—"}
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                </tr>
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">(c) Nil-rated / Exempt</td>
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.outward.nil_exempt_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                </tr>
                {/* 3.1(d) — reverse charge. Tax with NO taxable value on this
                    working: §49(4) with §2(82) puts it outside the credit
                    ledger entirely, so it is carried as the cash liability the
                    challan needs rather than as turnover. */}
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">(d) Inward supplies liable to reverse charge</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.rcm_inward.igst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.rcm_inward.cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.rcm_inward.sgst_paise)}</td>
                </tr>
                {/* 3.1(e) — and it is NOT 3.1(c). Nil-rated and exempt are
                    supplies GST reaches and then charges at nil or relieves
                    under §11; non-GST is outside the levy altogether — §9(1)
                    and §9(2) exclude petroleum and alcoholic liquor for human
                    consumption, and Schedule III puts a further list outside
                    "supply". The engine had no accumulator for it until
                    GST-06, so this row could not exist. */}
                <tr className="hover:bg-[#F8FAFC]">
                  <td className="px-5 py-3 text-[#334155]">(e) Non-GST outward supplies</td>
                  <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(w.outward.non_gst_paise ?? 0)}</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                </tr>
                <tr className="bg-blue-50 font-semibold">
                  <td className="px-5 py-3 text-blue-800">
                    Total output tax — rows (a) and (b)
                    {/* (d) is in the table above it and deliberately NOT in
                        this total. §2(82) defines output tax as EXCLUDING tax
                        payable on reverse charge, and §49(4) then bars the
                        credit ledger from discharging it — so reverse-charge
                        tax is always cash, always on top, and adding it here
                        would make this figure the wrong base for the Table 6
                        set-off below. It is carried to the challan panel
                        instead, which is where it is actually paid. */}
                    <span className="block text-[10px] font-normal text-blue-700 mt-0.5">
                      Reverse charge (d) is excluded — s.2(82) puts it outside output tax,
                      and s.49(4) makes it cash. It is on the challan below.
                    </span>
                  </td>
                  {/* No value total. The portal's 3.1 has none, and summing
                      (a)+(b)+(c)+(e) under a heading that reads "Total Output
                      Tax" would label a turnover as a tax. */}
                  <td className="px-5 py-3 text-right font-mono text-[#94A3B8]">—</td>
                  {/* The IGST total INCLUDES the zero-rated IGST in the row
                      above. It used to be taxable_igst_paise alone, so once
                      that row started printing a real figure — a s.16(3)(b)
                      export made on payment of tax — this line contradicted
                      the line above it and disagreed with the Table 6
                      liability it is set off against. §16(3)(b) tax is owed in
                      THIS return and refunded later under §54; the portal's
                      Table 6.1 includes it, and so does the filing demo's
                      head_liability. */}
                  <td className="px-5 py-3 text-right font-mono text-blue-900">
                    {r(w.outward.taxable_igst_paise + w.outward.zero_rated_igst_paise)}
                  </td>
                  <td className="px-5 py-3 text-right font-mono text-blue-900">{r(w.outward.taxable_cgst_paise)}</td>
                  <td className="px-5 py-3 text-right font-mono text-blue-900">{r(w.outward.taxable_sgst_paise)}</td>
                </tr>
              </tbody>
            </table>
          </section>

          {/* Table 3.2 — OF the supplies already in 3.1(a). Computed by
              gstr3b_computer since the set-off work and served to nobody until
              GST-22, so the portal cross-check a CA is asked about at filing
              time — 3.2 against 3.1(a), and against GSTR-1's B2CL and B2CS —
              could not be made here at all.

              A BREAKDOWN, NEVER AN ADDITION. Every rupee in it is already in
              3.1(a) above; the section says so rather than leaving a reader to
              wonder whether the two tables add up.

              The place of supply is shown as the two-digit state CODE because
              that is what the form takes and what this codebase holds — there
              is no state-code-to-name table anywhere in it, and writing one
              into a screen would be a new vocabulary in the browser with
              nothing on the server to check it against. */}
          {(() => {
            const s32 = w.inter_state_3_2;
            const rows: { kind: string; pos: string; txval: number; iamt: number }[] = [];
            for (const [kind, label] of [
              ["unregistered", "Unregistered persons"],
              ["composition", "Composition taxable persons"],
              ["uin", "UIN holders"],
            ] as const) {
              const byPos = s32?.[kind] ?? {};
              for (const pos of Object.keys(byPos).sort()) {
                rows.push({ kind: label, pos, txval: byPos[pos].txval, iamt: byPos[pos].iamt });
              }
            }
            if (!rows.length) return null;   // nothing to declare is not a table
            return (
              <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
                <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
                  <h3 className="font-semibold text-[#1E293B] text-sm">
                    Table 3.2 — Inter-state supplies to unregistered persons, composition dealers and UIN holders
                  </h3>
                  <p className="text-xs text-[#64748B] mt-0.5">
                    Of the supplies already declared in 3.1(a) — a breakdown, not an addition.
                    The portal checks it against 3.1(a) and against GSTR-1.
                  </p>
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-[#64748B] uppercase border-b border-[#F1F5F9]">
                      <th className="text-left px-5 py-2.5 font-medium">Recipient</th>
                      <th className="text-left px-5 py-2.5 font-medium">Place of supply (state code)</th>
                      <th className="text-right px-5 py-2.5 font-medium">Taxable value</th>
                      <th className="text-right px-5 py-2.5 font-medium">IGST</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {rows.map((row) => (
                      <tr key={`${row.kind}-${row.pos}`} className="hover:bg-[#F8FAFC]">
                        <td className="px-5 py-3 text-[#334155]">{row.kind}</td>
                        <td className="px-5 py-3 font-mono text-[#64748B]">{row.pos}</td>
                        <td className="px-5 py-3 text-right font-mono text-[#334155]">{r(row.txval)}</td>
                        <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(row.iamt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </section>
            );
          })()}

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

          {/* Rule 36(4) — the working behind the credit, which the return never
              shows. Computed in apps/api since the engine was written and
              rendered by NOTHING until 11-09-2026: a CA whose claim had been
              trimmed saw only the trimmed figure. s.16(2)(aa) makes the
              supplier's filing decisive, so this is the difference between a
              credit that is safe and one that is not. */}
          {w.rule_36_4 && (
            <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
              <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
                <h3 className="font-semibold text-[#1E293B] text-sm">
                  Rule 36(4) — books against GSTR-2B
                </h3>
                <p className="text-xs text-[#64748B] mt-0.5">
                  CGST Rule 36(4) with s.16(2)(aa): credit is available only where the
                  supplier has furnished the invoice and it has reached you in GSTR-2B.
                </p>
              </div>

              {!w.rule_36_4.compared ? (
                /* NOT THE SAME AS "nothing was capped". No 2A is on file, so
                   nothing was compared — and the figures alone cannot tell a
                   CA which of the two it is. Saying so is the whole point of
                   `compared` being a field of its own. */
                <div className="px-5 py-4 bg-[#FFFBEB] border-b border-amber-100">
                  <p className="text-sm text-amber-900 font-medium">
                    No GSTR-2B on file for this period — nothing was compared.
                  </p>
                  <p className="text-xs text-amber-800 mt-1">
                    The credit below is the purchase register alone. Rule 36(4) has not
                    been applied, which is not the same as it having been applied and
                    found nothing to trim. Upload the period&apos;s GSTR-2B on the
                    client&apos;s GSTR-2B Recon tab to check it.
                  </p>
                </div>
              ) : w.rule_36_4.cap_applied ? (
                <div className="px-5 py-4 bg-[#FEF2F2] border-b border-red-100">
                  <p className="text-sm text-red-900 font-medium">
                    Credit was trimmed to the GSTR-2B figure.
                  </p>
                  <p className="text-xs text-red-800 mt-1">
                    Your books claim more than suppliers have filed. The difference is
                    not lost — it becomes available in the return for the period in
                    which the supplier files. Chase the supplier, or check the
                    document against the GSTR-2B Recon tab.
                  </p>
                </div>
              ) : (
                <div className="px-5 py-4 bg-[#F0FDF4] border-b border-emerald-100">
                  <p className="text-sm text-emerald-900 font-medium">
                    Books agree with GSTR-2B — no credit withheld.
                  </p>
                </div>
              )}

              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-[#64748B] uppercase border-b border-[#F1F5F9]">
                    <th className="text-left px-5 py-2.5 font-medium">Measured</th>
                    <th className="text-right px-5 py-2.5 font-medium">IGST</th>
                    <th className="text-right px-5 py-2.5 font-medium">CGST</th>
                    <th className="text-right px-5 py-2.5 font-medium">SGST</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F8FAFC]">
                  <tr className="hover:bg-[#F8FAFC]">
                    <td className="px-5 py-3 text-[#334155]">
                      Per the purchase register
                      <span className="block text-xs text-[#94A3B8]">
                        Before s.17(5) and before any Table 4(B) reversal
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.itc.igst_paise)}</td>
                    <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.itc.cgst_paise)}</td>
                    <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.itc.sgst_paise)}</td>
                  </tr>
                  <tr className="hover:bg-[#F8FAFC]">
                    <td className="px-5 py-3 text-[#334155]">
                      Per GSTR-2B
                      <span className="block text-xs text-[#94A3B8]">
                        {w.rule_36_4.gstr2a_record_count} document
                        {w.rule_36_4.gstr2a_record_count === 1 ? "" : "s"} on file
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.rule_36_4.gstr2a_igst_paise)}</td>
                    <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.rule_36_4.gstr2a_cgst_paise)}</td>
                    <td className="px-5 py-3 text-right font-mono text-[#0F172A]">{r(w.rule_36_4.gstr2a_sgst_paise)}</td>
                  </tr>
                  {/* OUTSIDE THE CAP, and the row exists because without it the
                      table above reads as an unexplained excess. Rule 36(4)
                      reaches only invoices the SUPPLIER must furnish under
                      s.37(1); reverse-charge tax is self-assessed on the
                      recipient's own s.31(3)(f) invoice, so GSTR-2B
                      structurally cannot carry it. */}
                  {(w.rule_36_4.self_assessed_igst_paise > 0 ||
                    w.rule_36_4.self_assessed_cgst_paise > 0 ||
                    w.rule_36_4.self_assessed_sgst_paise > 0) && (
                    <tr className="hover:bg-[#F8FAFC] bg-[#FCFDFE]">
                      <td className="px-5 py-3 text-[#475569] text-xs">
                        Of which self-assessed — not capped
                        <span className="block text-[#94A3B8]">
                          Reverse charge under s.9(3)/(4). No supplier files it, so
                          GSTR-2B cannot carry it and Rule 36(4) does not reach it.
                        </span>
                      </td>
                      <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.rule_36_4.self_assessed_igst_paise)}</td>
                      <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.rule_36_4.self_assessed_cgst_paise)}</td>
                      <td className="px-5 py-3 text-right font-mono text-[#64748B] text-xs">{r(w.rule_36_4.self_assessed_sgst_paise)}</td>
                    </tr>
                  )}
                </tbody>
              </table>

              {/* WHICH DOCUMENTS (GST-19). The table above is a per-head total,
                  and s.16(2)(aa) is a condition on EACH invoice — so a month
                  with one unfiled bill and one over-claimed bill used to net to
                  zero and show nothing here at all. Rendering the list is the
                  half of the finding a CA actually acts on: without it they
                  cross-reference the GSTR-2B Recon tab by hand.

                  The reason sentence is SERVED, never composed here. Which of
                  the five answers applies is a statutory judgement and a second
                  copy of the wording in the browser is how the two come to say
                  different things about one invoice. */}
              {w.rule_36_4.per_document?.applied &&
                w.rule_36_4.per_document.withheld.length > 0 && (
                <div className="border-t border-ps-border">
                  <div className="px-5 py-3 bg-state-problem-surface border-b border-state-problem-border">
                    <p className="text-sm font-medium text-state-problem">
                      {w.rule_36_4.per_document.withheld.length} document
                      {w.rule_36_4.per_document.withheld.length === 1 ? "" : "s"} withheld
                      — {r(w.rule_36_4.per_document.withheld_total_paise)}
                    </p>
                    <p className="text-xs text-ps-body mt-1">
                      s.16(2)(aa) allows the credit only where the supplier has
                      furnished THIS invoice and it has reached you. Each row below
                      says which condition failed, because what to do about it
                      differs: a document GSTR-2B does not carry is a supplier to
                      chase, and one GSTR-2B carries and refuses is a document to
                      check.
                    </p>
                  </div>
                  <ul className="divide-y divide-ps-muted">
                    {w.rule_36_4.per_document.withheld.map((d, i) => (
                      <li key={d.document_id ?? `${d.label}-${i}`} className="px-5 py-3">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <p className="text-sm text-ps-ink font-medium truncate">
                              {d.label || "(unnumbered)"}
                              {d.supplier ? (
                                <span className="text-ps-label font-normal"> · {d.supplier}</span>
                              ) : null}
                            </p>
                            <p className="text-xs text-ps-label mt-0.5">{d.reason}</p>
                          </div>
                          <span className="font-mono text-sm text-state-problem whitespace-nowrap">
                            {r(d.withheld_total_paise)}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* NOT WITHHELD, AND NOT SILENT. A bill recorded after the
                  period's GSTR-2B was reconciled was never examined by it, so
                  its absence from the match is not evidence the supplier failed
                  to file — withholding it would cost the client credit they are
                  entitled to, invisibly. The credit stands and the action is to
                  re-reconcile. */}
              {(w.rule_36_4.per_document?.not_assessed?.length ?? 0) > 0 && (
                <div className="px-5 py-3 border-t border-ps-border bg-state-attention-surface">
                  <p className="text-sm font-medium text-state-attention">
                    {w.rule_36_4.per_document.not_assessed.length} bill
                    {w.rule_36_4.per_document.not_assessed.length === 1 ? " was" : "s were"} recorded
                    after this period&apos;s GSTR-2B was reconciled
                  </p>
                  <p className="text-xs text-ps-body mt-1">
                    That reconciliation never looked at{" "}
                    {w.rule_36_4.per_document.not_assessed.length === 1 ? "it" : "them"}, so its
                    silence says nothing about whether the supplier filed. The credit is
                    not withheld. Re-run the GSTR-2B reconciliation for this period to have
                    s.16(2)(aa) asked of{" "}
                    {w.rule_36_4.per_document.not_assessed.length === 1 ? "it" : "them"}.
                  </p>
                  <p className="text-xs text-ps-label mt-1.5">
                    {w.rule_36_4.per_document.not_assessed
                      .map(d => d.label || "(unnumbered)")
                      .join(", ")}
                  </p>
                </div>
              )}

              {/* What the pass could not reach, in the engine's own words. */}
              {(w.rule_36_4.per_document?.notes?.length ?? 0) > 0 && (
                <div className="px-5 py-3 border-t border-ps-border bg-ps-bg">
                  {w.rule_36_4.per_document.notes.map((n, i) => (
                    <p key={i} className="text-xs text-ps-label">{n}</p>
                  ))}
                </div>
              )}
            </section>
          )}

          {/* Table 6 — Net Tax Payable */}
          <section className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
            <div className="px-5 py-3 bg-[#F8FAFC] border-b border-[#E2E8F0]">
              <h3 className="font-semibold text-[#1E293B] text-sm">Table 6 — Net Tax Payable</h3>
              <p className="text-xs text-[#64748B] mt-0.5">CGST Act Section 49(5) with Rule 88A: IGST credit is spent first, then CGST and SGST credit may each be set against IGST — but never against each other.</p>
            </div>
            {/* The four heads are the SET-OFF result. Reverse-charge tax is not
                in them and cannot be: s.49(4) lets the electronic credit ledger
                pay only "output tax", and s.2(82) defines output tax as
                EXCLUDING "tax payable by him on reverse charge basis". The row
                below carries it, because "Total" here was being read as the
                challan amount and was short by the whole of Table 3.1(d). */}
            <div className="grid grid-cols-4 divide-x divide-[#F1F5F9] text-center">
              {[
                { label: "IGST", value: w.net_payable.igst_paise, color: "text-blue-700" },
                { label: "CGST", value: w.net_payable.cgst_paise, color: "text-blue-600" },
                { label: "SGST", value: w.net_payable.sgst_paise, color: "text-purple-700" },
                { label: "After set-off", value: w.net_payable.total_paise, color: "text-[#0F172A] font-bold" },
              ].map(item => (
                <div key={item.label} className="px-4 py-5">
                  <p className="text-xs text-[#64748B] font-medium mb-1">{item.label}</p>
                  <p className={`text-lg font-semibold font-mono ${item.color}`}>{r(item.value)}</p>
                </div>
              ))}
            </div>
            <div className="border-t border-[#E2E8F0] divide-y divide-[#F1F5F9]">
              <div className="flex items-baseline justify-between px-5 py-3">
                <div>
                  <p className="text-sm text-[#334155]">Reverse charge, payable in cash</p>
                  <p className="text-[10px] text-[#64748B] mt-0.5">
                    Table 3.1(d). CGST Act s.49(4) with s.2(82) — the credit ledger cannot pay this.
                  </p>
                </div>
                <p className="text-lg font-semibold font-mono text-purple-700">{r(w.net_payable.rcm_cash_paise)}</p>
              </div>
              <div className="flex items-baseline justify-between px-5 py-4 bg-[#FEF2F2]">
                <div>
                  <p className="text-sm font-semibold text-[#0F172A]">Total payable in cash</p>
                  <p className="text-[10px] text-[#64748B] mt-0.5">
                    This is the challan figure — the set-off result plus the reverse-charge tax.
                  </p>
                </div>
                <p className="text-xl font-bold font-mono text-red-700">{r(w.net_payable.challan_total_paise)}</p>
              </div>
            </div>
            {/* A total of zero says nothing about whether credit was exhausted
                or barely touched. Apex, April 2026: nil payable over
                Rs 36,54,961.65 of unused credit. */}
            <div className="px-5 py-3 border-t border-[#F1F5F9] bg-[#FCFDFE] grid grid-cols-3 gap-3 text-center">
              {[
                { label: "Credit available (4C)", value: w.itc_utilisation.available_paise },
                { label: "Set off against tax", value: w.itc_utilisation.consumed_paise },
                { label: "Carried forward", value: w.itc_utilisation.carried_forward_paise,
                  accent: w.itc_utilisation.carried_forward_paise > 0 ? "text-emerald-700" : "" },
              ].map(item => (
                <div key={item.label}>
                  <p className="text-[11px] text-[#94A3B8]">{item.label}</p>
                  <p className={`text-sm font-semibold font-mono ${item.accent ?? ""}`}>{r(item.value)}</p>
                </div>
              ))}
            </div>
            {w.itc_utilisation.carried_forward_paise > 0 && (
              <p className="px-5 pb-3 text-xs text-[#64748B]">
                Credit exceeded this period&apos;s liability, so nothing is payable and
                the balance carries into the next return. It is not a refund.
              </p>
            )}
          </section>

          {/* Rule 37A — the SUPPLIER's default. Reported beside the return and
              never folded into it, same as Rule 37 above, and separately from
              it because they are unrelated rules that share one box. */}
          {(rule37a || rule37aError) && (
            <section className="bg-white border border-[#E2E8F0] rounded-xl">
              <header className="px-5 py-3 border-b border-[#E2E8F0]">
                <h3 className="text-sm font-semibold text-[#0F172A]">
                  Rule 37A — credit resting on a supplier&apos;s GSTR-3B
                </h3>
                {rule37a && (
                  <p className="mt-0.5 text-xs text-[#64748B]">{rule37a.rule}</p>
                )}
              </header>

              {rule37aError ? (
                <p className="px-5 py-4 text-sm text-[#64748B]">
                  <strong className="text-[#334155]">Rule 37A not checked.</strong>{" "}
                  {rule37aError} The figures above are unaffected.
                </p>
              ) : rule37a ? (
                <div className="px-5 py-4 space-y-3 text-sm">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <p className="text-[#334155]">
                      Supplier files GSTR-3B by{" "}
                      <strong>{rule37a.supplier_deadline}</strong>
                      {rule37a.supplier_deadline_passed && " — passed"}
                    </p>
                    <p className="text-[#334155]">
                      Client reverses by{" "}
                      <strong>{rule37a.recipient_deadline}</strong>
                      {rule37a.recipient_deadline_passed && " — passed"}
                    </p>
                  </div>

                  {rule37a.suppliers.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead className="text-left text-xs uppercase text-[#64748B]">
                          <tr>
                            <th className="py-1">Supplier</th>
                            <th className="py-1">GSTIN</th>
                            <th className="py-1">Documents</th>
                            <th className="py-1 text-right">Credit at risk</th>
                          </tr>
                        </thead>
                        <tbody>
                          {rule37a.suppliers.map((s) => (
                            <tr key={`${s.vendor_id ?? s.vendor_name}`}
                                className="border-t border-[#F1F5F9]">
                              <td className="py-1">{s.vendor_name}</td>
                              <td className="py-1 font-mono text-xs">
                                {s.vendor_gstin ?? "—"}
                              </td>
                              <td className="py-1 tabular-nums">{s.bill_count}</td>
                              <td className="py-1 text-right tabular-nums">
                                {r(s.total_paise)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                        <tfoot>
                          <tr className="border-t border-[#E2E8F0] font-medium">
                            <td className="py-1" colSpan={3}>
                              {rule37a.totals.supplier_count} supplier(s),{" "}
                              {rule37a.totals.bill_count} document(s)
                            </td>
                            <td className="py-1 text-right tabular-nums">
                              {r(rule37a.totals.total_paise)}
                            </td>
                          </tr>
                        </tfoot>
                      </table>
                    </div>
                  ) : null}

                  {rule37a.gaps.map((g) => (
                    <p key={g} className="text-xs text-[#92400E]">{g}</p>
                  ))}
                  {rule37a.caveats.map((c) => (
                    <p key={c} className="text-xs text-[#64748B]">{c}</p>
                  ))}
                </div>
              ) : null}
            </section>
          )}

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
            // Rule 37(1) requires the credit back "along with interest payable
            // thereon under section 50", and this panel used to state the tax
            // and stop (GST-28). Summed over the bills THIS return carries,
            // not over every overdue bill: the earlier ones belong to a return
            // already filed and their interest is that return's problem.
            const dueInterest = due.reduce((t, b) => ({
              availment: t.availment + b.interest.from_availment.interest_paise,
              expiry: t.expiry + b.interest.from_expiry.interest_paise,
            }), { availment: 0, expiry: 0 });

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

                    {/* §50 interest. Two figures because the rule no longer
                        says which clock, and showing one would over- or
                        under-state a sum the client pays over. */}
                    <div className="mt-4 pt-3 border-t border-amber-200">
                      <p className="text-xs text-amber-900 font-semibold mb-1.5">
                        Interest under §50(1) on that reversal, to {rule37!.as_of}
                      </p>
                      <div className="grid grid-cols-2 gap-2">
                        <div className="rounded-lg bg-white/70 border border-amber-200 px-3 py-2">
                          <p className="text-[10px] text-amber-700">From the date the credit was availed</p>
                          <p className="font-mono text-sm text-amber-900">{r(dueInterest.availment)}</p>
                        </div>
                        <div className="rounded-lg bg-white/70 border border-amber-200 px-3 py-2">
                          <p className="text-[10px] text-amber-700">From the day the 180 days expired</p>
                          <p className="font-mono text-sm text-amber-900">{r(dueInterest.expiry)}</p>
                        </div>
                      </div>
                      {rule37!.interest_caveats.map((c, i) => (
                        <p key={i} className="text-[11px] text-amber-700 mt-2">{c}</p>
                      ))}
                    </div>
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

          {/* Rule 43 — the capital-goods twin, and reported the same way */}
          {(rule43 || rule43Error) && (() => {
            if (rule43Error) {
              return (
                <section className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl p-4 text-sm text-[#64748B]">
                  <strong className="text-[#334155]">Rule 43 not checked.</strong>{" "}
                  {rule43Error} The figures above are unaffected, but the capital-goods
                  apportionment has not been worked for this period.
                </section>
              );
            }
            const r43 = rule43!;
            const running = r43.assets.filter(a => a.included);
            const unclassified = r43.assets.filter(a => a.use === null);

            // A refusal is not a nil answer. Rule 43(1)(g)'s proviso sends the
            // CA to the last period whose turnover is known, and that is a
            // different period's figures — never substituted here.
            if (r43.refused) {
              return (
                <section className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl p-4">
                  <p className="text-sm text-[#334155] font-semibold mb-1">
                    Rule 43 could not be worked for this period
                  </p>
                  <p className="text-xs text-[#64748B]">{r43.refusal}</p>
                  {running.length > 0 && (
                    <p className="text-xs text-[#64748B] mt-2">
                      {running.length} common capital good{running.length !== 1 ? "s are" : " is"} still
                      inside the five years, carrying {r(r43.common_credit_paise.igst
                        + r43.common_credit_paise.cgst + r43.common_credit_paise.sgst)} of credit.
                    </p>
                  )}
                </section>
              );
            }

            if (r43.assets.length === 0) {
              return null;   // no fixed assets at all — nothing worth a panel
            }

            const nothingDue = r43.te_total_paise === 0 && unclassified.length === 0;
            if (nothingDue) {
              return (
                <section className="bg-[#F8FAFC] border border-[#E2E8F0] rounded-xl p-4 flex items-start gap-2">
                  <CheckCircle className="w-4 h-4 text-[#94A3B8] mt-0.5 shrink-0" />
                  <p className="text-sm text-[#64748B]">
                    <strong className="text-[#334155]">No Rule 43 reversal due.</strong>{" "}
                    {running.length === 0
                      ? "No common capital good is inside its five-year life this period."
                      : "There were no exempt supplies this period, so the exempt share of the instalment is nil."}
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
                      Rule 43 — capital goods used partly for exempt supplies
                    </h3>
                    <p className="text-xs text-amber-800 mt-0.5">
                      CGST Rule 43: one-sixtieth of the credit on each common capital good,
                      apportioned by exempt turnover, is added back to output tax — every month
                      for five years, per tax head.
                    </p>
                  </div>
                </div>

                {r43.te_total_paise > 0 && (
                  <div className="px-5 py-4">
                    <div className="flex items-baseline justify-between mb-3">
                      <p className="text-sm text-amber-900">
                        <strong>Te</strong> for this period, over {running.length} capital
                        good{running.length !== 1 ? "s" : ""}
                      </p>
                      <p className="font-mono font-semibold text-amber-900">{r(r43.te_total_paise)}</p>
                    </div>
                    <div className="grid grid-cols-3 gap-2 mb-3">
                      {(["igst", "cgst", "sgst"] as const).map(h => (
                        <div key={h} className="rounded-lg bg-white/70 border border-amber-200 px-3 py-2">
                          <p className="text-[10px] uppercase tracking-wide text-amber-700">{h}</p>
                          <p className="font-mono text-sm text-amber-900">{r(r43.te_paise[h])}</p>
                        </div>
                      ))}
                    </div>
                    {r43.exempt_turnover_paise !== null && r43.total_turnover_paise !== null && (
                      <p className="text-xs text-amber-800">
                        E ÷ F = {r(r43.exempt_turnover_paise)} ÷ {r(r43.total_turnover_paise)}, from{" "}
                        {r43.turnover_source}. Common credit running:{" "}
                        {r(r43.common_credit_paise.igst + r43.common_credit_paise.cgst
                           + r43.common_credit_paise.sgst)} over {r43.useful_life_months} months.
                      </p>
                    )}
                    <ul className="mt-3 space-y-1.5">
                      {running.map(a => (
                        <li key={a.asset_id} className="text-xs text-amber-800 flex items-baseline justify-between gap-4">
                          <span>
                            {a.asset_name}
                            <span className="text-amber-700 ml-2">
                              instalment {a.period_index} of {r43.useful_life_months}
                            </span>
                          </span>
                          <span className="font-mono shrink-0">
                            {r(a.credit_paise.igst + a.credit_paise.cgst + a.credit_paise.sgst)} credit
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* The gaps are the point. An unclassified asset is left OUT,
                    so the figure above is understated by whatever it carries —
                    and a CA cannot know that from a number. */}
                {r43.gaps.length > 0 && (
                  <div className="px-5 py-3 border-t border-amber-200">
                    <p className="text-xs font-semibold text-amber-900 mb-1.5">
                      {r43.gaps.length} asset{r43.gaps.length !== 1 ? "s are" : " is"} not in this
                      working, and should be
                    </p>
                    <ul className="space-y-1">
                      {r43.gaps.map((g, i) => (
                        <li key={i} className="text-xs text-amber-800">• {g}</li>
                      ))}
                    </ul>
                    <p className="text-[11px] text-amber-700 mt-2">
                      Record the use on the asset in the client&apos;s Fixed Assets tab, then
                      recompute.
                    </p>
                  </div>
                )}

                {r43.caveats.length > 0 && (
                  <div className="px-5 py-3 border-t border-amber-200 space-y-1">
                    {r43.caveats.map((c, i) => (
                      <p key={i} className="text-[11px] text-amber-700">{c}</p>
                    ))}
                  </div>
                )}

                <div className="px-5 py-3 bg-amber-100/60 border-t border-amber-200 text-xs text-amber-900">
                  <strong>Not included in Table 4(B) above.</strong> {r43.how_to_declare}
                </div>
              </section>
            );
          })()}

          {/* THE THREE PARTS OF THE RETURN'S FACE THAT ARE NOT FIGURES (GST-22).
              Table 5.1 (what being late costs), what the bank lines a CA marked
              as carrying GST put on this return, and the rows filed nil because
              nothing here can derive them. All three came back from
              /from-books, `computeGSTR3B` dropped them, and this screen showed
              none of them — while the per-client GST tab showed all three, so
              the two GSTR-3B screens disagreed about how much of the return
              they show. One component, both screens. */}
          <div className="space-y-3">
            <Gstr3bFindings
              periodWindow={result.period_window}
              monthsWithout2b={result.months_without_gstr2b}
              lateFiling={result.late_filing}
              reconciliation={result.reconciliation}
              bankLineCaveats={result.bank_line_caveats}
              undeclarableRows={result.undeclarable_rows}
            />
          </div>

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
