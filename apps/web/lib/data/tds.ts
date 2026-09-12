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
  /** The section code for the PERIOD, not a routing key — the same rule as
   *  `form` above. `"194J"` up to 31-03-2026 and `"393(1)"` from FY 2026-27,
   *  because the Income-tax Act 2025 collapsed the whole 194-series into it.
   *  The form number was already translated and this was not, so a FY 2026-27
   *  26Q came back as Form 140 with every line citing a section that Act does
   *  not contain (TDS-17). Display this; never store it, never route on it. */
  section: string;
  /** The stored 1961 code that produced the label above. §393(1) HAS NO
   *  REVERSE — the whole 194-series collapses into it — so anything reading
   *  this payload back to route, match a challan or look up a rate must use
   *  this field. Optional only because a payload saved before TDS-17 has no
   *  such key. */
  section_1961?: string;
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

/* Compute26QRequest / Compute24QRequest AND THEIR TWO CALLERS ARE GONE.
 *
 * `/api/tds/26q/compute` and `/24q/compute` are pure functions over deductee
 * rows the CALLER supplies, and the only caller was `/tds/returns`, which
 * built those rows in the browser out of `tds_deductions` and `tds_challans`.
 * That is the assembly TDS-03 was supposed to end and TDS-29 outlived: every
 * row went out with `tds_deposited_paise = tds_deducted_paise`, so the
 * engine's shortfall check could not fire, and the deductor block had to be
 * invented because the browser had nowhere to read it from.
 *
 * `computeReturnFromBooks` below is the replacement and the endpoints stay —
 * they have their own tests and their own reason to exist. What is deleted is
 * the browser-side wrapper, because a dead wrapper for a deleted pattern is
 * an invitation to rebuild it. */

