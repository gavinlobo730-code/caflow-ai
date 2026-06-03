"use client";

/**
 * Auto Journals — AI-generated journal entry suggestions for CA approval.
 *
 * Sources scanned:
 * - Salary: payroll_employees (EPF Act 1952, ESI Act 1948)
 * - Depreciation: fixed_assets (IT Act Section 32)
 * - Loan EMI: loans (reducing balance method)
 * - FD Interest Accrual: fixed_deposits (IT Act Section 194A)
 * - GST Liability: compliance_calendar (CGST Act Section 39)
 * - TDS Payable: compliance_calendar (IT Act Section 194C/194J etc.)
 *
 * All monetary calculations use integer paise — never floating point.
 * Nothing posts automatically — CA must click "Approve & Post".
 */

import { useState, useEffect, useCallback } from "react";
import { Zap, CheckCircle, X, RotateCcw, ChevronDown, ChevronRight, AlertCircle } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "@/lib/data/getFirmId";
import { formatPaise } from "@/lib/services/formatting";

// ─── Types ────────────────────────────────────────────────────────────────────

interface Client {
  id: string;
  name: string;
}

interface JournalLine {
  account_name: string;
  account_type: string;
  debit_paise: number;
  credit_paise: number;
}

interface AutoJournalSuggestion {
  id: string;
  firm_id: string;
  client_id: string;
  source_type: "salary" | "depreciation" | "loan_emi" | "fd_interest" | "gst_liability" | "tds_payable";
  source_id: string | null;
  period_month: number;
  period_year: number;
  description: string;
  lines: JournalLine[];
  status: "pending" | "approved" | "dismissed";
  journal_entry_id: string | null;
  created_at: string;
}

interface PayrollEmployee {
  id: string;
  name: string;
  basic_paise: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
  is_active: boolean;
}

interface FixedAsset {
  id: string;
  asset_name: string;
  purchase_cost_paise: number;
  salvage_value_paise: number;
  useful_life_years: number | null;
  depreciation_method: "SL" | "WDV";
  wdv_rate_percent: number | null;
  accumulated_depreciation_paise: number;
  is_disposed: boolean;
}

interface Loan {
  id: string;
  lender_name: string;
  outstanding_paise: number;
  interest_rate_percent: number;
  emi_paise: number | null;
  status: string;
}

interface FixedDeposit {
  id: string;
  bank_name: string;
  principal_paise: number;
  interest_rate_percent: number;
  status: string;
}

interface ComplianceTask {
  id: string;
  compliance_type: string;
  due_date: string;
  period_start: string;
  period_end: string;
}

interface Account {
  id: string;
  account_name: string;
  account_type: string;
}

// ─── Constants ────────────────────────────────────────────────────────────────

const SOURCE_LABELS: Record<AutoJournalSuggestion["source_type"], string> = {
  salary: "Salary",
  depreciation: "Depreciation",
  loan_emi: "Loan EMI",
  fd_interest: "FD Interest",
  gst_liability: "GST Liability",
  tds_payable: "TDS Payable",
};

const SOURCE_COLORS: Record<AutoJournalSuggestion["source_type"], string> = {
  salary: "bg-blue-100 text-blue-700",
  depreciation: "bg-purple-100 text-purple-700",
  loan_emi: "bg-orange-100 text-orange-700",
  fd_interest: "bg-green-100 text-green-700",
  gst_liability: "bg-red-100 text-red-700",
  tds_payable: "bg-yellow-100 text-yellow-700",
};

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

// ─── Calculation Helpers ──────────────────────────────────────────────────────

/**
 * Calculate monthly PF employer contribution per EPF Act 1952 Section 6.
 * Rate: 12% of basic salary. Ceiling: ₹15,000/month = 1,500,000 paise.
 * All arithmetic in integer paise.
 */
function calcPFPaise(basicPaise: number): number {
  // EPF Act 1952 — PF ceiling ₹15,000/month
  const PF_CEILING_PAISE = 1_500_000;
  const effectiveBasic = Math.min(basicPaise, PF_CEILING_PAISE);
  return Math.floor(effectiveBasic * 12 / 100);
}

