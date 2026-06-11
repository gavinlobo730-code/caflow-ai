"use client";

/**
 * Loan & Fixed Deposit Tracker
 *
 * Loan interest calculations follow standard reducing balance method.
 * EMI formula: P × r × (1+r)^n / ((1+r)^n - 1) where r = monthly interest rate
 * All monetary values stored as integer paise — never floating point.
 *
 * TDS on FD interest per IT Act Section 194A — threshold ₹40,000 p.a.
 * (₹50,000 for senior citizens). TDS rate: 10% (20% if PAN not furnished).
 */

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  Plus,
  X,
  AlertTriangle,
  Calculator,
  IndianRupee,
  TrendingDown,
  Landmark,
  Bell,
} from "lucide-react";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { formatPaise } from "@/lib/services/formatting";

// ─── Types ────────────────────────────────────────────────────────────────────

type LoanType =
  | "term_loan"
  | "overdraft"
  | "cc"
  | "home_loan"
  | "vehicle_loan"
  | "personal_loan"
  | "other";

type LoanStatus = "active" | "closed" | "overdue";
type FDStatus = "active" | "matured" | "broken";

interface Client {
  id: string;
  name: string;
}

interface Loan {
  id: string;
  firm_id: string;
  client_id: string;
  loan_type: LoanType;
  lender_name: string;
  account_number: string | null;
  principal_paise: number;
  outstanding_paise: number;
  interest_rate_percent: number;
  emi_paise: number | null;
  disbursement_date: string;
  maturity_date: string | null;
  status: LoanStatus;
  notes: string | null;
  created_at: string;
  clients?: { name: string };
}

interface FixedDeposit {
  id: string;
  firm_id: string;
  client_id: string;
  bank_name: string;
  fd_number: string | null;
  principal_paise: number;
  interest_rate_percent: number;
  start_date: string;
  maturity_date: string;
  maturity_amount_paise: number;
  is_auto_renewed: boolean;
  tds_applicable: boolean;
  status: FDStatus;
  notes: string | null;
  created_at: string;
  clients?: { name: string };
}

// ─── Constants ────────────────────────────────────────────────────────────────

const LOAN_TYPE_LABELS: Record<LoanType, string> = {
  term_loan: "Term Loan",
  overdraft: "Overdraft",
  cc: "Cash Credit",
  home_loan: "Home Loan",
  vehicle_loan: "Vehicle Loan",
  personal_loan: "Personal Loan",
  other: "Other",
};

const TODAY_ISO = new Date().toISOString().slice(0, 10);

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * EMI formula: P × r × (1+r)^n / ((1+r)^n - 1)
 * where r = monthly interest rate (annual rate / 12 / 100)
 * Returns EMI in paise (integer arithmetic).
 */
function calculateEMIPaise(
  principalPaise: number,
  annualRatePercent: number,
  tenureMonths: number
): number {
  if (tenureMonths <= 0 || annualRatePercent <= 0) return 0;
  // Use integer-safe arithmetic: work in paise throughout
  const r = annualRatePercent / 12 / 100;
  const pow = Math.pow(1 + r, tenureMonths);
  const emi = (principalPaise * r * pow) / (pow - 1);
  return Math.round(emi); // integer paise
}

/**
 * Compound interest maturity amount for FD.
 * Formula: P × (1 + r/100)^(days/365) — annual compounding
 * Returns maturity amount in paise (integer arithmetic).
 * Per standard bank FD calculation practice.
 */
function calculateFDMaturityPaise(
  principalPaise: number,
  annualRatePercent: number,
  startDate: string,
  maturityDate: string
): number {
  if (!startDate || !maturityDate) return principalPaise;
  const days =
    (new Date(maturityDate).getTime() - new Date(startDate).getTime()) /
    (24 * 60 * 60 * 1000);
  if (days <= 0) return principalPaise;
  const factor = Math.pow(1 + annualRatePercent / 100, days / 365);
  return Math.round(principalPaise * factor); // integer paise
}

function daysToDate(isoDate: string): number {
  const target = new Date(isoDate).getTime();
  const now = new Date(TODAY_ISO).getTime();
  return Math.ceil((target - now) / (24 * 60 * 60 * 1000));
}

