/**
 * Income Tax data layer — ITR computation via backend engine.
 * IT Act 1961 — all amounts in paise (integer arithmetic).
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "./getFirmId";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

export interface S80CInput {
  ppf_paise?: number;
  elss_paise?: number;
  lic_paise?: number;
  nsc_paise?: number;
  home_loan_principal_paise?: number;
  tuition_fees_paise?: number;
  fd_5yr_paise?: number;
  sukanya_samriddhi_paise?: number;
  ulip_paise?: number;
}

export interface S80DInput {
  self_family_premium_paise?: number;
  self_family_is_senior?: boolean;
  parents_premium_paise?: number;
  parents_is_senior?: boolean;
}

export interface Donation80G {
  description: string;
  amount_paise: number;
  deduction_pct: 100 | 50;
}

export interface HRAInput {
  basic_salary_paise: number;
  hra_received_paise: number;
  rent_paid_paise: number;
  is_metro: boolean;
}

export interface ComputeITRRequest {
  gross_salary_paise?: number;
  other_income_paise?: number;
  house_property_income_paise?: number;
  business_income_paise?: number;
  capital_gains_stcg_paise?: number;
  capital_gains_ltcg_paise?: number;
  capital_gains_ltcg_other_paise?: number;
  exempt_income_paise?: number;
  use_new_regime: boolean;
  is_senior_citizen?: boolean;
  is_very_senior_citizen?: boolean;
  s80c?: S80CInput;
  nps_80ccd1b_paise?: number;
  s80d?: S80DInput;
  donations_80g?: Donation80G[];
  savings_interest_80tta_paise?: number;
  hra?: HRAInput;
  home_loan_interest_24b_paise?: number;
  other_deductions_paise?: number;
  tds_deducted_paise?: number;
  advance_tax_paid_paise?: number;
}

export interface ITRComputeResult {
  regime: "new" | "old";
  income: {
    gross_total_paise: number;
    standard_deduction_paise: number;
    total_deductions_paise: number;
    taxable_income_paise: number;
  };
  deductions: {
    s80c_paise: number;
    s80ccd_paise: number;
    s80d_paise: number;
    s80g_paise: number;
    s80tta_paise: number;
    hra_paise: number;
    s24b_paise: number;
  };
  tax: {
    tax_before_cess_paise: number;
    rebate_87a_paise: number;
    surcharge_paise: number;
    cess_paise: number;
    total_tax_paise: number;
  };
  payable: {
    tds_and_advance_paise: number;
    net_payable_paise: number;
    is_refund: boolean;
  };
  warnings: string[];
  validation_errors: string[];
  ca_review_required: true;
}

export interface TaxPlanningRecord {
  id?: string;
  client_id: string;
  financial_year: string;
  gross_income_paise: number;
  ppf_paise?: number;
  elss_paise?: number;
  lic_paise?: number;
  nsc_paise?: number;
  home_loan_principal_paise?: number;
  hra_paise?: number;
  nps_80ccd_paise?: number;
  health_insurance_80d_paise?: number;
  home_loan_interest_24b_paise?: number;
  regime?: "old" | "new";
  tax_paise?: number;
}

// ── API Calls ──────────────────────────────────────────────────────────────

/** Compute ITR via backend engine. All computation server-side. */
export async function computeITR(req: ComputeITRRequest): Promise<ITRComputeResult> {
  const res = await fetch(`${API_BASE}/api/income-tax/compute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`ITR compute failed: ${res.statusText}`);
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? "ITR computation error");
  return json.data as ITRComputeResult;
}

/** Compute HRA exemption under IT Act Section 10(13A). */
export async function computeHRAExemption(
  basicSalaryPaise: number,
  hraReceivedPaise: number,
  rentPaidPaise: number,
  isMetro: boolean,
): Promise<{ exemption_paise: number; taxable_hra_paise: number }> {
  const params = new URLSearchParams({
    basic_salary_paise: String(basicSalaryPaise),
    hra_received_paise: String(hraReceivedPaise),
    rent_paid_paise: String(rentPaidPaise),
    is_metro: String(isMetro),
  });
  const res = await fetch(`${API_BASE}/api/income-tax/hra/compute?${params}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`HRA compute failed: ${res.statusText}`);
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? "HRA computation error");
  return json.data;
}

// ── Supabase Queries ───────────────────────────────────────────────────────

export async function getTaxPlanningRecord(
  clientId: string,
  financialYear: string,
): Promise<TaxPlanningRecord | null> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("tax_planning_records")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("financial_year", financialYear)
    .maybeSingle();
  if (error) throw new Error(error.message);
  return data as TaxPlanningRecord | null;
}

export async function saveTaxPlanningRecord(record: TaxPlanningRecord): Promise<string> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("tax_planning_records")
    .upsert({
      firm_id: firmId,
      ...record,
      updated_at: new Date().toISOString(),
    }, { onConflict: "client_id,financial_year" })
    .select("id")
    .single();
  if (error || !data) throw new Error(error?.message ?? "Failed to save tax planning record");
  return data.id as string;
}

export async function getCapitalGains(
  clientId: string,
  financialYear?: string,
): Promise<Record<string, unknown>[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb
    .from("capital_gains")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId);
  if (financialYear) {
    // Filter by FY using sale_date (April 1 to March 31)
    const year = parseInt(financialYear.split("-")[0]);
    q = q.gte("sale_date", `${year}-04-01`).lte("sale_date", `${year + 1}-03-31`);
  }
  const { data, error } = await q.order("sale_date", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Record<string, unknown>[];
}

export async function saveCapitalGain(gain: Record<string, unknown>): Promise<string> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("capital_gains")
    .insert({ firm_id: firmId, ...gain, created_at: new Date().toISOString() })
    .select("id")
    .single();
  if (error || !data) throw new Error(error?.message ?? "Failed to save capital gain");
  return data.id as string;
}

export async function getAdvanceTaxPayments(
  clientId: string,
  financialYear: string,
): Promise<Record<string, unknown>[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("advance_tax_payments")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("financial_year", financialYear)
    .order("installment_number");
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Record<string, unknown>[];
}

export async function getITNotices(clientId: string): Promise<Record<string, unknown>[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("it_notices")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .order("date_received", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Record<string, unknown>[];
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Current financial year string e.g. "2025-26" */
export function currentFinancialYear(): string {
  const now = new Date();
  const yr = now.getFullYear();
  const mo = now.getMonth() + 1;
  return mo >= 4 ? `${yr}-${String(yr + 1).slice(2)}` : `${yr - 1}-${String(yr).slice(2)}`;
}

/** Format paise as ₹ display string */
export function formatPaise(paise: number): string {
  const rupees = Math.floor(Math.abs(paise) / 100);
  const p = Math.abs(paise) % 100;
  const s = rupees.toLocaleString("en-IN");
  return (paise < 0 ? "-₹" : "₹") + s + "." + String(p).padStart(2, "0");
}
