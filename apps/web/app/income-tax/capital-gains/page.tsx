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
 */

import { useState, useMemo, useEffect } from "react";
import Link from "next/link";
import { ChevronLeft, Calculator, Info, BookOpen, Plus, X, Trash2 } from "lucide-react";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";

// ─── Cost Inflation Index (CII) — IT Act Section 48, Proviso ────────────────
// Base year: FY 2001-02 = 100
const CII: Record<string, number> = {
  "2001-02": 100, "2002-03": 105, "2003-04": 109, "2004-05": 113, "2005-06": 117,
  "2006-07": 122, "2007-08": 129, "2008-09": 137, "2009-10": 148, "2010-11": 167,
  "2011-12": 184, "2012-13": 200, "2013-14": 220, "2014-15": 240, "2015-16": 254,
  "2016-17": 264, "2017-18": 272, "2018-19": 280, "2019-20": 289, "2020-21": 301,
  "2021-22": 317, "2022-23": 331, "2023-24": 348, "2024-25": 363, "2025-26": 380,
};

const CII_YEARS = Object.keys(CII).sort();

// Asset types with their holding period thresholds and tax treatment
const ASSET_TYPES_CALC = [
  { value: "equity",     label: "Listed Equity / Equity MF" },
  { value: "debt_mf",   label: "Debt MF / Bonds (post Apr 2023)" },
  { value: "property",  label: "Immovable Property" },
  { value: "unlisted",  label: "Unlisted Shares" },
  { value: "vda",       label: "Cryptocurrency / VDA" },
  { value: "gold",      label: "Gold / Jewellery" },
];

// Asset types for register (matches DB constraint)
const ASSET_TYPES_REG = [
  { value: "equity_shares", label: "Equity Shares" },
  { value: "mutual_funds",  label: "Mutual Funds" },
  { value: "property",      label: "Immovable Property" },
  { value: "bonds",         label: "Bonds" },
  { value: "other",         label: "Other" },
];

function getHoldingMonths(purchaseDate: string, saleDate: string): number {
  const purchase = new Date(purchaseDate);
  const sale = new Date(saleDate);
  return (sale.getFullYear() - purchase.getFullYear()) * 12 + (sale.getMonth() - purchase.getMonth());
}

function getFYFromDate(date: string): string {
  const d = new Date(date);
  const y = d.getFullYear();
  const m = d.getMonth(); // 0=Jan
  if (m >= 3) return `${y}-${String(y + 1).slice(2)}`;
  return `${y - 1}-${String(y).slice(2)}`;
}

function getFYFull(date: string): string {
  // returns e.g. "2023-24"
  const d = new Date(date);
  const y = d.getFullYear();
  const m = d.getMonth();
  if (m >= 3) return `${y}-${String(y + 1).slice(-2)}`;
  return `${y - 1}-${String(y).slice(-2)}`;
}

interface CalcResult {
  holdingMonths: number;
  isLongTerm: boolean;
  termLabel: string;
  gainPaise: number;
  indexedCostPaise: number;
  gainWithIndexation: number;
  taxRatePercent: number;
  taxRateWithIndexation: number;
  taxLiabilityPaise: number;
  taxWithIndexationPaise: number;
  finalTaxPaise: number;
  taxNote: string;
  sectionRef: string;
}

