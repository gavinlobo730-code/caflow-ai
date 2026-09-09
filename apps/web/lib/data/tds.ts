/**
 * TDS Engine data layer — 24Q/26Q return computation and filing.
 *
 * IT Act Section 192 — TDS on Salary (Form 24Q)
 * IT Act Section 194 — TDS on non-salary (Form 26Q)
 * IT Act Section 203 — TDS Certificates (Form 16 / 16A)
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to the e-filing portal or any
 * government portal. Returns are uploaded manually on incometax.gov.in;
 * TRACES is post-filing only.
 * All amounts in integer paise. Never float.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "./getFirmId";
import { currentFinancialYearLabel } from "@/lib/dateMath";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

export type TDSReturnStatus = "pending" | "prepared" | "ca_approved" | "filed" | "revised";
export type TDSReturnType = "24Q" | "26Q" | "27Q" | "27EQ";
export type TDSQuarter = "Q1" | "Q2" | "Q3" | "Q4";

export interface TDSDeductee {
  deductee_name: string;
  deductee_pan: string;
  section: string;
  nature_of_payment: string;
  payment_date: string;
  payment_amount_paise: number;
  tds_rate_pct: number;
  tds_deducted_paise: number;
  tds_deposited_paise: number;
  challan_no: string;
  bsr_code: string;
  challan_date: string;
  is_lower_deduction?: boolean;
  lower_deduction_cert?: string;
}

export interface TDSChallan {
  challan_no: string;
  bsr_code: string;
  payment_date: string;
  tds_paise: number;
  surcharge_paise?: number;
  interest_paise?: number;
  total_paise: number;
  bank_name?: string;
  section?: string;
}

export interface Compute26QRequest {
  client_id: string;
  tan: string;
  deductor_name: string;
  deductor_pan: string;
  deductor_address: string;
  financial_year: string;
  quarter: TDSQuarter;
  deductees: TDSDeductee[];
  challans?: TDSChallan[];
}

export interface Compute24QRequest {
  client_id: string;
  tan: string;
  deductor_name: string;
  deductor_pan: string;
  deductor_address: string;
  financial_year: string;
  quarter: TDSQuarter;
  deductees: TDSDeductee[];
  challans?: TDSChallan[];
}

export interface TDSReturnPayload {
  form: "24Q" | "26Q";
  tan: string;
  deductor_name: string;
  financial_year: string;
  quarter: string;
  quarter_end_date: string;
  total_salary_paise?: number;
  total_payment_paise?: number;
  total_tds_deducted_paise: number;
  total_tds_deposited_paise: number;
  deductee_count: number;
  deductees: TDSDeductee[];
  challans: TDSChallan[];
  validation_errors: string[];
  warnings: string[];
}

export interface TDSReturn {
  id: string;
  client_id: string;
  return_type: TDSReturnType;
  financial_year: string;
  quarter: TDSQuarter;
  due_date: string;
  total_deductions_paise: number;
  total_deposits_paise: number;
  deductee_count: number;
  status: TDSReturnStatus;
  prn?: string;
  ack_number?: string;
  filed_at?: string;
  fvu_json?: TDSReturnPayload;
  validation_errors: string[];
}

// ── API Calls ──────────────────────────────────────────────────────────────

// AUTHENTICATED, like every other call in this file. Both of these used to be
// a bare fetch carrying only Content-Type, while routers/tds.py guards each
// with Depends(rbac("tds","compute")) and core/auth.py raises 401 when there is
// no Bearer header (the dev fallback applies only when SUPABASE_URL is unset).
// So "Prepare a Return" could not compute anything in production — it threw
// "26Q compute failed: Unauthorized" whatever the books held (TDS-03).
export async function compute26Q(req: Compute26QRequest): Promise<TDSReturnPayload> {
  const json = await authedFetch<TDSReturnPayload>("/api/tds/26q/compute", {
    method: "POST", body: JSON.stringify(req),
  });
  if (!json.success) throw new Error(json.error ?? "26Q computation error");
  return json.data;
}

export async function compute24Q(req: Compute24QRequest): Promise<TDSReturnPayload> {
  const json = await authedFetch<TDSReturnPayload>("/api/tds/24q/compute", {
    method: "POST", body: JSON.stringify(req),
  });
  if (!json.success) throw new Error(json.error ?? "24Q computation error");
  return json.data;
}

/** Authenticated fetch to the TDS API — the ONE way this file talks to it.
 *
 * Every route it reaches is Depends(rbac("tds", …)), and core/auth.py answers
 * 401 to a request with no Bearer header, so a bare fetch here is not a style
 * choice: it is a call that cannot succeed. Declared below its first callers
 * because function declarations hoist; the alternative is moving it above the
 * types, which reads worse. */
async function authedFetch<T>(path: string, init?: RequestInit): Promise<{ success: boolean; data: T; error: string | null }> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  return res.json();
}

export interface TDSSection {
  section: string;
  threshold_paise: number;
  aggregate_threshold_paise: number | null;
  rate_individual_pct: number;
  rate_company_pct: number;
}

