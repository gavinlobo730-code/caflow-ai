"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import { Plus, Loader2, ChevronDown, ChevronUp, AlertTriangle, CheckCircle, Save } from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const FY_OPTIONS = ["2025-26", "2024-25", "2023-24"];
const AY_OPTIONS = ["2026-27", "2025-26", "2024-25"];
const SECTION_OPTIONS = ["40A(3)", "43B_pf", "43B_gst", "43B_bonus", "43B_leave", "other"];

async function apiFetch(path: string, opts?: RequestInit) {
  const { supabase } = await import("@/lib/supabase/client");
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts?.headers ?? {}),
    },
  });
  return res.json();
}

function paise(amount: number) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 })
    .format(amount / 100);
}

interface Snapshot {
  id: string;
  version: number;
  regime: string;
  financial_year: string;
  taxable_income_paise: number;
  tax_liability_paise: number;
  net_payable_paise: number;
  is_refund: boolean;
  status: string;
  created_at: string;
}

interface Disallowance {
  id: string;
  section: string;
  description: string;
  amount_paise: number;
  status: string;
  auto_detected: boolean;
}

interface ComputeResult {
  income: { taxable_income_paise: number };
  tax: { total_tax_paise: number; rebate_87a_paise: number };
  payable: { net_payable_paise: number; is_refund: boolean };
  warnings: string[];
}

interface BFLoss {
  id: string;
  assessment_year: string;
  loss_type: string;
  original_amount_paise: number;
  remaining_amount_paise: number;
  expiry_assessment_year: string;
}

