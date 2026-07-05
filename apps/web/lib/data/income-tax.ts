/**
 * Income Tax data layer — ITR computation via backend engine.
 * IT Act 1961 — all amounts in paise (integer arithmetic).
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to Income Tax Portal
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "./getFirmId";
import { currentFinancialYearLabel } from "@/lib/dateMath";

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
  /** Financial year e.g. "2025-26" — omit to default to the current FY. */
  fy?: string;
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
  /** Section 80CCD(2) — employer NPS contribution, available under BOTH
   * regimes (unlike every other Chapter VI-A deduction here). */
  employer_nps_80ccd2_paise?: number;
  is_government_employee?: boolean;
  salary_for_80ccd2_paise?: number;
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
  fy: string;
  rates_verified: boolean;
  income: {
    gross_total_paise: number;
    standard_deduction_paise: number;
    total_deductions_paise: number;
    taxable_income_paise: number;
  };
  deductions: {
    s80c_paise: number;
    s80ccd_paise: number;
    s80ccd2_paise: number;
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
  tuition_fees_paise?: number;
  other_80c_paise?: number;
  hra_paise?: number;
  nps_80ccd_paise?: number;
  health_insurance_80d_paise?: number;
  home_loan_interest_24b_paise?: number;
  other_deductions_paise?: number;
  regime?: "old" | "new";
  tax_paise?: number;
}

// ── API Calls ──────────────────────────────────────────────────────────────

/** Compute ITR via backend engine. All computation server-side. */
export async function computeITR(req: ComputeITRRequest): Promise<ITRComputeResult> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token;
  const res = await fetch(`${API_BASE}/api/income-tax/compute`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
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
    }, { onConflict: "firm_id,client_id,financial_year" })
    .select("id")
    .single();
  if (error || !data) throw new Error(error?.message ?? "Failed to save tax planning record");
  return data.id as string;
}

// ── Capital gains (R3.1b) ──────────────────────────────────────────────────
// Section 45/48/2(42A)/111A/112A/112/115BBH/50AA — all computed server-side
// by domain/income_tax/capital_gains_engine.py. Previously this file (and,
// separately and more consequentially, apps/web/app/income-tax/capital-gains/
// page.tsx's own inline logic) read/wrote the capital_gains table directly
// from the browser, computing gain_type/tax_rate_percent/indexed_cost_paise
// client-side with no server-side validation.

export type CapitalGainsAssetType = "equity" | "debt_mf" | "property" | "unlisted" | "vda" | "gold";
export type CapitalGainsRegisterAssetType = "equity_shares" | "mutual_funds" | "property" | "bonds" | "other";

export interface ComputeCapitalGainsRequest {
  asset_type: CapitalGainsAssetType | CapitalGainsRegisterAssetType;
  purchase_date: string;   // YYYY-MM-DD
  sale_date: string;       // YYYY-MM-DD
  purchase_cost_paise: number;
  sale_value_paise: number;
  improvement_cost_paise?: number;
}

export interface CapitalGainsComputeResult {
  holding_months: number;
  is_long_term: boolean;
  gain_type: "STCG" | "LTCG";
  gain_paise: number;
  indexed_cost_paise: number;
  gain_with_indexation_paise: number;
  tax_rate_percent: number;
  tax_with_indexation_percent: number | null;
  /** Both amounts pre-computed server-side — never re-derive tax_rate_percent
   * * gain_paise client-side (the backend rounds with integer round-half-up,
   * not float Math.round, so a client-side re-derivation could disagree by
   * a paise in edge cases). */
  tax_without_indexation_paise: number;
  tax_with_indexation_paise: number | null;
  tax_liability_paise: number;
  section_ref: string;
  note: string;
  is_slab_rate_estimate: boolean;
}

export interface CapitalGainsRecord {
  id: string;
  client_id: string;
  asset_description: string;
  asset_type: CapitalGainsRegisterAssetType;
  purchase_date: string;
  sale_date: string;
  purchase_cost_paise: number;
  improvement_cost_paise: number;
  sale_value_paise: number;
  indexed_cost_paise: number | null;
  gain_type: "STCG" | "LTCG" | null;
  tax_rate_percent: number | null;
  created_at: string;
}

