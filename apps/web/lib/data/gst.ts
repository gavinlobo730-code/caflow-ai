/**
 * GST Engine data layer — GSTR-1 and GSTR-3B payload generation.
 *
 * Architecture:
 *   1. Fetch raw data from Supabase (transactions, gstr2a_records)
 *   2. POST to FastAPI /api/gst/* for computation (pure Python, testable)
 *   3. Store result in gstr1_returns / gstr3b_returns in Supabase
 *
 * CGST Act Section 37 — GSTR-1 (outward supplies)
 * CGST Act Section 39 — GSTR-3B (summary return)
 * All amounts in integer paise. Never float.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { getFirmId } from "./getFirmId";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────

export type GSTInvoiceCategory =
  | "B2B" | "B2CS" | "B2CL" | "CDNR" | "CDNA"
  | "EXP_WP" | "EXP_WOP" | "NIL_EXEMPT";

export type SupplyType = "taxable" | "zero_rated" | "nil_rated" | "exempt" | "non_gst";
export type InvoiceType = "Regular" | "SEZ_with_payment" | "SEZ_without_payment" | "Deemed_export";
export type GSTReturnStatus = "draft" | "validated" | "ca_approved" | "submitted";

export interface GSTTransaction {
  id: string;
  transaction_type: string;
  transaction_date: string;
  reference_no: string | null;
  party_name: string;
  party_gstin: string | null;
  place_of_supply: string | null;
  is_interstate: boolean;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  cess_paise: number;
  is_reverse_charge: boolean;
  supply_type: SupplyType;
  invoice_type: InvoiceType;
  gst_invoice_category: GSTInvoiceCategory | null;
  original_invoice_id: string | null;
  status: string;
}

export interface GSTR2ARecord {
  id: string;
  supplier_gstin: string;
  supplier_name: string | null;
  invoice_number: string;
  invoice_date: string | null;
  taxable_value_paise: number;
  igst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
}

export interface GSTR3BWorking {
  outward: {
    taxable_igst_paise: number;
    taxable_cgst_paise: number;
    taxable_sgst_paise: number;
    zero_rated_paise: number;
    nil_exempt_paise: number;
  };
  itc: {
    book_igst_paise: number;
    book_cgst_paise: number;
    book_sgst_paise: number;
    gstr2a_igst_paise: number;
    gstr2a_cgst_paise: number;
    gstr2a_sgst_paise: number;
    eligible_igst_paise: number;
    eligible_cgst_paise: number;
    eligible_sgst_paise: number;
    rule_36_4_cap_applied: boolean;
  };
  net_payable: {
    igst_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    total_paise: number;
  };
}

export interface ValidationError {
  field: string;
  message: string;
  invoice_ref: string | null;
  severity: "error" | "warning";
}

export interface GSTR3BComputeResult {
  payload: Record<string, unknown>;
  working: GSTR3BWorking;
  validation_warnings: ValidationError[];
  period: string;
  gstin: string;
  ca_review_required: true;
}

export interface GSTR1BuildResult {
  payload: Record<string, unknown>;
  summary: {
    period: string;
    gstin: string;
    counts: Record<string, number>;
    totals_rupees: Record<string, number>;
  };
  invoice_count: number;
  taxable_total_rupees: number;
  tax_total_rupees: number;
  validation_errors: ValidationError[];
  validation_warnings: ValidationError[];
  ca_review_required: true;
}

export interface ClassifyResult {
  results: Record<string, GSTInvoiceCategory>;
  counts: Record<string, number>;
  total: number;
}

// ── Period helpers ─────────────────────────────────────────────────────────

/** Convert YYYY-MM to GSTN period MMYYYY. */
export function toPeriod(yearMonth: string): string {
  const [yyyy, mm] = yearMonth.split("-");
  return `${mm}${yyyy}`;
}

/** Convert GSTN period MMYYYY to YYYY-MM. */
export function fromPeriod(period: string): string {
  const mm = period.slice(0, 2);
  const yyyy = period.slice(2);
  return `${yyyy}-${mm}`;
}

/** Get the last day of a month for date range queries. */
function lastDayOfMonth(yearMonth: string): string {
  const [yyyy, mm] = yearMonth.split("-").map(Number);
  const last = new Date(yyyy, mm, 0).getDate();
  return `${yearMonth}-${String(last).padStart(2, "0")}`;
}

// ── Data Fetchers ──────────────────────────────────────────────────────────

