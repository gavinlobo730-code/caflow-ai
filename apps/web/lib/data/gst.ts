/**
 * GST Engine data layer — GSTR-1 and GSTR-3B payload generation.
 *
 * Architecture:
 *   1. POST to FastAPI /api/gst/{gstr1,gstr3b}/from-books, which reads the
 *      POSTED BOOKS server-side and reconciles the return to the General Ledger
 *   2. Store the result in gstr1_returns / gstr3b_returns in Supabase
 *
 * It used to work differently: the browser read a `transactions` table, sent the
 * rows to the API, and got a computed return back. Migration 139 dropped that
 * table as "an abandoned alternate transaction model ... no code reads or writes
 * it" — which was true of the backend and false of this file. Both screens have
 * been failing on a missing relation ever since, so the fetch-then-compute path
 * is gone and these functions now call the from-books endpoints, which read the
 * live tables (client_sales_invoices, purchase_bills, the credit/debit note
 * tables) and reconcile against journal_entries/journal_lines.
 *
 * That also honours CLAUDE.md's "zero business logic in the frontend": deciding
 * which rows belong in a return is the backend's job, not this file's.
 *
 * CGST Act Section 37 — GSTR-1 (outward supplies)
 * CGST Act Section 39 — GSTR-3B (summary return)
 * All amounts in integer paise. Never float.
 */
import { getSupabaseClient } from "@/lib/supabase/client";
import { api } from "@/lib/api";
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

/** The `working` block of POST /api/gst/gstr3b/from-books.
 *
 *  This interface used to describe a DIFFERENT endpoint — /gstr3b/compute,
 *  which reports book vs GSTR-2A vs eligible ITC and a net_payable block.
 *  computeGSTR3B was moved to /from-books without the type moving with it, and
 *  because the move happens at an `apiPost<FromBooksGSTR3B>` cast, tsc had
 *  nothing to check it against. The screen rendered ITC as "Rs NaN" and threw
 *  outright on w.net_payable, which is undefined there.
 *
 *  So: these fields are the ones /from-books actually returns. Anything added
 *  to the screen must be added to the endpoint, and
 *  apps/api/tests/test_gstr3b_screen_contract.py reads this screen's bindings
 *  and checks every one against a real response. */
