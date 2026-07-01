"use client";

/**
 * Section 80 Deductions Planner — Per-client ITR planning tool
 * IT Act Section 80C — limit ₹1,50,000 for various investments
 * IT Act Section 80CCD(1B) — NPS additional ₹50,000
 * IT Act Section 80D — Health insurance premiums
 * IT Act Section 80G — Donations to approved funds
 * IT Act Section 80TTA/80TTB — Savings interest deduction
 * IT Act Section 10(13A) — HRA exemption
 * IT Act Section 24(b) — Home loan interest ₹2,00,000 limit
 * All calculations in integer paise. New regime slabs FY 2026-27.
 */

import { useState, useCallback } from "react";
import { Save, ChevronDown, ChevronUp } from "lucide-react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { getClients } from "@/lib/data/clients";
import type { Client } from "@/lib/types";
import { useEffect } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface S80CItems {
  ppf: number;
  elss: number;
  lic: number;
  nsc: number;
  homeLoanPrincipal: number;
  tuitionFees: number;
  fd5yr: number;
}

interface S80DItems {
  selfFamilyPremium: number;
  selfFamilySenior: boolean;
  parentsPremium: number;
  parentsSenior: boolean;
}

interface DeductionState {
  grossIncomePaise: number;
  // 80C items (all in paise)
  s80c: S80CItems;
  nps80ccd: number;
  // 80D
  s80d: S80DItems;
  // 80G donations (paise, deduction %)
  donations: { description: string; amountPaise: number; deductionPct: 100 | 50 }[];
  // 80TTA/80TTB
  savingsInterestPaise: number;
  isSeniorCitizen: boolean;
  // HRA (Section 10(13A))
  basicSalaryPaise: number;
  hraReceivedPaise: number;
  rentPaidPaise: number;
  cityType: "metro" | "non-metro";
  // Section 24(b)
  homeLoanInterestPaise: number;
}

// ─── Limits (all in paise) ────────────────────────────────────────────────────
// IT Act Section 80C limit
const LIMIT_80C = 150000 * 100;
// IT Act Section 80CCD(1B) additional NPS limit
const LIMIT_NPS = 50000 * 100;
// IT Act Section 80D limits
const LIMIT_80D_SELF = 25000 * 100;
const LIMIT_80D_SELF_SENIOR = 50000 * 100;
const LIMIT_80D_PARENTS = 25000 * 100;
const LIMIT_80D_PARENTS_SENIOR = 50000 * 100;
// IT Act Section 80TTA
const LIMIT_80TTA = 10000 * 100;
// IT Act Section 80TTB (senior citizen)
const LIMIT_80TTB = 50000 * 100;
// IT Act Section 24(b) — self-occupied property
const LIMIT_24B = 200000 * 100;
// Standard deduction FY 2024-25 onwards
const STANDARD_DEDUCTION = 75000 * 100;

/** min(a, b) for integer paise */
function minPaise(a: number, b: number) { return a < b ? a : b; }

/** Integer paise to ₹ display */
function fmtP(paise: number): string {
  const rupees = Math.floor(Math.abs(paise) / 100);
  const p = Math.abs(paise) % 100;
  const s = rupees.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return (paise < 0 ? "-₹" : "₹") + s + "." + String(p).padStart(2, "0");
}

/** ₹ input → paise (integer) */
function rsToPaise(rs: string): number {
  const v = parseFloat(rs || "0");
  if (isNaN(v) || v < 0) return 0;
  return Math.round(v * 100);
}

/** paise → ₹ string for input */
function paiseToRsStr(p: number): string {
  return p === 0 ? "" : (p / 100).toFixed(2);
}

// ─── Compute HRA Exemption (IT Act Section 10(13A)) ──────────────────────────
function calcHraExemption(basic: number, hraReceived: number, rentPaid: number, metro: boolean): number {
  if (rentPaid === 0) return 0;
  // Exemption = min(actual HRA, 50%/40% of basic, rent paid - 10% of basic)
  const pct = metro ? 5000 : 4000; // basis points: 50% = 5000bp, 40% = 4000bp
  const halfBasic = Math.round((basic * pct) / 10000);
  const rentMinusTen = Math.max(0, rentPaid - Math.round((basic * 1000) / 10000));
  return minPaise(hraReceived, minPaise(halfBasic, rentMinusTen));
}

