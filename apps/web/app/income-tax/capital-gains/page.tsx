"use client";

/**
 * Capital Gains Calculator — IT Act 1961
 * Section 2(29B): Short-term capital gains
 * Section 2(29A): Long-term capital gains
 * Section 45: Chargeability of capital gains
 * Section 48: Mode of computation
 * Section 54: Exemptions
 * Budget 2024 amendments: LTCG rates revised to 12.5%, STCG equity to 20%, holding periods unchanged
 * Finance Act 2023: Debt MF taxed as per slab (removed indexation benefit)
 */

import { useState, useMemo } from "react";
import Link from "next/link";
import { ChevronLeft, Calculator, Info } from "lucide-react";

// ─── Cost Inflation Index (CII) — IT Act Section 48, Proviso ────────────────
// Base year: FY 2001-02 = 100
const CII: Record<string, number> = {
  "2001-02": 100, "2002-03": 105, "2003-04": 109, "2004-05": 113, "2005-06": 117,
  "2006-07": 122, "2007-08": 129, "2008-09": 137, "2009-10": 148, "2010-11": 167,
  "2011-12": 184, "2012-13": 200, "2013-14": 220, "2014-15": 240, "2015-16": 254,
  "2016-17": 264, "2017-18": 272, "2018-19": 280, "2019-20": 289, "2020-21": 301,
  "2021-22": 317, "2022-23": 331, "2023-24": 348, "2024-25": 363,
};

const CII_YEARS = Object.keys(CII).sort();