export interface TDSAmountResult {
  section: string;
  fy: string;
  rates_verified: boolean;
  payment_amount_paise: number;
  threshold_paise: number;
  aggregate_threshold_paise: number | null;
  tds_applicable: boolean;
  applicable_rate_pct: number;
  tds_paise: number;
}

/** IT Act Chapter XVII-B section list with current thresholds/rates — the
 * authoritative replacement for a hardcoded section dropdown. */
export async function listTdsSections(fy?: string): Promise<{ fy: string; rates_verified: boolean; sections: TDSSection[] }> {
  const resp = await authedFetch<{ fy: string; rates_verified: boolean; sections: TDSSection[] }>(
    `/api/tds/sections${fy ? `?fy=${encodeURIComponent(fy)}` : ""}`
  );
  if (!resp.success) throw new Error(resp.error ?? "Failed to load TDS sections");
  return resp.data;
}

/** Single-payment TDS calculation via the authoritative TDSComputer.resolve_tds().
 * Pass `pan` when known so is_company/§206AA are derived server-side the same
 * way the real purchase-bill TDS deduction already does — never re-derive
 * individual-vs-company or no-PAN rules on the frontend. */
export async function computeTdsAmount(params: {
  section: string;
  payment_amount_paise: number;
  pan?: string | null;
  fy?: string;
}): Promise<TDSAmountResult> {
  const resp = await authedFetch<TDSAmountResult>("/api/tds/compute-amount", {
    method: "POST",
    body: JSON.stringify(params),
  });
  if (!resp.success) throw new Error(resp.error ?? "TDS calculation failed");
  return resp.data;
}

/** What the server answers when a deduction is recorded or re-costed.
 *
 *  `explain` is the engine's working, not decoration. A CA needs to see WHY a
 *  figure is what it is — below the threshold, floored by §206AA, or charged on
 *  a year's aggregate with §200 crediting what earlier entries withheld — and
 *  `gaps` names what the calculation could not see. */
export type DeductionExplain = {
  applies: boolean;
  reason: string | null;
  rate_pct: number;
  tds_paise: number;
  fy_prior_taxable_paise: number;
  fy_prior_tds_paise: number;
  gaps: string[];
  gap_messages: string[];
};

export type RecordedDeduction = Record<string, unknown> & {
  id?: string;
  explain?: DeductionExplain;
};

/** Record a deduction. THE RATE AND THE TAX ARE NOT SENT — they are the
 *  engine's answers (IT Act Chapter XVII-B), resolved server-side from the
 *  section, the amount, the payee's PAN and the year's running aggregate.
 *
 *  This replaces a browser-side `Math.round(gross * rate / 100)` against a
 *  hardcoded table that had §194D and §194H at 5% where the statute says 2%,
 *  §194C flat at the company rate, §194Q on the whole sum instead of the
 *  excess, and no threshold on anything. */
export async function createTdsDeduction(body: {
  client_id: string;
  deductee_name: string;
  deductee_pan?: string | null;
  section: string;
  payment_amount_paise: number;
  transaction_date: string;
  nature_of_payment?: string | null;
  challan_no?: string | null;
  notes?: string | null;
}): Promise<RecordedDeduction> {
  const resp = await authedFetch<RecordedDeduction>("/api/tds-workspace/deductions", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!resp.success) throw new Error(resp.error ?? "Could not record the deduction");
  return resp.data;
}

/** What WOULD be deducted, without recording anything.
 *
 *  Uses the SAME server function as the save, so the figure a CA approves is
 *  the figure that lands. Deliberately NOT computeTdsAmount(): that endpoint
 *  has no place for the year's running aggregate, so it always answers as
 *  though this were the payee's first payment — and on the entry that crosses
 *  a §194C/§194H/§194J aggregate threshold that is the whole difference. */
export async function previewTdsDeduction(body: {
  client_id: string;
  deductee_name: string;
  deductee_pan?: string | null;
  section: string;
  payment_amount_paise: number;
  transaction_date: string;
}): Promise<{
  tds_rate_pct: number;
  tds_paise: number;
  quarter: string;
  financial_year: string;
  explain: DeductionExplain;
}> {
  const resp = await authedFetch<{
    tds_rate_pct: number; tds_paise: number; quarter: string;
    financial_year: string; explain: DeductionExplain;
  }>("/api/tds-workspace/deductions/preview", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!resp.success) throw new Error(resp.error ?? "Could not compute the deduction");
  return resp.data;
}

/** Correct a hand-entered deduction; the engine re-runs on whatever changed.
 *  A row that came from a purchase bill is refused server-side — it is rebuilt
 *  from the bill on every receive, so an edit here would silently revert. */
export async function updateTdsDeduction(
  id: string,
  body: Partial<{
    deductee_name: string;
    deductee_pan: string | null;
    section: string;
    payment_amount_paise: number;
    transaction_date: string;
    nature_of_payment: string | null;
    challan_no: string | null;
    notes: string | null;
  }>,
): Promise<RecordedDeduction> {
  const resp = await authedFetch<RecordedDeduction>(
    `/api/tds-workspace/deductions/${encodeURIComponent(id)}`,
    { method: "PATCH", body: JSON.stringify(body) });
  if (!resp.success) throw new Error(resp.error ?? "Could not update the deduction");
  return resp.data;
}