function formatDate(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

const inputCls =
  "w-full border border-[#E2E8F0] rounded-lg px-3 py-2 text-sm text-[#0F172A] focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white";

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function LoansAndFDPage() {
  const [tab, setTab] = useState<"loans" | "fd">("loans");
  const [clients, setClients] = useState<Client[]>([]);
  const [loans, setLoans] = useState<Loan[]>([]);
  const [fds, setFDs] = useState<FixedDeposit[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Add Loan modal
  const [showAddLoan, setShowAddLoan] = useState(false);
  const [loanForm, setLoanForm] = useState({
    client_id: "",
    loan_type: "term_loan" as LoanType,
    lender_name: "",
    account_number: "",
    principal: "",
    outstanding: "",
    interest_rate: "",
    emi: "",
    disbursement_date: TODAY_ISO,
    maturity_date: "",
    notes: "",
  });
  const [loanError, setLoanError] = useState<string | null>(null);
  const [loanSaving, setLoanSaving] = useState(false);

  // Add FD modal
  const [showAddFD, setShowAddFD] = useState(false);
  const [fdForm, setFDForm] = useState({
    client_id: "",
    bank_name: "",
    fd_number: "",
    principal: "",
    interest_rate: "",
    start_date: TODAY_ISO,
    maturity_date: "",
    is_auto_renewed: false,
    tds_applicable: true,
    notes: "",
  });
  const [fdError, setFDError] = useState<string | null>(null);
  const [fdSaving, setFDSaving] = useState(false);

  // EMI Calculator
  const [calcPrincipal, setCalcPrincipal] = useState("");
  const [calcRate, setCalcRate] = useState("");
  const [calcTenure, setCalcTenure] = useState("");
  const [calcResult, setCalcResult] = useState<number | null>(null);

  // Load data
  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const [
        { data: clientsData },
        { data: loansData },
        { data: fdsData },
      ] = await Promise.all([
        sb.from("clients").select("id, name").eq("firm_id", firmId).order("name"),
        sb
          .from("loans")
          .select("*, clients(name)")
          .eq("firm_id", firmId)
          .order("created_at", { ascending: false }),
        sb
          .from("fixed_deposits")
          .select("*, clients(name)")
          .eq("firm_id", firmId)
          .order("created_at", { ascending: false }),
      ]);
      setClients((clientsData ?? []) as Client[]);
      setLoans((loansData ?? []) as Loan[]);
      setFDs((fdsData ?? []) as FixedDeposit[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // ─── Add Loan ──────────────────────────────────────────────────────────────

  async function handleAddLoan() {
    setLoanError(null);
    if (!loanForm.client_id) { setLoanError("Select a client"); return; }
    if (!loanForm.lender_name.trim()) { setLoanError("Lender name is required"); return; }
    const principal = Math.round(parseFloat(loanForm.principal) * 100);
    const outstanding = Math.round(parseFloat(loanForm.outstanding) * 100);
    const rate = parseFloat(loanForm.interest_rate);
    if (isNaN(principal) || principal <= 0) { setLoanError("Enter a valid principal amount"); return; }
    if (isNaN(outstanding) || outstanding < 0) { setLoanError("Enter a valid outstanding amount"); return; }
    if (isNaN(rate) || rate <= 0) { setLoanError("Enter a valid interest rate"); return; }
    if (!loanForm.disbursement_date) { setLoanError("Disbursement date is required"); return; }

    setLoanSaving(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const emiPaise = loanForm.emi ? Math.round(parseFloat(loanForm.emi) * 100) : null;
      const { error: insertErr } = await sb.from("loans").insert({
        firm_id: firmId,
        client_id: loanForm.client_id,
        loan_type: loanForm.loan_type,
        lender_name: loanForm.lender_name.trim(),
        account_number: loanForm.account_number.trim() || null,
        principal_paise: principal,
        outstanding_paise: outstanding,
        interest_rate_percent: rate,
        emi_paise: emiPaise,
        disbursement_date: loanForm.disbursement_date,
        maturity_date: loanForm.maturity_date || null,
        status: "active",
        notes: loanForm.notes.trim() || null,
      });
      if (insertErr) throw new Error(insertErr.message);
      setShowAddLoan(false);
      resetLoanForm();
      await loadData();
    } catch (err) {
      setLoanError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setLoanSaving(false);
    }
  }

  function resetLoanForm() {
    setLoanForm({
      client_id: "",
      loan_type: "term_loan",
      lender_name: "",
      account_number: "",
      principal: "",
      outstanding: "",
      interest_rate: "",
      emi: "",
      disbursement_date: TODAY_ISO,
      maturity_date: "",
      notes: "",
    });
    setLoanError(null);
  }

  // ─── Add FD ────────────────────────────────────────────────────────────────

  async function handleAddFD() {
    setFDError(null);
    if (!fdForm.client_id) { setFDError("Select a client"); return; }
    if (!fdForm.bank_name.trim()) { setFDError("Bank name is required"); return; }
    const principal = Math.round(parseFloat(fdForm.principal) * 100);
    const rate = parseFloat(fdForm.interest_rate);
    if (isNaN(principal) || principal <= 0) { setFDError("Enter a valid principal amount"); return; }
    if (isNaN(rate) || rate <= 0) { setFDError("Enter a valid interest rate"); return; }
    if (!fdForm.start_date) { setFDError("Start date is required"); return; }
    if (!fdForm.maturity_date) { setFDError("Maturity date is required"); return; }
    if (fdForm.maturity_date <= fdForm.start_date) { setFDError("Maturity date must be after start date"); return; }

    const maturityPaise = calculateFDMaturityPaise(principal, rate, fdForm.start_date, fdForm.maturity_date);

    setFDSaving(true);
    try {
      const firmId = await getFirmId();
      const sb = getSupabaseClient();
      const { error: insertErr } = await sb.from("fixed_deposits").insert({
        firm_id: firmId,
        client_id: fdForm.client_id,
        bank_name: fdForm.bank_name.trim(),
        fd_number: fdForm.fd_number.trim() || null,
        principal_paise: principal,
        interest_rate_percent: rate,
        start_date: fdForm.start_date,
        maturity_date: fdForm.maturity_date,
        maturity_amount_paise: maturityPaise,
        is_auto_renewed: fdForm.is_auto_renewed,
        // TDS on FD interest per IT Act Section 194A — threshold ₹40,000 p.a. (₹50,000 for senior citizens)
        tds_applicable: fdForm.tds_applicable,
        status: "active",
        notes: fdForm.notes.trim() || null,
      });
      if (insertErr) throw new Error(insertErr.message);
      setShowAddFD(false);
      resetFDForm();
      await loadData();
    } catch (err) {
      setFDError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setFDSaving(false);
    }
  }

  function resetFDForm() {
    setFDForm({
      client_id: "",
      bank_name: "",
      fd_number: "",
      principal: "",
      interest_rate: "",
      start_date: TODAY_ISO,
      maturity_date: "",
      is_auto_renewed: false,
      tds_applicable: true,
      notes: "",
    });
    setFDError(null);
  }

  // ─── EMI Calculator ────────────────────────────────────────────────────────

  function runEMICalc() {
    const p = Math.round(parseFloat(calcPrincipal) * 100);
    const r = parseFloat(calcRate);
    const n = parseInt(calcTenure, 10);
    if (!isNaN(p) && !isNaN(r) && !isNaN(n) && p > 0 && r > 0 && n > 0) {
      setCalcResult(calculateEMIPaise(p, r, n));
    }
  }

  // ─── Loan summary stats ────────────────────────────────────────────────────

  const totalLoans = loans.length;
  const totalOutstandingPaise = loans
    .filter((l) => l.status !== "closed")
    .reduce((s, l) => s + l.outstanding_paise, 0);
  const totalEMIPaise = loans
    .filter((l) => l.status === "active" && l.emi_paise)
    .reduce((s, l) => s + (l.emi_paise ?? 0), 0);
  const overdueCount = loans.filter((l) => l.status === "overdue").length;

  // ─── FD summary stats ─────────────────────────────────────────────────────

  const totalFDs = fds.length;
  const totalFDPrincipalPaise = fds
    .filter((f) => f.status === "active")
    .reduce((s, f) => s + f.principal_paise, 0);
  const totalFDMaturityPaise = fds
    .filter((f) => f.status === "active")
    .reduce((s, f) => s + f.maturity_amount_paise, 0);
  const maturingThisMonthCount = fds.filter((f) => {
    if (f.status !== "active") return false;
    const days = daysToDate(f.maturity_date);
    return days >= 0 && days <= 30;
  }).length;

  // ─── Derived FD form maturity ──────────────────────────────────────────────

  const fdPreviewMaturityPaise =
    fdForm.principal && fdForm.interest_rate && fdForm.start_date && fdForm.maturity_date
      ? calculateFDMaturityPaise(
          Math.round(parseFloat(fdForm.principal) * 100),
          parseFloat(fdForm.interest_rate),
          fdForm.start_date,
          fdForm.maturity_date
        )
      : null;

  const maturingSoonFDs = fds.filter((f) => {
    if (f.status !== "active") return false;
    const days = daysToDate(f.maturity_date);
    return days >= 0 && days <= 30;
  });

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          <Link href="/accounting" className="text-[#94A3B8] hover:text-[#475569] mt-0.5">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-xl font-semibold text-[#0F172A]">Loans & Fixed Deposits</h1>
            <p className="text-sm text-[#64748B] mt-0.5">Track client borrowings and FD investments</p>
          </div>
        </div>
        <button
          onClick={() => tab === "loans" ? setShowAddLoan(true) : setShowAddFD(true)}
          className="flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          <Plus className="w-4 h-4" />
          {tab === "loans" ? "Add Loan" : "Add FD"}
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 flex gap-2 text-sm text-red-700">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-[#F1F5F9] rounded-xl p-1 w-fit">
        <button
          onClick={() => setTab("loans")}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${tab === "loans" ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}
        >
          Loans
        </button>
        <button
          onClick={() => setTab("fd")}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${tab === "fd" ? "bg-white text-[#0F172A] shadow-sm" : "text-[#64748B] hover:text-[#334155]"}`}
        >
          Fixed Deposits
        </button>
      </div>

      {/* ================================================================== */}
      {/* LOANS TAB                                                            */}
      {/* ================================================================== */}
      {tab === "loans" && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard
              icon={<TrendingDown className="w-4 h-4 text-blue-600" />}
              iconBg="bg-blue-50"
              label="Total Loans"
              value={loading ? "…" : String(totalLoans)}
              sub="accounts tracked"
            />
            <SummaryCard
              icon={<IndianRupee className="w-4 h-4 text-red-600" />}
              iconBg="bg-red-50"
              label="Total Outstanding"
              value={loading ? "…" : formatPaise(totalOutstandingPaise)}
              sub="across active loans"
            />
            <SummaryCard
              icon={<Calculator className="w-4 h-4 text-purple-600" />}
              iconBg="bg-purple-50"
              label="Total EMI/Month"
              value={loading ? "…" : formatPaise(totalEMIPaise)}
              sub="combined monthly EMI"
            />
            <SummaryCard
              icon={<AlertTriangle className="w-4 h-4 text-amber-600" />}
              iconBg="bg-amber-50"
              label="Overdue"
              value={loading ? "…" : String(overdueCount)}
              sub="loans marked overdue"
            />
          </div>

          {/* Loans table */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-[#0F172A]">Loan Register</h2>
            </div>
            {loading ? (
              <div className="px-5 py-12 text-center text-sm text-[#94A3B8] animate-pulse">Loading…</div>
            ) : loans.length === 0 ? (
              <div className="px-5 py-12 text-center space-y-2">
                <TrendingDown className="w-10 h-10 text-gray-200 mx-auto" />
                <p className="text-sm text-[#64748B]">No loans recorded yet</p>
                <button
                  onClick={() => setShowAddLoan(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-lg hover:bg-blue-100 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> Add first loan
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-[#F8FAFC] text-[10px] text-[#94A3B8] uppercase tracking-wide">
                      <th className="text-left px-5 py-2.5">Lender</th>
                      <th className="text-left px-4 py-2.5">Client</th>
                      <th className="text-left px-4 py-2.5">Type</th>
                      <th className="text-right px-4 py-2.5">Principal</th>
                      <th className="text-right px-4 py-2.5">Outstanding</th>
                      <th className="text-right px-4 py-2.5">Rate%</th>
                      <th className="text-right px-4 py-2.5">EMI</th>
                      <th className="text-left px-4 py-2.5">Maturity</th>
                      <th className="text-left px-4 py-2.5">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {loans.map((loan) => (
                      <tr key={loan.id} className="hover:bg-[#F8FAFC]/50">
                        <td className="px-5 py-3">
                          <p className="font-medium text-[#0F172A]">{loan.lender_name}</p>
                          {loan.account_number && (
                            <p className="text-[10px] font-mono text-[#94A3B8]">{loan.account_number}</p>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-[#475569]">
                          {loan.clients?.name ?? "—"}
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700">
                            {LOAN_TYPE_LABELS[loan.loan_type]}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right text-xs tabular-nums text-[#334155]">
                          {formatPaise(loan.principal_paise)}
                        </td>
                        <td className="px-4 py-3 text-right text-xs tabular-nums font-medium text-[#0F172A]">
                          {formatPaise(loan.outstanding_paise)}
                        </td>
                        <td className="px-4 py-3 text-right text-xs text-[#475569]">
                          {loan.interest_rate_percent}%
                        </td>
                        <td className="px-4 py-3 text-right text-xs tabular-nums text-[#334155]">
                          {loan.emi_paise ? formatPaise(loan.emi_paise) : "—"}
                        </td>
                        <td className="px-4 py-3 text-xs text-[#475569]">
                          {loan.maturity_date ? formatDate(loan.maturity_date) : "—"}
                        </td>
                        <td className="px-4 py-3">
                          <LoanStatusBadge status={loan.status} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* EMI Calculator */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] p-5">
            <div className="flex items-center gap-2 mb-4">
              <Calculator className="w-5 h-5 text-blue-600" />
              <h2 className="text-sm font-semibold text-[#0F172A]">EMI Calculator</h2>
            </div>
            <p className="text-xs text-[#94A3B8] mb-4">
              Formula: EMI = P × r × (1+r)^n / ((1+r)^n − 1) where r = monthly rate (annual rate ÷ 12 ÷ 100)
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">Principal (₹)</label>
                <input
                  type="number"
                  min="0"
                  step="1000"
                  placeholder="e.g. 1000000"
                  value={calcPrincipal}
                  onChange={(e) => setCalcPrincipal(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">Interest Rate (% p.a.)</label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="e.g. 10.5"
                  value={calcRate}
                  onChange={(e) => setCalcRate(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-[#334155] mb-1.5">Tenure (months)</label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  placeholder="e.g. 60"
                  value={calcTenure}
                  onChange={(e) => setCalcTenure(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>
            <div className="mt-4 flex items-center gap-4">
              <button
                onClick={runEMICalc}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                Calculate EMI
              </button>
              {calcResult !== null && (
                <div className="bg-blue-50 rounded-lg px-4 py-2">
                  <span className="text-xs text-blue-600 font-medium">Monthly EMI: </span>
                  <span className="text-base font-bold text-blue-800">{formatPaise(calcResult)}</span>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {/* ================================================================== */}
      {/* FD TAB                                                               */}
      {/* ================================================================== */}
      {tab === "fd" && (
        <>
          {/* Maturing soon banner */}
          {maturingSoonFDs.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-5 py-4 flex gap-3">
              <Bell className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <p className="text-sm font-semibold text-amber-800">
                  {maturingSoonFDs.length} FD{maturingSoonFDs.length > 1 ? "s" : ""} maturing within 30 days
                </p>
                <p className="text-xs text-amber-700 mt-0.5">
                  {maturingSoonFDs
                    .map(
                      (f) =>
                        `${f.bank_name}${f.fd_number ? ` (${f.fd_number})` : ""} — matures ${formatDate(f.maturity_date)} (${daysToDate(f.maturity_date)} days)`
                    )
                    .join(" · ")}
                </p>
              </div>
            </div>
          )}

          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <SummaryCard
              icon={<Landmark className="w-4 h-4 text-blue-600" />}
              iconBg="bg-blue-50"
              label="Total FDs"
              value={loading ? "…" : String(totalFDs)}
              sub="deposits tracked"
            />
            <SummaryCard
              icon={<IndianRupee className="w-4 h-4 text-green-600" />}
              iconBg="bg-green-50"
              label="Total Principal"
              value={loading ? "…" : formatPaise(totalFDPrincipalPaise)}
              sub="active FDs"
            />
            <SummaryCard
              icon={<TrendingDown className="w-4 h-4 text-purple-600" />}
              iconBg="bg-purple-50"
              label="Total Maturity Value"
              value={loading ? "…" : formatPaise(totalFDMaturityPaise)}
              sub="on maturity"
            />
            <SummaryCard
              icon={<Bell className="w-4 h-4 text-amber-600" />}
              iconBg="bg-amber-50"
              label="Maturing This Month"
              value={loading ? "…" : String(maturingThisMonthCount)}
              sub="within 30 days"
            />
          </div>

          {/* FD table */}
          <div className="bg-white rounded-xl border border-[#F1F5F9] overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-50">
              <h2 className="text-sm font-semibold text-[#0F172A]">FD Register</h2>
              <p className="text-xs text-[#94A3B8] mt-0.5">
                {/* TDS on FD interest per IT Act Section 194A — threshold ₹40,000 p.a. (₹50,000 for senior citizens) */}
                TDS applicable per IT Act Section 194A — ₹40,000 threshold p.a.
              </p>
            </div>
            {loading ? (
              <div className="px-5 py-12 text-center text-sm text-[#94A3B8] animate-pulse">Loading…</div>
            ) : fds.length === 0 ? (
              <div className="px-5 py-12 text-center space-y-2">
                <Landmark className="w-10 h-10 text-gray-200 mx-auto" />
                <p className="text-sm text-[#64748B]">No fixed deposits recorded yet</p>
                <button
                  onClick={() => setShowAddFD(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-50 text-blue-600 text-xs font-medium rounded-lg hover:bg-blue-100 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" /> Add first FD
                </button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-[#F8FAFC] text-[10px] text-[#94A3B8] uppercase tracking-wide">
                      <th className="text-left px-5 py-2.5">Bank</th>
                      <th className="text-left px-4 py-2.5">Client</th>
                      <th className="text-left px-4 py-2.5">FD No.</th>
                      <th className="text-right px-4 py-2.5">Principal</th>
                      <th className="text-right px-4 py-2.5">Rate%</th>
                      <th className="text-left px-4 py-2.5">Start</th>
                      <th className="text-left px-4 py-2.5">Maturity</th>
                      <th className="text-right px-4 py-2.5">Maturity Amt</th>
                      <th className="text-right px-4 py-2.5">Days Left</th>
                      <th className="text-left px-4 py-2.5">TDS</th>
                      <th className="text-left px-4 py-2.5">Status</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F8FAFC]">
                    {fds.map((fd) => {
                      const days = daysToDate(fd.maturity_date);
                      const isMaturingSoon = fd.status === "active" && days >= 0 && days <= 30;
                      return (
                        <tr key={fd.id} className={`hover:bg-[#F8FAFC]/50 ${isMaturingSoon ? "bg-amber-50/30" : ""}`}>
                          <td className="px-5 py-3 font-medium text-[#0F172A]">{fd.bank_name}</td>
                          <td className="px-4 py-3 text-xs text-[#475569]">{fd.clients?.name ?? "—"}</td>
                          <td className="px-4 py-3 text-xs font-mono text-[#475569]">{fd.fd_number ?? "—"}</td>
                          <td className="px-4 py-3 text-right text-xs tabular-nums text-[#334155]">
                            {formatPaise(fd.principal_paise)}
                          </td>
                          <td className="px-4 py-3 text-right text-xs text-[#475569]">
                            {fd.interest_rate_percent}%
                          </td>
                          <td className="px-4 py-3 text-xs text-[#475569]">{formatDate(fd.start_date)}</td>
                          <td className="px-4 py-3 text-xs text-[#475569]">{formatDate(fd.maturity_date)}</td>
                          <td className="px-4 py-3 text-right text-xs tabular-nums font-medium text-[#0F172A]">
                            {formatPaise(fd.maturity_amount_paise)}
                          </td>
                          <td className="px-4 py-3 text-right text-xs tabular-nums">
                            {fd.status !== "active" ? (
                              <span className="text-[#94A3B8]">—</span>
                            ) : days < 0 ? (
                              <span className="text-red-500">Matured</span>
                            ) : (
                              <span className={isMaturingSoon ? "text-amber-600 font-medium" : "text-[#475569]"}>
                                {days}d
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {fd.tds_applicable ? (
                              <span className="px-2 py-0.5 rounded-full bg-red-50 text-red-600 font-medium">s.194A</span>
                            ) : (
                              <span className="text-[#94A3B8]">No</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <FDStatusBadge status={fd.status} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* ================================================================== */}
      {/* MODAL: Add Loan                                                       */}
      {/* ================================================================== */}
      {showAddLoan && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-5 border-b border-[#F1F5F9]">
              <h3 className="text-base font-semibold text-[#0F172A]">Add Loan</h3>
              <button onClick={() => { setShowAddLoan(false); resetLoanForm(); }} className="text-[#94A3B8] hover:text-[#475569]">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <FormField label="Client" required>
                <select value={loanForm.client_id} onChange={(e) => setLoanForm({ ...loanForm, client_id: e.target.value })} className={inputCls}>
                  <option value="">Select client…</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </FormField>
              <FormField label="Loan Type" required>
                <select value={loanForm.loan_type} onChange={(e) => setLoanForm({ ...loanForm, loan_type: e.target.value as LoanType })} className={inputCls}>
                  {Object.entries(LOAN_TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </FormField>
              <FormField label="Lender Name" required>
                <input type="text" placeholder="e.g. HDFC Bank" value={loanForm.lender_name} onChange={(e) => setLoanForm({ ...loanForm, lender_name: e.target.value })} className={inputCls} />
              </FormField>
              <FormField label="Account Number" optional>
                <input type="text" placeholder="Loan account number" value={loanForm.account_number} onChange={(e) => setLoanForm({ ...loanForm, account_number: e.target.value })} className={inputCls} />
              </FormField>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Principal Amount (₹)" required>
                  <input type="number" min="0" step="0.01" placeholder="0.00" value={loanForm.principal} onChange={(e) => setLoanForm({ ...loanForm, principal: e.target.value })} className={inputCls} />
                </FormField>
                <FormField label="Outstanding Amount (₹)" required>
                  <input type="number" min="0" step="0.01" placeholder="0.00" value={loanForm.outstanding} onChange={(e) => setLoanForm({ ...loanForm, outstanding: e.target.value })} className={inputCls} />
                </FormField>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Interest Rate (% p.a.)" required>
                  <input type="number" min="0" step="0.01" placeholder="e.g. 10.5" value={loanForm.interest_rate} onChange={(e) => setLoanForm({ ...loanForm, interest_rate: e.target.value })} className={inputCls} />
                </FormField>
                <FormField label="EMI Amount (₹)" optional>
                  <input type="number" min="0" step="0.01" placeholder="0.00" value={loanForm.emi} onChange={(e) => setLoanForm({ ...loanForm, emi: e.target.value })} className={inputCls} />
                </FormField>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Disbursement Date" required>
                  <input type="date" value={loanForm.disbursement_date} onChange={(e) => setLoanForm({ ...loanForm, disbursement_date: e.target.value })} className={inputCls} />
                </FormField>
                <FormField label="Maturity Date" optional>
                  <input type="date" value={loanForm.maturity_date} onChange={(e) => setLoanForm({ ...loanForm, maturity_date: e.target.value })} className={inputCls} />
                </FormField>
              </div>
              <FormField label="Notes" optional>
                <textarea rows={2} placeholder="Any additional notes…" value={loanForm.notes} onChange={(e) => setLoanForm({ ...loanForm, notes: e.target.value })} className={inputCls} />
              </FormField>
              {loanError && <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{loanError}</p>}
            </div>
            <div className="px-6 py-4 border-t border-[#F1F5F9] flex gap-3 justify-end">
              <button onClick={() => { setShowAddLoan(false); resetLoanForm(); }} className="px-4 py-2 text-sm font-medium text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-white/[0.08]">Cancel</button>
              <button onClick={handleAddLoan} disabled={loanSaving} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {loanSaving ? "Saving…" : "Add Loan"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ================================================================== */}
      {/* MODAL: Add FD                                                         */}
      {/* ================================================================== */}
      {showAddFD && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between px-6 py-5 border-b border-[#F1F5F9]">
              <h3 className="text-base font-semibold text-[#0F172A]">Add Fixed Deposit</h3>
              <button onClick={() => { setShowAddFD(false); resetFDForm(); }} className="text-[#94A3B8] hover:text-[#475569]">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="px-6 py-5 space-y-4">
              <FormField label="Client" required>
                <select value={fdForm.client_id} onChange={(e) => setFDForm({ ...fdForm, client_id: e.target.value })} className={inputCls}>
                  <option value="">Select client…</option>
                  {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </FormField>
              <FormField label="Bank Name" required>
                <input type="text" placeholder="e.g. State Bank of India" value={fdForm.bank_name} onChange={(e) => setFDForm({ ...fdForm, bank_name: e.target.value })} className={inputCls} />
              </FormField>
              <FormField label="FD Number" optional>
                <input type="text" placeholder="FD receipt/account number" value={fdForm.fd_number} onChange={(e) => setFDForm({ ...fdForm, fd_number: e.target.value })} className={inputCls} />
              </FormField>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Principal (₹)" required>
                  <input type="number" min="0" step="0.01" placeholder="0.00" value={fdForm.principal} onChange={(e) => setFDForm({ ...fdForm, principal: e.target.value })} className={inputCls} />
                </FormField>
                <FormField label="Interest Rate (% p.a.)" required>
                  <input type="number" min="0" step="0.01" placeholder="e.g. 7.0" value={fdForm.interest_rate} onChange={(e) => setFDForm({ ...fdForm, interest_rate: e.target.value })} className={inputCls} />
                </FormField>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Start Date" required>
                  <input type="date" value={fdForm.start_date} onChange={(e) => setFDForm({ ...fdForm, start_date: e.target.value })} className={inputCls} />
                </FormField>
                <FormField label="Maturity Date" required>
                  <input type="date" value={fdForm.maturity_date} onChange={(e) => setFDForm({ ...fdForm, maturity_date: e.target.value })} className={inputCls} />
                </FormField>
              </div>

              {/* Auto-calculated maturity amount preview */}
              {fdPreviewMaturityPaise !== null && !isNaN(fdPreviewMaturityPaise) && fdPreviewMaturityPaise > 0 && (
                <div className="bg-green-50 rounded-lg px-4 py-3 text-xs space-y-1">
                  <p className="text-green-700 font-semibold">Auto-calculated Maturity Amount</p>
                  <p className="text-green-800 text-sm font-bold">{formatPaise(fdPreviewMaturityPaise)}</p>
                  <p className="text-green-600">Formula: P × (1 + r/100)^(days/365) — annual compounding</p>
                </div>
              )}

              <div className="flex gap-4">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={fdForm.is_auto_renewed}
                    onChange={(e) => setFDForm({ ...fdForm, is_auto_renewed: e.target.checked })}
                    className="rounded"
                  />
                  <span className="text-xs font-medium text-[#334155]">Auto Renewal</span>
                </label>
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={fdForm.tds_applicable}
                    onChange={(e) => setFDForm({ ...fdForm, tds_applicable: e.target.checked })}
                    className="rounded"
                  />
                  <span className="text-xs font-medium text-[#334155]">TDS Applicable (s.194A)</span>
                </label>
              </div>
              {fdForm.tds_applicable && (
                <p className="text-[10px] text-amber-600 bg-amber-50 px-3 py-2 rounded-lg">
                  {/* TDS on FD interest per IT Act Section 194A — threshold ₹40,000 p.a. (₹50,000 for senior citizens) */}
                  IT Act Section 194A — TDS deducted on FD interest exceeding ₹40,000 p.a. (₹50,000 for senior citizens). TDS rate: 10% (20% if PAN not furnished).
                </p>
              )}
              <FormField label="Notes" optional>
                <textarea rows={2} placeholder="Any additional notes…" value={fdForm.notes} onChange={(e) => setFDForm({ ...fdForm, notes: e.target.value })} className={inputCls} />
              </FormField>
              {fdError && <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg">{fdError}</p>}
            </div>
            <div className="px-6 py-4 border-t border-[#F1F5F9] flex gap-3 justify-end">
              <button onClick={() => { setShowAddFD(false); resetFDForm(); }} className="px-4 py-2 text-sm font-medium text-[#334155] bg-[#F1F5F9] rounded-lg hover:bg-white/[0.08]">Cancel</button>
              <button onClick={handleAddFD} disabled={fdSaving} className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50">
                {fdSaving ? "Saving…" : "Add FD"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({
  icon,
  iconBg,
  label,
  value,
  sub,
}: {
  icon: React.ReactNode;
  iconBg: string;
  label: string;
  value: string;
  sub: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-[#F1F5F9] p-4">
      <div className="flex items-center gap-2 mb-3">
        <div className={`w-8 h-8 rounded-lg ${iconBg} flex items-center justify-center`}>{icon}</div>
        <span className="text-xs text-[#64748B]">{label}</span>
      </div>
      <p className="text-lg font-semibold text-[#0F172A]">{value}</p>
      <p className="text-xs text-[#94A3B8] mt-0.5">{sub}</p>
    </div>
  );
}

function LoanStatusBadge({ status }: { status: LoanStatus }) {
  const styles: Record<LoanStatus, string> = {
    active: "bg-green-100 text-green-700",
    overdue: "bg-red-100 text-red-700",
    closed: "bg-[#F1F5F9] text-[#64748B]",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[status]}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function FDStatusBadge({ status }: { status: FDStatus }) {
  const styles: Record<FDStatus, string> = {
    active: "bg-green-100 text-green-700",
    matured: "bg-blue-100 text-blue-700",
    broken: "bg-red-100 text-red-700",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${styles[status]}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function FormField({
  label,
  required,
  optional,
  children,
}: {
  label: string;
  required?: boolean;
  optional?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-[#334155] mb-1.5">
        {label}
        {required && <span className="text-red-500 ml-0.5">*</span>}
        {optional && <span className="text-[#94A3B8] font-normal ml-1">(optional)</span>}
      </label>
      {children}
    </div>
  );
}