export interface GSTR3BWorking {
  outward: {
    taxable_value_paise: number;
    taxable_igst_paise: number;
    taxable_cgst_paise: number;
    taxable_sgst_paise: number;
    zero_rated_paise: number;
    /** The IGST on those supplies. Nil under an LUT or bond (CGST s.16(3)(a));
     *  real on an export made ON PAYMENT OF TAX (s.16(3)(b)), which is refunded
     *  later under s.54 but is a liability in this return. Table 6.1 of the
     *  portal's own form includes it, and the ledger reconciliation counts it
     *  as output tax. */
    zero_rated_igst_paise: number;
    nil_exempt_paise: number;
    /** Table 3.1(e) — non-GST outward supplies. NOT 3.1(c): nil-rated and
     *  exempt are supplies GST reaches and then charges at nil or relieves
     *  (CGST s.11); non-GST is outside the levy entirely — petroleum and
     *  alcoholic liquor for human consumption (s.9(1), s.9(2)), and Schedule
     *  III. Optional because a return saved before GST-06 has no such key;
     *  the row reads 0 rather than blank, which is the correct declaration. */
    non_gst_paise?: number;
  };
  /** Table 3.2 — OF the supplies already in 3.1(a), the inter-state ones made
   *  to unregistered persons, composition dealers and UIN holders, keyed by
   *  2-digit place-of-supply state code. A breakdown, never an addition: the
   *  portal cross-checks it against 3.1(a) and against GSTR-1's B2CL/B2CS.
   *  Optional for the same reason as non_gst_paise. */
  inter_state_3_2?: {
    unregistered: Record<string, { txval: number; iamt: number }>;
    composition: Record<string, { txval: number; iamt: number }>;
    uin: Record<string, { txval: number; iamt: number }>;
  };
  rcm_inward: {
    igst_paise: number;
    cgst_paise: number;
    sgst_paise: number;
  };
  itc: {
    /** As per the purchase register, before Section 17(5) and before Table 4(B). */
    igst_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    /** Table 4(A) — gross, as the portal populates it from GSTR-2B. */
    avail_igst_paise: number;
    avail_cgst_paise: number;
    avail_sgst_paise: number;
    /** Table 4(C) — after the Table 4(B) reversals. What is actually claimed. */
    net_igst_paise: number;
    net_cgst_paise: number;
    net_sgst_paise: number;
  };
  /** Table 4(B). permanent = 4(B)(1) (Rules 38/42/43 and Section 17(5));
   *  reclaimable = 4(B)(2) (Rule 37/37A, Section 16(2)(b) and (c)). */
  itc_reversal: {
    permanent_paise: HeadAmounts;
    reclaimable_paise: HeadAmounts;
    reasons: ITCReversalReason[];
  };
  net_payable: {
    igst_paise: number;
    cgst_paise: number;
    sgst_paise: number;
    /** The set-off result: what the three heads come to after the s.49(5)
     *  cross-utilisation. NOT the challan amount — see challan_total_paise. */
    total_paise: number;
    /** Reverse-charge tax under s.9(3)/(4). It cannot be discharged out of
     *  credit: s.49(4) lets the electronic credit ledger pay only "output
     *  tax", and s.2(82) defines that as EXCLUDING "tax payable by him on
     *  reverse charge basis". So it is always cash, always on top. */
    rcm_cash_paise: number;
    /** What the CA actually pays — total_paise + rcm_cash_paise. This is the
     *  figure to carry to the payment screen; `total_paise` alone was being
     *  read as the amount due and was short by the whole of Table 3.1(d). */
    challan_total_paise: number;
  };
  /** CGST Rule 36(4) — the working behind the credit, which the return itself
   *  never shows. The rule caps eligible ITC at the credit suppliers have
   *  actually filed, and s.16(2)(aa) makes that decisive rather than
   *  advisory. Computed since the engine was written and rendered by NOTHING
   *  until 11-09-2026: a CA whose claim had been trimmed saw only the trimmed
   *  figure, with no statement that a cap fired or what it was measured
   *  against.
   *
   *  `compared` is the one that cannot be inferred from the amounts. A book
   *  figure equal to the 2A figure and a book figure with no 2A uploaded at
   *  all both show "no cap applied", and they mean opposite things. */
  rule_36_4: {
    /** How many GSTR-2A/2B rows were on file for the period. Zero is the
     *  not-compared state, not a claim that no supplier filed. */
    gstr2a_record_count: number;
    gstr2a_igst_paise: number;
    gstr2a_cgst_paise: number;
    gstr2a_sgst_paise: number;
    /** True where the cap actually bit on at least one head. */
    cap_applied: boolean;
    /** False where no 2A was on file, so nothing was compared. */
    compared: boolean;
    /** Reverse-charge tax, which is OUTSIDE the cap. Rule 36(4) reaches only
     *  invoices "required to be furnished by the supplier under sub-section
     *  (1) of section 37"; s.9(3)/(4) tax is self-assessed on the recipient's
     *  own s.31(3)(f) invoice, so no supplier furnishes it and GSTR-2B
     *  structurally cannot carry it. Without this the screen shows a book
     *  total above the 2A with no cap and no way to tell whether that is
     *  right. */
    self_assessed_igst_paise: number;
    self_assessed_cgst_paise: number;
    self_assessed_sgst_paise: number;
  };
  /** The other side of Table 6, which the form itself never states: credit
   *  available, credit spent, credit left. Net tax of zero is true both when
   *  liability and credit cancel out and when credit exceeds liability by
   *  lakhs, and only this tells the two apart. Derived in apps/api as the
   *  residual of the same set-off that produced net_payable, so the pair
   *  cannot drift. */
  itc_utilisation: {
    available_paise: number;
    consumed_paise: number;
    carried_forward_paise: number;
  };
}

export interface HeadAmounts {
  igst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  cess_paise: number;
}