async function _authHeaders(): Promise<Record<string, string>> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const token = session?.access_token;
  return { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

/** Stateless capital-gains estimator — computes only, never persists. */
export async function computeCapitalGains(req: ComputeCapitalGainsRequest): Promise<CapitalGainsComputeResult> {
  const res = await fetch(`${API_BASE}/api/income-tax/capital-gains/compute`, {
    method: "POST", headers: await _authHeaders(), body: JSON.stringify(req),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Capital gains compute failed: ${res.statusText}`);
  return json.data as CapitalGainsComputeResult;
}

export async function listCapitalGains(clientId: string): Promise<CapitalGainsRecord[]> {
  const res = await fetch(`${API_BASE}/api/income-tax/capital-gains?client_id=${encodeURIComponent(clientId)}`, {
    headers: await _authHeaders(),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to load capital gains: ${res.statusText}`);
  return (json.data ?? []) as CapitalGainsRecord[];
}

export interface CreateCapitalGainRequest extends ComputeCapitalGainsRequest {
  client_id: string;
  asset_description: string;
  asset_type: CapitalGainsRegisterAssetType;
}

/** Computes AND persists a register entry — gain_type/tax_rate_percent/
 * indexed_cost_paise are computed server-side, never sent by the caller. */
export async function createCapitalGain(req: CreateCapitalGainRequest): Promise<CapitalGainsRecord> {
  const res = await fetch(`${API_BASE}/api/income-tax/capital-gains`, {
    method: "POST", headers: await _authHeaders(), body: JSON.stringify(req),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to save capital gain: ${res.statusText}`);
  return json.data as CapitalGainsRecord;
}

export async function deleteCapitalGain(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/income-tax/capital-gains/${encodeURIComponent(id)}`, {
    method: "DELETE", headers: await _authHeaders(),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to delete capital gain: ${res.statusText}`);
}

/** Cost Inflation Index table (Section 48, 2nd proviso) — fetched from the
 * backend so the reference display can never drift from the table the
 * engine actually computes with (see capital_gains_engine.py). */
export async function getCiiTable(): Promise<{ ciiByFy: Record<string, number>; latestVerifiedFy: string }> {
  const res = await fetch(`${API_BASE}/api/income-tax/capital-gains/cii-table`, { headers: await _authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to load CII table: ${res.statusText}`);
  return { ciiByFy: json.data.cii_by_fy, latestVerifiedFy: json.data.latest_verified_fy };
}

// ── Advance tax interest (R3.13a) ───────────────────────────────────────────
// Section 207/208/234C — all computed server-side by
// domain/income_tax/advance_tax_interest_engine.py. Previously
// apps/web/app/income-tax/advance-tax/page.tsx computed interest itself
// with an incorrect formula (actual-payment-delay months, no 12%/36%
// trigger tolerance — the Section 234B shape, not 234C's fixed 3/3/3/1
// month periods) and wrote straight to advance_tax_payments from the
// browser with no server-side validation.

export interface AdvanceTaxInstallmentInput {
  installment_number: 1 | 2 | 3 | 4;
  paid_amount_paise: number;
  paid_date?: string | null; // YYYY-MM-DD
  challan_number?: string | null;
}

export interface ComputeAdvanceTaxRequest {
  fy: string;
  estimated_tax_paise: number;
  installments: AdvanceTaxInstallmentInput[];
}

export interface AdvanceTaxInstallmentResult {
  installment_number: 1 | 2 | 3 | 4;
  due_date: string;
  cumulative_required_percent: number;
  trigger_percent: number;
  required_cumulative_paise: number;
  actual_cumulative_paid_paise: number;
  is_short: boolean;
  shortfall_paise: number;
  interest_months: number;
  interest_paise: number;
}

export interface AdvanceTaxComputeResult {
  fy: string;
  estimated_tax_paise: number;
  total_interest_paise: number;
  section_ref: string;
  installments: AdvanceTaxInstallmentResult[];
}

export interface AdvanceTaxRecord {
  id: string;
  client_id: string;
  financial_year: string;
  installment_number: 1 | 2 | 3 | 4;
  due_date: string;
  required_percent: number;
  estimated_tax_paise: number;
  paid_amount_paise: number;
  paid_date: string | null;
  challan_number: string | null;
}

export interface SaveAdvanceTaxRequest extends ComputeAdvanceTaxRequest {
  client_id: string;
}

/** Stateless Section 234C interest estimator — computes only, never persists. */
export async function computeAdvanceTaxInterest(req: ComputeAdvanceTaxRequest): Promise<AdvanceTaxComputeResult> {
  const res = await fetch(`${API_BASE}/api/income-tax/advance-tax/compute`, {
    method: "POST", headers: await _authHeaders(), body: JSON.stringify(req),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Advance tax compute failed: ${res.statusText}`);
  return json.data as AdvanceTaxComputeResult;
}

export async function listAdvanceTaxPayments(clientId: string, fy: string): Promise<AdvanceTaxRecord[]> {
  const params = new URLSearchParams({ client_id: clientId, fy });
  const res = await fetch(`${API_BASE}/api/income-tax/advance-tax?${params}`, { headers: await _authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to load advance tax payments: ${res.statusText}`);
  return (json.data ?? []) as AdvanceTaxRecord[];
}

/** Persists the recorded payment facts — due_date/required_percent are
 * always derived server-side from the FY's Section 208 schedule, never
 * sent by the caller. Interest is never stored (it's derived, not a
 * fact) — call computeAdvanceTaxInterest() for the current breakdown. */
export async function saveAdvanceTaxPayments(req: SaveAdvanceTaxRequest): Promise<AdvanceTaxRecord[]> {
  const res = await fetch(`${API_BASE}/api/income-tax/advance-tax`, {
    method: "POST", headers: await _authHeaders(), body: JSON.stringify(req),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to save advance tax payments: ${res.statusText}`);
  return json.data as AdvanceTaxRecord[];
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
  return currentFinancialYearLabel();
}

/** Format paise as ₹ display string */
export function formatPaise(paise: number): string {
  const rupees = Math.floor(Math.abs(paise) / 100);
  const p = Math.abs(paise) % 100;
  const s = rupees.toLocaleString("en-IN");
  return (paise < 0 ? "-₹" : "₹") + s + "." + String(p).padStart(2, "0");
}
