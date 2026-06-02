"use client";

/**
 * Advance Tax Calculator — IT Act Section 208
 * Taxpayers with tax liability > ₹10,000 must pay tax in 4 instalments.
 * Missing instalments attracts interest under Section 234B and 234C.
 *
 * Slab rates: New Regime FY 2026-27
 * Rebate u/s 87A: no tax if income ≤ ₹12,00,000 under new regime
 * Cess: 4% on tax after rebate — Finance Act 2023
 *
 * All monetary calculations use integer paise arithmetic (never floating point).
 */

import { useState, useEffect } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  AlertCircle,
  Info,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { getClients } from "@/lib/data/clients";
import { formatPaise } from "@/lib/services/formatting";
import type { Client } from "@/lib/types";

// ---------------------------------------------------------------------------
// Tax computation — all arithmetic in paise (integer)
// ---------------------------------------------------------------------------

/**
 * Compute income tax under New Regime for FY 2026-27.
 * IT Act Section 115BAC — New Tax Regime slabs.
 * Slab rates effective AY 2027-28:
 *   0 – 4,00,000:      0%
 *   4,00,001 – 8,00,000:  5%
 *   8,00,001 – 12,00,000: 10%
 *   12,00,001 – 16,00,000: 15%
 *   16,00,001 – 20,00,000: 20%
 *   20,00,001 – 24,00,000: 25%
 *   24,00,001+:            30%
 *
 * @param taxableIncomePaise - taxable income in paise (integer)
 * @returns tax before cess in paise (integer)
 */
function computeNewRegimeTax(taxableIncomePaise: number): number {
  // Work in rupees for slab logic, convert back to paise at end
  const slabs = [
    { limit: 400000_00, rate: 0 },      // 0–4L: 0%
    { limit: 800000_00, rate: 5 },      // 4–8L: 5%
    { limit: 1200000_00, rate: 10 },    // 8–12L: 10%
    { limit: 1600000_00, rate: 15 },    // 12–16L: 15%
    { limit: 2000000_00, rate: 20 },    // 16–20L: 20%
    { limit: 2400000_00, rate: 25 },    // 20–24L: 25%
    { limit: Infinity, rate: 30 },      // 24L+: 30%
  ];

  let remaining = taxableIncomePaise;
  let tax = 0;
  let prev = 0;

  for (const slab of slabs) {
    if (remaining <= 0) break;
    const slabLimitPaise = slab.limit === Infinity ? Infinity : slab.limit;
    const slabSize = slabLimitPaise === Infinity ? remaining : Math.min(slabLimitPaise - prev, remaining);
    // Integer multiplication: (slabSize * rate) / 100, truncated
    tax += Math.floor((slabSize * slab.rate) / 100);
    remaining -= slabSize;
    prev = slab.limit === Infinity ? prev : slab.limit;
  }

  return tax;
}

/**
 * Compute income tax under Old Regime.
 * IT Act — Old regime slabs for individuals below 60 years:
 *   0 – 2,50,000:      0%
 *   2,50,001 – 5,00,000: 5%
 *   5,00,001 – 10,00,000: 20%
 *   10,00,001+:          30%
 *
 * @param taxableIncomePaise - taxable income in paise (integer)
 * @returns tax before cess in paise (integer)
 */
function computeOldRegimeTax(taxableIncomePaise: number): number {
  const slabs = [
    { limit: 250000_00, rate: 0 },
    { limit: 500000_00, rate: 5 },
    { limit: 1000000_00, rate: 20 },
    { limit: Infinity, rate: 30 },
  ];

  let remaining = taxableIncomePaise;
  let tax = 0;
  let prev = 0;

  for (const slab of slabs) {
    if (remaining <= 0) break;
    const slabLimitPaise = slab.limit === Infinity ? Infinity : slab.limit;
    const slabSize = slabLimitPaise === Infinity ? remaining : Math.min(slabLimitPaise - prev, remaining);
    tax += Math.floor((slabSize * slab.rate) / 100);
    remaining -= slabSize;
    prev = slab.limit === Infinity ? prev : slab.limit;
  }

  return tax;
}

/**
 * Apply rebate u/s 87A.
 * New regime: rebate up to ₹60,000 if taxable income ≤ ₹12,00,000.
 * Old regime: rebate up to ₹12,500 if taxable income ≤ ₹5,00,000.
 * Finance Act 2023 — Section 87A
 */