/** Fetch all posted sales and credit/debit note transactions for a period. */
export async function fetchSalesTransactions(
  clientId: string,
  yearMonth: string,  // YYYY-MM
): Promise<GSTTransaction[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const from = `${yearMonth}-01`;
  const to = lastDayOfMonth(yearMonth);

  const { data, error } = await sb
    .from("transactions")
    .select(
      "id,transaction_type,transaction_date,reference_no,party_name,party_gstin," +
      "place_of_supply,is_interstate,taxable_amount_paise,cgst_paise,sgst_paise," +
      "igst_paise,cess_paise,is_reverse_charge,supply_type,invoice_type," +
      "gst_invoice_category,original_invoice_id,status"
    )
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("status", "posted")
    .in("transaction_type", ["sales_invoice", "credit_note", "debit_note"])
    .gte("transaction_date", from)
    .lte("transaction_date", to)
    .is("deleted_at", null)
    .order("transaction_date");

  if (error) throw new Error(`Failed to fetch sales transactions: ${error.message}`);
  return (data ?? []) as GSTTransaction[];
}

/** Fetch posted purchase transactions for ITC computation. */
export async function fetchPurchaseTransactions(
  clientId: string,
  yearMonth: string,
): Promise<GSTTransaction[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const from = `${yearMonth}-01`;
  const to = lastDayOfMonth(yearMonth);

  const { data, error } = await sb
    .from("transactions")
    .select(
      "id,transaction_type,transaction_date,reference_no,party_name,party_gstin," +
      "taxable_amount_paise,cgst_paise,sgst_paise,igst_paise,cess_paise," +
      "is_reverse_charge,supply_type,invoice_type,status"
    )
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("status", "posted")
    .eq("transaction_type", "purchase_invoice")
    .gte("transaction_date", from)
    .lte("transaction_date", to)
    .is("deleted_at", null);

  if (error) throw new Error(`Failed to fetch purchase transactions: ${error.message}`);
  return (data ?? []) as GSTTransaction[];
}

/** Fetch GSTR-2A records for the period. Period format: MMYYYY. */
export async function fetchGSTR2ARecords(
  clientId: string,
  period: string,  // MMYYYY
): Promise<GSTR2ARecord[]> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  const { data, error } = await sb
    .from("gstr2a_records")
    .select("id,supplier_gstin,supplier_name,invoice_number,invoice_date,taxable_value_paise,igst_paise,cgst_paise,sgst_paise")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("return_period", period);

  if (error) throw new Error(`Failed to fetch GSTR-2A records: ${error.message}`);
  return (data ?? []) as GSTR2ARecord[];
}

/** Fetch transaction line items for a set of transaction IDs. */
export async function fetchTransactionLines(
  transactionIds: string[],
): Promise<Record<string, unknown[]>> {
  if (transactionIds.length === 0) return {};
  const sb = getSupabaseClient();

  const { data, error } = await sb
    .from("transaction_lines")
    .select("transaction_id,description,hsn_sac_code,quantity,unit,rate_paise,taxable_paise,gst_rate,cgst_paise,sgst_paise,igst_paise,cess_paise")
    .in("transaction_id", transactionIds);

  if (error) throw new Error(`Failed to fetch transaction lines: ${error.message}`);

  const byTxn: Record<string, unknown[]> = {};
  for (const line of data ?? []) {
    const txnId = (line as Record<string, unknown>).transaction_id as string;
    if (!byTxn[txnId]) byTxn[txnId] = [];
    byTxn[txnId].push(line);
  }
  return byTxn;
}

/** Get client GSTIN from clients table. */
export async function getClientGSTIN(clientId: string): Promise<string> {
  const sb = getSupabaseClient();
  const { data, error } = await sb
    .from("clients")
    .select("gstin")
    .eq("id", clientId)
    .single();

  if (error || !data?.gstin) {
    throw new Error(`Client GSTIN not found for client ${clientId}`);
  }
  return data.gstin as string;
}

// ── API Calls ──────────────────────────────────────────────────────────────

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(JSON.stringify(err.detail ?? err));
  }
  const json = await res.json();
  if (!json.success) throw new Error(json.error ?? "API error");
  return json.data as T;
}