/**
 * Calculate monthly ESIC employee contribution per ESI Act 1948 Section 40.
 * Rate: 0.75% of basic. Applicable only if basic ≤ ₹21,000/month = 2,100,000 paise.
 * All arithmetic in integer paise.
 */
function calcESICPaise(basicPaise: number, esiApplicable: boolean): number {
  // ESI Act 1948 — ceiling ₹21,000/month
  const ESIC_CEILING_PAISE = 2_100_000;
  if (!esiApplicable || basicPaise > ESIC_CEILING_PAISE) return 0;
  return Math.floor(basicPaise * 75 / 10000); // 0.75% = 75/10000
}

/**
 * Monthly depreciation per IT Act Section 32.
 * WDV method: Section 32(1)(ii) — rate applied to written-down value.
 * SL method: Section 32(1)(i) — straight line over useful life.
 * All arithmetic in integer paise.
 */
function calcDepreciationPaise(asset: FixedAsset): number {
  if (asset.is_disposed) return 0;
  if (asset.depreciation_method === "WDV" && asset.wdv_rate_percent !== null) {
    // IT Act Section 32(1)(ii) — WDV method
    const wdv = asset.purchase_cost_paise - asset.accumulated_depreciation_paise;
    if (wdv <= 0) return 0;
    return Math.floor(wdv * asset.wdv_rate_percent / 100 / 12);
  } else if (asset.depreciation_method === "SL" && asset.useful_life_years && asset.useful_life_years > 0) {
    // IT Act Section 32(1)(i) — SL method
    const depreciableBase = asset.purchase_cost_paise - asset.salvage_value_paise;
    if (depreciableBase <= 0) return 0;
    return Math.floor(depreciableBase / asset.useful_life_years / 12);
  }
  return 0;
}

/**
 * Split loan EMI into interest and principal components.
 * Reducing balance method — interest = outstanding × monthly rate.
 * All arithmetic in integer paise.
 */
function calcLoanSplit(loan: Loan): { interestPaise: number; principalPaise: number } {
  if (!loan.emi_paise || loan.status !== "active") return { interestPaise: 0, principalPaise: 0 };
  const interestPaise = Math.floor(loan.outstanding_paise * loan.interest_rate_percent / 100 / 12);
  const principalPaise = loan.emi_paise - interestPaise;
  return { interestPaise, principalPaise: Math.max(0, principalPaise) };
}

/**
 * Monthly FD interest accrual — simple interest basis.
 * Per IT Act Section 194A — TDS threshold ₹40,000 p.a.
 * All arithmetic in integer paise.
 */
function calcFDMonthlyInterestPaise(fd: FixedDeposit): number {
  if (fd.status !== "active") return 0;
  return Math.floor(fd.principal_paise * fd.interest_rate_percent / 100 / 12);
}

// ─── Suggestion Generator ─────────────────────────────────────────────────────