// ─── Compute Tax — New Regime FY 2026-27 ─────────────────────────────────────
// Slabs: 0-4L=0%, 4-8L=5%, 8-12L=10%, 12-16L=15%, 16-20L=20%, 20-24L=25%, 24L+=30%
// Rebate u/s 87A: no tax if income ≤ ₹12L
function calcNewRegimeTax(taxableIncomePaise: number): number {
  if (taxableIncomePaise <= 0) return 0;
  const inc = taxableIncomePaise; // paise
  const L = 100 * 100; // 1 lakh in paise = 10000 paise → 1L = 100*100 = 10000
  // Slabs in paise
  const SLAB = [
    { upto: 400 * L, rate: 0 },
    { upto: 800 * L, rate: 500 },
    { upto: 1200 * L, rate: 1000 },
    { upto: 1600 * L, rate: 1500 },
    { upto: 2000 * L, rate: 2000 },
    { upto: 2400 * L, rate: 2500 },
  ];
  let tax = 0;
  let prev = 0;
  for (const slab of SLAB) {
    if (inc <= prev) break;
    const slabIncome = minPaise(inc, slab.upto) - prev;
    tax += Math.round((slabIncome * slab.rate) / 10000);
    prev = slab.upto;
  }
  if (inc > 2400 * L) {
    tax += Math.round(((inc - 2400 * L) * 3000) / 10000);
  }
  // Rebate u/s 87A: no tax if taxable income ≤ ₹12L
  if (taxableIncomePaise <= 1200 * L) return 0;
  return tax;
}

// ─── Old Regime Tax (standard slabs with deductions) ─────────────────────────
function calcOldRegimeTax(taxableIncomePaise: number): number {
  if (taxableIncomePaise <= 0) return 0;
  const L = 100 * 100;
  // Standard slabs: 0-2.5L=0%, 2.5-5L=5%, 5-10L=20%, 10L+=30%
  let tax = 0;
  if (taxableIncomePaise > 250 * L) {
    tax += Math.round((minPaise(taxableIncomePaise, 500 * L) - 250 * L) * 500 / 10000);
  }
  if (taxableIncomePaise > 500 * L) {
    tax += Math.round((minPaise(taxableIncomePaise, 1000 * L) - 500 * L) * 2000 / 10000);
  }
  if (taxableIncomePaise > 1000 * L) {
    tax += Math.round((taxableIncomePaise - 1000 * L) * 3000 / 10000);
  }
  // Rebate u/s 87A for old regime: income ≤ 5L
  if (taxableIncomePaise <= 500 * L) return 0;
  return tax;
}

// ─── Input ────────────────────────────────────────────────────────────────────
function PaiseInput({ label, valuePaise, onChange, note }: {
  label: string; valuePaise: number; onChange: (p: number) => void; note?: string;
}) {
  const [raw, setRaw] = useState(paiseToRsStr(valuePaise));
  return (
    <div className="flex items-center justify-between gap-4 py-2 border-b border-[#F1F5F9] last:border-0">
      <div>
        <span className="text-sm text-[#334155]">{label}</span>
        {note && <span className="block text-xs text-[#94A3B8]">{note}</span>}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <span className="text-sm text-[#94A3B8]">₹</span>
        <input
          type="number" min="0" step="1" value={raw}
          onChange={e => { setRaw(e.target.value); onChange(rsToPaise(e.target.value)); }}
          className="w-28 border border-[#E2E8F0] rounded px-2 py-1 text-sm text-right outline-none focus:border-blue-500"
          placeholder="0"
        />
      </div>
    </div>
  );
}