/** Remove a hand-entered deduction. Manager+ server-side (tds:write), the same
 *  tier migration 345 gives DELETE on the table. */
export async function deleteTdsDeduction(id: string): Promise<void> {
  const resp = await authedFetch<{ deleted: string }>(
    `/api/tds-workspace/deductions/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!resp.success) throw new Error(resp.error ?? "Could not delete the deduction");
}

// ── Supabase Queries ───────────────────────────────────────────────────────

export async function getTDSReturns(clientId: string): Promise<TDSReturn[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("tds_returns")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .order("financial_year", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as TDSReturn[];
}

export async function getTDSDeductions(
  clientId: string,
  financialYear?: string,
  quarter?: string,
): Promise<Record<string, unknown>[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb
    .from("tds_deductions")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId);
  if (financialYear) q = q.eq("financial_year", financialYear);
  if (quarter) q = q.eq("quarter", quarter);
  const { data, error } = await q.order("transaction_date", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Record<string, unknown>[];
}

/** The quarter's deposits.
 *
 *  BOTH halves of the period, or neither. tds_challans holds financial_year
 *  and quarter separately (migration 037) and this filtered on the quarter
 *  alone, so a return for Q3 2026-27 also collected every Q3 challan the
 *  client had ever deposited — reconciling this year's deduction against last
 *  year's payment, and reporting a shortfall or a surplus that is not real. */
export async function getTDSChallans(
  clientId: string,
  financialYear?: string,
  quarter?: string,
): Promise<Record<string, unknown>[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb
    .from("tds_challans")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId);
  if (financialYear) q = q.eq("financial_year", financialYear);
  if (quarter) q = q.eq("quarter", quarter);
  const { data, error } = await q.order("payment_date", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Record<string, unknown>[];
}

/** Status transitions go through the backend (PATCH /returns/{id}/status)
 * rather than writing tds_returns directly from the browser — the backend
 * enforces the explicit CA-confirmation gate, requires a PRN before "filed",
 * and records an audit-log entry + timeline event that a direct Supabase
 * write from here would silently skip. */
export async function approveTDSReturn(returnId: string): Promise<void> {
  const resp = await authedFetch(`/api/tds-workspace/returns/${returnId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status: "ca_approved", ca_approved: true }),
  });
  if (!resp.success) throw new Error(resp.error ?? "Approval failed");
}

export async function markTDSFiled(returnId: string, prn: string, ackNumber: string): Promise<void> {
  const resp = await authedFetch(`/api/tds-workspace/returns/${returnId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status: "filed", ca_approved: true, prn, ack_number: ackNumber }),
  });
  if (!resp.success) throw new Error(resp.error ?? "Failed to mark as filed");
}

export async function saveTDSReturn(
  clientId: string,
  payload: TDSReturnPayload,
  status: TDSReturnStatus = "prepared",
): Promise<string> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  const { data, error } = await sb
    .from("tds_returns")
    .upsert({
      firm_id: firmId,
      client_id: clientId,
      return_type: payload.form,
      financial_year: payload.financial_year,
      quarter: payload.quarter as TDSQuarter,
      quarter_end: payload.quarter_end_date,
      due_date: computeDueDate(payload.quarter, payload.financial_year),
      total_deductions_paise: payload.total_tds_deducted_paise,
      total_deposits_paise: payload.total_tds_deposited_paise,
      deductee_count: payload.deductee_count,
      status,
      fvu_json: payload,
      validation_errors: payload.validation_errors,
      updated_at: new Date().toISOString(),
    }, {
      onConflict: "client_id,return_type,financial_year,quarter",
    })
    .select("id")
    .single();

  if (error || !data) throw new Error(error?.message ?? "Failed to save TDS return");
  return data.id as string;
}

export function downloadTDSJSON(payload: TDSReturnPayload): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `TDS_${payload.form}_${payload.financial_year}_${payload.quarter}_${payload.tan}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Helpers ────────────────────────────────────────────────────────────────

/** Quarter due dates — 31 Jul, 31 Oct, 31 Jan, 31 May (CBDT circular) */
function computeDueDate(quarter: string, fy: string): string {
  const year = parseInt(fy.split("-")[0]);
  const map: Record<string, string> = {
    Q1: `${year}-07-31`,
    Q2: `${year}-10-31`,
    Q3: `${year + 1}-01-31`,
    Q4: `${year + 1}-05-31`,
  };
  return map[quarter] ?? `${year + 1}-05-31`;
}

export function currentFinancialYear(): string {
  return currentFinancialYearLabel();
}

export function currentQuarter(): TDSQuarter {
  const mo = new Date().getMonth() + 1;
  if (mo >= 4 && mo <= 6) return "Q1";
  if (mo >= 7 && mo <= 9) return "Q2";
  if (mo >= 10 && mo <= 12) return "Q3";
  return "Q4";
}