async function generateSuggestions(
  sb: ReturnType<typeof getSupabaseClient>,
  firmId: string,
  clientId: string,
  month: number,
  year: number,
): Promise<Omit<AutoJournalSuggestion, "id" | "created_at">[]> {
  const suggestions: Omit<AutoJournalSuggestion, "id" | "created_at">[] = [];

  // ── 1. Salary Journals (EPF Act 1952, ESI Act 1948) ───────────────────────
  const { data: employees } = await sb
    .from("payroll_employees")
    .select("id, name, basic_paise, pf_applicable, esi_applicable, is_active")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("is_active", true);

  for (const emp of (employees as PayrollEmployee[] ?? [])) {
    const basicPaise = emp.basic_paise;
    const pfPaise = emp.pf_applicable ? calcPFPaise(basicPaise) : 0;
    // ESI Act 1948 — 0.75% employee contribution
    const esicPaise = calcESICPaise(basicPaise, emp.esi_applicable);
    // TDS on salary — placeholder per IT Act Section 192
    const tdsPaise = 0; // CA to determine actual TDS
    // Net payable to employee after deductions
    const netPayPaise = basicPaise - pfPaise - esicPaise - tdsPaise;

    const lines: JournalLine[] = [
      { account_name: "Salary Expense", account_type: "Expense", debit_paise: basicPaise, credit_paise: 0 },
      { account_name: "Salary Payable", account_type: "Liability", debit_paise: 0, credit_paise: netPayPaise },
    ];
    if (pfPaise > 0) {
      lines.push({ account_name: "PF Payable", account_type: "Liability", debit_paise: 0, credit_paise: pfPaise });
    }
    if (esicPaise > 0) {
      lines.push({ account_name: "ESIC Payable", account_type: "Liability", debit_paise: 0, credit_paise: esicPaise });
    }
    if (tdsPaise > 0) {
      lines.push({ account_name: "TDS Payable", account_type: "Liability", debit_paise: 0, credit_paise: tdsPaise });
    }

    suggestions.push({
      firm_id: firmId,
      client_id: clientId,
      source_type: "salary",
      source_id: emp.id,
      period_month: month,
      period_year: year,
      description: `Salary journal for ${emp.name} — ${MONTH_NAMES[month - 1]} ${year}`,
      lines,
      status: "pending",
      journal_entry_id: null,
    });
  }

  // ── 2. Depreciation Journals (IT Act Section 32) ──────────────────────────
  const { data: assets } = await sb
    .from("fixed_assets")
    .select("id, asset_name, purchase_cost_paise, salvage_value_paise, useful_life_years, depreciation_method, wdv_rate_percent, accumulated_depreciation_paise, is_disposed")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("is_disposed", false);

  for (const asset of (assets as FixedAsset[] ?? [])) {
    // IT Act Section 32 — depreciation on owned assets
    const depPaise = calcDepreciationPaise(asset);
    if (depPaise <= 0) continue;

    suggestions.push({
      firm_id: firmId,
      client_id: clientId,
      source_type: "depreciation",
      source_id: asset.id,
      period_month: month,
      period_year: year,
      description: `Depreciation for ${asset.asset_name} — ${MONTH_NAMES[month - 1]} ${year} (IT Act Section 32)`,
      lines: [
        { account_name: "Depreciation Expense", account_type: "Expense", debit_paise: depPaise, credit_paise: 0 },
        { account_name: "Accumulated Depreciation", account_type: "Asset", debit_paise: 0, credit_paise: depPaise },
      ],
      status: "pending",
      journal_entry_id: null,
    });
  }

  // ── 3. Loan EMI Journals ──────────────────────────────────────────────────
  const { data: loans } = await sb
    .from("loans")
    .select("id, lender_name, outstanding_paise, interest_rate_percent, emi_paise, status")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("status", "active");

  for (const loan of (loans as Loan[] ?? [])) {
    if (!loan.emi_paise) continue;
    const { interestPaise, principalPaise } = calcLoanSplit(loan);
    if (interestPaise <= 0 && principalPaise <= 0) continue;

    const lines: JournalLine[] = [];
    if (interestPaise > 0) {
      lines.push({ account_name: "Interest Expense", account_type: "Expense", debit_paise: interestPaise, credit_paise: 0 });
    }
    if (principalPaise > 0) {
      lines.push({ account_name: "Loan Liability", account_type: "Liability", debit_paise: principalPaise, credit_paise: 0 });
    }
    lines.push({ account_name: "Bank Account", account_type: "Asset", debit_paise: 0, credit_paise: loan.emi_paise });

    suggestions.push({
      firm_id: firmId,
      client_id: clientId,
      source_type: "loan_emi",
      source_id: loan.id,
      period_month: month,
      period_year: year,
      description: `Loan EMI — ${loan.lender_name} — ${MONTH_NAMES[month - 1]} ${year}`,
      lines,
      status: "pending",
      journal_entry_id: null,
    });
  }

  // ── 4. FD Interest Accrual (IT Act Section 194A) ──────────────────────────
  const { data: fds } = await sb
    .from("fixed_deposits")
    .select("id, bank_name, principal_paise, interest_rate_percent, status")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("status", "active");

  for (const fd of (fds as FixedDeposit[] ?? [])) {
    // IT Act Section 194A — TDS on FD interest; accrue monthly
    const interestPaise = calcFDMonthlyInterestPaise(fd);
    if (interestPaise <= 0) continue;

    suggestions.push({
      firm_id: firmId,
      client_id: clientId,
      source_type: "fd_interest",
      source_id: fd.id,
      period_month: month,
      period_year: year,
      description: `FD interest accrual — ${fd.bank_name} — ${MONTH_NAMES[month - 1]} ${year} (IT Act Section 194A)`,
      lines: [
        { account_name: "FD Interest Receivable", account_type: "Asset", debit_paise: interestPaise, credit_paise: 0 },
        { account_name: "Interest Income", account_type: "Revenue", debit_paise: 0, credit_paise: interestPaise },
      ],
      status: "pending",
      journal_entry_id: null,
    });
  }

  // ── 5. GST Liability Journal (CGST Act Section 39) ────────────────────────
  // Only when GSTR-3B is due this month
  const { data: gstTasks } = await sb
    .from("compliance_calendar")
    .select("id, compliance_type, due_date, period_start, period_end")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("compliance_type", "GSTR3B")
    .gte("due_date", `${year}-${String(month).padStart(2, "0")}-01`)
    .lte("due_date", `${year}-${String(month).padStart(2, "0")}-31`);

  for (const task of (gstTasks as ComplianceTask[] ?? [])) {
    // CGST Act Section 39 — GSTR-3B GST liability journal. CA to fill actual amounts.
    suggestions.push({
      firm_id: firmId,
      client_id: clientId,
      source_type: "gst_liability",
      source_id: task.id,
      period_month: month,
      period_year: year,
      description: `GST liability journal — GSTR-3B due ${task.due_date} (CGST Act Section 39) — fill amounts from GST return`,
      lines: [
        { account_name: "GST Output Tax Payable", account_type: "Liability", debit_paise: 0, credit_paise: 0 },
        { account_name: "GST Input Tax Credit", account_type: "Asset", debit_paise: 0, credit_paise: 0 },
        { account_name: "Net GST Cash Payable", account_type: "Liability", debit_paise: 0, credit_paise: 0 },
      ],
      status: "pending",
      journal_entry_id: null,
    });
  }

  // ── 6. TDS Payable Journal (IT Act Section 194C/194J etc.) ────────────────
  const { data: tdsTasks } = await sb
    .from("compliance_calendar")
    .select("id, compliance_type, due_date, period_start, period_end")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .in("compliance_type", ["TDS24Q", "TDS26Q"])
    .gte("due_date", `${year}-${String(month).padStart(2, "0")}-01`)
    .lte("due_date", `${year}-${String(month).padStart(2, "0")}-31`);

  for (const task of (tdsTasks as ComplianceTask[] ?? [])) {
    // IT Act Section 200 — TDS deposit. CA to fill actual amounts.
    suggestions.push({
      firm_id: firmId,
      client_id: clientId,
      source_type: "tds_payable",
      source_id: task.id,
      period_month: month,
      period_year: year,
      description: `TDS payable journal — ${task.compliance_type} due ${task.due_date} (IT Act Section 200) — fill amounts from TDS return`,
      lines: [
        { account_name: "TDS Expense", account_type: "Expense", debit_paise: 0, credit_paise: 0 },
        { account_name: "TDS Payable", account_type: "Liability", debit_paise: 0, credit_paise: 0 },
      ],
      status: "pending",
      journal_entry_id: null,
    });
  }

  return suggestions;
}

