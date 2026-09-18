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
  /** IT Act s.80G's four categories are the PRODUCT of two independent facts
   *  about the donee, and only the percentage was ever sent — so every
   *  donation was deducted at its percentage with no ceiling. s.80G(4) caps
   *  donations in the residual category at 10% of adjusted gross total income.
   *
   *  Omitted, the backend defaults it to true (subject to the limit), which is
   *  the residual category the section itself puts an unlisted donee in and
   *  the direction that cannot over-claim. A fund listed in s.80G(1)(i) — the
   *  PM National Relief Fund and its neighbours — must be marked false. */
  subject_to_qualifying_limit?: boolean;
  /** s.80G(5D) bars a deduction for a cash donation over Rs 2,000. Omitted OR
   *  null means "the CA did not say", which the backend allows while warning —
   *  a zero for "paid by cheque" and a zero for "nobody stated the mode" are
   *  not the same number. null is accepted as well as omission because the
   *  screen holds the tri-state as a value, and `undefined` would be dropped
   *  by JSON.stringify in a way that reads as an oversight rather than a
   *  recorded "not stated". Pydantic's Optional[bool] takes both. */
  paid_in_cash?: boolean | null;
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
  // Authenticated: routers/income_tax.py guards /hra/compute with
  // Depends(rbac("income_tax", "compute")), and core/auth.py answers 401 when
  // there is no Bearer header. This was the one call in this file that sent
  // none, so the HRA calculator could not compute against a real deployment.
  const res = await fetch(`${API_BASE}/api/income-tax/hra/compute?${params}`, {
    method: "POST", headers: await _authHeaders(),
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

/** Who the assessee is. The fifth proviso to IT Act s.112(1) lets a RESIDENT
 *  INDIVIDUAL OR HUF pay the lower of 12.5% without indexation and 20% with
 *  it, on immovable property acquired before 23-07-2024. A company, an LLP or
 *  a non-resident never gets that option. */
export type CapitalGainsAssesseeType =
  | "unspecified"
  | "resident_individual_huf"
  | "other";

export interface ComputeCapitalGainsRequest {
  asset_type: CapitalGainsAssetType | CapitalGainsRegisterAssetType;
  purchase_date: string;   // YYYY-MM-DD
  sale_date: string;       // YYYY-MM-DD
  purchase_cost_paise: number;
  sale_value_paise: number;
  improvement_cost_paise?: number;
  /** Omitted, the backend charges the flat 12.5% and returns both candidate
   *  figures with a note saying why the option was withheld — so an
   *  unanswered question reads as one, rather than as a claim nobody was
   *  entitled to make. */
  assessee_type?: CapitalGainsAssesseeType;
  /** IT-28. Whether the security is LISTED in a recognised stock exchange in
   *  India — the proviso to s.2(42A) gives it a 12-month holding period
   *  against 24 for everything else, and `asset_type` cannot carry it.
   *  A TRI-STATE: `null`/omitted means NOT RECORDED, which takes the unlisted
   *  period (more tax, never less) and comes back as a named gap. */
  is_listed_security?: boolean | null;
  /** IT-19. Fair market value on 31-01-2018 of the WHOLE holding sold — not a
   *  per-share price. s.55(2)(ac) deems the cost of a s.112A asset acquired
   *  before 01-02-2018 to be the higher of the actual cost and the lower of
   *  this and the sale value. Omitted leaves the actual cost standing, which
   *  over-states the gain, and the response names it. */
  fmv_31_01_2018_paise?: number | null;
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
  /** The cost s.48 was actually computed on — the actual cost of acquisition,
   *  or the s.55(2)(ac) deemed cost where the substitution ran. */
  cost_of_acquisition_paise?: number;
  grandfathered_cost_is_applied?: boolean;
  grandfathering_working?: string[];
  /** NOT interchangeable, and rendered differently: `gaps` are facts nobody
   *  recorded that a CA has to go and find, `caveats` are settled reasons a
   *  section does not reach this transfer. */
  gaps?: string[];
  caveats?: string[];
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
  transferred_asset_nature: TransferredAssetNature | null;
  /** Migration 402. Both nullable with no default and nothing back-filled —
   *  `null` is NOT RECORDED, never a guess. */
  is_listed_security: boolean | null;
  fmv_31_01_2018_paise: number | null;
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
  /** IT-19 — what was SOLD, in the vocabulary the s.54 family charges on.
   *  `asset_type` cannot carry it: 'property' covers both a residential house
   *  and a plot, and s.54 reaches one while s.54F reaches the other. Omitted
   *  is a real answer (not recorded) and the exemption working then refuses
   *  rather than guessing. */
  transferred_asset_nature?: TransferredAssetNature | null;
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

// ── s.54 / 54B / 54EC / 54F reinvestment exemption (IT-19) ──────────────────
// Everything here is READ from the backend. The four sections differ in ways
// that decide the figure — s.54F apportions on net consideration where s.54
// takes the lower of two amounts, s.54EC's Rs 50 lakh spans two financial
// years, s.54B reaches a short-term gain — and
// domain/income_tax/reinvestment_exemption.py is the one place that knows it.

export type ReinvestmentSection = "54" | "54B" | "54EC" | "54F";
export type AcquisitionKind = "purchase" | "construction" | "bonds";
export type TransferredAssetNature =
  "residential_house" | "agricultural_land" | "land_or_building" | "other";

export interface ReinvestmentSectionInfo {
  section: ReinvestmentSection;
  heading: string;
  reaches: TransferredAssetNature[];
  requires_long_term: boolean;
  new_asset: string;
  proportionate: boolean;
  cgas_available: boolean;
  invested_cap_paise: number | null;
  lock_in_years: number;
}

export interface ReinvestmentClaim {
  id: string | null;
  section: ReinvestmentSection;
  heading: string;
  new_asset_description: string | null;
  allowed: boolean;
  exemption_paise: number;
  amount_considered_paise: number;
  deadline: string | null;
  within_time: boolean | null;
  working: string[];
  /** Facts nobody recorded. A claim with a gap is NOT allowed — and the
   *  sentence says what to go and record. */
  gaps: string[];
  caveats: string[];
}

export interface CapitalGainExemption {
  gain_paise: number;
  total_exemption_paise: number;
  taxable_gain_paise: number;
  claims: ReinvestmentClaim[];
  gaps: string[];
  caveats: string[];
}

export interface ReinvestmentInput {
  section: ReinvestmentSection;
  new_asset_description: string;
  acquisition_kind?: AcquisitionKind | null;
  acquisition_date?: string | null;
  cost_paise?: number;
  cgas_deposit_paise?: number;
  cgas_deposit_date?: string | null;
  other_residential_houses_owned?: number | null;
  agricultural_use_two_years?: boolean | null;
  new_asset_transferred_on?: string | null;
  notes?: string | null;
}

export async function getReinvestmentSections(): Promise<{
  sections: ReinvestmentSectionInfo[];
  asset_natures: TransferredAssetNature[];
  acquisition_kinds: AcquisitionKind[];
}> {
  const res = await fetch(`${API_BASE}/api/income-tax/capital-gains/sections`, {
    headers: await _authHeaders(),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to load the s.54 sections: ${res.statusText}`);
  return json.data;
}

export async function getCapitalGainExemption(recordId: string): Promise<CapitalGainExemption> {
  const res = await fetch(
    `${API_BASE}/api/income-tax/capital-gains/${encodeURIComponent(recordId)}/exemption`,
    { headers: await _authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to load the exemption working: ${res.statusText}`);
  return json.data as CapitalGainExemption;
}

export async function addReinvestment(recordId: string, req: ReinvestmentInput): Promise<{ id: string }> {
  const res = await fetch(
    `${API_BASE}/api/income-tax/capital-gains/${encodeURIComponent(recordId)}/reinvestments`,
    { method: "POST", headers: await _authHeaders(), body: JSON.stringify(req) });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to record the claim: ${res.statusText}`);
  return json.data;
}

export async function deleteReinvestment(recordId: string, claimId: string): Promise<void> {
  // One template literal, deliberately: the reachability scan matches the
  // path as written, and a URL split across a concatenation reads to it as an
  // endpoint no screen calls.
  const path = `/api/income-tax/capital-gains/${encodeURIComponent(recordId)}/reinvestments/${encodeURIComponent(claimId)}`;
  const res = await fetch(`${API_BASE}${path}`,
    { method: "DELETE", headers: await _authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to delete the claim: ${res.statusText}`);
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
  /** §211(1) proviso — a §44AD/§44ADA assessee pays the whole advance tax by
   *  15 March, so there is ONE instalment and §234C(1)(b) is the charging limb.
   *  Sent, never inferred: whether the presumptive scheme is opted into is the
   *  CA's determination, not something a tax figure reveals (IT-06). */
  is_presumptive_44ad_44ada?: boolean;
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
  /** "Section 234C(1)(a)" or "Section 234C(1)(b)" — the LIMB, because they are
   *  different sentences with different schedules. */
  section_ref: string;
  is_presumptive_44ad_44ada: boolean;
  /** The statute the answer rests on, in one sentence, for the CA to check. */
  basis: string;
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

/** One section's interest, as apps/api/routers/income_tax._section_interest_payload
 *  serves it. `reasons` is shown rather than summarised: each sentence names
 *  the rule applied and the figures it was applied to, which is what a CA
 *  checks. */
export interface SectionInterestResult {
  section: string;
  applies: boolean;
  base_paise: number;
  months: number;
  interest_paise: number;
  from_date: string | null;
  to_date: string | null;
  reasons: string[];
}

/** The §139(1) due date and its provenance. `decided: false` means the statute
 *  does not settle it on facts this app holds, the EARLIER of the two dates was
 *  taken, and the §234A interest below is therefore a FLOOR — early costs
 *  nothing and late costs exactly this interest. */
export interface ITRDueDateBasis {
  financial_year: string;
  due_date: string;
  is_audit: boolean;
  decided: boolean;
  basis: string;
  statutory_gaps: string[];
}

export interface Section234ABRequest {
  fy: string;
  tax_on_total_income_paise: number;
  assessed_tax_paise?: number | null;
  tds_tcs_paise?: number;
  advance_tax_paid_paise?: number;
  relief_paise?: number;
  /** null / omitted means NOT YET FURNISHED, which is NOT nil interest — the
   *  engine runs the period to the assessment date and says it is still
   *  running. Reporting zero for an unfiled return would tell a CA the
   *  cheapest moment to file is never. */
  return_furnished_on?: string | null;
  assessment_date?: string | null;
  entity_type?: string | null;
  has_tax_audit_engagement?: boolean;
  has_transfer_pricing_report?: boolean;
}

export interface Section234ABResult {
  fy: string;
  section_234a: SectionInterestResult;
  section_234b: SectionInterestResult;
  total_interest_paise: number;
  /** §140A(1)'s own figure — the tax payable on the basis of the return after
   *  the TDS/TCS, advance tax and §90/90A/91 relief the section names. Served
   *  from this endpoint because it already has all four inputs; the §140A
   *  panel passes it straight through rather than subtracting them itself. */
  section_140a_tax_due_paise: number;
  itr_due_date: ITRDueDateBasis;
  assessment_date: string;
  return_furnished_on: string | null;
}

/** Stateless §234A (filing late) and §234B (advance tax short of 90%) — computes
 *  only, never persists. The §139(1) due date is NOT sent: it is derived by
 *  compliance_obligation_service.itr_due_date_for_client, the one authority for
 *  it, and comes back with its own basis. */
export async function computeSection234ABInterest(req: Section234ABRequest): Promise<Section234ABResult> {
  const res = await fetch(`${API_BASE}/api/income-tax/interest/234ab`, {
    method: "POST", headers: await _authHeaders(), body: JSON.stringify(req),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `234A/234B compute failed: ${res.statusText}`);
  return json.data as Section234ABResult;
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

// ── §140A self-assessment tax — the Challan 280 (IT-13) ─────────────────────
// IT Act §140A(1) makes the tax, interest and fee on a return payable BEFORE
// the return is furnished, and requires the return to be "accompanied by proof
// of payment". That proof is a Challan 280. Nothing here recorded one, so
// Schedule IT was keyed off a bank receipt and the ITR keying sheet printed
// §140A as a structural nil.
//
// EVERY FIGURE IS THE SERVER'S. The appropriation order — fee, then interest,
// then tax — is `domain/income_tax/self_assessment.py`, and no part of it is
// restated here.

export interface SelfAssessmentChallan {
  id: string;
  client_id: string;
  financial_year: string;
  bsr_code: string;
  deposit_date: string;
  challan_serial_no: string;
  tax_paise: number;
  surcharge_paise: number;
  cess_paise: number;
  interest_paise: number;
  fee_paise: number;
  /** What left the bank account, and what Schedule IT's Amount column takes. */
  total_paise: number;
  major_head: string;
  minor_head: string;
  bank_name: string | null;
  notes: string | null;
}

/** How the aggregate paid lands across §140A(1)'s three heads. `null` where no
 *  tax due was supplied — appropriating against a liability nobody has
 *  computed would invent an outstanding figure. */
export interface SelfAssessmentAppropriation {
  towards_fee_paise: number;
  towards_interest_paise: number;
  towards_tax_paise: number;
  fee_outstanding_paise: number;
  interest_outstanding_paise: number;
  tax_outstanding_paise: number;
  total_applied_paise: number;
  is_fully_paid: boolean;
}

export interface SelfAssessmentPosition {
  financial_year: string;
  challans: SelfAssessmentChallan[];
  total_paid_paise: number;
  appropriation: SelfAssessmentAppropriation | null;
  /** Actionable — a mis-headed challan, a split that does not foot, §140A(3). */
  gaps: string[];
  /** Settled statements the CA should read once, not act on. */
  caveats: string[];
  verified: boolean;
}

export interface SelfAssessmentChallanInput {
  client_id: string;
  financial_year: string;
  bsr_code: string;
  deposit_date: string;
  challan_serial_no: string;
  tax_paise: number;
  surcharge_paise: number;
  cess_paise: number;
  interest_paise: number;
  fee_paise: number;
  total_paise: number;
  major_head?: string;
  minor_head?: string;
  bank_name?: string | null;
  notes?: string | null;
}

/** The year's challans and, where the dues are known, the §140A appropriation.
 *  The three dues are OPTIONAL: a CA records a challan before the computation
 *  is finished, and the server names the absence rather than defaulting it. */
export async function getSelfAssessmentPosition(
  clientId: string,
  fy: string,
  dues?: { taxDuePaise?: number; interestDuePaise?: number; feeDuePaise?: number },
): Promise<SelfAssessmentPosition> {
  const params = new URLSearchParams({ client_id: clientId, fy });
  if (dues?.taxDuePaise !== undefined) params.set("tax_due_paise", String(dues.taxDuePaise));
  if (dues?.interestDuePaise !== undefined) params.set("interest_due_paise", String(dues.interestDuePaise));
  if (dues?.feeDuePaise !== undefined) params.set("fee_due_paise", String(dues.feeDuePaise));
  const res = await fetch(`${API_BASE}/api/income-tax/self-assessment?${params}`, { headers: await _authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to load self-assessment challans: ${res.statusText}`);
  return json.data as SelfAssessmentPosition;
}

export async function createSelfAssessmentChallan(req: SelfAssessmentChallanInput): Promise<SelfAssessmentChallan> {
  const res = await fetch(`${API_BASE}/api/income-tax/self-assessment`, {
    method: "POST", headers: await _authHeaders(), body: JSON.stringify(req),
  });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to record the challan: ${res.statusText}`);
  return json.data as SelfAssessmentChallan;
}

export async function deleteSelfAssessmentChallan(challanId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/income-tax/self-assessment/${challanId}`,
    { method: "DELETE", headers: await _authHeaders() });
  const json = await res.json();
  if (!res.ok || !json.success) throw new Error(json.error ?? `Failed to remove the challan: ${res.statusText}`);
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
