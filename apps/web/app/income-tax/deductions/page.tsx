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
 *
 * All tax computation (slabs, rebate, surcharge, cess, deduction eligibility,
 * HRA exemption) happens server-side via computeITR() → POST
 * /api/income-tax/compute (domain/income_tax/itr_engine.py), the FY-versioned
 * single source of truth also used by ITR filing. This page previously
 * duplicated that engine locally with its own slab tables, which had drifted
 * out of sync (audit finding F18: a paise/rupee scaling bug made every slab
 * boundary 10x too low) and incorrectly applied HRA exemption to the new
 * regime's taxable income (Section 10(13A) is old-regime-only under Section
 * 115BAC). CLAUDE.md: zero business logic in the frontend.
 */

import { paiseFromRupeeInput } from "@/lib/money/rupeeInput";
import { useState, useCallback, useEffect } from "react";
import { Save, ChevronDown, ChevronUp } from "lucide-react";
import { ClientLookup } from "@/components/lookups/ClientLookup";
import { getClients } from "@/lib/data/clients";
import { computeITR, saveTaxPlanningRecord, type ITRComputeResult } from "@/lib/data/income-tax";
import type { Client } from "@/lib/types";

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
  // Section 80CCD(2) — employer NPS contribution. Unlike every other
  // Chapter VI-A deduction on this page, available under BOTH regimes
  // (see itr_engine.py's LIMIT_80CCD2_* constants for the cap split).
  employerNps80ccd2: number;
  isGovernmentEmployee: boolean;
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