export interface ITCReversalReason {
  reason: string;
  reclaimable: boolean;
  igst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  cess_paise: number;
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

/** Books-vs-ledger agreement, returned by every from-books computation. The
 *  whole point of computing from posted books is that the answer can be proved
 *  against the General Ledger, so the proof travels with the result. */
export interface GLReconciliation {
  reconciled: boolean;
  [block: string]: unknown;
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
  // PAISE, renamed from the previous *_rupees fields rather than converted. The
  // rename is deliberate: a silent unit change behind the same name is how a
  // GST total ends up 100x wrong, and the compiler now catches every reader.
  taxable_total_paise: number;
  tax_total_paise: number;
  reconciliation: GLReconciliation;
  /** Things that get the return REJECTED at the portal or filed wrong — a
   *  duplicate invoice number, IGST on an intra-state supply, CGST != SGST, a
   *  place of supply that is not a state. These used to be unreachable: the
   *  validator ran only on POST /gst/gstr1/build and POST /gst/validate/gstr1,
   *  and this file has always posted to /from-books. */
  validation_errors: ValidationError[];
  /** Judgement calls, not rejections — an invoice dated outside the s.37(3)
   *  window, tax that does not follow from the rate. */
  validation_warnings: ValidationError[];
  /** Documents the payload does NOT carry, and why. A different thing from a
   *  validation error: an error is a document that IS in the return and is
   *  wrong; a gap is a document that is not in the return at all. Filing short
   *  is the failure a CA hears about from the recipient. */
  payload_gaps: PayloadGap[];
  ca_review_required: true;
}

/** One document the GSTR-1 payload leaves out. `kind` is the category it was
 *  classified as (SEZ_WOP, DEEMED_EXPORT, CDNUR). */
export interface PayloadGap {
  kind: string;
  reference_no: string;
  reason: string;
}

/** Raw shape of POST /api/gst/gstr1/from-books. */
interface FromBooksGSTR1 {
  period: string;
  gstin: string;
  payload: Record<string, unknown>;
  summary: GSTR1BuildResult["summary"];
  invoice_count: number;
  taxable_total_paise: number;
  tax_total_paise: number;
  reconciliation: GLReconciliation;
  validation_errors: ValidationError[];
  validation_warnings: ValidationError[];
  payload_gaps: PayloadGap[];
}

/** Raw shape of POST /api/gst/gstr3b/from-books. */
interface FromBooksGSTR3B {
  period: string;
  gstin: string;
  payload: Record<string, unknown>;
  working: GSTR3BWorking;
  reconciliation: GLReconciliation;
  validation_errors: ValidationError[];
  validation_warnings: ValidationError[];
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
// lastDayOfMonth() lived here — it built the date range for the deleted
// transaction fetchers. The from-books endpoints derive the period bounds
// server-side (_period_bounds in services/gst_return_service.py), so the
// browser no longer needs to know how long a month is.

// ── Data Fetchers ──────────────────────────────────────────────────────────

/** Fetch all posted sales and credit/debit note transactions for a period. */
// fetchSalesTransactions / fetchPurchaseTransactions lived here. Both read
// `transactions`, dropped by migration 139. The from-books endpoints select the
// same supplies server-side from the live invoice/bill/note tables, so there is
// nothing for a replacement to do here.

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

// fetchTransactionLines lived here. It read `transaction_lines`, dropped by the
// same migration 139; GSTR-1 line detail now comes from the from-books payload.

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
  // Every /api/gst/* route is guarded by rbac("gst", "compute"), so an
  // unauthenticated POST is a 401 — which this helper omitted entirely. Alongside
  // the dropped `transactions` table that made this path doubly non-functional.
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}),
    },
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