/** Classify transactions and persist gst_invoice_category back to Supabase. */
export async function classifyAndPersistTransactions(
  transactions: GSTTransaction[],
): Promise<ClassifyResult> {
  const result = await apiPost<ClassifyResult>("/api/gst/classify", {
    transactions,
  });

  // Persist classification back to Supabase in batches
  const sb = getSupabaseClient();
  const updates = Object.entries(result.results).map(([id, category]) =>
    sb.from("transactions").update({ gst_invoice_category: category }).eq("id", id)
  );
  await Promise.all(updates);

  return result;
}

// ── GSTR-3B ────────────────────────────────────────────────────────────────

/**
 * Compute GSTR-3B for a client and period.
 * Fetches data from Supabase, computes via API, stores result.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
export async function computeGSTR3B(
  clientId: string,
  yearMonth: string,  // YYYY-MM
): Promise<GSTR3BComputeResult> {
  const period = toPeriod(yearMonth);
  const [gstin, sales, purchases, gstr2a] = await Promise.all([
    getClientGSTIN(clientId),
    fetchSalesTransactions(clientId, yearMonth),
    fetchPurchaseTransactions(clientId, yearMonth),
    fetchGSTR2ARecords(clientId, period),
  ]);

  const result = await apiPost<GSTR3BComputeResult>("/api/gst/gstr3b/compute", {
    gstin,
    period,
    sales,
    purchases,
    gstr2a_records: gstr2a,
  });

  // Persist to Supabase
  await saveGSTR3BReturn(clientId, period, gstin, result);

  return result;
}

export async function saveGSTR3BReturn(
  clientId: string,
  period: string,
  gstin: string,
  result: GSTR3BComputeResult,
): Promise<void> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const w = result.working;

  await sb.from("gstr3b_returns").upsert({
    firm_id: firmId,
    client_id: clientId,
    period,
    // Use string (gstin) not from clients table to avoid stale data
    outward_taxable_igst_paise: w.outward.taxable_igst_paise,
    outward_taxable_cgst_paise: w.outward.taxable_cgst_paise,
    outward_taxable_sgst_paise: w.outward.taxable_sgst_paise,
    outward_zero_rated_paise: w.outward.zero_rated_paise,
    outward_nil_exempt_paise: w.outward.nil_exempt_paise,
    itc_igst_paise: w.itc.eligible_igst_paise,
    itc_cgst_paise: w.itc.eligible_cgst_paise,
    itc_sgst_paise: w.itc.eligible_sgst_paise,
    itc_book_igst_paise: w.itc.book_igst_paise,
    itc_book_cgst_paise: w.itc.book_cgst_paise,
    itc_book_sgst_paise: w.itc.book_sgst_paise,
    itc_2a_igst_paise: w.itc.gstr2a_igst_paise,
    itc_2a_cgst_paise: w.itc.gstr2a_cgst_paise,
    itc_2a_sgst_paise: w.itc.gstr2a_sgst_paise,
    net_igst_paise: w.net_payable.igst_paise,
    net_cgst_paise: w.net_payable.cgst_paise,
    net_sgst_paise: w.net_payable.sgst_paise,
    payload_json: result.payload,
    validation_errors: result.validation_warnings,
    status: "draft",
    updated_at: new Date().toISOString(),
  }, { onConflict: "client_id,period" });
}

/** CA approves GSTR-3B — marks as ca_approved, records approver. */
export async function approveGSTR3B(
  clientId: string,
  period: string,
  userId: string,
): Promise<void> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { error } = await sb
    .from("gstr3b_returns")
    .update({
      status: "ca_approved",
      ca_approved_by: userId,
      ca_approved_at: new Date().toISOString(),
    })
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("period", period);

  if (error) throw new Error(`Failed to approve GSTR-3B: ${error.message}`);
}

// ── GSTR-1 ─────────────────────────────────────────────────────────────────