export default function TaxComputationPage() {
  const params = useParams<{ id: string }>();
  const clientId = params.id;

  const [fy, setFy] = useState(FY_OPTIONS[0]);
  const [ay, setAy] = useState(AY_OPTIONS[0]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [disallowances, setDisallowances] = useState<Disallowance[]>([]);
  const [bfLosses, setBfLosses] = useState<BFLoss[]>([]);
  const [activeSection, setActiveSection] = useState<string | null>("overview");

  // Computation inputs
  const [regime, setRegime] = useState("new");
  const [salary, setSalary] = useState("");
  const [businessIncome, setBusinessIncome] = useState("");
  const [otherIncome, setOtherIncome] = useState("");
  const [tds, setTds] = useState("");
  const [advanceTax, setAdvanceTax] = useState("");
  const [computing, setComputing] = useState(false);
  const [computeResult, setComputeResult] = useState<ComputeResult | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);

  // Disallowance form
  const [showDisallForm, setShowDisallForm] = useState(false);
  const [disallSection, setDisallSection] = useState("40A(3)");
  const [disallDesc, setDisallDesc] = useState("");
  const [disallAmount, setDisallAmount] = useState("");
  const [savingDisall, setSavingDisall] = useState(false);

  const load = useCallback(async () => {
    if (!clientId || clientId === "_placeholder") return;
    // Plain reads — routed directly to Supabase (RLS: firm_isolation) instead
    // of through the FastAPI backend, which cold-starts. Mirrors the exact
    // table/columns/filters/ordering of list_snapshots, list_disallowances,
    // and list_bf_losses in apps/api/domain/income_tax/computation_workspace.py.
    // The actual computation (POST /api/income-tax/compute) stays backend-routed.
    const supabase = getSupabaseClient();
    const [{ data: snapsData }, { data: disallData }, { data: lossData }] = await Promise.all([
      supabase
        .from("tax_computation_snapshots")
        .select("id, version, regime, financial_year, taxable_income_paise, tax_liability_paise, net_payable_paise, is_refund, status, created_at")
        .eq("client_id", clientId)
        .eq("financial_year", fy)
        .order("version", { ascending: false }),
      supabase
        .from("tax_disallowances")
        .select("id, section, description, amount_paise, status, auto_detected")
        .eq("client_id", clientId)
        .eq("financial_year", fy)
        .order("created_at", { ascending: false }),
      supabase
        .from("brought_forward_losses")
        .select("id, assessment_year, loss_type, original_amount_paise, remaining_amount_paise, expiry_assessment_year")
        .eq("client_id", clientId)
        .order("assessment_year"),
    ]);
    setSnapshots((snapsData as Snapshot[]) ?? []);
    setDisallowances((disallData as Disallowance[]) ?? []);
    setBfLosses((lossData as BFLoss[]) ?? []);
  }, [clientId, fy]);

  useEffect(() => { load(); }, [load]);

  async function handleCompute() {
    setComputing(true);
    setComputeError(null);
    const toP = (v: string) => Math.round(parseFloat(v || "0") * 100);
    try {
      // 1. Compute tax
      const computeRes = await apiFetch("/api/income-tax/compute", {
        method: "POST",
        body: JSON.stringify({
          fy,
          gross_salary_paise: toP(salary),
          business_income_paise: toP(businessIncome),
          other_income_paise: toP(otherIncome),
          tds_deducted_paise: toP(tds),
          advance_tax_paid_paise: toP(advanceTax),
          use_new_regime: regime === "new",
        }),
      });
      if (!computeRes.success) throw new Error(computeRes.error ?? "Computation failed");
      setComputeResult(computeRes.data);

      // 2. Save snapshot
      const totalDisall = disallowances
        .filter(d => d.status === "accepted")
        .reduce((s, d) => s + d.amount_paise, 0);

      await apiFetch("/api/itr/snapshots", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          financial_year: fy,
          assessment_year: ay,
          regime,
          income: {
            gross_salary_paise: toP(salary),
            business_income_paise: toP(businessIncome),
            other_income_paise: toP(otherIncome),
            total_disallowances_paise: totalDisall,
            advance_tax_paid_paise: toP(advanceTax),
            tds_deducted_paise: toP(tds),
            taxable_income_paise: computeRes.data?.income?.taxable_income_paise ?? 0,
            tax_liability_paise: computeRes.data?.tax?.total_tax_paise ?? 0,
            net_payable_paise: computeRes.data?.payable?.net_payable_paise ?? 0,
            is_refund: (computeRes.data?.payable?.net_payable_paise ?? 0) < 0,
          },
          computation_result: computeRes.data,
        }),
      });
      await load();
    } catch (err) {
      setComputeError(err instanceof Error ? err.message : "Failed");
    } finally {
      setComputing(false);
    }
  }

  async function handleSaveDisallowance() {
    setSavingDisall(true);
    try {
      const res = await apiFetch("/api/itr/disallowances", {
        method: "POST",
        body: JSON.stringify({
          client_id: clientId,
          financial_year: fy,
          section: disallSection,
          description: disallDesc,
          amount_paise: Math.round(parseFloat(disallAmount) * 100),
        }),
      });
      if (!res.success) throw new Error(res.error);
      setShowDisallForm(false);
      setDisallDesc("");
      setDisallAmount("");
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed");
    } finally {
      setSavingDisall(false);
    }
  }

  const toggle = (s: string) => setActiveSection(prev => prev === s ? null : s);
  const latestSnap = snapshots[0];

  return (
    <div className="p-6 max-w-4xl space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-[#1E293B]">Tax Computation Workspace</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">IT Act 1961 — Sections 40A, 43B, 80C–80JJAA</p>
        </div>
        <select
          value={fy}
          onChange={e => setFy(e.target.value)}
          className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {FY_OPTIONS.map(f => <option key={f}>{f}</option>)}
        </select>
      </div>

      {/* CA Review Banner */}
      <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 rounded-xl px-4 py-2.5">
        <AlertTriangle size={13} className="text-amber-600 flex-shrink-0" />
        <p className="text-xs text-amber-800 font-medium">CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT</p>
      </div>

      {/* Overview Card */}
      {latestSnap && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl p-5">
          <p className="text-xs font-semibold text-[#334155] mb-3">Latest Computation (v{latestSnap.version})</p>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <p className="text-[10px] text-[#94A3B8]">Taxable Income</p>
              <p className="text-sm font-semibold text-[#1E293B]">{paise(latestSnap.taxable_income_paise)}</p>
            </div>
            <div>
              <p className="text-[10px] text-[#94A3B8]">Tax Liability</p>
              <p className="text-sm font-semibold text-[#1E293B]">{paise(latestSnap.tax_liability_paise)}</p>
            </div>
            <div>
              <p className="text-[10px] text-[#94A3B8]">
                {latestSnap.is_refund ? "Refund" : "Payable"}
              </p>
              <p className={`text-sm font-semibold ${latestSnap.is_refund ? "text-green-600" : "text-red-600"}`}>
                {paise(Math.abs(latestSnap.net_payable_paise))}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3">
            <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
              latestSnap.status === "reviewed" ? "bg-green-100 text-green-700" :
              latestSnap.status === "finalized" ? "bg-blue-100 text-blue-700" :
              "bg-[#F1F5F9] text-[#64748B]"
            }`}>{latestSnap.status}</span>
            <span className="text-[10px] text-[#94A3B8]">
              {latestSnap.regime === "new" ? "New Regime" : "Old Regime"} · FY {latestSnap.financial_year}
            </span>
          </div>
        </div>
      )}

      {/* Computation Input Section */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
        <button
          onClick={() => toggle("compute")}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC] text-left"
        >
          <p className="text-xs font-semibold text-[#334155]">Run Computation</p>
          {activeSection === "compute" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
        </button>

        {activeSection === "compute" && (
          <div className="px-5 pb-5 border-t border-[#F1F5F9] space-y-4 pt-4">
            <div className="flex gap-3">
              <div className="flex-1">
                <label className="text-[10px] text-[#64748B] mb-1 block">Assessment Year</label>
                <select value={ay} onChange={e => setAy(e.target.value)}
                  className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                  {AY_OPTIONS.map(a => <option key={a}>{a}</option>)}
                </select>
              </div>
              <div className="flex-1">
                <label className="text-[10px] text-[#64748B] mb-1 block">Tax Regime</label>
                <select value={regime} onChange={e => setRegime(e.target.value)}
                  className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                  <option value="new">New Regime (Default)</option>
                  <option value="old">Old Regime</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {[
                { label: "Gross Salary (₹)", value: salary, set: setSalary },
                { label: "Business Income (₹)", value: businessIncome, set: setBusinessIncome },
                { label: "Other Income (₹)", value: otherIncome, set: setOtherIncome },
                { label: "TDS Deducted (₹)", value: tds, set: setTds },
                { label: "Advance Tax Paid (₹)", value: advanceTax, set: setAdvanceTax },
              ].map(({ label, value, set }) => (
                <div key={label}>
                  <label className="text-[10px] text-[#64748B] mb-1 block">{label}</label>
                  <input
                    type="number"
                    value={value}
                    onChange={e => set(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0"
                  />
                </div>
              ))}
            </div>

            {computeError && <p className="text-xs text-red-600">{computeError}</p>}

            <button
              onClick={handleCompute}
              disabled={computing}
              className="flex items-center gap-1.5 text-xs bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {computing && <Loader2 size={12} className="animate-spin" />}
              <Save size={12} />
              Compute &amp; Save Snapshot
            </button>

            {computeResult && (
              <div className="bg-[#F8FAFC] rounded-xl p-4 space-y-2">
                <p className="text-xs font-semibold text-[#334155]">Result</p>
                <div className="grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <p className="text-[#94A3B8]">Taxable Income</p>
                    <p className="font-medium">{paise(computeResult.income?.taxable_income_paise ?? 0)}</p>
                  </div>
                  <div>
                    <p className="text-[#94A3B8]">Tax Liability</p>
                    <p className="font-medium">{paise(computeResult.tax?.total_tax_paise ?? 0)}</p>
                  </div>
                  <div>
                    <p className="text-[#94A3B8]">Rebate 87A</p>
                    <p className="font-medium">{paise(computeResult.tax?.rebate_87a_paise ?? 0)}</p>
                  </div>
                  <div>
                    <p className="text-[#94A3B8]">{computeResult.payable?.is_refund ? "Refund" : "Net Payable"}</p>
                    <p className={`font-medium ${computeResult.payable?.is_refund ? "text-green-600" : "text-red-600"}`}>
                      {paise(Math.abs(computeResult.payable?.net_payable_paise ?? 0))}
                    </p>
                  </div>
                </div>
                {(computeResult.warnings?.length > 0) && (
                  <div className="mt-2 space-y-1">
                    {computeResult.warnings.map((w: string, i: number) => (
                      <p key={i} className="text-[10px] text-amber-600">⚠ {w}</p>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Disallowances Section */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
        <button
          onClick={() => toggle("disallowances")}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC]"
        >
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-[#334155]">Disallowances</p>
            <span className="text-[10px] px-1.5 py-0.5 bg-red-50 text-red-600 rounded-full">
              {disallowances.length}
            </span>
          </div>
          {activeSection === "disallowances" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
        </button>

        {activeSection === "disallowances" && (
          <div className="px-5 pb-5 border-t border-[#F1F5F9] pt-4 space-y-3">
            <p className="text-[11px] text-[#64748B]">
              IT Act §40A(3): Cash payments &gt;₹10,000 | §43B: Unpaid statutory liabilities
            </p>

            {disallowances.length === 0 ? (
              <p className="text-xs text-[#94A3B8] py-4 text-center">No disallowances recorded</p>
            ) : (
              <div className="space-y-2">
                {disallowances.map(d => (
                  <div key={d.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                    <div>
                      <p className="text-xs font-medium text-[#1E293B]">{d.description}</p>
                      <p className="text-[10px] text-[#94A3B8]">
                        §{d.section} · {d.auto_detected ? "Auto-detected" : "Manual"}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold text-red-600">{paise(d.amount_paise)}</p>
                      <span className={`text-[10px] ${d.status === "accepted" ? "text-green-600" : d.status === "rejected" ? "text-red-500" : "text-amber-600"}`}>
                        {d.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!showDisallForm ? (
              <button
                onClick={() => setShowDisallForm(true)}
                className="flex items-center gap-1 text-xs text-blue-600 hover:underline"
              >
                <Plus size={12} /> Add Disallowance
              </button>
            ) : (
              <div className="border border-[#E2E8F0] rounded-xl p-4 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Section</label>
                    <select value={disallSection} onChange={e => setDisallSection(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg">
                      {SECTION_OPTIONS.map(s => <option key={s}>{s}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-[10px] text-[#64748B] mb-1 block">Amount (₹)</label>
                    <input type="number" value={disallAmount} onChange={e => setDisallAmount(e.target.value)}
                      className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" placeholder="0" />
                  </div>
                </div>
                <div>
                  <label className="text-[10px] text-[#64748B] mb-1 block">Description</label>
                  <input value={disallDesc} onChange={e => setDisallDesc(e.target.value)}
                    className="w-full text-xs px-3 py-1.5 border border-[#E2E8F0] rounded-lg" placeholder="Payment description" />
                </div>
                <div className="flex gap-2">
                  <button onClick={() => setShowDisallForm(false)} className="text-xs px-3 py-1.5 border border-[#E2E8F0] rounded">Cancel</button>
                  <button
                    onClick={handleSaveDisallowance}
                    disabled={savingDisall || !disallDesc || !disallAmount}
                    className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded disabled:opacity-50 flex items-center gap-1"
                  >
                    {savingDisall && <Loader2 size={10} className="animate-spin" />}
                    Save
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Brought Forward Losses */}
      <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
        <button
          onClick={() => toggle("losses")}
          className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC]"
        >
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold text-[#334155]">Brought Forward Losses</p>
            <span className="text-[10px] px-1.5 py-0.5 bg-amber-50 text-amber-600 rounded-full">
              {bfLosses.length}
            </span>
          </div>
          {activeSection === "losses" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
        </button>

        {activeSection === "losses" && (
          <div className="px-5 pb-5 border-t border-[#F1F5F9] pt-4 space-y-3">
            <p className="text-[11px] text-[#64748B]">IT Act §72 (Business, 8 yrs) · §74 (Capital, 8 yrs)</p>
            {bfLosses.length === 0 ? (
              <p className="text-xs text-[#94A3B8] py-4 text-center">No carried-forward losses recorded</p>
            ) : (
              <div className="space-y-2">
                {bfLosses.map(l => (
                  <div key={l.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                    <div>
                      <p className="text-xs font-medium text-[#1E293B] capitalize">
                        {l.loss_type.replace(/_/g, " ")} Loss — AY {l.assessment_year}
                      </p>
                      <p className="text-[10px] text-[#94A3B8]">Expires AY {l.expiry_assessment_year}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs font-semibold text-[#1E293B]">{paise(l.remaining_amount_paise)}</p>
                      <p className="text-[10px] text-[#94A3B8]">remaining of {paise(l.original_amount_paise)}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Snapshot History */}
      {snapshots.length > 0 && (
        <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden">
          <button
            onClick={() => toggle("history")}
            className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-[#F8FAFC]"
          >
            <p className="text-xs font-semibold text-[#334155]">Computation History ({snapshots.length} versions)</p>
            {activeSection === "history" ? <ChevronUp size={14} className="text-[#94A3B8]" /> : <ChevronDown size={14} className="text-[#94A3B8]" />}
          </button>
          {activeSection === "history" && (
            <div className="px-5 pb-5 border-t border-[#F1F5F9] pt-4 space-y-2">
              {snapshots.map(s => (
                <div key={s.id} className="flex items-center justify-between p-3 bg-[#F8FAFC] rounded-lg">
                  <div>
                    <p className="text-xs font-medium text-[#1E293B]">Version {s.version} — {s.regime === "new" ? "New" : "Old"} Regime</p>
                    <p className="text-[10px] text-[#94A3B8]">{new Date(s.created_at).toLocaleDateString("en-IN")}</p>
                  </div>
                  <div className="text-right flex items-center gap-2">
                    {s.status === "reviewed" && <CheckCircle size={12} className="text-green-500" />}
                    <div>
                      <p className="text-xs font-semibold text-[#1E293B]">
                        {s.is_refund ? "+" : ""}{paise(Math.abs(s.net_payable_paise))}
                      </p>
                      <p className={`text-[10px] ${s.is_refund ? "text-green-600" : "text-red-500"}`}>
                        {s.is_refund ? "Refund" : "Payable"}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
