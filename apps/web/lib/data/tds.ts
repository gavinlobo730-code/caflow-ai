/**
 * TDS Engine data layer — 24Q/26Q return computation and filing.
 *
 * IT Act Section 192 — TDS on Salary (Form 24Q)
 * IT Act Section 194 — TDS on non-salary (Form 26Q)
 * IT Act Section 203 — TDS Certificates (Form 16 / 16A)
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
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

export async function compute26Q(req: Compute26QRequest): Promise<TDSReturnPayload> {
  const res = await fetch(`${API_BASE}/api/tds/26q/compute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`26Q compute failed: ${res.statusText}`);
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? "26Q computation error");
  return json.data as TDSReturnPayload;
}

export async function compute24Q(req: Compute24QRequest): Promise<TDSReturnPayload> {
  const res = await fetch(`${API_BASE}/api/tds/24q/compute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!res.ok) throw new Error(`24Q compute failed: ${res.statusText}`);
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? "24Q computation error");
  return json.data as TDSReturnPayload;
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

export async function getTDSChallans(clientId: string, quarter?: string): Promise<Record<string, unknown>[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  let q = sb
    .from("tds_challans")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId);
  if (quarter) q = q.eq("quarter", quarter);
  const { data, error } = await q.order("payment_date", { ascending: false });
  if (error) throw new Error(error.message);
  return (data ?? []) as unknown as Record<string, unknown>[];
}

export async function approveTDSReturn(returnId: string): Promise<void> {
  const sb = getSupabaseClient();
  const { error } = await sb
    .from("tds_returns")
    .update({ status: "ca_approved", ca_approved_at: new Date().toISOString() })
    .eq("id", returnId);
  if (error) throw new Error(error.message);
}

export async function markTDSFiled(returnId: string, prn: string, ackNumber: string): Promise<void> {
  const sb = getSupabaseClient();
  const { error } = await sb
    .from("tds_returns")
    .update({
      status: "filed",
      prn,
      ack_number: ackNumber,
      filed_at: new Date().toISOString(),
    })
    .eq("id", returnId);
  if (error) throw new Error(error.message);
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