function applyRebate87A(
  taxPaise: number,
  taxableIncomePaise: number,
  regime: "new" | "old"
): number {
  if (regime === "new") {
    // New regime: rebate if income ≤ ₹12L
    if (taxableIncomePaise <= 1200000_00) {
      // Max rebate ₹60,000 (6000000 paise)
      return Math.max(0, taxPaise - Math.min(taxPaise, 6000000));
    }
  } else {
    // Old regime: rebate if income ≤ ₹5L
    if (taxableIncomePaise <= 500000_00) {
      // Max rebate ₹12,500 (1250000 paise)
      return Math.max(0, taxPaise - Math.min(taxPaise, 1250000));
    }
  }
  return taxPaise;
}

/** Add 4% health & education cess — Finance Act 2007 Section 2 */
function addCess(taxAfterRebatePaise: number): number {
  // Cess = 4% of tax, in integer paise
  return taxAfterRebatePaise + Math.floor((taxAfterRebatePaise * 4) / 100);
}

interface TaxResult {
  grossIncomePaise: number;
  deductionsPaise: number;
  taxableIncomePaise: number;
  taxBeforeRebatePaise: number;
  rebatePaise: number;
  taxAfterRebatePaise: number;
  cessPaise: number;
  totalTaxPaise: number;
  // 4 instalments
  instalment1Paise: number; // 15% by 15 Jun
  instalment2Paise: number; // 45% cumulative by 15 Sep
  instalment3Paise: number; // 75% cumulative by 15 Dec
  instalment4Paise: number; // 100% by 15 Mar
}

function computeTax(
  salaryPaise: number,
  businessPaise: number,
  stcgPaise: number,
  ltcgPaise: number,
  otherPaise: number,
  deductionsPaise: number,
  regime: "new" | "old"
): TaxResult {
  const grossIncomePaise =
    salaryPaise + businessPaise + stcgPaise + ltcgPaise + otherPaise;

  // Under new regime, most deductions (80C, 80D etc.) are not available
  // except standard deduction of ₹75,000 for salaried — IT Act Section 115BAC
  const effectiveDeductions = regime === "new" ? 0 : deductionsPaise;
  const taxableIncomePaise = Math.max(
    0,
    grossIncomePaise - effectiveDeductions
  );

  const taxBeforeRebatePaise =
    regime === "new"
      ? computeNewRegimeTax(taxableIncomePaise)
      : computeOldRegimeTax(taxableIncomePaise);

  const taxAfterRebatePaise = applyRebate87A(
    taxBeforeRebatePaise,
    taxableIncomePaise,
    regime
  );
  const rebatePaise = taxBeforeRebatePaise - taxAfterRebatePaise;

  const totalTaxPaise = addCess(taxAfterRebatePaise);
  const cessPaise = totalTaxPaise - taxAfterRebatePaise;

  // Instalment amounts — IT Act Section 208/211
  // 15% by 15 Jun, cumulative 45% by 15 Sep, 75% by 15 Dec, 100% by 15 Mar
  const instalment1Paise = Math.floor((totalTaxPaise * 15) / 100);
  const instalment2Paise =
    Math.floor((totalTaxPaise * 45) / 100) - instalment1Paise;
  const instalment3Paise =
    Math.floor((totalTaxPaise * 75) / 100) -
    instalment1Paise -
    instalment2Paise;
  const instalment4Paise =
    totalTaxPaise -
    instalment1Paise -
    instalment2Paise -
    instalment3Paise;

  return {
    grossIncomePaise,
    deductionsPaise: effectiveDeductions,
    taxableIncomePaise,
    taxBeforeRebatePaise,
    rebatePaise,
    taxAfterRebatePaise,
    cessPaise,
    totalTaxPaise,
    instalment1Paise,
    instalment2Paise,
    instalment3Paise,
    instalment4Paise,
  };
}

/**
 * Compute Section 234C interest.
 * 1% per month on shortfall for 3 months (rounded to nearest month).
 * IT Act Section 234C — deferral of advance tax.
 */
function compute234CInterest(
  shortfallPaise: number
): number {
  if (shortfallPaise <= 0) return 0;
  // 1% per month × 3 months = 3%
  return Math.floor((shortfallPaise * 1 * 3) / 100);
}