// ─── Display-only statutory limits (all in paise) ────────────────────────────
// Fixed reference figures for the "Limit:"/"Remaining:" UI labels only — never
// used to compute eligibility or tax. The actual eligible/capped amount for
// each section comes from computeITR()'s response (old-regime deductions),
// which is the only place these limits are applied.
const LIMIT_80C = 150000 * 100;
const LIMIT_NPS = 50000 * 100;
// Section 80CCD(2) cap is a % of salary, not a fixed amount — these
// percentages are display-label-only (mirrors itr_engine.py's LIMIT_80CCD2_*
// constants; see that module for the government/other split and its
// PENDING STATUTORY VERIFICATION note re: the new-regime-only enhancement
// for non-government employees).
const LIMIT_80CCD2_OTHER_PCT = 10;
const LIMIT_80CCD2_GOVT_PCT = 14;
const LIMIT_80D_SELF = 25000 * 100;
const LIMIT_80D_SELF_SENIOR = 50000 * 100;
const LIMIT_80D_PARENTS = 25000 * 100;
const LIMIT_80D_PARENTS_SENIOR = 50000 * 100;
const LIMIT_80TTA = 10000 * 100;
const LIMIT_80TTB = 50000 * 100;
const LIMIT_24B = 200000 * 100;

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
  employerNps80ccd2: 0,
  isGovernmentEmployee: false,
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

  const [oldResult, setOldResult] = useState<ITRComputeResult | null>(null);
  const [newResult, setNewResult] = useState<ITRComputeResult | null>(null);
  const [computing, setComputing] = useState(false);
  const [computeError, setComputeError] = useState<string | null>(null);

  useEffect(() => {
    getClients().then(c => { setClients(c); if (c.length > 0) setClientId(c[0].id); }).catch(() => {});
  }, []);

  const upd = useCallback((patch: Partial<DeductionState>) => setState(s => ({ ...s, ...patch })), []);

  // Raw entered totals — plain sums of user input for display, not eligibility decisions.
  const total80cRaw = Object.values(state.s80c).reduce((a, b) => a + b, 0);

  // ── Server-side computation ───────────────────────────────────────────────
  // Two calls (old/new regime) since /api/income-tax/compute takes one regime
  // at a time — same pattern as clients/[id]/tax/computation/page.tsx.
  // Debounced: `state` changes on every keystroke in every field (including
  // fields like a donation's description that don't affect tax at all) —
  // without the delay each character fires two RBAC-gated backend calls.
  useEffect(() => {
    let cancelled = false;

    const baseReq = {
      gross_salary_paise: state.grossIncomePaise,
      is_senior_citizen: state.isSeniorCitizen,
      s80c: {
        ppf_paise: state.s80c.ppf,
        elss_paise: state.s80c.elss,
        lic_paise: state.s80c.lic,
        nsc_paise: state.s80c.nsc,
        home_loan_principal_paise: state.s80c.homeLoanPrincipal,
        tuition_fees_paise: state.s80c.tuitionFees,
        fd_5yr_paise: state.s80c.fd5yr,
      },
      nps_80ccd1b_paise: state.nps80ccd,
      employer_nps_80ccd2_paise: state.employerNps80ccd2,
      is_government_employee: state.isGovernmentEmployee,
      s80d: {
        self_family_premium_paise: state.s80d.selfFamilyPremium,
        self_family_is_senior: state.s80d.selfFamilySenior,
        parents_premium_paise: state.s80d.parentsPremium,
        parents_is_senior: state.s80d.parentsSenior,
      },
      donations_80g: state.donations.map(d => ({
        description: d.description,
        amount_paise: d.amountPaise,
        deduction_pct: d.deductionPct,
      })),
      savings_interest_80tta_paise: state.savingsInterestPaise,
      hra: {
        basic_salary_paise: state.basicSalaryPaise,
        hra_received_paise: state.hraReceivedPaise,
        rent_paid_paise: state.rentPaidPaise,
        is_metro: state.cityType === "metro",
      },
      home_loan_interest_24b_paise: state.homeLoanInterestPaise,
    };

    const timer = setTimeout(() => {
      if (cancelled) return;
      setComputing(true);
      setComputeError(null);
      Promise.all([
        computeITR({ ...baseReq, use_new_regime: false }),
        computeITR({ ...baseReq, use_new_regime: true }),
      ]).then(([oldR, newR]) => {
        if (cancelled) return;
        setOldResult(oldR);
        setNewResult(newR);
      }).catch(e => {
        if (!cancelled) setComputeError(e instanceof Error ? e.message : "Computation failed");
      }).finally(() => {
        if (!cancelled) setComputing(false);
      });
    }, 400);

    return () => { cancelled = true; clearTimeout(timer); };
  }, [state]);

  // Old regime is the only response with non-zero Chapter VI-A deductions —
  // the new regime disallows all of these except the standard deduction AND
  // Section 80CCD(2) (see itr_engine.py's regime-conditional deduction block).
  const elig80c = oldResult?.deductions.s80c_paise ?? 0;
  const eligNps = oldResult?.deductions.s80ccd_paise ?? 0;
  // 80CCD(2) is identical in both regime responses (survives 115BAC) — read
  // from newResult so it's populated even before an old-regime call resolves.
  const eligCcd2 = newResult?.deductions.s80ccd2_paise ?? 0;
  const elig80d = oldResult?.deductions.s80d_paise ?? 0;
  const elig80g = oldResult?.deductions.s80g_paise ?? 0;
  const eligTta = oldResult?.deductions.s80tta_paise ?? 0;
  const hraExemption = oldResult?.deductions.hra_paise ?? 0;
  const elig24b = oldResult?.deductions.s24b_paise ?? 0;
  const standardDed = newResult?.income.standard_deduction_paise ?? 0;
  const totalDeductions = oldResult?.income.total_deductions_paise ?? 0;

  const netTaxableNew = newResult?.income.taxable_income_paise ?? 0;
  const netTaxableOld = oldResult?.income.taxable_income_paise ?? 0;
  const newRegimeTax = newResult?.tax.total_tax_paise ?? 0;
  const oldRegimeTax = oldResult?.tax.total_tax_paise ?? 0;
  const fy = newResult?.fy || oldResult?.fy || "";
  const ratesVerified = (newResult?.rates_verified ?? true) && (oldResult?.rates_verified ?? true);

  const recommended = newRegimeTax <= oldRegimeTax ? "new" : "old";

  const selfLimit = state.s80d.selfFamilySenior ? LIMIT_80D_SELF_SENIOR : LIMIT_80D_SELF;
  const parentsLimit = state.s80d.parentsSenior ? LIMIT_80D_PARENTS_SENIOR : LIMIT_80D_PARENTS;
  const ttaLimit = state.isSeniorCitizen ? LIMIT_80TTB : LIMIT_80TTA;

  async function handleSave() {
    if (!clientId || !oldResult || !newResult) return;
    setSaving(true);
    try {
      await saveTaxPlanningRecord({
        client_id: clientId,
        financial_year: fy,
        gross_income_paise: state.grossIncomePaise,
        ppf_paise: state.s80c.ppf,
        elss_paise: state.s80c.elss,
        lic_paise: state.s80c.lic,
        nsc_paise: state.s80c.nsc,
        home_loan_principal_paise: state.s80c.homeLoanPrincipal,
        tuition_fees_paise: state.s80c.tuitionFees,
        other_80c_paise: state.s80c.fd5yr,
        hra_paise: hraExemption,
        nps_80ccd_paise: state.nps80ccd,
        health_insurance_80d_paise: state.s80d.selfFamilyPremium + state.s80d.parentsPremium,
        home_loan_interest_24b_paise: state.homeLoanInterestPaise,
        regime: recommended,
        tax_paise: recommended === "new" ? newRegimeTax : oldRegimeTax,
      });
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

      {!ratesVerified && fy && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800">
          FY {fy} statutory rates are carried forward from the last verified year, pending confirmation
          against the official Finance Act / CBDT circulars for {fy}. Do not rely on these figures for
          filing until verified.
        </div>
      )}

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
        <span className="text-sm text-blue-800">Standard Deduction (New Regime, FY {fy || "—"})</span>
        <span className="font-semibold text-blue-900">{fmtP(standardDed)}</span>
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

      {/* 80CCD(2) Employer NPS — available under BOTH regimes */}
      <SectionCard
        title="Section 80CCD(2) — Employer NPS (both regimes)"
        eligible={eligCcd2} entered={state.employerNps80ccd2}
      >
        <PaiseInput label="Employer's NPS Contribution" valuePaise={state.employerNps80ccd2}
          onChange={v => upd({ employerNps80ccd2: v })}
          note={`Capped at ${state.isGovernmentEmployee ? LIMIT_80CCD2_GOVT_PCT : LIMIT_80CCD2_OTHER_PCT}% of salary`} />
        <div className="flex items-center justify-between py-2">
          <span className="text-sm text-[#334155]">Government Employee</span>
          <input type="checkbox" checked={state.isGovernmentEmployee}
            onChange={e => upd({ isGovernmentEmployee: e.target.checked })} />
        </div>
        <p className="text-xs text-[#94A3B8] mt-1">
          Unlike every other deduction on this page, Section 80CCD(2) reduces tax under
          both the old and new regime.
        </p>
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
                onChange={e => {
                  // A s.80G donation deducted at 100% or 50% of a mis-read
                  // amount is a deduction claimed on a number nobody entered.
                  // Keeping the previous value is right for a live field: the
                  // CA is mid-keystroke, not submitting.
                  const paise = paiseFromRupeeInput(e.target.value || "0");
                  if (paise === null) return;
                  const ds = [...state.donations]; ds[i].amountPaise = paise; upd({ donations: ds });
                }}
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
      <SectionCard title="HRA Exemption — Section 10(13A) (Old Regime Only)" eligible={hraExemption}>
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
        {computeError && <p className="text-xs text-red-600">{computeError}</p>}
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
            {newResult && newRegimeTax === 0 && netTaxableNew > 0 && <p className="text-xs text-green-600 mt-1">Rebate u/s 87A — NIL tax</p>}
          </div>
          <div className={`rounded-lg p-3 border-2 ${recommended === "old" ? "border-green-500 bg-green-50" : "border-[#E2E8F0] bg-[#F8FAFC]"}`}>
            <p className="text-xs font-medium text-[#475569] mb-1">Old Regime Tax {recommended === "old" && "✓ Recommended"}</p>
            <p className="text-xl font-bold font-mono text-[#0F172A]">{fmtP(oldRegimeTax)}</p>
            <p className="text-xs text-[#64748B] mt-1">Taxable: {fmtP(netTaxableOld)}</p>
          </div>
        </div>

        <div className={`rounded-lg px-4 py-3 text-sm font-medium ${recommended === "new" ? "bg-green-100 text-green-800" : "bg-blue-100 text-blue-800"}`}>
          {computing
            ? "Computing…"
            : <>Recommendation: <strong>{recommended === "new" ? "New Regime" : "Old Regime"}</strong> saves {fmtP(Math.abs(newRegimeTax - oldRegimeTax))} more in taxes.</>}
        </div>

        <div>
          <label className="text-xs font-medium text-[#334155] block mb-1">Notes</label>
          <textarea rows={2} value={notes} onChange={e => setNotes(e.target.value)}
            className="w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm outline-none focus:border-blue-500 resize-none"
            placeholder="Planning notes…" />
        </div>

        <button onClick={handleSave} disabled={saving || !clientId || computing || !oldResult || !newResult}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-60">
          <Save size={15} /> {saving ? "Saving…" : "Save for Client"}
        </button>
        {saveMsg && <p className="text-xs text-green-600">{saveMsg}</p>}
      </div>
    </div>
  );
}