/**
 * Build GSTR-1 for a client and period.
 * Classifies invoices, builds payload, stores result.
 *
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
export async function buildGSTR1(
  clientId: string,
  yearMonth: string,
): Promise<GSTR1BuildResult> {
  const period = toPeriod(yearMonth);
  const [gstin, invoices] = await Promise.all([
    getClientGSTIN(clientId),
    fetchSalesTransactions(clientId, yearMonth),
  ]);

  // Classify any unclassified transactions
  const unclassified = invoices.filter(i => !i.gst_invoice_category);
  if (unclassified.length > 0) {
    await classifyAndPersistTransactions(unclassified);
    // Re-fetch with classifications applied
    const reclassified = await fetchSalesTransactions(clientId, yearMonth);
    return _buildGSTR1FromInvoices(clientId, yearMonth, period, gstin, reclassified);
  }

  return _buildGSTR1FromInvoices(clientId, yearMonth, period, gstin, invoices);
}

async function _buildGSTR1FromInvoices(
  clientId: string,
  yearMonth: string,
  period: string,
  gstin: string,
  invoices: GSTTransaction[],
): Promise<GSTR1BuildResult> {
  const invoiceIds = invoices.map(i => i.id);
  const linesMap = await fetchTransactionLines(invoiceIds);

  const result = await apiPost<GSTR1BuildResult>("/api/gst/gstr1/build", {
    gstin,
    period,
    invoices,
    invoice_lines: linesMap,
    aggregate_turnover_paise: 0,  // CA can override if needed
  });

  await saveGSTR1Return(clientId, period, gstin, result);
  return result;
}

export async function saveGSTR1Return(
  clientId: string,
  period: string,
  gstin: string,
  result: GSTR1BuildResult,
): Promise<void> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  await sb.from("gstr1_returns").upsert({
    firm_id: firmId,
    client_id: clientId,
    period,
    gstin,
    payload_json: result.payload,
    summary_json: result.summary,
    validation_errors: [...result.validation_errors, ...result.validation_warnings],
    status: result.validation_errors.length === 0 ? "validated" : "draft",
    validated_at: result.validation_errors.length === 0 ? new Date().toISOString() : null,
    updated_at: new Date().toISOString(),
  }, { onConflict: "client_id,period" });
}

/** CA approves GSTR-1 — marks as ca_approved. */
export async function approveGSTR1(
  clientId: string,
  period: string,
  userId: string,
): Promise<void> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { error } = await sb
    .from("gstr1_returns")
    .update({
      status: "ca_approved",
      ca_approved_by: userId,
      ca_approved_at: new Date().toISOString(),
    })
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("period", period);

  if (error) throw new Error(`Failed to approve GSTR-1: ${error.message}`);
}

// ── Return Fetchers ────────────────────────────────────────────────────────

export async function getGSTR3BReturn(clientId: string, period: string) {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("gstr3b_returns")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("period", period)
    .maybeSingle();

  if (error) throw new Error(error.message);
  return data;
}

export async function getGSTR1Return(clientId: string, period: string) {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();
  const { data, error } = await sb
    .from("gstr1_returns")
    .select("*")
    .eq("firm_id", firmId)
    .eq("client_id", clientId)
    .eq("period", period)
    .maybeSingle();

  if (error) throw new Error(error.message);
  return data;
}

/** List all GSTR-1 and GSTR-3B returns for a client. */
export async function getGSTReturns(clientId: string) {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  const [gstr1, gstr3b] = await Promise.all([
    sb.from("gstr1_returns").select("id,period,status,ca_approved_at,arn,created_at")
      .eq("firm_id", firmId).eq("client_id", clientId).order("period", { ascending: false }),
    sb.from("gstr3b_returns").select("id,period,status,net_igst_paise,net_cgst_paise,net_sgst_paise,ca_approved_at,arn,created_at")
      .eq("firm_id", firmId).eq("client_id", clientId).order("period", { ascending: false }),
  ]);

  return {
    gstr1: gstr1.data ?? [],
    gstr3b: gstr3b.data ?? [],
  };
}

// ── Download helpers ────────────────────────────────────────────────────────

/**
 * Download GSTR-1 payload as a JSON file.
 * Only available for ca_approved returns.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 */
export function downloadGSTR1JSON(payload: Record<string, unknown>, period: string, gstin: string): void {
  const filename = `GSTR1_${gstin}_${period}.json`;
  const content = JSON.stringify(payload, null, 2);
  triggerDownload(content, filename, "application/json");
}

export function downloadGSTR3BJSON(payload: Record<string, unknown>, period: string, gstin: string): void {
  const filename = `GSTR3B_${gstin}_${period}.json`;
  const content = JSON.stringify(payload, null, 2);
  triggerDownload(content, filename, "application/json");
}

function triggerDownload(content: string, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Update transactions.ts types (additive) ─────────────────────────────────

/** Extended transaction interface with GST Engine fields. */
export interface GSTEngineTransactionFields {
  is_reverse_charge: boolean;
  supply_type: SupplyType;
  invoice_type: InvoiceType;
  original_invoice_id: string | null;
  cess_paise: number;
  gst_invoice_category: GSTInvoiceCategory | null;
}