function computeGains(
  assetType: string,
  purchasePaise: number,
  salePaise: number,
  purchaseDate: string,
  saleDate: string,
  improvementPaise: number,
  purchaseFY: string,
  saleFY: string,
): CalcResult | null {
  if (!purchaseDate || !saleDate || salePaise <= 0 || purchasePaise <= 0) return null;

  const holdingMonths = getHoldingMonths(purchaseDate, saleDate);

  // Determine long-term threshold by asset type — IT Act Section 2(42A)
  let ltThreshold = 12; // months
  if (assetType === "property" || assetType === "unlisted" || assetType === "gold") ltThreshold = 24;

  const isLongTerm = holdingMonths >= ltThreshold;
  const termLabel = isLongTerm ? "Long Term" : "Short Term";

  // Gain = Sale Price - Cost of Acquisition - Improvement Costs (Section 48)
  const costPaise = purchasePaise + improvementPaise;
  const gainPaise = salePaise - costPaise;

  // Indexed cost of acquisition — Section 48 proviso (only for property, indexed benefit)
  const ciiPurchase = CII[purchaseFY] ?? 100;
  const ciiSale = CII[saleFY] ?? 363;
  const indexedCostPaise = Math.round((purchasePaise * ciiSale) / ciiPurchase) + improvementPaise;
  const gainWithIndexation = salePaise - indexedCostPaise;

  let taxRatePercent = 0;
  let taxRateWithIndexation = 0;
  let taxNote = "";
  let sectionRef = "";

  switch (assetType) {
    case "equity":
      if (!isLongTerm) {
        // STCG on listed equity: 20% — Budget 2024 (effective 23 Jul 2024), IT Act Section 111A
        taxRatePercent = 20;
        taxNote = "STCG on listed equity/equity MF: 20% (Budget 2024 — Section 111A)";
        sectionRef = "Section 111A";
      } else {
        // LTCG on listed equity: 12.5% on gains > ₹1,25,000 — Budget 2024, IT Act Section 112A
        // Exemption: first ₹1,25,000 of LTCG is tax-free
        const exemptionPaise = 125000 * 100; // ₹1,25,000 in paise
        const taxableGainPaise = Math.max(0, gainPaise - exemptionPaise);
        taxRatePercent = 12.5;
        const taxLiability = Math.round((taxableGainPaise * 125) / 1000); // 12.5% integer
        taxNote = `LTCG on listed equity: 12.5% on gains exceeding ₹1,25,000 (Budget 2024 — Section 112A). Exempt: ₹1,25,000.`;
        sectionRef = "Section 112A";
        return {
          holdingMonths, isLongTerm, termLabel, gainPaise, indexedCostPaise, gainWithIndexation,
          taxRatePercent, taxRateWithIndexation, taxLiabilityPaise: taxLiability,
          taxWithIndexationPaise: taxLiability, finalTaxPaise: taxLiability, taxNote, sectionRef,
        };
      }
      break;

    case "debt_mf":
      // Finance Act 2023: Debt MF purchased after 1 Apr 2023 — no indexation, taxed at slab rate
      taxRatePercent = 30; // Approximate highest slab — actual rate depends on taxpayer's slab
      taxNote = "Debt MF (purchased after 1 Apr 2023): Taxed as per income slab — Finance Act 2023 amendment. Rate shown at 30% (highest slab). Adjust for your actual slab.";
      sectionRef = "Section 50AA (Finance Act 2023)";
      break;

    case "property":
      if (!isLongTerm) {
        // STCG on property: slab rate — Section 48
        taxRatePercent = 30;
        taxNote = "STCG on immovable property (< 24 months): Taxed at slab rate (shown at 30%). Adjust for your slab.";
        sectionRef = "Section 48";
      } else {
        // LTCG on property: Budget 2024 — 12.5% without indexation OR 20% with indexation (taxpayer's choice)
        // Whichever results in lower tax
        taxRatePercent = 12.5;
        taxRateWithIndexation = 20;
        taxNote = "LTCG on property: Budget 2024 — 12.5% without indexation OR 20% with indexation. Whichever is lower (Section 112).";
        sectionRef = "Section 112 (Budget 2024 amendment)";
      }
      break;

    case "unlisted":
      if (!isLongTerm) {
        taxRatePercent = 30;
        taxNote = "STCG on unlisted shares (< 24 months): Taxed at slab rate (shown at 30%).";
        sectionRef = "Section 48";
      } else {
        taxRatePercent = 12.5;
        taxNote = "LTCG on unlisted shares (≥ 24 months): 12.5% without indexation — Budget 2024 (Section 112).";
        sectionRef = "Section 112 (Budget 2024)";
      }
      break;

    case "vda":
      // Cryptocurrency/VDA: Always 30% flat + 1% TDS Section 194S — IT Act Section 115BBH
      taxRatePercent = 30;
      taxNote = "VDA/Cryptocurrency: 30% flat tax regardless of holding period (Section 115BBH). Additionally, 1% TDS under Section 194S applies on every transaction.";
      sectionRef = "Section 115BBH + Section 194S";
      break;

    case "gold":
      if (!isLongTerm) {
        taxRatePercent = 30;
        taxNote = "STCG on gold (< 24 months): Taxed at slab rate (shown at 30%).";
        sectionRef = "Section 48";
      } else {
        taxRatePercent = 12.5;
        taxNote = "LTCG on gold (≥ 24 months): 12.5% without indexation — Budget 2024 (Section 112).";
        sectionRef = "Section 112 (Budget 2024)";
      }
      break;
  }

  // Tax calculations — integer paise arithmetic
  const taxableGain = Math.max(0, gainPaise);
  const taxLiabilityPaise = Math.round((taxableGain * taxRatePercent * 100) / 10000);
  const taxWithIndexationPaise = taxRateWithIndexation > 0
    ? Math.round((Math.max(0, gainWithIndexation) * taxRateWithIndexation * 100) / 10000)
    : taxLiabilityPaise;

  const finalTaxPaise = Math.min(taxLiabilityPaise, taxWithIndexationPaise);

  return {
    holdingMonths, isLongTerm, termLabel, gainPaise, indexedCostPaise, gainWithIndexation,
    taxRatePercent, taxRateWithIndexation, taxLiabilityPaise, taxWithIndexationPaise,
    finalTaxPaise, taxNote, sectionRef,
  };
}