/**
 * Compute Section 234B interest.
 * Applicable if total advance tax paid < 90% of assessed tax.
 * 1% per month from 1 April to date of assessment (use today).
 * IT Act Section 234B — default in payment of advance tax.
 */
function compute234BInterest(
  totalTaxPaise: number,
  totalPaidPaise: number,
  today: Date
): number {
  const ninetyCutoff = Math.floor((totalTaxPaise * 90) / 100);
  if (totalPaidPaise >= ninetyCutoff) return 0;

  const shortfall = ninetyCutoff - totalPaidPaise;
  // From 1 April of the assessment year (April 1, 2027 for FY 2026-27)
  // to today
  const aprilFirst = new Date("2027-04-01");
  const diffMs = today.getTime() - aprilFirst.getTime();
  if (diffMs <= 0) {
    // Before April 1 — no 234B yet
    const months = Math.ceil(
      (aprilFirst.getTime() - today.getTime()) / (30 * 24 * 60 * 60 * 1000)
    );
    void months;
    return 0;
  }
  const months = Math.ceil(diffMs / (30 * 24 * 60 * 60 * 1000));
  return Math.floor((shortfall * 1 * months) / 100);
}

// ---------------------------------------------------------------------------
// Helper: parse rupee string to paise
// ---------------------------------------------------------------------------
function rupeesToPaise(val: string): number {
  const n = parseFloat(val.replace(/,/g, ""));
  if (isNaN(n) || n < 0) return 0;
  // Multiply by 100 and round to get paise (integer)
  return Math.round(n * 100);
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const TODAY = new Date("2026-06-02");

const INSTALMENT_SCHEDULE = [
  {
    label: "1st Instalment",
    dueDate: "15 Jun 2026",
    dueDateISO: "2026-06-15",
    cumPct: 15,
    key: "instalment1" as const,
  },
  {
    label: "2nd Instalment",
    dueDate: "15 Sep 2026",
    dueDateISO: "2026-09-15",
    cumPct: 45,
    key: "instalment2" as const,
  },
  {
    label: "3rd Instalment",
    dueDate: "15 Dec 2026",
    dueDateISO: "2026-12-15",
    cumPct: 75,
    key: "instalment3" as const,
  },
  {
    label: "4th Instalment",
    dueDate: "15 Mar 2027",
    dueDateISO: "2027-03-15",
    cumPct: 100,
    key: "instalment4" as const,
  },
];

const STORAGE_KEY_PREFIX = "caflow_advance_tax_";

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

export default function AdvanceTaxPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState<string>("");
  const [regime, setRegime] = useState<"new" | "old">("new");

  // Income inputs (in rupees as strings for the form)
  const [salary, setSalary] = useState("0");
  const [business, setBusiness] = useState("0");
  const [stcg, setStcg] = useState("0");
  const [ltcg, setLtcg] = useState("0");
  const [other, setOther] = useState("0");
  const [deductions, setDeductions] = useState("0");

  // Paid amounts per instalment (in rupees as strings)
  const [paid1, setPaid1] = useState("0");
  const [paid2, setPaid2] = useState("0");
  const [paid3, setPaid3] = useState("0");
  const [paid4, setPaid4] = useState("0");

  const [showGuide, setShowGuide] = useState(false);

  // Load clients on mount
  useEffect(() => {
    getClients().then(setClients).catch(() => {});
  }, []);

  // Load saved data when client changes
  useEffect(() => {
    if (!selectedClientId) return;
    try {
      const saved = localStorage.getItem(STORAGE_KEY_PREFIX + selectedClientId);
      if (saved) {
        const d = JSON.parse(saved);
        setRegime(d.regime ?? "new");
        setSalary(d.salary ?? "0");
        setBusiness(d.business ?? "0");
        setStcg(d.stcg ?? "0");
        setLtcg(d.ltcg ?? "0");
        setOther(d.other ?? "0");
        setDeductions(d.deductions ?? "0");
        setPaid1(d.paid1 ?? "0");
        setPaid2(d.paid2 ?? "0");
        setPaid3(d.paid3 ?? "0");
        setPaid4(d.paid4 ?? "0");
      } else {
        // Reset
        setRegime("new");
        setSalary("0");
        setBusiness("0");
        setStcg("0");
        setLtcg("0");
        setOther("0");
        setDeductions("0");
        setPaid1("0");
        setPaid2("0");
        setPaid3("0");
        setPaid4("0");
      }
    } catch {}
  }, [selectedClientId]);

  // Save to localStorage whenever inputs change
  useEffect(() => {
    if (!selectedClientId) return;
    try {
      localStorage.setItem(
        STORAGE_KEY_PREFIX + selectedClientId,
        JSON.stringify({
          regime,
          salary,
          business,
          stcg,
          ltcg,
          other,
          deductions,
          paid1,
          paid2,
          paid3,
          paid4,
        })
      );
    } catch {}
  }, [
    selectedClientId,
    regime,
    salary,
    business,
    stcg,
    ltcg,
    other,
    deductions,
    paid1,
    paid2,
    paid3,
    paid4,
  ]);

  // Compute tax
  const result = computeTax(
    rupeesToPaise(salary),
    rupeesToPaise(business),
    rupeesToPaise(stcg),
    rupeesToPaise(ltcg),
    rupeesToPaise(other),
    rupeesToPaise(deductions),
    regime
  );

  const paidPaise = [
    rupeesToPaise(paid1),
    rupeesToPaise(paid2),
    rupeesToPaise(paid3),
    rupeesToPaise(paid4),
  ];

  const instalmentDue = [
    result.instalment1Paise,
    result.instalment2Paise,
    result.instalment3Paise,
    result.instalment4Paise,
  ];

  // Cumulative paid at each instalment
  const cumulativePaid = paidPaise.reduce<number[]>((acc, v) => {
    acc.push((acc[acc.length - 1] ?? 0) + v);
    return acc;
  }, []);

  // Shortfall per instalment (cumulative required - cumulative paid)
  const cumulativeRequired = [15, 45, 75, 100].map((pct) =>
    Math.floor((result.totalTaxPaise * pct) / 100)
  );
  const shortfalls = cumulativeRequired.map((req, i) =>
    Math.max(0, req - (cumulativePaid[i] ?? 0))
  );

  // 234C interest per instalment
  const interest234C = shortfalls.map((s) => compute234CInterest(s));

  // 234B interest — total advance tax vs 90% of total tax
  const totalPaidPaise = paidPaise.reduce((a, b) => a + b, 0);
  const interest234B = compute234BInterest(
    result.totalTaxPaise,
    totalPaidPaise,
    TODAY
  );

  const advanceTaxApplicable = result.totalTaxPaise >= 1000000; // ₹10,000 = 1,000,000 paise

  const setPaidFns = [setPaid1, setPaid2, setPaid3, setPaid4];

  const inputCls =
    "w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 text-right tabular-nums";

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Link
          href="/income-tax"
          className="text-gray-400 hover:text-gray-600 mt-0.5"
        >
          <ArrowLeft className="w-5 h-5" />
        </Link>
        <div>
          <h1 className="text-xl font-semibold text-gray-900">
            Advance Tax Calculator
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            IT Act Section 208 / 234B / 234C — FY 2026-27
          </p>
        </div>
      </div>

      {/* Client Selector */}
      <div className="bg-white rounded-xl border border-gray-100 p-4 flex items-center gap-4">
        <label className="text-sm font-medium text-gray-700 whitespace-nowrap">
          Client
        </label>
        <select
          value={selectedClientId}
          onChange={(e) => setSelectedClientId(e.target.value)}
          className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Select client (optional — saves data per client)</option>
          {clients.map((c) => (
            <option key={c.id} value={c.id}>
              {c.client_name}
              {c.pan ? ` — ${c.pan}` : ""}
            </option>
          ))}
        </select>
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        {/* LEFT: Income Input Form */}
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">
                  Estimated Income — FY 2026-27
                </h2>
                <p className="text-xs text-gray-400 mt-0.5">
                  All amounts in ₹ (rupees)
                </p>
              </div>
              {/* Regime toggle */}
              <div className="flex items-center rounded-lg border border-gray-200 overflow-hidden text-xs font-medium">
                <button
                  onClick={() => setRegime("new")}
                  className={`px-3 py-1.5 transition-colors ${regime === "new" ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-50"}`}
                >
                  New Regime
                </button>
                <button
                  onClick={() => setRegime("old")}
                  className={`px-3 py-1.5 transition-colors ${regime === "old" ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-50"}`}
                >
                  Old Regime
                </button>
              </div>
            </div>

            <div className="p-5 space-y-3">
              {[
                {
                  label: "Salary Income",
                  value: salary,
                  setter: setSalary,
                  hint: "Gross salary before standard deduction",
                },
                {
                  label: "Business / Professional Income",
                  value: business,
                  setter: setBusiness,
                  hint: "Net profit from business or profession",
                },
                {
                  label: "Short-term Capital Gains (STCG)",
                  value: stcg,
                  setter: setStcg,
                  hint: "IT Act Section 111A and other STCG",
                },
                {
                  label: "Long-term Capital Gains (LTCG)",
                  value: ltcg,
                  setter: setLtcg,
                  hint: "IT Act Section 112 / 112A",
                },
                {
                  label: "Other Income",
                  value: other,
                  setter: setOther,
                  hint: "Interest, rent, dividends etc.",
                },
              ].map(({ label, value, setter, hint }) => (
                <div key={label}>
                  <label className="text-xs font-medium text-gray-700 block mb-1">
                    {label}
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="1000"
                    value={value}
                    onChange={(e) => setter(e.target.value)}
                    className={inputCls}
                    placeholder="0"
                  />
                  <p className="text-[10px] text-gray-400 mt-0.5">{hint}</p>
                </div>
              ))}

              {/* Deductions — only for old regime */}
              <div>
                <label className="text-xs font-medium text-gray-700 block mb-1">
                  Less: Deductions (80C, 80D etc.)
                  {regime === "new" && (
                    <span className="ml-1 text-gray-400 font-normal">
                      (not applicable under new regime)
                    </span>
                  )}
                </label>
                <input
                  type="number"
                  min="0"
                  step="1000"
                  value={deductions}
                  onChange={(e) => setDeductions(e.target.value)}
                  disabled={regime === "new"}
                  className={`${inputCls} ${regime === "new" ? "opacity-40 cursor-not-allowed" : ""}`}
                  placeholder="0"
                />
                <p className="text-[10px] text-gray-400 mt-0.5">
                  IT Act Section 80C (max ₹1.5L), 80D, 80TTA etc.
                </p>
              </div>
            </div>
          </div>

          {/* ITR Form Guide — collapsible */}
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <button
              onClick={() => setShowGuide((v) => !v)}
              className="w-full flex items-center justify-between px-5 py-3.5 text-sm font-medium text-gray-700 hover:bg-gray-50/50 transition-colors"
            >
              <span className="flex items-center gap-2 text-xs text-gray-500">
                <Info className="w-3.5 h-3.5" />
                New Regime Slab Rates — FY 2026-27
              </span>
              {showGuide ? (
                <ChevronUp className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              )}
            </button>
            {showGuide && (
              <div className="px-5 pb-4 border-t border-gray-50 pt-3">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-gray-400">
                      <th className="text-left py-1">Income Range</th>
                      <th className="text-right py-1">Rate</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50 text-gray-700">
                    {[
                      ["Up to ₹4,00,000", "0%"],
                      ["₹4,00,001 – ₹8,00,000", "5%"],
                      ["₹8,00,001 – ₹12,00,000", "10%"],
                      ["₹12,00,001 – ₹16,00,000", "15%"],
                      ["₹16,00,001 – ₹20,00,000", "20%"],
                      ["₹20,00,001 – ₹24,00,000", "25%"],
                      ["Above ₹24,00,000", "30%"],
                    ].map(([range, rate]) => (
                      <tr key={range}>
                        <td className="py-1.5">{range}</td>
                        <td className="py-1.5 text-right font-medium">{rate}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="text-[10px] text-gray-400 mt-2">
                  + 4% Cess · Rebate u/s 87A (income ≤ ₹12L: zero tax) · IT Act Section 115BAC
                </p>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT: Tax Summary + Instalment Schedule */}
        <div className="space-y-4">
          {/* Tax Summary */}
          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-gray-900">
                Tax Summary
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                {regime === "new" ? "New Regime — IT Act Section 115BAC" : "Old Regime"}
              </p>
            </div>
            <div className="divide-y divide-gray-50">
              {[
                { label: "Gross Total Income", value: result.grossIncomePaise, indent: false },
                ...(regime === "old"
                  ? [{ label: "Less: Deductions (Chapter VI-A)", value: -result.deductionsPaise, indent: true }]
                  : []),
                { label: "Taxable Income", value: result.taxableIncomePaise, indent: false, bold: true },
                { label: "Tax on Taxable Income", value: result.taxBeforeRebatePaise, indent: true },
                ...(result.rebatePaise > 0
                  ? [{ label: "Less: Rebate u/s 87A", value: -result.rebatePaise, indent: true }]
                  : []),
                { label: "Tax after Rebate", value: result.taxAfterRebatePaise, indent: false },
                { label: "Add: 4% Cess", value: result.cessPaise, indent: true },
                { label: "Total Tax Liability", value: result.totalTaxPaise, indent: false, bold: true, highlight: true },
              ].map(({ label, value, indent, bold, highlight }) => (
                <div
                  key={label}
                  className={`flex items-center justify-between px-5 py-2.5 ${highlight ? "bg-blue-50" : ""}`}
                >
                  <span
                    className={`text-xs ${indent ? "pl-3 text-gray-500" : bold ? "font-semibold text-gray-900" : "text-gray-700"}`}
                  >
                    {label}
                  </span>
                  <span
                    className={`text-sm tabular-nums ${value < 0 ? "text-green-700" : ""} ${bold ? "font-semibold text-gray-900" : "text-gray-700"} ${highlight ? "font-bold text-blue-700" : ""}`}
                  >
                    {value < 0 ? `(${formatPaise(-value)})` : formatPaise(value)}
                  </span>
                </div>
              ))}
            </div>

            {/* Advance tax applicable flag */}
            {result.totalTaxPaise > 0 && !advanceTaxApplicable && (
              <div className="px-5 py-3 bg-green-50 border-t border-green-100">
                <p className="text-xs text-green-700">
                  Tax liability ≤ ₹10,000 — advance tax not applicable (IT Act Section 208)
                </p>
              </div>
            )}
            {advanceTaxApplicable && (
              <div className="px-5 py-3 bg-amber-50 border-t border-amber-100">
                <p className="text-xs text-amber-700 font-medium">
                  Advance tax mandatory — liability exceeds ₹10,000 (IT Act Section 208)
                </p>
              </div>
            )}
          </div>

          {/* Instalment Schedule */}
          {advanceTaxApplicable && (
            <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-50">
                <h2 className="text-sm font-semibold text-gray-900">
                  Instalment Schedule
                </h2>
                <p className="text-xs text-gray-400 mt-0.5">
                  IT Act Section 211 — enter actual payments to compute 234C interest
                </p>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 text-gray-400 text-[10px] uppercase tracking-wide">
                      <th className="text-left px-4 py-2.5">Instalment</th>
                      <th className="text-left px-3 py-2.5">Due Date</th>
                      <th className="text-right px-3 py-2.5">% Due</th>
                      <th className="text-right px-3 py-2.5">Amount Due</th>
                      <th className="text-right px-3 py-2.5">Amt Paid</th>
                      <th className="text-right px-3 py-2.5">Shortfall</th>
                      <th className="text-right px-4 py-2.5">234C Int.</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {INSTALMENT_SCHEDULE.map((inst, i) => {
                      const isPast = inst.dueDateISO < TODAY.toISOString().slice(0, 10);
                      const shortfall = shortfalls[i] ?? 0;
                      const interest = interest234C[i] ?? 0;
                      return (
                        <tr key={inst.key} className="hover:bg-gray-50/50">
                          <td className="px-4 py-3">
                            <p className="font-medium text-gray-900">{inst.label}</p>
                            <span
                              className={`text-[10px] px-1.5 py-0.5 rounded ${isPast ? "bg-gray-100 text-gray-500" : "bg-blue-50 text-blue-600"}`}
                            >
                              {isPast ? "Past" : "Upcoming"}
                            </span>
                          </td>
                          <td className="px-3 py-3 text-gray-600">{inst.dueDate}</td>
                          <td className="px-3 py-3 text-right text-gray-600">{inst.cumPct}%</td>
                          <td className="px-3 py-3 text-right font-medium text-gray-900">
                            {formatPaise(instalmentDue[i] ?? 0)}
                          </td>
                          <td className="px-3 py-3 text-right">
                            <input
                              type="number"
                              min="0"
                              step="100"
                              value={[paid1, paid2, paid3, paid4][i]}
                              onChange={(e) => setPaidFns[i]?.(e.target.value)}
                              className="w-24 border border-gray-200 rounded px-2 py-1 text-xs text-right tabular-nums focus:outline-none focus:ring-1 focus:ring-blue-500"
                            />
                          </td>
                          <td className="px-3 py-3 text-right">
                            <span className={shortfall > 0 ? "text-red-600 font-medium" : "text-gray-400"}>
                              {shortfall > 0 ? formatPaise(shortfall) : "—"}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right">
                            <span className={interest > 0 ? "text-red-600 font-medium" : "text-gray-400"}>
                              {interest > 0 ? formatPaise(interest) : "—"}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr className="border-t border-gray-100 bg-gray-50/50">
                      <td colSpan={3} className="px-4 py-2.5 text-xs font-medium text-gray-500">
                        Total
                      </td>
                      <td className="px-3 py-2.5 text-right text-xs font-semibold text-gray-900">
                        {formatPaise(result.totalTaxPaise)}
                      </td>
                      <td className="px-3 py-2.5 text-right text-xs font-semibold text-gray-900">
                        {formatPaise(totalPaidPaise)}
                      </td>
                      <td className="px-3 py-2.5 text-right text-xs font-semibold text-red-600">
                        {formatPaise(shortfalls.reduce((a, b) => a + b, 0))}
                      </td>
                      <td className="px-4 py-2.5 text-right text-xs font-semibold text-red-600">
                        {formatPaise(interest234C.reduce((a, b) => a + b, 0))}
                      </td>
                    </tr>
                  </tfoot>
                </table>
              </div>

              <div className="px-5 py-3 border-t border-gray-50 bg-gray-50/30">
                <p className="text-[10px] text-gray-400">
                  Section 234C: 1% per month × 3 months on shortfall at each instalment date · IT Act Section 234C
                </p>
              </div>
            </div>
          )}

          {/* 234B Interest */}
          {advanceTaxApplicable && (
            <div className="bg-white rounded-xl border border-gray-100 p-5 space-y-3">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">
                  Section 234B Interest — Default in Advance Tax
                </h2>
                <p className="text-xs text-gray-400 mt-0.5">
                  Applicable if total advance tax paid &lt; 90% of total tax — IT Act Section 234B
                </p>
              </div>

              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between">
                  <span className="text-gray-500">Total Tax Liability</span>
                  <span className="font-medium text-gray-900">
                    {formatPaise(result.totalTaxPaise)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">90% threshold</span>
                  <span className="text-gray-700">
                    {formatPaise(Math.floor((result.totalTaxPaise * 90) / 100))}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-500">Total Advance Tax Paid</span>
                  <span className={totalPaidPaise < Math.floor((result.totalTaxPaise * 90) / 100) ? "text-red-600 font-medium" : "text-green-600 font-medium"}>
                    {formatPaise(totalPaidPaise)}
                  </span>
                </div>
                <div className="flex justify-between border-t border-gray-100 pt-2 mt-2">
                  <span className="font-semibold text-gray-700">234B Interest (1%/month from 1 Apr 2027)</span>
                  <span className={`font-bold ${interest234B > 0 ? "text-red-600" : "text-green-600"}`}>
                    {interest234B > 0 ? formatPaise(interest234B) : "Nil"}
                  </span>
                </div>
              </div>

              {totalPaidPaise >= Math.floor((result.totalTaxPaise * 90) / 100) && (
                <p className="text-xs text-green-700 bg-green-50 rounded px-3 py-2">
                  Advance tax paid ≥ 90% of total tax — Section 234B interest not applicable.
                </p>
              )}
            </div>
          )}

          {/* Important disclaimer */}
          <div className="bg-amber-50 border border-amber-100 rounded-xl px-5 py-4 flex gap-3">
            {/* CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT */}
            <AlertCircle className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-amber-800 uppercase tracking-wide">
                CA Review Required
              </p>
              <p className="text-xs text-amber-700 mt-1">
                This calculator provides estimates only. Capital gains (STCG u/s
                111A, LTCG u/s 112A) may be taxed at special rates and must be
                reviewed separately. Verify with the income tax portal before
                making payments.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