async function apiGet<T>(path: string): Promise<T> {
  const { data: { session } } = await getSupabaseClient().auth.getSession();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: session?.access_token
      ? { Authorization: `Bearer ${session.access_token}` }
      : {},
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
// classifyAndPersistTransactions lived here. It POSTed to /api/gst/classify and
// wrote the answer back to `transactions` — a table migration 139 dropped. The
// from-books builder classifies each supply as it reads it (domain/gst/
// classifier.py), so nothing needs to be persisted client-side first.

// ── GSTR-3B ────────────────────────────────────────────────────────────────

/** One overdue bill from GET /api/gst/itc/rule37. */
export interface Rule37Bill {
  bill_id: string;
  bill_no: string | null;
  bill_date: string | null;
  vendor_id: string | null;
  status: string;
  total_paise: number;
  paid_paise: number;
  unpaid_paise: number;
  days_outstanding: number;
  payment_due_by: string;
  /** MMYYYY. Rule 37(1): the period AFTER the one the 180 days expired in. */
  reverse_in_period: string;
  reversal: { igst_paise: number; cgst_paise: number; sgst_paise: number; total_paise: number };
}

export interface Rule37Report {
  as_of: string;
  rule: string;
  bills: Rule37Bill[];
  bill_count: number;
  totals: { igst_paise: number; cgst_paise: number; sgst_paise: number; total_paise: number };
  ca_review_required: true;
}

/** Bills 180 days unpaid as at `asOf`, and the credit Rule 37 reverses.
 *
 *  `asOf` is the period END, not today: the CA is asking "what does THIS return
 *  have to carry", and a bill that crosses 180 days next week belongs in next
 *  month's answer, not this one.
 *
 *  # CA REVIEW REQUIRED — this reports; it posts no journal and files nothing.
 */
export async function fetchRule37Report(
  clientId: string,
  asOf: string,          // YYYY-MM-DD
): Promise<Rule37Report> {
  // /api/gst-workspace, not /api/gst — routers/gst_workspace.py carries its own
  // prefix. test_gst_api_paths_exist.py checks this against the live app.
  return apiGet<Rule37Report>(
    `/api/gst-workspace/itc/rule37?client_id=${encodeURIComponent(clientId)}` +
    `&as_of=${encodeURIComponent(asOf)}`,
  );
}


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
  const result = await apiPost<FromBooksGSTR3B>("/api/gst/gstr3b/from-books", {
    client_id: clientId,
    period,
  });

  // Carried, not assumed empty. This said "the from-books endpoint reports no
  // validation_warnings", which described the endpoint rather than the rules:
  // validate_gstr3b existed and ran only from POST /gst/gstr3b/compute, the
  // path that takes invoices from the CALLER and that no screen uses. Its one
  // substantive rule — ITC more than three times the output tax — now runs on
  // the books, and a warning is a thing the CA should see before filing.
  const shaped: GSTR3BComputeResult = {
    payload: result.payload,
    working: result.working,
    validation_warnings: result.validation_warnings ?? [],
    period: result.period,
    gstin: result.gstin,
    ca_review_required: true,
  };

  await saveGSTR3BReturn(clientId, period, result.gstin, shaped);
  return shaped;
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
    // Table 4(C) — the credit the return actually claims, after 4(B).
    itc_igst_paise: w.itc.net_igst_paise,
    itc_cgst_paise: w.itc.net_cgst_paise,
    itc_sgst_paise: w.itc.net_sgst_paise,
    // The purchase register, before Section 17(5) and before any reversal.
    itc_book_igst_paise: w.itc.igst_paise,
    itc_book_cgst_paise: w.itc.cgst_paise,
    itc_book_sgst_paise: w.itc.sgst_paise,
    // itc_2a_* are deliberately NOT written. The from-books path does no
    // GSTR-2A comparison — that is the 2A/2B reconciliation screen's job — so
    // these three read as whatever they last held. Writing 0 would assert that
    // no supplier filed anything against this client for the period, which is
    // a different and much worse claim than "not computed here". They default
    // to 0 NOT NULL on a first insert (migration 036), which is the same
    // not-computed state the columns have always carried on this path.
    net_igst_paise: w.net_payable.igst_paise,
    net_cgst_paise: w.net_payable.cgst_paise,
    net_sgst_paise: w.net_payable.sgst_paise,
    // Migration 339. The three above are the Table 6 SET-OFF residual; these
    // two are what the CA actually pays. §49(4) allows the credit ledger to
    // pay only "output tax" and §2(82) excludes "tax payable by him on reverse
    // charge basis" from that, so Table 3.1(d) is always cash and always on
    // top. Stored beside the residual rather than instead of it: a reader has
    // to be able to tell a return carrying reverse charge from one where the
    // credit simply ran out.
    rcm_cash_paise: w.net_payable.rcm_cash_paise,
    cash_payable_paise: w.net_payable.challan_total_paise,
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
  const result = await apiPost<FromBooksGSTR1>("/api/gst/gstr1/from-books", {
    client_id: clientId,
    period,
    aggregate_turnover_paise: 0,   // CA can override on the client GST screen
  });

  const shaped: GSTR1BuildResult = {
    payload: result.payload,
    summary: result.summary,
    invoice_count: result.invoice_count,
    // Paise straight through — NOT divided by 100 here. Converting to rupees in
    // the browser is exactly the float rounding CLAUDE.md forbids, and the
    // callers now format paise (see the `r()` helper in the GSTR-1 page).
    taxable_total_paise: result.taxable_total_paise,
    tax_total_paise: result.tax_total_paise,
    reconciliation: result.reconciliation,
    // Carried, not discarded. This was `validation_warnings: []` — a literal
    // empty array — because the endpoint returned nothing to carry. It does
    // now.
    validation_errors: result.validation_errors ?? [],
    validation_warnings: result.validation_warnings ?? [],
    payload_gaps: result.payload_gaps ?? [],
    ca_review_required: true,
  };

  await saveGSTR1Return(clientId, period, result.gstin, shaped);
  return shaped;
}