// ─── Component ────────────────────────────────────────────────────────────────

function LoadingSpinner() {
  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4 animate-pulse">
      <div className="h-8 bg-gray-200 rounded w-64" />
      <div className="h-32 bg-gray-100 rounded-xl" />
      <div className="h-48 bg-gray-100 rounded-xl" />
    </div>
  );
}

function SuggestionCard({
  suggestion,
  onApprove,
  onDismiss,
  onUndo,
  approving,
}: {
  suggestion: AutoJournalSuggestion;
  onApprove: (id: string) => void;
  onDismiss: (id: string) => void;
  onUndo: (id: string) => void;
  approving: string | null;
}) {
  const totalDebit = suggestion.lines.reduce((s, l) => s + l.debit_paise, 0);
  const totalCredit = suggestion.lines.reduce((s, l) => s + l.credit_paise, 0);
  const isPlaceholder = totalDebit === 0 && totalCredit === 0;

  return (
    <Card className={`border ${suggestion.status === "approved" ? "border-green-200 bg-green-50/30" : suggestion.status === "dismissed" ? "border-gray-200 opacity-60" : "border-gray-200"}`}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <Badge className={`text-xs shrink-0 ${SOURCE_COLORS[suggestion.source_type]}`}>
              {SOURCE_LABELS[suggestion.source_type]}
            </Badge>
            <div className="min-w-0">
              <p className="text-sm font-medium text-gray-900 truncate">{suggestion.description}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {MONTH_NAMES[suggestion.period_month - 1]} {suggestion.period_year}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {suggestion.status === "approved" && (
              <Badge className="text-xs bg-green-100 text-green-700">
                <CheckCircle size={10} className="mr-1" /> Posted
              </Badge>
            )}
            {suggestion.status === "dismissed" && (
              <>
                <Badge className="text-xs bg-gray-100 text-gray-500">Dismissed</Badge>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs"
                  onClick={() => onUndo(suggestion.id)}
                >
                  <RotateCcw size={12} className="mr-1" /> Undo
                </Button>
              </>
            )}
            {suggestion.status === "pending" && (
              <>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 text-xs text-gray-500 hover:text-gray-700"
                  onClick={() => onDismiss(suggestion.id)}
                >
                  <X size={12} className="mr-1" /> Dismiss
                </Button>
                <Button
                  size="sm"
                  className="h-7 text-xs bg-green-600 hover:bg-green-700 text-white"
                  onClick={() => onApprove(suggestion.id)}
                  disabled={approving === suggestion.id}
                >
                  <CheckCircle size={12} className="mr-1" />
                  {approving === suggestion.id ? "Posting…" : "Approve & Post"}
                </Button>
              </>
            )}
          </div>
        </div>

        {isPlaceholder && (
          <div className="mt-3 flex items-center gap-2 text-xs text-amber-700 bg-amber-50 rounded px-3 py-2">
            <AlertCircle size={12} />
            Draft placeholder — fill actual amounts from the return before approving.
          </div>
        )}

        {/* Debit/Credit Table */}
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-gray-50">
                <th className="text-left px-2 py-1 font-medium text-gray-600 border border-gray-200">Account</th>
                <th className="text-left px-2 py-1 font-medium text-gray-600 border border-gray-200">Type</th>
                <th className="text-right px-2 py-1 font-medium text-gray-600 border border-gray-200">Debit</th>
                <th className="text-right px-2 py-1 font-medium text-gray-600 border border-gray-200">Credit</th>
              </tr>
            </thead>
            <tbody>
              {suggestion.lines.map((line, i) => (
                <tr key={i} className="hover:bg-gray-50/50">
                  <td className="px-2 py-1 border border-gray-200 text-gray-800">{line.account_name}</td>
                  <td className="px-2 py-1 border border-gray-200 text-gray-500">{line.account_type}</td>
                  <td className="px-2 py-1 border border-gray-200 text-right font-mono text-gray-800">
                    {line.debit_paise > 0 ? formatPaise(line.debit_paise) : "—"}
                  </td>
                  <td className="px-2 py-1 border border-gray-200 text-right font-mono text-gray-800">
                    {line.credit_paise > 0 ? formatPaise(line.credit_paise) : "—"}
                  </td>
                </tr>
              ))}
              {!isPlaceholder && (
                <tr className="bg-gray-50 font-semibold">
                  <td colSpan={2} className="px-2 py-1 border border-gray-200 text-gray-700">Total</td>
                  <td className="px-2 py-1 border border-gray-200 text-right font-mono text-gray-800">{formatPaise(totalDebit)}</td>
                  <td className="px-2 py-1 border border-gray-200 text-right font-mono text-gray-800">{formatPaise(totalCredit)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AutoJournalsPage() {
  const [clients, setClients] = useState<Client[]>([]);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [suggestions, setSuggestions] = useState<AutoJournalSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [approving, setApproving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showPosted, setShowPosted] = useState(false);
  const [firmId, setFirmId] = useState<string | null>(null);

  const now = new Date();
  const currentMonth = now.getMonth() + 1;
  const currentYear = now.getFullYear();

  const sb = getSupabaseClient();

  const loadData = useCallback(async (fId: string, cId: string) => {
    if (!cId) { setSuggestions([]); return; }
    const { data, error: err } = await sb
      .from("auto_journal_suggestions")
      .select("*")
      .eq("firm_id", fId)
      .eq("client_id", cId)
      .eq("period_month", currentMonth)
      .eq("period_year", currentYear)
      .order("created_at", { ascending: false });
    if (err) setError(err.message);
    else setSuggestions((data ?? []) as AutoJournalSuggestion[]);
  }, [sb, currentMonth, currentYear]);

  useEffect(() => {
    (async () => {
      try {
        const fId = await getFirmId();
        setFirmId(fId);
        const { data: clientData } = await sb
          .from("clients")
          .select("id, name")
          .eq("firm_id", fId)
          .eq("status", "active")
          .order("name");
        const clientList = (clientData ?? []) as Client[];
        setClients(clientList);
        if (clientList.length > 0) {
          setSelectedClientId(clientList[0].id);
          await loadData(fId, clientList[0].id);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (firmId && selectedClientId) {
      loadData(firmId, selectedClientId);
    }
  }, [firmId, selectedClientId, loadData]);

  const handleGenerate = async () => {
    if (!firmId || !selectedClientId) return;
    setGenerating(true);
    setError(null);
    try {
      const newSuggestions = await generateSuggestions(sb, firmId, selectedClientId, currentMonth, currentYear);
      if (newSuggestions.length === 0) {
        setError("No data found for the selected client. Add payroll employees, fixed assets, or loans first.");
        setGenerating(false);
        return;
      }
      const { error: insertErr } = await sb
        .from("auto_journal_suggestions")
        .insert(newSuggestions);
      if (insertErr) throw new Error(insertErr.message);
      await loadData(firmId, selectedClientId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate suggestions");
    } finally {
      setGenerating(false);
    }
  };

  const handleApprove = async (suggestionId: string) => {
    if (!firmId) return;
    setApproving(suggestionId);
    setError(null);
    try {
      const suggestion = suggestions.find((s) => s.id === suggestionId);
      if (!suggestion) throw new Error("Suggestion not found");

      // Fetch chart of accounts to match by name
      const { data: accounts } = await sb
        .from("chart_of_accounts")
        .select("id, account_name, account_type")
        .eq("firm_id", firmId)
        .eq("client_id", suggestion.client_id);

      const accountMap = new Map<string, string>();
      for (const acc of (accounts ?? []) as Account[]) {
        accountMap.set(acc.account_name.toLowerCase(), acc.id);
      }

      // CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
      // Insert journal entry
      const today = new Date().toISOString().split("T")[0];
      const { data: jeData, error: jeErr } = await sb
        .from("journal_entries")
        .insert({
          firm_id: firmId,
          client_id: suggestion.client_id,
          entry_date: today,
          narration: suggestion.description,
          reference_no: "AUTO",
          entry_type: "Journal",
          status: "posted",
        })
        .select("id")
        .single();
      if (jeErr) throw new Error(jeErr.message);

      // Insert journal lines
      const journalLines = suggestion.lines.map((line) => ({
        entry_id: jeData.id,
        account_id: accountMap.get(line.account_name.toLowerCase()) ?? null,
        account_name_memo: line.account_name,
        debit_paise: line.debit_paise,
        credit_paise: line.credit_paise,
        narration: suggestion.description,
      }));

      const { error: linesErr } = await sb.from("journal_lines").insert(journalLines);
      if (linesErr) throw new Error(linesErr.message);

      // Update suggestion status
      const { error: updateErr } = await sb
        .from("auto_journal_suggestions")
        .update({ status: "approved", journal_entry_id: jeData.id })
        .eq("id", suggestionId);
      if (updateErr) throw new Error(updateErr.message);

      setSuggestions((prev) =>
        prev.map((s) =>
          s.id === suggestionId
            ? { ...s, status: "approved", journal_entry_id: jeData.id }
            : s,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to approve");
    } finally {
      setApproving(null);
    }
  };

  const handleDismiss = async (suggestionId: string) => {
    const { error: err } = await sb
      .from("auto_journal_suggestions")
      .update({ status: "dismissed" })
      .eq("id", suggestionId);
    if (err) { setError(err.message); return; }
    setSuggestions((prev) =>
      prev.map((s) => s.id === suggestionId ? { ...s, status: "dismissed" } : s),
    );
  };

  const handleUndo = async (suggestionId: string) => {
    const { error: err } = await sb
      .from("auto_journal_suggestions")
      .update({ status: "pending" })
      .eq("id", suggestionId);
    if (err) { setError(err.message); return; }
    setSuggestions((prev) =>
      prev.map((s) => s.id === suggestionId ? { ...s, status: "pending" } : s),
    );
  };

  if (loading) return <LoadingSpinner />;

  const pending = suggestions.filter((s) => s.status === "pending");
  const approved = suggestions.filter((s) => s.status === "approved");
  const dismissed = suggestions.filter((s) => s.status === "dismissed");

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-indigo-100 flex items-center justify-center">
            <Zap size={16} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Auto Journals</h1>
            <p className="text-xs text-gray-500">
              AI-generated journal entries for {MONTH_NAMES[currentMonth - 1]} {currentYear} — CA approval required
            </p>
          </div>
        </div>
      </div>

      {/* Controls */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-end gap-3 flex-wrap">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs font-medium text-gray-700 mb-1">Client</label>
              <select
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                value={selectedClientId}
                onChange={(e) => setSelectedClientId(e.target.value)}
              >
                <option value="">Select client…</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
            <Button
              onClick={handleGenerate}
              disabled={!selectedClientId || generating}
              className="bg-indigo-600 hover:bg-indigo-700 text-white"
            >
              <Zap size={14} className="mr-2" />
              {generating ? "Scanning…" : "Generate Suggestions"}
            </Button>
          </div>
          {error && (
            <div className="mt-3 flex items-center gap-2 text-sm text-red-600 bg-red-50 rounded px-3 py-2">
              <AlertCircle size={14} /> {error}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pending Suggestions */}
      {suggestions.length === 0 && !generating && (
        <Card>
          <CardContent className="p-8 text-center text-gray-500 text-sm">
            No suggestions yet. Select a client and click &quot;Generate Suggestions&quot; to scan existing data.
          </CardContent>
        </Card>
      )}

      {pending.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <span className="w-5 h-5 rounded-full bg-amber-100 text-amber-700 text-xs flex items-center justify-center font-bold">{pending.length}</span>
            Pending Approval
          </h2>
          {pending.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              onApprove={handleApprove}
              onDismiss={handleDismiss}
              onUndo={handleUndo}
              approving={approving}
            />
          ))}
        </div>
      )}

      {/* Dismissed Suggestions */}
      {dismissed.length > 0 && (
        <div className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500">Dismissed ({dismissed.length})</h2>
          {dismissed.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              onApprove={handleApprove}
              onDismiss={handleDismiss}
              onUndo={handleUndo}
              approving={approving}
            />
          ))}
        </div>
      )}

      {/* Posted (collapsed by default) */}
      {approved.length > 0 && (
        <div className="space-y-3">
          <button
            className="flex items-center gap-2 text-sm font-semibold text-gray-500 hover:text-gray-700 transition-colors"
            onClick={() => setShowPosted(!showPosted)}
          >
            {showPosted ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            Posted Entries ({approved.length})
          </button>
          {showPosted && approved.map((s) => (
            <SuggestionCard
              key={s.id}
              suggestion={s}
              onApprove={handleApprove}
              onDismiss={handleDismiss}
              onUndo={handleUndo}
              approving={approving}
            />
          ))}
        </div>
      )}
    </div>
  );
}
