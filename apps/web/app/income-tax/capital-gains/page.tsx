"use client";

/**
 * Capital Gains Calculator & Register — IT Act 1961
 * Section 2(29B): Short-term capital gains
 * Section 2(29A): Long-term capital gains
 * Section 45: Chargeability of capital gains
 * Section 48: Mode of computation
 * Section 54: Exemptions
 * Budget 2024 amendments: LTCG rates revised to 12.5%, STCG equity to 20%, holding periods unchanged
 * Finance Act 2023: Debt MF taxed as per slab (removed indexation benefit)
 *
 * R3.1b: all classification/indexation/tax-rate computation now happens on
 * the backend (domain/income_tax/capital_gains_engine.py) — this page only
 * collects input and displays results. See that module's docstring for the
 * verification status of the CII table and the asset-type tax treatment.
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { ChevronLeft, Calculator, Info, BookOpen, Plus, X, Trash2 } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { TableSkeleton } from "@/components/ui/skeleton";
import { api, type ApiResp } from "@/lib/api";
import {
  computeCapitalGains, listCapitalGains, createCapitalGain, deleteCapitalGain, getCiiTable,
  type CapitalGainsAssetType, type CapitalGainsRegisterAssetType,
  type CapitalGainsComputeResult, type CapitalGainsRecord,
} from "@/lib/data/income-tax";

// Asset types with their holding period thresholds and tax treatment
const ASSET_TYPES_CALC: { value: CapitalGainsAssetType; label: string }[] = [
  { value: "equity",     label: "Listed Equity / Equity MF" },
  { value: "debt_mf",    label: "Debt MF / Bonds (post Apr 2023)" },
  { value: "property",   label: "Immovable Property" },
  { value: "unlisted",   label: "Unlisted Shares" },
  { value: "vda",        label: "Cryptocurrency / VDA" },
  { value: "gold",       label: "Gold / Jewellery" },
];

// Asset types for register (matches DB constraint)
const ASSET_TYPES_REG: { value: CapitalGainsRegisterAssetType; label: string }[] = [
  { value: "equity_shares", label: "Equity Shares" },
  { value: "mutual_funds",  label: "Mutual Funds" },
  { value: "property",      label: "Immovable Property" },
  { value: "bonds",         label: "Bonds" },
  { value: "other",         label: "Other" },
];

function getFYFromDate(dateStr: string): string {
  const d = new Date(dateStr);
  const y = d.getFullYear();
  const m = d.getMonth(); // 0=Jan
  if (m >= 3) return `${y}-${String(y + 1).slice(2)}`;
  return `${y - 1}-${String(y).slice(2)}`;
}

interface Client { id: string; client_name: string; }

const BLANK_REG = {
  asset_description: "",
  asset_type: "equity_shares" as CapitalGainsRegisterAssetType,
  purchase_date: "",
  sale_date: "",
  purchase_cost_rs: "",
  improvement_cost_rs: "",
  sale_value_rs: "",
};

function rsToP(rs: string): number {
  return Math.round(parseFloat(rs || "0") * 100);
}

function fmtRs(paise: number): string {
  return "₹" + (paise / 100).toLocaleString("en-IN", { minimumFractionDigits: 2 });
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CapitalGainsPage() {
  const [activeTab, setActiveTab] = useState<"calculator" | "register">("calculator");

  // ── CII reference table (fetched once, display + FY dropdown only —
  // never used to compute anything client-side) ──
  const [ciiByFy, setCiiByFy] = useState<Record<string, number>>({});
  useEffect(() => {
    getCiiTable().then(({ ciiByFy }) => setCiiByFy(ciiByFy)).catch(() => {});
  }, []);
  const ciiYears = Object.keys(ciiByFy).sort();

  // ── Calculator state ──
  const [assetType, setAssetType] = useState<CapitalGainsAssetType>("equity");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [purchaseRupees, setPurchaseRupees] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [saleRupees, setSaleRupees] = useState("");
  const [improvementRupees, setImprovementRupees] = useState("");

  const purchasePaise = Math.round(parseFloat(purchaseRupees || "0") * 100);
  const salePaise = Math.round(parseFloat(saleRupees || "0") * 100);
  const improvementPaise = Math.round(parseFloat(improvementRupees || "0") * 100);
  const purchaseFY = purchaseDate ? getFYFromDate(purchaseDate) : "";
  const saleFY = saleDate ? getFYFromDate(saleDate) : "";

  const [result, setResult] = useState<CapitalGainsComputeResult | null>(null);
  const [computeError, setComputeError] = useState<string | null>(null);
  const [computing, setComputing] = useState(false);

  // Server-side compute, debounced 400ms (matches the deductions page's
  // pattern) so every keystroke doesn't fire a request.
  useEffect(() => {
    if (!purchaseDate || !saleDate || purchasePaise <= 0 || salePaise <= 0) {
      setResult(null);
      setComputeError(null);
      return;
    }
    const timer = setTimeout(() => {
      setComputing(true);
      computeCapitalGains({
        asset_type: assetType,
        purchase_date: purchaseDate,
        sale_date: saleDate,
        purchase_cost_paise: purchasePaise,
        sale_value_paise: salePaise,
        improvement_cost_paise: improvementPaise,
      })
        .then(r => { setResult(r); setComputeError(null); })
        .catch(e => { setResult(null); setComputeError(e instanceof Error ? e.message : "Failed to compute"); })
        .finally(() => setComputing(false));
    }, 400);
    return () => clearTimeout(timer);
  }, [assetType, purchaseDate, saleDate, purchasePaise, salePaise, improvementPaise]);

  const showIndexation = assetType === "property" && result?.is_long_term && result?.tax_with_indexation_percent != null;
  const showCII = assetType === "property";

  // ── Register state ──
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [records, setRecords] = useState<CapitalGainsRecord[]>([]);
  const [regLoading, setRegLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [regForm, setRegForm] = useState(BLANK_REG);
  const [saving, setSaving] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);

  useEffect(() => {
    (api.clients.list() as Promise<ApiResp<{ clients: Client[] }>>).then(res => {
      const cl = res.data?.clients ?? [];
      setClients(cl);
      if (cl.length > 0) setSelectedClientId(cl[0].id);
    }).catch(() => {});
  }, []);

  const loadRecords = useCallback(async () => {
    if (!selectedClientId) return;
    setRegLoading(true);
    try {
      const data = await listCapitalGains(selectedClientId);
      setRecords(data);
    } catch {
      setRecords([]);
    }
    setRegLoading(false);
  }, [selectedClientId]);

  useEffect(() => {
    if (activeTab === "register" && selectedClientId) loadRecords();
  }, [activeTab, selectedClientId, loadRecords]);

  // Live preview for the "Add Transaction" modal — same debounced
  // server-side compute as the calculator tab, not a client-side re-implementation.
  const [regPreview, setRegPreview] = useState<CapitalGainsComputeResult | null>(null);
  useEffect(() => {
    if (!showModal || !regForm.purchase_date || !regForm.sale_date || !regForm.purchase_cost_rs || !regForm.sale_value_rs) {
      setRegPreview(null);
      return;
    }
    const timer = setTimeout(() => {
      computeCapitalGains({
        asset_type: regForm.asset_type,
        purchase_date: regForm.purchase_date,
        sale_date: regForm.sale_date,
        purchase_cost_paise: rsToP(regForm.purchase_cost_rs),
        sale_value_paise: rsToP(regForm.sale_value_rs),
        improvement_cost_paise: rsToP(regForm.improvement_cost_rs),
      }).then(setRegPreview).catch(() => setRegPreview(null));
    }, 400);
    return () => clearTimeout(timer);
  }, [showModal, regForm.asset_type, regForm.purchase_date, regForm.sale_date,
      regForm.purchase_cost_rs, regForm.sale_value_rs, regForm.improvement_cost_rs]);

  async function handleSaveRecord() {
    if (!selectedClientId) return;
    if (!regForm.asset_description.trim() || !regForm.purchase_date || !regForm.sale_date) {
      setRegError("Asset description, purchase date, and sale date are required");
      return;
    }
    setSaving(true);
    setRegError(null);
    try {
      await createCapitalGain({
        client_id: selectedClientId,
        asset_description: regForm.asset_description.trim(),
        asset_type: regForm.asset_type,
        purchase_date: regForm.purchase_date,
        sale_date: regForm.sale_date,
        purchase_cost_paise: rsToP(regForm.purchase_cost_rs),
        improvement_cost_paise: rsToP(regForm.improvement_cost_rs),
        sale_value_paise: rsToP(regForm.sale_value_rs),
      });
      setShowModal(false);
      setRegForm(BLANK_REG);
      await loadRecords();
    } catch (e) {
      setRegError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRecord(id: string) {
    if (!confirm("Delete this record?")) return;
    try {
      await deleteCapitalGain(id);
      await loadRecords();
    } catch { /* leave the row in place on failure */ }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-[#94A3B8] hover:text-[#475569]">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-[#0F172A]">Capital Gains</h1>
          <p className="text-sm text-[#64748B] mt-0.5">IT Act Section 45 — Capital Gains Tax (Budget 2024 rates)</p>
        </div>
      </div>

      {/* Tab switcher */}
      <div className="flex border-b border-[#E2E8F0]">
        <button
          onClick={() => setActiveTab("calculator")}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === "calculator" ? "border-blue-600 text-blue-600" : "border-transparent text-[#64748B] hover:text-[#334155]"}`}
        >
          <Calculator className="w-4 h-4" /> Calculator
        </button>
        <button
          onClick={() => setActiveTab("register")}
          className={`flex items-center gap-2 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${activeTab === "register" ? "border-blue-600 text-blue-600" : "border-transparent text-[#64748B] hover:text-[#334155]"}`}
        >
          <BookOpen className="w-4 h-4" /> Register
        </button>
      </div>

      {/* ── Calculator Tab ── */}
      {activeTab === "calculator" && (
        <>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Input Form */}
            <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 space-y-4">
              <div className="flex items-center gap-2 mb-2">
                <Calculator className="w-4 h-4 text-blue-600" />
                <h2 className="text-sm font-semibold text-[#0F172A]">Asset Details</h2>
              </div>

              <div>
                <label className="text-xs font-medium text-[#334155] block mb-1">Asset Type</label>
                <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={assetType} onChange={e => setAssetType(e.target.value as CapitalGainsAssetType)}>
                  {ASSET_TYPES_CALC.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Purchase Date</label>
                  <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purchaseDate} onChange={e => setPurchaseDate(e.target.value)} />
                </div>
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Sale Date</label>
                  <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={saleDate} onChange={e => setSaleDate(e.target.value)} />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Purchase Price (₹)</label>
                  <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purchaseRupees} onChange={e => setPurchaseRupees(e.target.value)} placeholder="0.00" />
                </div>
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Sale Price (₹)</label>
                  <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={saleRupees} onChange={e => setSaleRupees(e.target.value)} placeholder="0.00" />
                </div>
              </div>

              {(assetType === "property" || assetType === "gold") && (
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Improvement Costs (₹) — optional</label>
                  <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={improvementRupees} onChange={e => setImprovementRupees(e.target.value)} placeholder="0.00" />
                </div>
              )}

              {showCII && purchaseFY && saleFY && (
                <div className="bg-[#F8FAFC] rounded-lg px-3 py-2">
                  <p className="text-[10px] text-[#94A3B8]">
                    Purchase FY: {purchaseFY} (CII: {ciiByFy[purchaseFY] ?? "—"}) · Sale FY: {saleFY} (CII: {ciiByFy[saleFY] ?? "—"})
                  </p>
                </div>
              )}
            </div>

            {/* Result Panel */}
            <div className="space-y-4">
              {computeError && (
                <div className="bg-red-50 border border-red-100 rounded-xl p-4 text-sm text-red-700">{computeError}</div>
              )}
              {!result ? (
                <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 flex items-center justify-center h-full min-h-[200px]">
                  <div className="text-center">
                    <Calculator className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                    <p className="text-sm text-[#94A3B8]">
                      {computing ? "Computing…" : "Enter asset details to compute capital gains"}
                    </p>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                    <h3 className="text-xs font-semibold text-[#64748B] uppercase tracking-wide mb-3">Classification</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-[#94A3B8]">Holding Period</p>
                        <p className="text-sm font-semibold text-[#0F172A]">{result.holding_months} months</p>
                      </div>
                      <div>
                        <p className="text-xs text-[#94A3B8]">Classification</p>
                        <span className={`inline-flex text-xs font-semibold px-2 py-0.5 rounded-full ${result.is_long_term ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                          {result.is_long_term ? "Long Term" : "Short Term"} Capital Gain
                        </span>
                      </div>
                      <div>
                        <p className="text-xs text-[#94A3B8]">Capital Gain</p>
                        <p className={`text-sm font-semibold ${result.gain_paise >= 0 ? "text-green-700" : "text-red-700"}`}>
                          {result.gain_paise >= 0 ? "+" : ""}₹{(result.gain_paise / 100).toLocaleString("en-IN")}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-[#94A3B8]">Applicable Rate</p>
                        <p className="text-sm font-semibold text-[#0F172A]">{result.tax_rate_percent}%</p>
                      </div>
                    </div>
                  </div>

                  <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                    <h3 className="text-xs font-semibold text-[#64748B] uppercase tracking-wide mb-3">Tax Computation</h3>
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-[#475569]">Sale Price</span>
                        <span className="font-medium">₹{(salePaise / 100).toLocaleString("en-IN")}</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-[#475569]">Cost of Acquisition</span>
                        <span className="font-medium">₹{(purchasePaise / 100).toLocaleString("en-IN")}</span>
                      </div>
                      {improvementPaise > 0 && (
                        <div className="flex justify-between text-sm">
                          <span className="text-[#475569]">Improvement Cost</span>
                          <span className="font-medium">₹{(improvementPaise / 100).toLocaleString("en-IN")}</span>
                        </div>
                      )}
                      <div className="border-t border-[#F1F5F9] pt-2 flex justify-between text-sm font-semibold">
                        <span className="text-[#1E293B]">Capital Gain</span>
                        <span className={result.gain_paise >= 0 ? "text-green-700" : "text-red-700"}>
                          ₹{(result.gain_paise / 100).toLocaleString("en-IN")}
                        </span>
                      </div>

                      {showIndexation && (
                        <div className="mt-3 border-t border-dashed border-[#F1F5F9] pt-3">
                          <p className="text-xs font-medium text-[#64748B] mb-2">With Indexation ({result.tax_with_indexation_percent}%)</p>
                          <div className="flex justify-between text-sm">
                            <span className="text-[#475569]">Indexed Cost (CII {ciiByFy[purchaseFY] ?? "—"} → {ciiByFy[saleFY] ?? "—"})</span>
                            <span>₹{(result.indexed_cost_paise / 100).toLocaleString("en-IN")}</span>
                          </div>
                          <div className="flex justify-between text-sm font-semibold mt-1">
                            <span className="text-[#1E293B]">Gain (indexed)</span>
                            <span className={result.gain_with_indexation_paise >= 0 ? "text-green-700" : "text-red-700"}>
                              ₹{(result.gain_with_indexation_paise / 100).toLocaleString("en-IN")}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="bg-blue-50 rounded-xl border border-blue-100 p-4">
                    <h3 className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-3">Estimated Tax Liability</h3>
                    {showIndexation ? (
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                          <span className="text-[#475569]">Tax without indexation ({result.tax_rate_percent}%)</span>
                          <span className="font-medium">{fmtRs(result.tax_without_indexation_paise)}</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-[#475569]">Tax with indexation ({result.tax_with_indexation_percent}%)</span>
                          <span className="font-medium">{fmtRs(result.tax_with_indexation_paise ?? 0)}</span>
                        </div>
                        <div className="border-t border-blue-200 pt-2 flex justify-between">
                          <span className="text-sm font-semibold text-[#1E293B]">Recommended (lower)</span>
                          <span className="text-lg font-bold text-blue-700">{fmtRs(result.tax_liability_paise)}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-[#475569]">Tax @ {result.tax_rate_percent}%</span>
                        <span className="text-2xl font-bold text-blue-700">{fmtRs(result.tax_liability_paise)}</span>
                      </div>
                    )}
                  </div>

                  <div className="bg-amber-50 rounded-lg p-3 flex gap-2">
                    <Info className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs text-amber-800 font-medium">{result.section_ref}</p>
                      <p className="text-xs text-amber-700 mt-0.5">{result.note}</p>
                      <p className="text-[10px] text-amber-600 mt-1">
                        {result.is_slab_rate_estimate
                          ? "This rate is an ESTIMATE at the highest slab — your actual liability depends on your own income slab. "
                          : ""}
                        This is an estimate. Add to ITR filing and consult CA for final computation. Surcharge and cess apply.
                      </p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* CII Table */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-[#0F172A]">Cost Inflation Index (CII) Table</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">IT Act Section 48 — Base year FY 2001-02 = 100</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <tbody>
                  <tr>
                    {ciiYears.map(y => (
                      <td key={y} className={`px-3 py-2 text-center border-r border-gray-50 ${purchaseFY === y || saleFY === y ? "bg-blue-50" : ""}`}>
                        <p className="text-[10px] text-[#94A3B8]">FY {y}</p>
                        <p className="text-xs font-semibold text-[#0F172A]">{ciiByFy[y]}</p>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Register Tab ── */}
      {activeTab === "register" && (
        <div className="space-y-4">
          {/* Client selector + Add button */}
          <div className="flex items-end gap-4 flex-wrap">
            <div>
              <label className="text-xs font-medium text-[#334155] block mb-1">Client</label>
              <div className="min-w-[200px]">
                <ClientLookup
                  clients={clients}
                  value={selectedClientId}
                  onChange={setSelectedClientId}
                  ariaLabel="Client"
                  placeholder="Select client…"
                />
              </div>
            </div>
            <Button size="sm" onClick={() => { setRegForm(BLANK_REG); setRegError(null); setShowModal(true); }} className="flex items-center gap-1">
              <Plus className="w-4 h-4" /> Add Transaction
            </Button>
          </div>

          {/* Records table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-blue-600" />
                Capital Gains Register ({records.length})
              </CardTitle>
            </CardHeader>
            {regLoading ? (
              <TableSkeleton cols={10} bare />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-[#F8FAFC] text-xs text-[#64748B] uppercase tracking-wide">
                      <th className="px-4 py-3 text-left">Asset</th>
                      <th className="px-4 py-3 text-left">Type</th>
                      <th className="px-4 py-3 text-left">Purchase</th>
                      <th className="px-4 py-3 text-left">Sale</th>
                      <th className="px-4 py-3 text-right">Cost</th>
                      <th className="px-4 py-3 text-right">Sale Value</th>
                      <th className="px-4 py-3 text-right">Indexed Cost</th>
                      <th className="px-4 py-3 text-center">Gain Type</th>
                      <th className="px-4 py-3 text-right">Tax Rate</th>
                      <th className="px-4 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {records.map(r => {
                      const gain = r.sale_value_paise - r.purchase_cost_paise - r.improvement_cost_paise;
                      return (
                        <tr key={r.id} className="hover:bg-[#F8FAFC]">
                          <td className="px-4 py-3 font-medium text-[#0F172A] max-w-[160px] truncate">{r.asset_description}</td>
                          <td className="px-4 py-3 text-[#475569] text-xs">{ASSET_TYPES_REG.find(a => a.value === r.asset_type)?.label ?? r.asset_type}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.purchase_date}</td>
                          <td className="px-4 py-3 text-[#475569]">{r.sale_date}</td>
                          <td className="px-4 py-3 text-right text-[#334155]">{fmtRs(r.purchase_cost_paise)}</td>
                          <td className="px-4 py-3 text-right text-[#334155]">{fmtRs(r.sale_value_paise)}</td>
                          <td className="px-4 py-3 text-right text-[#475569] text-xs">{r.indexed_cost_paise != null ? fmtRs(r.indexed_cost_paise) : "—"}</td>
                          <td className="px-4 py-3 text-center">
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${r.gain_type === "LTCG" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                              {r.gain_type ?? "—"}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right text-[#334155]">{r.tax_rate_percent != null ? `${r.tax_rate_percent}%` : "—"}</td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex flex-col items-end gap-1">
                              <span className={`text-xs font-semibold ${gain >= 0 ? "text-green-700" : "text-red-700"}`}>{gain >= 0 ? "+" : ""}{fmtRs(gain)}</span>
                              <button onClick={() => handleDeleteRecord(r.id)} className="text-[#CBD5E1] hover:text-red-500 transition-colors">
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                    {records.length === 0 && (
                      <tr><td colSpan={10} className="px-4 py-8 text-center text-[#94A3B8] text-sm">No capital gains transactions recorded yet.</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {/* Add Transaction Modal */}
          {showModal && (
            <div className="fixed inset-0 bg-[#0F172A]/60 z-50 flex items-center justify-center p-4">
              <div className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
                <div className="flex items-center justify-between px-5 py-4 border-b">
                  <h2 className="text-sm font-semibold text-[#0F172A]">Add Capital Gains Transaction</h2>
                  <button onClick={() => setShowModal(false)}><X className="w-4 h-4 text-[#94A3B8]" /></button>
                </div>
                <div className="px-5 py-4 space-y-4">
                  {regError && <div className="bg-red-50 text-red-700 text-xs px-3 py-2 rounded-lg">{regError}</div>}

                  <div>
                    <label className="text-xs font-medium text-[#334155] block mb-1">Asset Description *</label>
                    <input className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.asset_description} onChange={e => setRegForm(f => ({ ...f, asset_description: e.target.value }))} placeholder="e.g. Reliance Industries Ltd — 100 shares" />
                  </div>

                  <div>
                    <label className="text-xs font-medium text-[#334155] block mb-1">Asset Type *</label>
                    <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.asset_type} onChange={e => setRegForm(f => ({ ...f, asset_type: e.target.value as CapitalGainsRegisterAssetType }))}>
                      {ASSET_TYPES_REG.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                    </select>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-[#334155] block mb-1">Purchase Date *</label>
                      <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.purchase_date} onChange={e => setRegForm(f => ({ ...f, purchase_date: e.target.value }))} />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-[#334155] block mb-1">Sale Date *</label>
                      <input type="date" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.sale_date} onChange={e => setRegForm(f => ({ ...f, sale_date: e.target.value }))} />
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-medium text-[#334155] block mb-1">Purchase Cost (₹)</label>
                      <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.purchase_cost_rs} onChange={e => setRegForm(f => ({ ...f, purchase_cost_rs: e.target.value }))} placeholder="0" />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-[#334155] block mb-1">Sale Value (₹)</label>
                      <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.sale_value_rs} onChange={e => setRegForm(f => ({ ...f, sale_value_rs: e.target.value }))} placeholder="0" />
                    </div>
                  </div>

                  <div>
                    <label className="text-xs font-medium text-[#334155] block mb-1">Improvement Cost (₹) — optional</label>
                    <input type="number" min="0" className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.improvement_cost_rs} onChange={e => setRegForm(f => ({ ...f, improvement_cost_rs: e.target.value }))} placeholder="0" />
                  </div>

                  {/* Server-computed preview (STCG/LTCG, rate, indexed cost) */}
                  {regPreview && (
                    <div className="bg-blue-50 rounded-lg px-4 py-3 space-y-1">
                      <div className="flex justify-between text-xs">
                        <span className="text-[#475569]">Holding Period</span>
                        <span className="font-medium text-[#0F172A]">{regPreview.holding_months} months</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-[#475569]">Classification</span>
                        <span className={`font-semibold ${regPreview.gain_type === "LTCG" ? "text-green-700" : "text-amber-700"}`}>{regPreview.gain_type}</span>
                      </div>
                      <div className="flex justify-between text-xs">
                        <span className="text-[#475569]">Tax Rate</span>
                        <span className="font-medium text-[#0F172A]">{regPreview.tax_rate_percent}%</span>
                      </div>
                      {regForm.asset_type === "property" && (
                        <div className="flex justify-between text-xs">
                          <span className="text-[#475569]">Indexed Cost</span>
                          <span className="font-medium text-[#0F172A]">{fmtRs(regPreview.indexed_cost_paise)}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex justify-end gap-3 px-5 py-4 border-t">
                  <Button variant="outline" size="sm" onClick={() => setShowModal(false)}>Cancel</Button>
                  <Button size="sm" onClick={handleSaveRecord} disabled={saving}>{saving ? "Saving…" : "Save Transaction"}</Button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