export async function saveGSTR1Return(
  clientId: string,
  period: string,
  gstin: string,
  result: GSTR1BuildResult,
): Promise<void> {
  const sb = getSupabaseClient();
  const firmId = await getFirmId();

  // ONE PREDICATE, used for both the status and its timestamp, so they cannot
  // disagree about the same return.
  //
  // "validated" is a claim that the checks RAN AND PASSED. It used to be
  // unconditional, under a comment saying a result in hand is a validated one
  // — true while the validator was unreachable from this path, false the
  // moment it was wired in. A gap counts the same as an error: a return that
  // leaves a document out is not one whose checks passed, and the CA has to
  // act on it before filing (record the recipient's GSTIN, or fold the note
  // into Table 7).
  const readyToFile =
    result.validation_errors.length === 0 && result.payload_gaps.length === 0;

  await sb.from("gstr1_returns").upsert({
    firm_id: firmId,
    client_id: clientId,
    period,
    gstin,
    payload_json: result.payload,
    summary_json: result.summary,
    validation_errors: [...result.validation_errors, ...result.validation_warnings],
    // "validated" means the checks RAN AND PASSED, which is a different claim
    // from "the builder did not raise". It used to be unconditional, under a
    // comment saying a result in hand is a validated one — true while the
    // validator was unreachable from this path and false the moment it was
    // wired in. A return carrying an error the portal will reject is a draft.
    status: readyToFile ? "validated" : "draft",
    validated_at: readyToFile ? new Date().toISOString() : null,
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

/**
 * Record that a return has been manually filed on the GST portal and capture the ARN.
 * Called after the CA uploads the JSON to gst.gov.in and receives the ARN.
 * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
 *
 * WHY THESE TWO GO THROUGH THE API AND NOT POSTGREST
 *     They used to write `status: "submitted"` straight into gstr3b_returns /
 *     gstr1_returns over PostgREST. That skipped the backend entirely, and the
 *     backend is where two things happen that nothing else does:
 *
 *       1. `record_filing` (services/gst_filing_record_service.py) writes the
 *          `public.filings` row. That table is the ONLY thing
 *          journal_period_lock_reason (migrations 266/267) reads to decide
 *          whether a filed return freezes the period behind it. With nothing
 *          writing it, the table stayed empty and the lock could never fire —
 *          a filed GSTR-3B left every journal entry in its period still
 *          editable, against CGST Act §37(3)/§39(9). Production showed exactly
 *          that: one gstr3b_returns row sitting at ca_approved, no ARN, and
 *          `filings` empty.
 *       2. `rbac()` runs. It does not run on a PostgREST call — the only check
 *          there is RLS — so any role that could open the screen could mark a
 *          return filed. The route requires Manager-or-above plus an explicit
 *          ca_approved, and it also records the approver, submitted_at and the
 *          ARN on the return row.
 *
 *     The signatures are unchanged, so the two screens calling them do not
 *     move. The (client, period) → return id lookup is a READ and stays on
 *     PostgREST; it is the WRITE that had to move.
 */
export async function markGSTR3BFiled(
  clientId: string,
  period: string,
  arn: string,
): Promise<void> {
  const existing = await getGSTR3BReturn(clientId, period);
  const returnId = (existing as { id?: string } | null)?.id;
  if (!returnId) {
    throw new Error(
      `No GSTR-3B has been computed for ${fromPeriod(period)} — compute and approve it before recording the filing.`);
  }
  // # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT: ca_approved is the CA's own
  // confirmation click reaching the server, not a formality the client sets.
  const res = await api.gstWorkspace.setGstr3bStatus(returnId, {
    status: "submitted",
    ca_approved: true,
    arn,
  });
  // This router answers a refusal as HTTP 200 with { success: false, error },
  // so an unchecked call reports "filed" for a request the server declined.
  if (!res.success) throw new Error(res.error ?? "Failed to mark GSTR-3B as filed");
}

export async function markGSTR1Filed(
  clientId: string,
  period: string,
  arn: string,
): Promise<void> {
  const existing = await getGSTR1Return(clientId, period);
  const returnId = (existing as { id?: string } | null)?.id;
  if (!returnId) {
    throw new Error(
      `No GSTR-1 has been built for ${fromPeriod(period)} — build and approve it before recording the filing.`);
  }
  // # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
  const res = await api.gstWorkspace.setGstr1Status(returnId, {
    status: "submitted",
    ca_approved: true,
    arn,
  });
  if (!res.success) throw new Error(res.error ?? "Failed to mark GSTR-1 as filed");
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