function SectionCard({ title, children, eligible, limit, entered }: {
  title: string; children: React.ReactNode;
  eligible?: number; limit?: number; entered?: number;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="bg-white rounded-xl border border-[#E2E8F0] overflow-hidden">
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-[#F8FAFC]">
        <span className="font-medium text-[#0F172A] text-sm">{title}</span>
        <div className="flex items-center gap-3">
          {eligible !== undefined && (
            <span className="text-xs text-green-600 font-medium">Eligible: {fmtP(eligible)}</span>
          )}
          {open ? <ChevronUp size={15} className="text-[#94A3B8]" /> : <ChevronDown size={15} className="text-[#94A3B8]" />}
        </div>
      </button>
      {open && (
        <div className="px-4 pb-4">
          {(limit !== undefined || entered !== undefined) && (
            <div className="flex gap-4 text-xs text-[#64748B] mb-3">
              {limit !== undefined && <span>Limit: {fmtP(limit)}</span>}
              {entered !== undefined && <span>Entered: {fmtP(entered)}</span>}
              {eligible !== undefined && limit !== undefined && (
                <span className="text-blue-600">Remaining: {fmtP(Math.max(0, limit - eligible))}</span>
              )}
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

const DEFAULT_STATE: DeductionState = {
  grossIncomePaise: 0,
  s80c: { ppf: 0, elss: 0, lic: 0, nsc: 0, homeLoanPrincipal: 0, tuitionFees: 0, fd5yr: 0 },
  nps80ccd: 0,
  s80d: { selfFamilyPremium: 0, selfFamilySenior: false, parentsPremium: 0, parentsSenior: false },
  donations: [],
  savingsInterestPaise: 0,
  isSeniorCitizen: false,
  basicSalaryPaise: 0,
  hraReceivedPaise: 0,
  rentPaidPaise: 0,
  cityType: "metro",
  homeLoanInterestPaise: 0,
};

export default function DeductionsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [clientId, setClientId] = useState("");
  const [state, setState] = useState<DeductionState>(DEFAULT_STATE);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [notes, setNotes] = useState("");

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
  }, []);

  const upd = useCallback((patch: Partial<DeductionState>) => setState(s => ({ ...s, ...patch })), []);

  // ── Compute deductions ────────────────────────────────────────────────────

  // IT Act Section 80C
  const total80cRaw = Object.values(state.s80c).reduce((a, b) => a + b, 0);
  const elig80c = minPaise(total80cRaw, LIMIT_80C);

  // IT Act Section 80CCD(1B) — NPS additional
  const eligNps = minPaise(state.nps80ccd, LIMIT_NPS);

  // IT Act Section 80D
  const selfLimit = state.s80d.selfFamilySenior ? LIMIT_80D_SELF_SENIOR : LIMIT_80D_SELF;
  const parentsLimit = state.s80d.parentsSenior ? LIMIT_80D_PARENTS_SENIOR : LIMIT_80D_PARENTS;
  const elig80d = minPaise(state.s80d.selfFamilyPremium, selfLimit) + minPaise(state.s80d.parentsPremium, parentsLimit);

  // IT Act Section 80G — donations
  const elig80g = state.donations.reduce((sum, d) => {
    const pct = d.deductionPct === 100 ? 10000 : 5000;
    return sum + Math.round((d.amountPaise * pct) / 10000);
  }, 0);

  // IT Act Section 80TTA/80TTB
  const ttaLimit = state.isSeniorCitizen ? LIMIT_80TTB : LIMIT_80TTA;
  const eligTta = minPaise(state.savingsInterestPaise, ttaLimit);

  // IT Act Section 10(13A) — HRA
  const hraExemption = calcHraExemption(
    state.basicSalaryPaise, state.hraReceivedPaise, state.rentPaidPaise, state.cityType === "metro"
  );

  // IT Act Section 24(b) — home loan interest
  const elig24b = minPaise(state.homeLoanInterestPaise, LIMIT_24B);

  // Standard deduction (salary)
  const standardDed = STANDARD_DEDUCTION;

  const totalDeductions = elig80c + eligNps + elig80d + elig80g + eligTta + hraExemption + elig24b + standardDed;

  const netTaxableNew = Math.max(0, state.grossIncomePaise - standardDed - hraExemption);
  const netTaxableOld = Math.max(0, state.grossIncomePaise - totalDeductions);

  const newRegimeTax = calcNewRegimeTax(netTaxableNew);
  const oldRegimeTax = calcOldRegimeTax(netTaxableOld);

  const recommended = newRegimeTax <= oldRegimeTax ? "new" : "old";

  async function handleSave() {
    if (!clientId) return;
    setSaving(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const fy = "2026-27";
      const { error } = await sb.from("tax_planning_records").upsert({
        firm_id: firmId,
        client_id: clientId,
        fy,
        gross_income_paise: state.grossIncomePaise,
        total_deductions_paise: totalDeductions,
        new_regime_tax_paise: newRegimeTax,
        old_regime_tax_paise: oldRegimeTax,
        recommended_regime: recommended,
        notes,
        updated_at: new Date().toISOString(),
      }, { onConflict: "firm_id,client_id,fy" });
      if (error) throw new Error(error.message);
      setSaveMsg("Saved successfully");
      setTimeout(() => setSaveMsg(null), 3000);
    } catch (e) {
      setSaveMsg(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="p-4 md:p-6 max-w-4xl mx-auto space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg md:text-xl font-semibold text-[#0F172A]">Section 80 Deductions Planner</h1>
          <p className="text-sm text-[#64748B] mt-0.5">IT Act — Compute deductions and compare tax regimes</p>
        </div>
        <div className="flex items-center gap-2">
          <ClientLookup
            clients={clients}
            value={clientId}
            onChange={setClientId}
            ariaLabel="Client"
            placeholder="Select client…"
          />
        </div>
      </div>

      {/* Gross Income */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4">
        <PaiseInput label="Gross Total Income (₹)" valuePaise={state.grossIncomePaise}
          onChange={v => upd({ grossIncomePaise: v })}
          note="Before any deductions" />
        <div className="mt-3 flex items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-[#334155]">
            <input type="checkbox" checked={state.isSeniorCitizen}
              onChange={e => upd({ isSeniorCitizen: e.target.checked })} />
            Senior Citizen (60+)
          </label>
        </div>
      </div>

      {/* Standard Deduction */}
      <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 flex items-center justify-between">
        <span className="text-sm text-blue-800">Standard Deduction (FY 2024-25 onwards)</span>
        <span className="font-semibold text-blue-900">{fmtP(STANDARD_DEDUCTION)}</span>
      </div>

      {/* 80C */}
      <SectionCard title="Section 80C — Investments & Payments" eligible={elig80c} limit={LIMIT_80C} entered={total80cRaw}>
        {(Object.keys(state.s80c) as (keyof S80CItems)[]).map(k => {
          const labels: Record<keyof S80CItems, string> = {
            ppf: "PPF", elss: "ELSS", lic: "LIC Premium", nsc: "NSC",
            homeLoanPrincipal: "Home Loan Principal Repayment",
            tuitionFees: "Tuition Fees (2 children)", fd5yr: "5-Year Tax Saver FD",
          };
          return (
            <PaiseInput key={k} label={labels[k]} valuePaise={state.s80c[k]}
              onChange={v => upd({ s80c: { ...state.s80c, [k]: v } })} />
          );
        })}
      </SectionCard>

      {/* 80CCD(1B) NPS */}
      <SectionCard title="Section 80CCD(1B) — NPS (additional)" eligible={eligNps} limit={LIMIT_NPS} entered={state.nps80ccd}>
        <PaiseInput label="NPS Contribution (over 80C)" valuePaise={state.nps80ccd}
          onChange={v => upd({ nps80ccd: v })} />
      </SectionCard>

      {/* 80D */}
      <SectionCard title="Section 80D — Health Insurance" eligible={elig80d}>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-sm text-[#334155]">Self + Family Premium</span>
            <div className="flex items-center gap-3">
              <label className="flex items-center gap-1 text-xs text-[#64748B]">
                <input type="checkbox" checked={state.s80d.selfFamilySenior}
                  onChange={e => upd({ s80d: { ...state.s80d, selfFamilySenior: e.target.checked } })} />
                Senior (₹50k limit)
              </label>
            </div>
          </div>
          <PaiseInput label="Premium Amount" valuePaise={state.s80d.selfFamilyPremium}
            onChange={v => upd({ s80d: { ...state.s80d, selfFamilyPremium: v } })}
            note={`Limit: ${fmtP(selfLimit)}`} />
          <div className="flex items-center justify-between">
            <span className="text-sm text-[#334155]">Parents Premium</span>
            <label className="flex items-center gap-1 text-xs text-[#64748B]">
              <input type="checkbox" checked={state.s80d.parentsSenior}
                onChange={e => upd({ s80d: { ...state.s80d, parentsSenior: e.target.checked } })} />
              Senior parents (₹50k limit)
            </label>
          </div>
          <PaiseInput label="Parents Premium Amount" valuePaise={state.s80d.parentsPremium}
            onChange={v => upd({ s80d: { ...state.s80d, parentsPremium: v } })}
            note={`Limit: ${fmtP(parentsLimit)}`} />
        </div>
      </SectionCard>

      {/* 80G */}
      <SectionCard title="Section 80G — Donations" eligible={elig80g}>
        <div className="space-y-2">
          {state.donations.map((d, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input type="text" value={d.description}
                onChange={e => { const ds = [...state.donations]; ds[i].description = e.target.value; upd({ donations: ds }); }}
                placeholder="Fund/Trust name"
                className="flex-1 border border-[#E2E8F0] rounded px-2 py-1 text-sm outline-none focus:border-blue-500" />
              <input type="number" min="0" value={d.amountPaise / 100}
                onChange={e => { const ds = [...state.donations]; ds[i].amountPaise = Math.round(parseFloat(e.target.value || "0") * 100); upd({ donations: ds }); }}
                placeholder="₹"
                className="w-24 border border-[#E2E8F0] rounded px-2 py-1 text-sm outline-none focus:border-blue-500" />
              <select value={d.deductionPct}
                onChange={e => { const ds = [...state.donations]; ds[i].deductionPct = parseInt(e.target.value) as 100 | 50; upd({ donations: ds }); }}
                className="border border-[#E2E8F0] rounded px-2 py-1 text-sm outline-none focus:border-blue-500">
                <option value={100}>100%</option>
                <option value={50}>50%</option>
              </select>
              <button onClick={() => upd({ donations: state.donations.filter((_, j) => j !== i) })}
                className="text-red-600 hover:text-red-600 text-xs">✕</button>
            </div>
          ))}
          <button onClick={() => upd({ donations: [...state.donations, { description: "", amountPaise: 0, deductionPct: 100 }] })}
            className="text-xs text-blue-600 hover:underline">+ Add Donation</button>
        </div>
      </SectionCard>

      {/* 80TTA / 80TTB */}
      <SectionCard title={state.isSeniorCitizen ? "Section 80TTB — Interest Income (Senior)" : "Section 80TTA — Savings Interest"}
        eligible={eligTta} limit={ttaLimit} entered={state.savingsInterestPaise}>
        <PaiseInput label="Savings Account Interest" valuePaise={state.savingsInterestPaise}
          onChange={v => upd({ savingsInterestPaise: v })} />
      </SectionCard>

      {/* HRA — IT Act Section 10(13A) */}
      <SectionCard title="HRA Exemption — Section 10(13A)" eligible={hraExemption}>
        <div className="space-y-1">
          <PaiseInput label="Basic Salary" valuePaise={state.basicSalaryPaise}
            onChange={v => upd({ basicSalaryPaise: v })} />
          <PaiseInput label="HRA Received from Employer" valuePaise={state.hraReceivedPaise}
            onChange={v => upd({ hraReceivedPaise: v })} />
          <PaiseInput label="Actual Rent Paid" valuePaise={state.rentPaidPaise}
            onChange={v => upd({ rentPaidPaise: v })} />
          <div className="py-2 flex items-center gap-4">
            <span className="text-sm text-[#334155]">City Type</span>
            <label className="flex items-center gap-1 text-sm text-[#475569]">
              <input type="radio" name="city" value="metro" checked={state.cityType === "metro"}
                onChange={() => upd({ cityType: "metro" })} /> Metro (50%)
            </label>
            <label className="flex items-center gap-1 text-sm text-[#475569]">
              <input type="radio" name="city" value="non-metro" checked={state.cityType === "non-metro"}
                onChange={() => upd({ cityType: "non-metro" })} /> Non-Metro (40%)
            </label>
          </div>
        </div>
      </SectionCard>

      {/* Section 24(b) */}
      <SectionCard title="Section 24(b) — Home Loan Interest (Self-Occupied)" eligible={elig24b} limit={LIMIT_24B} entered={state.homeLoanInterestPaise}>
        <PaiseInput label="Home Loan Interest Paid" valuePaise={state.homeLoanInterestPaise}
          onChange={v => upd({ homeLoanInterestPaise: v })} />
      </SectionCard>

      {/* Summary */}
      <div className="bg-white rounded-xl border border-[#E2E8F0] p-4 space-y-3">
        <h2 className="font-semibold text-[#0F172A] text-sm">Tax Summary</h2>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-[#475569]">Gross Total Income</span><span className="font-mono">{fmtP(state.grossIncomePaise)}</span></div>
          <div className="flex justify-between"><span className="text-[#475569]">Total Deductions (Old Regime)</span><span className="font-mono text-green-600">— {fmtP(totalDeductions)}</span></div>
          <div className="flex justify-between border-t pt-2"><span className="font-medium">Net Taxable Income (Old Regime)</span><span className="font-mono font-semibold">{fmtP(netTaxableOld)}</span></div>
          <div className="flex justify-between border-t pt-2"><span className="font-medium">Net Taxable Income (New Regime)</span><span className="font-mono font-semibold">{fmtP(netTaxableNew)}</span></div>
        </div>

        <div className="grid grid-cols-2 gap-3 mt-3">
          <div className={`rounded-lg p-3 border-2 ${recommended === "new" ? "border-green-500 bg-green-50" : "border-[#E2E8F0] bg-[#F8FAFC]"}`}>
            <p className="text-xs font-medium text-[#475569] mb-1">New Regime Tax {recommended === "new" && "✓ Recommended"}</p>
            <p className="text-xl font-bold font-mono text-[#0F172A]">{fmtP(newRegimeTax)}</p>
            <p className="text-xs text-[#64748B] mt-1">Taxable: {fmtP(netTaxableNew)}</p>
            {netTaxableNew <= 1200 * 100 * 100 && <p className="text-xs text-green-600 mt-1">Rebate u/s 87A — NIL tax</p>}
          </div>
          <div className={`rounded-lg p-3 border-2 ${recommended === "old" ? "border-green-500 bg-green-50" : "border-[#E2E8F0] bg-[#F8FAFC]"}`}>
            <p className="text-xs font-medium text-[#475569] mb-1">Old Regime Tax {recommended === "old" && "✓ Recommended"}</p>
            <p className="text-xl font-bold font-mono text-[#0F172A]">{fmtP(oldRegimeTax)}</p>
            <p className="text-xs text-[#64748B] mt-1">Taxable: {fmtP(netTaxableOld)}</p>
          </div>
        </div>

        <div className={`rounded-lg px-4 py-3 text-sm font-medium ${recommended === "new" ? "bg-green-100 text-green-800" : "bg-blue-100 text-blue-800"}`}>
          Recommendation: <strong>{recommended === "new" ? "New Regime" : "Old Regime"}</strong> saves {fmtP(Math.abs(newRegimeTax - oldRegimeTax))} more in taxes.
        </div>

        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Notes</label>
          <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
            placeholder="Planning notes…" />
        </div>

        <button onClick={handleSave} disabled={saving || !clientId}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-60">
          <Save size={15} /> {saving ? "Saving…" : "Save for Client"}
        </button>
        {saveMsg && <p className="text-xs text-green-600">{saveMsg}</p>}
      </div>
    </div>
  );
}