// Asset types with their holding period thresholds and tax treatment
const ASSET_TYPES = [
  { value: "equity",     label: "Listed Equity / Equity MF" },
  { value: "debt_mf",   label: "Debt MF / Bonds (post Apr 2023)" },
  { value: "property",  label: "Immovable Property" },
  { value: "unlisted",  label: "Unlisted Shares" },
  { value: "vda",       label: "Cryptocurrency / VDA" },
  { value: "gold",      label: "Gold / Jewellery" },
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

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CapitalGainsPage() {
  const [assetType, setAssetType] = useState("equity");
  const [purchaseDate, setPurchaseDate] = useState("");
  const [purchaseRupees, setPurchaseRupees] = useState("");
  const [saleDate, setSaleDate] = useState("");
  const [saleRupees, setSaleRupees] = useState("");
  const [improvementRupees, setImprovementRupees] = useState("");
  const [purchaseFY, setPurchaseFY] = useState("2020-21");

  // Convert to paise — integer arithmetic, never float
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

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link href="/income-tax" className="text-gray-400 hover:text-gray-600">
          <ChevronLeft className="w-4 h-4" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Capital Gains Calculator</h1>
          <p className="text-sm text-gray-500 mt-0.5">IT Act Section 45 — Capital Gains Tax Computation (Budget 2024 rates)</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Input Form */}
        <div className="bg-white rounded-xl border border-gray-100 p-5 space-y-4">
          <div className="flex items-center gap-2 mb-2">
            <Calculator className="w-4 h-4 text-blue-600" />
            <h2 className="text-sm font-semibold text-gray-900">Asset Details</h2>
          </div>

          <div>
            <label className="text-xs font-medium text-gray-700 block mb-1">Asset Type</label>
            <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={assetType} onChange={e => setAssetType(e.target.value)}>
              {ASSET_TYPES.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Purchase Date</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purchaseDate} onChange={e => setPurchaseDate(e.target.value)} />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Sale Date</label>
              <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={saleDate} onChange={e => setSaleDate(e.target.value)} />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Purchase Price (₹)</label>
              <input type="number" min="0" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purchaseRupees} onChange={e => setPurchaseRupees(e.target.value)} placeholder="0.00" />
            </div>
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Sale Price (₹)</label>
              <input type="number" min="0" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={saleRupees} onChange={e => setSaleRupees(e.target.value)} placeholder="0.00" />
            </div>
          </div>

          {(assetType === "property" || assetType === "gold") && (
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Improvement Costs (₹) — optional</label>
              <input type="number" min="0" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={improvementRupees} onChange={e => setImprovementRupees(e.target.value)} placeholder="0.00" />
            </div>
          )}

          {showCII && (
            <div>
              <label className="text-xs font-medium text-gray-700 block mb-1">Purchase FY (for CII indexation)</label>
              <select className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" value={purchaseFY} onChange={e => setPurchaseFY(e.target.value)}>
                {CII_YEARS.map(y => <option key={y} value={y}>FY {y} (CII: {CII[y]})</option>)}
              </select>
              <p className="text-[10px] text-gray-400 mt-1">Sale FY: {saleFY} (CII: {CII[saleFY] ?? "—"})</p>
            </div>
          )}
        </div>

        {/* Result Panel */}
        <div className="space-y-4">
          {!result ? (
            <div className="bg-white rounded-xl border border-gray-100 p-5 flex items-center justify-center h-full min-h-[200px]">
              <div className="text-center">
                <Calculator className="w-8 h-8 text-gray-200 mx-auto mb-2" />
                <p className="text-sm text-gray-400">Enter asset details to compute capital gains</p>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Holding Period & Classification */}
              <div className="bg-white rounded-xl border border-gray-100 p-4">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Classification</h3>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <p className="text-xs text-gray-400">Holding Period</p>
                    <p className="text-sm font-semibold text-gray-900">{result.holdingMonths} months</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Classification</p>
                    <span className={`inline-flex text-xs font-semibold px-2 py-0.5 rounded-full ${result.isLongTerm ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                      {result.termLabel} Capital Gain
                    </span>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Capital Gain</p>
                    <p className={`text-sm font-semibold ${result.gainPaise >= 0 ? "text-green-700" : "text-red-700"}`}>
                      {result.gainPaise >= 0 ? "+" : ""}₹{(result.gainPaise / 100).toLocaleString("en-IN")}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-400">Applicable Rate</p>
                    <p className="text-sm font-semibold text-gray-900">{result.taxRatePercent}%</p>
                  </div>
                </div>
              </div>

              {/* Tax Computation */}
              <div className="bg-white rounded-xl border border-gray-100 p-4">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Tax Computation</h3>
                <div className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Sale Price</span>
                    <span className="font-medium">₹{(salePaise / 100).toLocaleString("en-IN")}</span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span className="text-gray-600">Cost of Acquisition</span>
                    <span className="font-medium">₹{(purchasePaise / 100).toLocaleString("en-IN")}</span>
                  </div>
                  {improvementPaise > 0 && (
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Improvement Cost</span>
                      <span className="font-medium">₹{(improvementPaise / 100).toLocaleString("en-IN")}</span>
                    </div>
                  )}
                  <div className="border-t border-gray-100 pt-2 flex justify-between text-sm font-semibold">
                    <span className="text-gray-800">Capital Gain</span>
                    <span className={result.gainPaise >= 0 ? "text-green-700" : "text-red-700"}>
                      ₹{(result.gainPaise / 100).toLocaleString("en-IN")}
                    </span>
                  </div>

                  {showIndexation && (
                    <>
                      <div className="mt-3 border-t border-dashed border-gray-100 pt-3">
                        <p className="text-xs font-medium text-gray-500 mb-2">With Indexation (20%)</p>
                        <div className="flex justify-between text-sm">
                          <span className="text-gray-600">Indexed Cost (CII {CII[purchaseFY]} → {CII[saleFY] ?? "—"})</span>
                          <span>₹{(result.indexedCostPaise / 100).toLocaleString("en-IN")}</span>
                        </div>
                        <div className="flex justify-between text-sm font-semibold mt-1">
                          <span className="text-gray-800">Gain (indexed)</span>
                          <span className={result.gainWithIndexation >= 0 ? "text-green-700" : "text-red-700"}>
                            ₹{(result.gainWithIndexation / 100).toLocaleString("en-IN")}
                          </span>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              </div>

              {/* Final Tax */}
              <div className="bg-blue-50 rounded-xl border border-blue-100 p-4">
                <h3 className="text-xs font-semibold text-blue-600 uppercase tracking-wide mb-3">Estimated Tax Liability</h3>
                {showIndexation ? (
                  <div className="space-y-2">
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Tax without indexation (12.5%)</span>
                      <span className="font-medium">₹{(result.taxLiabilityPaise / 100).toLocaleString("en-IN")}</span>
                    </div>
                    <div className="flex justify-between text-sm">
                      <span className="text-gray-600">Tax with indexation (20%)</span>
                      <span className="font-medium">₹{(result.taxWithIndexationPaise / 100).toLocaleString("en-IN")}</span>
                    </div>
                    <div className="border-t border-blue-200 pt-2 flex justify-between">
                      <span className="text-sm font-semibold text-gray-800">Recommended (lower)</span>
                      <span className="text-lg font-bold text-blue-700">₹{(result.finalTaxPaise / 100).toLocaleString("en-IN")}</span>
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">Tax @ {result.taxRatePercent}%</span>
                    <span className="text-2xl font-bold text-blue-700">₹{(result.finalTaxPaise / 100).toLocaleString("en-IN")}</span>
                  </div>
                )}
              </div>

              {/* Note */}
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
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-50">
          <h2 className="text-sm font-semibold text-gray-900">Cost Inflation Index (CII) Table</h2>
          <p className="text-xs text-gray-400 mt-0.5">IT Act Section 48 — Base year FY 2001-02 = 100</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              <tr>
                {CII_YEARS.map(y => (
                  <td key={y} className={`px-3 py-2 text-center border-r border-gray-50 ${purchaseFY === y || saleFY === y ? "bg-blue-50" : ""}`}>
                    <p className="text-[10px] text-gray-400">FY {y}</p>
                    <p className="text-xs font-semibold text-gray-900">{CII[y]}</p>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