export interface TDSReturnPayload {
  /** The form number for the PERIOD, not a routing key.
   *
   *  `"26Q"` up to 31-03-2026 and `"140"` from FY 2026-27 — CBDT Notification
   *  22/2026 renumbered the statements and `domain/tds/vocabulary.py` is the
   *  one place that knows it, so the API returns whichever the quarter's own
   *  Act uses. This was typed `"24Q" | "26Q"`, which was a lie the compiler
   *  could not catch (the value crosses the wire as JSON) and which read as
   *  permission to store it: `saveTDSReturn` wrote it into
   *  `tds_returns.return_type`, whose CHECK accepts only the four routing
   *  keys, so from 1 April 2026 every save from this screen was rejected
   *  (TDS-18). Display this; never store it. */
  form: string;
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
  /** Present only on a from-books build (services/tds_return_service.py).
   *  Optional so the same type serves both, and so a field the service adds
   *  later cannot break the compile before anybody has decided to show it. */
  act?: string;
  source?: string;
  statutory_gaps?: string[];
  challan_gaps?: string[];
  ca_review_required?: boolean;
  reconciliation?: {
    books_paise: number;
    ledger_paise: number;
    difference_paise: number;
    matched: boolean;
    account_found: boolean;
  };
  excluded_non_resident?: {
    bill_count: number;
    tds_paise: number;
    reason: string;
  };
  period?: {
    financial_year: string;
    quarter: string;
    start: string;
    end: string;
    due_date: string;
  };
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
/** Build a quarter's statement FROM THE POSTED BOOKS, server-side.
 *
 *  THIS REPLACES ASSEMBLING IT IN THE BROWSER, and the difference is not
 *  stylistic. `/tds/returns` used to read `tds_deductions` and `tds_challans`
 *  over PostgREST, map them into deductee rows itself, and post the result to
 *  `/compute` — a pure function over whatever the browser chose to send. Two
 *  things followed from that and neither was visible on screen:
 *
 *    * every deductee was stamped `tds_deposited_paise = tds_paise`, so the
 *      engine's own `deducted − deposited` shortfall check could not fire by
 *      construction (TDS-29). The server fills the deposited column FIFO from
 *      the challans that actually exist (domain/tds/challan_mapping.py), so a
 *      quarter deducted and not deposited now says so — §201(1A) runs at 1.5%
 *      a month from the date of deduction;
 *    * the deductor block had to come from somewhere, and the browser had
 *      nowhere to read it from, so it invented one.
 *
 *  The deductor block is deliberately NOT a parameter. The server reads the
 *  TAN from `client_statutory_identity` (migration 325), the PAN, name and
 *  address from the client, and REFUSES by name when a registration is not
 *  recorded — see `domain/tds/deductor.py`. A screen that could pass one
 *  could pass a wrong one.
 *
 *  Rule 31A(4) routes a deduction by the PAYEE's residency, so which of the
 *  three statements to build is the CA's choice of what they are filing, not
 *  something the browser infers from the books. */
export async function computeReturnFromBooks(
  returnType: TDSReturnType,
  params: { client_id: string; financial_year: string; quarter: TDSQuarter },
): Promise<TDSReturnPayload> {
  const path = {
    "24Q": "/api/tds/24q/from-books",
    "27Q": "/api/tds/27q/from-books",
    "26Q": "/api/tds/26q/from-books",
  }[returnType as "24Q" | "27Q" | "26Q"];
  if (!path) throw new Error(`No from-books builder for Form ${returnType}.`);
  const json = await authedFetch<TDSReturnPayload>(path, {
    method: "POST", body: JSON.stringify(params),
  });
  if (!json.success) {
    // A 422 from FastAPI is `{detail: "…"}`, not the `{success, data, error}`
    // envelope, and `detail` is where the deductor refusal's sentences are —
    // "This client has no TAN recorded…". Reading only `error` would replace
    // the one thing the CA needs (which registration to go and record) with a
    // generic failure, which is the shape of the defect this call replaced.
    const detail = (json as unknown as { detail?: unknown }).detail;
    throw new Error(
      json.error
      ?? (typeof detail === "string" ? detail : undefined)
      ?? `Couldn't build Form ${returnType} from the books.`,
    );
  }
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
  /** Whether a VENDOR may be marked with this section.
   *
   *  Decided by `domain/tds/residency.deduction_section_refusal`, the one
   *  function that decides it, and not by the screen keeping its own
   *  exclusion list — which is how the Schedule III caption list drifted in
   *  both directions at once.
   *
   *  False for §192 (salary; a bill would deduct nothing and say nothing) and
   *  for §206C (TCS; collected by a seller from a buyer and reported on 27EQ,
   *  so on a bill you are PAYING there is nothing to collect). Optional so a
   *  frontend deployed ahead of the backend keeps working — `?? true` is the
   *  behaviour that existed before the flag. */
  vendor_eligible?: boolean;
  section_197_eligible?: boolean;
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
export interface CreateChallanInput {
  client_id: string;
  bsr_code: string;
  challan_date: string;      // YYYY-MM-DD
  /** The TOTAL that left the bank — the figure on the counterfoil. The three
   *  component fields below say how much of it was not tax; the server takes
   *  tax as the remainder, so omitting them is the old "all of it is TDS"
   *  behaviour rather than a different one. */
  amount_paise: number;
  challan_no: string;
  section: string;
  financial_year: string;
  quarter: string;           // 'Q1'..'Q4'
  surcharge_paise?: number;
  /** IT Act s.201(1A) interest paid on this challan. */
  interest_paise?: number;
  /** The s.234E late-filing fee, and any s.271H penalty. */
  penalty_paise?: number;
  /** Challan 281 minor head: 200 = paid over by the deductor, 400 = against a
   *  demand raised on regular assessment. Migration 037 defaulted it to '200'
   *  and nothing could send anything else. */
  minor_head?: "200" | "400";
}

/** The challan-281 worksheet for one DEDUCTION month — GET
 *  /api/tds-workspace/deposit-due. Rule 30(2) sets the due date; s.201(1A)(ii)
 *  the interest. Every figure is the server's; the browser formats and nothing
 *  else. */
export interface DepositDueSection {
  section: string;
  deductee_count: number;
  taxable_paise: number;
  tax_paise: number;
  deposited_paise: number;
  outstanding_paise: number;
  interest_paise: number;
  payable_paise: number;
  late_row_count: number;
  earliest_deduction_date: string | null;
  latest_deduction_date: string | null;
}

export interface DepositDueWorksheet {
  client_id: string;
  month: string;
  due_date: string;
  due_date_rule: string;
  as_at: string;
  sections: DepositDueSection[];
  totals: {
    deductee_count: number;
    taxable_paise: number;
    tax_paise: number;
    deposited_paise: number;
    outstanding_paise: number;
    interest_paise: number;
    payable_paise: number;
    late_row_count: number;
  };
  covers: string;
  statutory_gaps: { kind: string; message: string; deductees: string[] }[];
}

export async function fetchDepositDue(
  clientId: string, month: string,
): Promise<DepositDueWorksheet> {
  const resp = await authedFetch<DepositDueWorksheet>(
    `/api/tds-workspace/deposit-due?client_id=${encodeURIComponent(clientId)}` +
    `&month=${encodeURIComponent(month)}`);
  if (!resp.success) throw new Error(resp.error ?? "Could not work out what is due");
  return resp.data;
}

/** Record an ITNS 281 deposit. IT Act s.200(1).
 *
 *  Through the API, not PostgREST: the server validates the payment date
 *  against a locked period, writes the audit-log entry and logs the client
 *  timeline event. The /tds Challans tab had no writer at all — the modal
 *  pushed a row into React state and the endpoint had no caller (TDS-15). */
export async function createTdsChallan(input: CreateChallanInput): Promise<RecordedChallan> {
  const resp = await authedFetch<RecordedChallan>("/api/tds-workspace/challans", {
    method: "POST", body: JSON.stringify(input),
  });
  if (!resp.success) throw new Error(resp.error ?? "Could not record the challan");
  return resp.data;
}

/** tds_challans as migration 037 defines it. */
export interface RecordedChallan {
  id: string;
  bsr_code: string;
  challan_no: string;
  payment_date: string;
  total_paise: number;
  /** The TAX part only — total less surcharge, interest and penalty. */
  tds_paise: number;
  surcharge_paise?: number;
  interest_paise?: number;
  penalty_paise?: number;
  minor_head?: string;
  financial_year: string;
  quarter: string;
  section: string | null;
  status: "deposited" | "matched" | "unmatched";
}

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

/* getTDSDeductions / getTDSChallans ARE GONE TOO, for the same reason.
 *
 * Both read a table straight out of the browser over PostgREST, so `rbac()`
 * never ran on either, and both existed only to feed the browser-side return
 * assembly above. The from-books payload carries the deductees AND the
 * challans the server actually matched, which is the figure the CA needs:
 * what a challan list shows is what was DEPOSITED, and pairing it with a
 * deduction is `domain/tds/challan_mapping.py`'s job, not a screen's. */

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

/** Save a computed statement — through the API, under the ROUTING KEY.
 *
 *  TWO THINGS WERE WRONG WITH THE VERSION THIS REPLACES.
 *
 *  It upserted `tds_returns` over PostgREST, so `rbac("tds","compute")` never
 *  ran and neither did the backend's own period-lock check or its deductee-PAN
 *  validation — the same shape as the GST "record as filed" write CLAUDE.md
 *  records, where a filed return did not lock its period because the browser
 *  wrote the row itself.
 *
 *  And it wrote `return_type: payload.form`. `form` is the number the
 *  PERIOD's Act uses — `"140"` for a FY 2026-27 26Q — while `return_type` is
 *  a routing column whose CHECK (migration 037) accepts only 24Q/26Q/27Q/27EQ.
 *  So from 1 April 2026 every save from this screen was rejected by the
 *  database and the CA saw "Failed to save TDS return" with no way to tell
 *  why (TDS-18). The key is passed explicitly now, and `CreateReturnRequest`
 *  constrains it to those four so a caller cannot reintroduce the confusion.
 *
 *  `status` is not sent: the endpoint creates at "pending" and the transition
 *  to prepared / approved / filed goes through `/returns/{id}/status`, which
 *  is where the PRN and acknowledgement are captured. */
export async function saveTDSReturn(
  clientId: string,
  returnType: TDSReturnType,
  payload: TDSReturnPayload,
): Promise<string> {
  const resp = await authedFetch<{ id: string }>("/api/tds-workspace/returns", {
    method: "POST",
    body: JSON.stringify({
      client_id: clientId,
      return_type: returnType,
      quarter: payload.quarter,
      financial_year: payload.financial_year,
      deductee_details: payload.deductees,
      total_deductions_paise: payload.total_tds_deducted_paise,
      total_deposits_paise: payload.total_tds_deposited_paise,
      deductee_count: payload.deductee_count,
      validation_errors: payload.validation_errors,
    }),
  });
  if (!resp.success || !resp.data?.id) {
    const detail = (resp as unknown as { detail?: unknown }).detail;
    throw new Error(
      resp.error
      ?? (typeof detail === "string" ? detail : undefined)
      ?? "Failed to save TDS return",
    );
  }
  return resp.data.id;
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

/* computeDueDate IS GONE — it was a statutory rule kept in the browser.
 *
 * Rule 31A(2)'s quarterly due dates live in
 * `services/compliance_engine.tds_return_due_date`, which is the authority
 * (CLAUDE.md), and `routers/tds_workspace.create_return` derives the stored
 * `due_date` from it. This copy existed only because `saveTDSReturn` wrote
 * the row itself; the row now comes from the server, which knows the rule. */

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