// ─── Register Types ───────────────────────────────────────────────────────────

interface Client { id: string; client_name: string; }

interface CGRecord {
  id: string;
  client_id: string;
  asset_description: string;
  asset_type: string;
  purchase_date: string;
  sale_date: string;
  purchase_cost_paise: number;
  improvement_cost_paise: number;
  sale_value_paise: number;
  indexed_cost_paise: number | null;
  gain_type: string | null;
  tax_rate_percent: number | null;
  created_at: string;
}

const BLANK_REG = {
  asset_description: "",
  asset_type: "equity_shares",
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

/**
 * Determine STCG/LTCG for register asset types
 * IT Act Section 2(42A) — holding period thresholds
 */
function getRegGainType(assetType: string, purchaseDate: string, saleDate: string): "STCG" | "LTCG" {
  const months = getHoldingMonths(purchaseDate, saleDate);
  if (assetType === "equity_shares" || assetType === "mutual_funds") {
    return months >= 12 ? "LTCG" : "STCG";
  }
  // property, bonds, other — 24 months
  return months >= 24 ? "LTCG" : "STCG";
}

/**
 * Compute tax rate for register asset types
 * IT Act Section 111A (STCG equity), Section 112A (LTCG equity), Section 112 (others)
 */
function getRegTaxRate(assetType: string, gainType: "STCG" | "LTCG"): number {
  if (assetType === "equity_shares" || assetType === "mutual_funds") {
    return gainType === "STCG" ? 20 : 12.5; // Budget 2024
  }
  return gainType === "STCG" ? 30 : 20; // slab / 20% with indexation
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function CapitalGainsPage() {
  const [activeTab, setActiveTab] = useState<"calculator" | "register">("calculator");

  // ── Calculator state ──
  const [assetType, setAssetType] = useState("equity");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [purchaseRupees, setPurchaseRupees] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [saleRupees, setSaleRupees] = useState("");
  const [improvementRupees, setImprovementRupees] = useState("");
  const [purchaseFY, setPurchaseFY] = useState("2020-21");

  const purchasePaise = Math.round(parseFloat(purchaseRupees || "0") * 100);
  const salePaise = Math.round(parseFloat(saleRupees || "0") * 100);
  const improvementPaise = Math.round(parseFloat(improvementRupees || "0") * 100);
  const saleFY = saleDate ? getFYFromDate(saleDate) : "2024-25";

  const result = useMemo(() => {
    if (!purchaseDate || !saleDate) return null;
    return computeGains(assetType, purchasePaise, salePaise, purchaseDate, saleDate, improvementPaise, purchaseFY, saleFY);
  }, [assetType, purchasePaise, salePaise, purchaseDate, saleDate, improvementPaise, purchaseFY, saleFY]);

  const showIndexation = assetType === "property" && result?.isLongTerm;
  const showCII = assetType === "property";

  // ── Register state ──
  const [firmId, setFirmId] = useState<string | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [records, setRecords] = useState<CGRecord[]>([]);
  const [regLoading, setRegLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [regForm, setRegForm] = useState(BLANK_REG);
  const [saving, setSaving] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);

  useEffect(() => {
    const sb = getSupabaseClient();
    getFirmId().then(async (fid) => {
      setFirmId(fid);
      const { data } = await sb.from("clients").select("id, client_name").eq("firm_id", fid).eq("is_active", true).order("client_name");
      const cl = (data ?? []) as Client[];
      setClients(cl);
      if (cl.length > 0) setSelectedClientId(cl[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    if (activeTab === "register" && selectedClientId && firmId) loadRecords();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, selectedClientId, firmId]);

  async function loadRecords() {
    if (!firmId || !selectedClientId) return;
    setRegLoading(true);
    const sb = getSupabaseClient();
    const { data } = await sb.from("capital_gains").select("*").eq("firm_id", firmId).eq("client_id", selectedClientId).order("sale_date", { ascending: false });
    setRecords((data ?? []) as CGRecord[]);
    setRegLoading(false);
  }

  async function handleSaveRecord() {
    if (!firmId || !selectedClientId) return;
    if (!regForm.asset_description.trim() || !regForm.purchase_date || !regForm.sale_date) {
      setRegError("Asset description, purchase date, and sale date are required");
      return;
    }
    setSaving(true);
    setRegError(null);

    const purchaseCostPaise = rsToP(regForm.purchase_cost_rs);
    const improvementCostPaise = rsToP(regForm.improvement_cost_rs);
    const saleValuePaise = rsToP(regForm.sale_value_rs);

    // Cost Inflation Index per IT Act Section 48, IT Rule 54HA
    // Base year 2001-02 = 100
    // Apply CII: Indexed Cost = (Cost × CII of sale year) / CII of purchase year
    const purchFY = getFYFull(regForm.purchase_date);
    const salFY = getFYFull(regForm.sale_date);
    const ciiP = CII[purchFY] ?? 100;
    const ciiS = CII[salFY] ?? 363;
    const indexedCostPaise = Math.round((purchaseCostPaise * ciiS) / ciiP) + improvementCostPaise;

    const gainType = getRegGainType(regForm.asset_type, regForm.purchase_date, regForm.sale_date);
    const taxRate = getRegTaxRate(regForm.asset_type, gainType);

    const sb = getSupabaseClient();
    const { error } = await sb.from("capital_gains").insert({
      firm_id: firmId,
      client_id: selectedClientId,
      asset_description: regForm.asset_description.trim(),
      asset_type: regForm.asset_type,
      purchase_date: regForm.purchase_date,
      sale_date: regForm.sale_date,
      purchase_cost_paise: purchaseCostPaise,
      improvement_cost_paise: improvementCostPaise,
      sale_value_paise: saleValuePaise,
      indexed_cost_paise: indexedCostPaise,
      gain_type: gainType,
      tax_rate_percent: taxRate,
    });

    setSaving(false);
    if (error) { setRegError(error.message); return; }
    setShowModal(false);
    setRegForm(BLANK_REG);
    await loadRecords();
  }

  async function deleteRecord(id: string) {
    if (!confirm("Delete this record?")) return;
    const sb = getSupabaseClient();
    await sb.from("capital_gains").delete().eq("id", id);
    await loadRecords();
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
                <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={assetType} onChange={e => setAssetType(e.target.value)}>
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

              {showCII && (
                <div>
                  <label className="text-xs font-medium text-[#334155] block mb-1">Purchase FY (for CII indexation)</label>
                  <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purchaseFY} onChange={e => setPurchaseFY(e.target.value)}>
                    {CII_YEARS.map(y => <option key={y} value={y}>FY {y} (CII: {CII[y]})</option>)}
                  </select>
                  <p className="text-[10px] text-[#94A3B8] mt-1">Sale FY: {saleFY} (CII: {CII[saleFY] ?? "—"})</p>
                </div>
              )}
            </div>

            {/* Result Panel */}
            <div className="space-y-4">
              {!result ? (
                <div className="bg-white rounded-xl border border-[#F1F5F9] p-5 flex items-center justify-center h-full min-h-[200px]">
                  <div className="text-center">
                    <Calculator className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                    <p className="text-sm text-[#94A3B8]">Enter asset details to compute capital gains</p>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
                    <h3 className="text-xs font-semibold text-[#64748B] uppercase tracking-wide mb-3">Classification</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <p className="text-xs text-[#94A3B8]">Holding Period</p>
                        <p className="text-sm font-semibold text-[#0F172A]">{result.holdingMonths} months</p>
                      </div>
                      <div>
                        <p className="text-xs text-[#94A3B8]">Classification</p>
                        <span className={`inline-flex text-xs font-semibold px-2 py-0.5 rounded-full ${result.isLongTerm ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                          {result.termLabel} Capital Gain
                        </span>
                      </div>
                      <div>
                        <p className="text-xs text-[#94A3B8]">Capital Gain</p>
                        <p className={`text-sm font-semibold ${result.gainPaise >= 0 ? "text-green-700" : "text-red-700"}`}>
                          {result.gainPaise >= 0 ? "+" : ""}₹{(result.gainPaise / 100).toLocaleString("en-IN")}
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-[#94A3B8]">Applicable Rate</p>
                        <p className="text-sm font-semibold text-[#0F172A]">{result.taxRatePercent}%</p>
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
                        <span className={result.gainPaise >= 0 ? "text-green-700" : "text-red-700"}>
                          ₹{(result.gainPaise / 100).toLocaleString("en-IN")}
                        </span>
                      </div>

                      {showIndexation && (
                        <div className="mt-3 border-t border-dashed border-[#F1F5F9] pt-3">
                          <p className="text-xs font-medium text-[#64748B] mb-2">With Indexation (20%)</p>
                          <div className="flex justify-between text-sm">
                            <span className="text-[#475569]">Indexed Cost (CII {CII[purchaseFY]} → {CII[saleFY] ?? "—"})</span>
                            <span>₹{(result.indexedCostPaise / 100).toLocaleString("en-IN")}</span>
                          </div>
                          <div className="flex justify-between text-sm font-semibold mt-1">
                            <span className="text-[#1E293B]">Gain (indexed)</span>
                            <span className={result.gainWithIndexation >= 0 ? "text-green-700" : "text-red-700"}>
                              ₹{(result.gainWithIndexation / 100).toLocaleString("en-IN")}
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
                          <span className="text-[#475569]">Tax without indexation (12.5%)</span>
                          <span className="font-medium">₹{(result.taxLiabilityPaise / 100).toLocaleString("en-IN")}</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-[#475569]">Tax with indexation (20%)</span>
                          <span className="font-medium">₹{(result.taxWithIndexationPaise / 100).toLocaleString("en-IN")}</span>
                        </div>
                        <div className="border-t border-blue-200 pt-2 flex justify-between">
                          <span className="text-sm font-semibold text-[#1E293B]">Recommended (lower)</span>
                          <span className="text-lg font-bold text-blue-700">₹{(result.finalTaxPaise / 100).toLocaleString("en-IN")}</span>
                        </div>
                      </div>
                    ) : (
                      <div className="flex justify-between items-center">
                        <span className="text-sm text-[#475569]">Tax @ {result.taxRatePercent}%</span>
                        <span className="text-2xl font-bold text-blue-700">₹{(result.finalTaxPaise / 100).toLocaleString("en-IN")}</span>
                      </div>
                    )}
                  </div>

                  <div className="bg-amber-50 rounded-lg p-3 flex gap-2">
                    <Info className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                    <div>
                      <p className="text-xs text-amber-800 font-medium">{result.sectionRef}</p>
                      <p className="text-xs text-amber-700 mt-0.5">{result.taxNote}</p>
                      <p className="text-[10px] text-amber-600 mt-1">This is an estimate. Add to ITR filing and consult CA for final computation. Surcharge and cess apply.</p>
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
                    {CII_YEARS.map(y => (
                      <td key={y} className={`px-3 py-2 text-center border-r border-gray-50 ${purchaseFY === y || saleFY === y ? "bg-blue-50" : ""}`}>
                        <p className="text-[10px] text-[#94A3B8]">FY {y}</p>
                        <p className="text-xs font-semibold text-[#0F172A]">{CII[y]}</p>
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
              <select className="border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[200px]" value={selectedClientId} onChange={e => setSelectedClientId(e.target.value)}>
                {clients.map(c => <option key={c.id} value={c.id}>{c.client_name}</option>)}
              </select>
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
              <div className="px-5 py-8 text-sm text-[#94A3B8] text-center animate-pulse">Loading…</div>
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
                              <button onClick={() => deleteRecord(r.id)} className="text-[#CBD5E1] hover:text-red-500 transition-colors">
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
                    <select className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={regForm.asset_type} onChange={e => setRegForm(f => ({ ...f, asset_type: e.target.value }))}>
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

                  {/* Preview STCG/LTCG */}
                  {regForm.purchase_date && regForm.sale_date && (
                    <div className="bg-blue-50 rounded-lg px-4 py-3 space-y-1">
                      {(() => {
                        const gt = getRegGainType(regForm.asset_type, regForm.purchase_date, regForm.sale_date);
                        const months = getHoldingMonths(regForm.purchase_date, regForm.sale_date);
                        const tr = getRegTaxRate(regForm.asset_type, gt);
                        const pFY = getFYFull(regForm.purchase_date);
                        const sFY = getFYFull(regForm.sale_date);
                        const ciiP = CII[pFY] ?? 100;
                        const ciiS = CII[sFY] ?? 363;
                        const purchCostP = rsToP(regForm.purchase_cost_rs);
                        // Cost Inflation Index per IT Act Section 48, IT Rule 54HA
                        // Base year 2001-02 = 100
                        // Apply CII: Indexed Cost = (Cost × CII of sale year) / CII of purchase year
                        const indexedP = Math.round((purchCostP * ciiS) / ciiP) + rsToP(regForm.improvement_cost_rs);
                        return (
                          <>
                            <div className="flex justify-between text-xs">
                              <span className="text-[#475569]">Holding Period</span>
                              <span className="font-medium text-[#0F172A]">{months} months</span>
                            </div>
                            <div className="flex justify-between text-xs">
                              <span className="text-[#475569]">Classification</span>
                              <span className={`font-semibold ${gt === "LTCG" ? "text-green-700" : "text-amber-700"}`}>{gt}</span>
                            </div>
                            <div className="flex justify-between text-xs">
                              <span className="text-[#475569]">Tax Rate</span>
                              <span className="font-medium text-[#0F172A]">{tr}%</span>
                            </div>
                            {regForm.asset_type === "property" && (
                              <div className="flex justify-between text-xs">
                                <span className="text-[#475569]">Indexed Cost (CII {ciiP}→{ciiS})</span>
                                <span className="font-medium text-[#0F172A]">{fmtRs(indexedP)}</span>
                              </div>
                            )}
                          </>
                        );
                      })()}
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
