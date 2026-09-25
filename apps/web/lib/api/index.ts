import { supabase } from "@/lib/supabase/client";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** What PATCH /api/compliance/calendar/{id}/filed answers.
 *
 *  `filing_recorded` is the same question as "is the period now locked".
 *  `filing_not_recorded_reason` is why not, per compliance type — a GSTR-9
 *  tick is a real thing to record and still closes no month, and a silent
 *  no-op there is the defect this replaced in a new place.
 *  `workspace_return` names a prepared GSTR-1/3B for the same client and
 *  period that is still not submitted in the client workspace: the
 *  disagreement, shown rather than resolved, because approving a return needs
 *  Manager+ and an explicit confirmation on the workspace endpoint (CGST §37).
 */
export type MarkFiledResult = {
  record: Record<string, unknown>;
  filing_recorded: boolean;
  filing_not_recorded_reason: string | null;
  period_locked_from: string | null;
  period_locked_to: string | null;
  workspace_return: { id: string; period: string; status: string; table: string } | null;
};

/** `public.firms` as the product reads it. `gstin` is RESOLVED — the row's two
 *  GSTIN columns are not both served, because choosing between them is
 *  `domain/firm/identity.py`'s job and a screen that could see both would have
 *  to repeat it. */
export type FirmProfile = {
  id?: string;
  name?: string | null;
  email?: string | null;
  gstin?: string | null;
  pan?: string | null;
  icai_mrn?: string | null;
  phone?: string | null;
  website?: string | null;
  address?: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  state?: string | null;
  pincode?: string | null;
};

/** Standard backend response envelope: { success, data, error }. */
export type ApiResp<T = unknown> = { success: boolean; data: T; error: string | null };

/** A row of `GET /api/clients`, narrowed to what a picker needs. The endpoint
 *  serves the whole `clients` row; naming only these keeps a caller from
 *  quietly depending on a column that is not part of the contract. */
export interface ClientSummary {
  id: string;
  client_name: string;
  entity_type?: string | null;
  gstin?: string | null;
}

/** One hub tile, exactly as `domain/hub/tiles.describe()` serialises it.
 *
 *  THE THREE STATES ARE TOLD APART BY TWO FIELDS, and a screen must not
 *  collapse them — the backend keeps them distinct as three different dicts
 *  and `tests/test_a_hub_tile_shows_what_is_outstanding.py` asserts it:
 *
 *    signal: 0     answerable: true    nothing is outstanding
 *    signal: null  answerable: false   nobody can tell — render the reason
 *    signal: null  answerable: true    this one tile's fetch failed
 *
 *  `href` is null where this tile has no destination AT THIS SCOPE (five
 *  modules have no firm-level screen — question G3), so the card must not
 *  render as a link. */
/** ── Related parties — AS 18 ─────────────────────────────────────────────
 *  The disclosure `domain/related_party/disclosure.py` decides. Typed rather
 *  than `unknown`, because a note is read by an auditor and a field the
 *  endpoint does not serve must not be reachable from a screen. */
export interface RelatedPartyDealings {
  sales_paise: number;
  purchases_paise: number;
  receivable_paise: number;
  payable_paise: number;
}

export interface RelatedParty {
  entity_id: string;
  name: string;
  pan: string | null;
  role: string;
  ownership_percent: number | null;
  /** "included" | "excluded" | "undetermined" — three answers, and the third
   *  is the point. See the domain module. */
  standing: string;
  reason: string;
  effective_from: string | null;
  effective_to: string | null;
  /** Always present, NULL where the party carries no PAN and so could not be
   *  matched at all. Null is unknown, never nil. */
  dealings: RelatedPartyDealings | null;
}

export interface RelatedPartyDisclosure {
  client_id: string;
  parties: RelatedParty[];
  included_count: number;
  undetermined_count: number;
  disclosure_required: boolean;
  section_185_loans: Record<string, unknown>[];
  transfer_pricing_flags: Record<string, unknown>[];
  transfer_pricing_count: number;
  entity_relationships: Record<string, unknown>[];
  gaps: string[];
  notes: string[];
}

export interface ClientEntityRole {
  id: string;
  entity_id: string | null;
  client_id: string;
  role: string;
  ownership_percent: number | null;
  effective_from: string | null;
  effective_to: string | null;
  notes: string | null;
  entity_name: string | null;
  entity_type: string | null;
  pan: string | null;
  email: string | null;
}

export interface RelationshipEntity {
  id: string;
  full_name: string;
  entity_type: string;
  pan: string | null;
  email: string | null;
}

/** `GET /api/intelligence/workload-insights` — `compute_workload_insights`. */
export interface WorkloadInsight {
  /** "overload" | "idle" | "unassigned_backlog" */
  type: string;
  user_id?: string;
  user_name?: string;
  detail: string;
}

export interface WorkloadInsightsPayload {
  insights: WorkloadInsight[];
  open_tasks: number;
  team_size: number;
}

export interface HubTile {
  id: string;
  label: string;
  href: string | null;
  question: string;
  unit: "count" | "paise";
  answerable: boolean;
  no_signal_because: string | null;
  signal: number | null;
}

export interface HubPayload {
  scope: "firm" | "client";
  client_id: string | null;
  tiles: HubTile[];
}

/** One client's row on a firm-level module worklist, exactly as
 *  `services/hub_worklist_service._with_names` serialises it.
 *
 *  `client_name` is null where the name could not be read. The row is STILL
 *  listed — a queue that silently omits a client is the failure the screen
 *  exists to prevent — so the screen shows the id rather than dropping it. */
export interface HubWorklistRow {
  client_id: string;
  signal: number;
  client_name: string | null;
  entity_type?: string | null;
}

/** A firm-level module worklist: which clients need work on one hub tile.
 *
 *  `question`, `unit` and `label` come off the TILE (`domain/hub/tiles.py`),
 *  never restated here, so a tile whose question is reworded cannot leave its
 *  worklist describing the old one.
 *
 *  `clients_examined` is what makes an empty `rows` readable: zero rows over
 *  forty clients is "nothing outstanding", zero rows over zero clients is
 *  "you are assigned to no clients". Same three-state discipline the hub's own
 *  tiles take. */
/** `GET /api/analytics/profitability`. Revenue less cost, in integer paise —
 *  cost being `effort_minutes * hourly_rate_paise / 60` off the time-tracking
 *  register. `firm_metrics` narrows with the caller's book on this endpoint
 *  (deliberately: the totals are summed from the very per-client rows being
 *  filtered, so leaving them firm-wide would let an Executive recover the
 *  practice's position by subtracting their own clients). */
export interface ProfitabilityPayload {
  period: string;
  firm_metrics: {
    total_revenue_paise: number;
    total_cost_paise: number;
    profit_paise: number;
    profit_margin_pct: number;
    num_clients_billed: number;
    avg_profit_per_client_paise: number;
  };
  by_client?: {
    client_id: string;
    client_name: string;
    revenue_paise: number;
    cost_paise: number;
    profit_paise: number;
    profit_margin_pct: number;
    status: string;
  }[];
}

/** `GET /api/analytics/revenue-vs-effort`. What was billed against what it
 *  cost to deliver — `realization_rate` is revenue ÷ (billable minutes at the
 *  recorded hourly rate), so 1.0 means the engagement recovered exactly what
 *  the time on it was worth. */
export interface RealizationPayload {
  period: string;
  total_revenue_paise: number;
  total_billable_minutes: number;
  avg_revenue_per_hour_paise: number;
  overall_realization_rate: number;
  by_client: {
    client_id: string;
    client_name: string;
    revenue_paise: number;
    effort_minutes: number;
    revenue_per_hour_paise: number;
    realization_rate: number;
  }[];
}

/** `GET /api/intelligence/compliance-risk`. Per-client risk of missing a
 *  filing, scored on the CLIENT'S OWN compliance records — overdue count,
 *  due-within-seven-days count, and any history of filing late. Not a money
 *  figure and not derived from task volume. */
export interface ComplianceRiskPayload {
  clients: {
    client_id: string;
    client_name: string;
    risk_score: number;
    risk_level: string;
    overdue_count: number;
    due_soon_count: number;
    late_filing_history: number;
    predicted_misses: {
      record_id?: string | null;
      compliance_type?: string | null;
      due_date?: string | null;
      reason?: string | null;
    }[];
  }[];
  high_risk_count: number;
  computed_at?: string | null;
}

/** `GET /api/cash-flow-forecast`. Every figure is integer paise and every one
 *  of them is a document somebody issued or received — nothing here is an
 *  average month or a seasonal fill. `unpriced` names the legs deliberately
 *  left out (statutory, payroll) and arrives on EVERY answer, because a dip a
 *  CA is reading has to say what it excludes. */
export interface CashFlowForecastPayload {
  as_at: string;
  opening_paise: number;
  months: {
    period: string;
    label: string;
    opening_paise: number;
    inflows_paise: number;
    outflows_paise: number;
    closing_paise: number;
    by_kind: Record<string, number>;
    is_shortfall: boolean;
  }[];
  first_shortfall: string | null;
  overdue_in_paise: number;
  overdue_out_paise: number;
  undated: { amount_paise: number; kind: string; reference: string }[];
  unpriced: { leg: string; why: string }[];
  gaps: string[];
}

/** `GET /api/intelligence/relationship-health`. `outstanding_paise` is REAL
 *  money — summed off invoices with status Issued or Overdue — not a figure
 *  derived from task counts, which is the trap CLAUDE.md records and which the
 *  memory pipeline's `cash_flow_risk_months` actually was until 25-09-2026. */
export interface RelationshipHealthPayload {
  clients: {
    client_id: string;
    client_name: string;
    health_score: number;
    health_level: string;
    open_tasks: number;
    overdue_tasks: number;
    overdue_invoices: number;
    outstanding_paise: number;
    recent_activity?: number;
  }[];
  at_risk_count: number;
  computed_at?: string | null;
}

/** `GET /api/intelligence/recommendations`. What to do, ranked. */
export interface RecommendationsPayload {
  recommendations: {
    category?: string | null;
    priority: string;
    title: string;
    detail?: string | null;
    action?: string | null;
    client_id?: string | null;
  }[];
  total?: number;
  critical?: number;
  high?: number;
  medium?: number;
  low?: number;
}

export interface HubWorklistPayload {
  tile: string;
  label: string;
  question: string;
  unit: "count" | "paise";
  column: string;
  opens_section: string;
  rows: HubWorklistRow[];
  clients_examined: number;
}

/** One statutory settlement on the handoff screen, exactly as
 *  domain/payroll/handoff.py serialises it. Every string here is composed on
 *  the SERVER — render them, do not rebuild them: they carry statutory
 *  reasoning (why professional tax shows no due date, why a blocked EPFO month
 *  still offers its file) that a sentence written in the browser would lose. */
export type HandoffField = { label: string; value: string | null; note: string | null };
export type HandoffFigure = {
  label: string;
  /** money in integer paise; null when the figure is a count or is in rupees */
  amount_paise: number | null;
  /** whole rupees — the ECR and the ESIC return both carry rupees, because
   *  both portals work in rupees. Not converted to paise and back: that would
   *  put a unit change inside the number the CA is checking against the portal. */
  rupees: number | null;
  count: number | null;
  note: string | null;
};
export type HandoffArtefact = {
  available: boolean; filename: string | null;
  endpoint: string | null; why_not: string | null;
};
export type HandoffObligation = {
  scheme: "epf" | "esic" | "professional_tax";
  key: string;
  title: string;
  authority: string;
  portal: string;
  portal_host: string;
  wage_month: string;
  period_label: string;
  state: string | null;
  due_date: string | null;
  /** set only when there is NO due date, and says why there is none */
  due_note: string | null;
  statute: string | null;
  identity: HandoffField[];
  confirm: HandoffFigure[];
  artefact: HandoffArtefact;
  /** would be refused at the portal today — fix before uploading */
  blocking: string[];
  warnings: string[];
  record_back: string | null;
  /** where the acknowledgement is one of a fixed set — EPFO's return types,
   *  which the server decides from what has already been filed. The form
   *  defaults to the first, so a month that needs a Supplementary does not get
   *  recorded as a Regular. */
  record_options: string[];
  recorded: Record<string, unknown> | null;
};
export type StatutoryHandoff = {
  run_id: string;
  client_id: string | null;
  month: string | null;
  obligations: HandoffObligation[];
  /** professional tax withheld from somebody with no state recorded — money
   *  taken from an employee that no authority will be paid */
  unattributed_pt_paise?: number;
  disclaimer?: string;
};

/** One entry that could have paid a remittance. `entry_total_paise` is what
 *  LEFT THE BANK, which is the figure a challan matches — a late challan
 *  carries interest under ESI Act s.39(5), which is an expense and not a
 *  reduction of the payable, so the liability debit is smaller. */
export type RemittanceCandidate = {
  journal_entry_id: string;
  entry_date: string;
  reference_no: string | null;
  narration: string | null;
  liability_debit_paise: number;
  entry_total_paise: number;
  days_apart: number;
  grade: "exact" | "near";
  /** composed on the server — render it, do not rebuild the sentence */
  reason: string;
};

export type Remittance = {
  id: string;
  scheme: "esic" | "professional_tax";
  wage_month: string;
  state: string | null;
  contribution_period: string | null;
  challan_number: string | null;
  challan_date: string | null;
  amount_paise: number;
  status: "submitted" | "paid";
  submitted_on: string;
  paid_on: string | null;
  journal_entry_id: string | null;
  notes: string | null;
};

/** GET /api/compliance/tax-audit-due-dates — both §44AB dates for one FY.
 *  `basis` names the section and the premise, and is shown rather than
 *  paraphrased: a date on a compliance screen is only as good as what a CA can
 *  check it against. */
export interface TaxAuditDueDates {
  financial_year: string;
  report_due_date: string;
  return_due_date: string;
  basis: string;
}

/** GET /api/payroll/tds-projection — one employee's §192 withholding for a
 *  financial year, month by month, from the SAME `_compute_slip` the payroll
 *  run pays from.
 *
 *  It replaces `lib/services/payrollTdsEstimate.ts`, which carried its own
 *  slab ladder hard-coded to FY 2025-26 with no old regime, no declaration
 *  and no §192(3) (PAY-10). `gaps` says what a projection cannot see — a
 *  month's attendance, and a bonus nobody has decided yet. */
export interface PayrollTdsProjection {
  financial_year: string;
  employee_id: string;
  months: { month: string; actual: boolean; gross_paise: number; tds_paise: number }[];
  deducted_so_far_paise: number;
  months_paid: number;
  projected_monthly_paise: number;
  projected_monthly_gross_paise: number;
  estimated_annual_tds_paise: number;
  estimated_annual_gross_paise: number;
  gaps: string[];
}

/** GET /api/income-tax/tax-audit/applicability — whether §44AB requires an
 *  audit, and on which limb.
 *
 *  THE NATURE OF THE ACTIVITY IS AN INPUT, NEVER INFERRED FROM THE AMOUNT.
 *  This screen used to read it off the turnover — above ₹1 crore "business",
 *  between ₹50 lakh and ₹1 crore "profession" — so a trader with ₹60 lakh was
 *  told an audit was mandatory when §44AB(a) does not reach them (IT-11).
 *
 *  `required` answers the clause tested and nothing else: `limbs_not_tested`
 *  names (c), (d) and (e), each of which compares DECLARED profit against a
 *  deemed figure that no turnover box carries. */
export interface TaxAuditApplicability {
  financial_year: string;
  required: boolean;
  clause: string;
  threshold_applied_paise: number;
  enhanced_limit_applied: boolean;
  basis: string;
  caveats: string[];
  limbs_not_tested: string[];
  form_type: string | null;
  report_due_date: string | null;
  return_due_date: string | null;
}

/** GET /api/income-tax/msme-43bh — what §43B(h) adds back this year, DERIVED
 *  from the purchase ledger rather than from a table the CA re-keys (PUR-15).
 *
 *  THE LIMIT IS FIFTEEN DAYS unless a written agreement says otherwise
 *  (MSMED §2(b)), and at most forty-five even then (the proviso to §15).
 *  Forty-five is the number every article quotes and it is the exception.
 *
 *  `allowed_on_payment_paise` is the other direction: an EARLIER year's bill
 *  that was disallowed then and was actually paid during this year comes back
 *  as a deduction now. */
export interface MSME43BHBill {
  bill_id: string;
  bill_no: string | null;
  vendor_name: string;
  bill_date: string | null;
  limit_days: number | null;
  limit_source: string;
  due_by: string | null;
  total_paise: number;
  deductible_paise: number;
  paid_in_time_paise: number;
  paid_late_paise: number;
  paid_late_in_fys: string[];
  unpaid_paise: number;
  disallowed_paise: number;
  reason: string;
  included: boolean;
}

/** One principal that missed MSMED §15, with §16's own clock on it.
 *  `interest_paise` is null where no Bank Rate was supplied — the working
 *  (which bills, from when, how many rests) survives the refusal. */
export interface MSMEDInterestAmount {
  bill_id: string;
  bill_no: string | null;
  vendor_name: string;
  principal_paise: number;
  /** The day AFTER the appointed day — §16 runs "from the date immediately
   *  following", so the day it fell due is not itself a day of delay. */
  from_date: string | null;
  to_date: string | null;
  /** Whole monthly rests that have FALLEN DUE. A part month is not charged. */
  months: number;
  part_days: number;
  annual_rate_bps: number | null;
  interest_paise: number | null;
  still_running: boolean;
  reason: string;
}

/** MSMED §16 — compound interest with monthly rests at THREE TIMES the RBI
 *  Bank Rate, which the buyer owes the SUPPLIER. A different number from
 *  §43B(h)'s add-back: that defers a deduction, §23 denies this one outright,
 *  so paying it never releases it and the two are independent.
 *
 *  `bank_rate_bps` is null unless the CA supplied one. Nothing in the product
 *  holds the Bank Rate — it moves by RBI notification partway through a year
 *  and a delay spanning a change is governed by more than one — so a null
 *  `interest_paise` is a REFUSAL naming what to look up, never a nil charge. */
export interface MSMEDInterest {
  financial_year: string;
  as_at: string | null;
  bank_rate_bps: number | null;
  charged_rate_bps: number | null;
  interest_paise: number | null;
  amounts: MSMEDInterestAmount[];
  gaps: string[];
  caveats: string[];
}

export interface MSME43BHWorking {
  financial_year: string;
  applicable: boolean;
  disallowed_paise: number;
  allowed_on_payment_paise: number;
  bills: MSME43BHBill[];
  /** One sentence per vendor whose MSMED classification is not recorded. */
  gaps: string[];
  caveats: string[];
  source: string;
  ca_review_required: true;
  /** MSMED §16, the debt to the supplier. Always present. */
  msmed_interest: MSMEDInterest;
}

/** GET /api/compliance/payroll-deposit-due-dates — what one payroll month owes.
 *  `gaps` names what is deliberately NOT dated (professional tax), because an
 *  absent row and a nil liability look the same on a calendar. */
export interface PayrollDepositDueDates {
  period: { year: number; month: number; quarter: string; financial_year_end: number };
  deposits: { label: string; authority: string; statute: string; due_date: string }[];
  returns: { label: string; quarter: string; authority: string; statute: string; due_date: string }[];
  gaps: string[];
}

/** GET /api/compliance/payroll-deposit-due-dates/fy — all twelve wage months
 *  of one financial year, plus its four TDS return dates. One call, because the
 *  firm payroll report is a whole-year calendar. */
export interface PayrollDepositDueDates_FY {
  financial_year: string;
  months: { year: number; month: number; quarter: string;
            deposits: { label: string; authority: string; statute: string; due_date: string }[] }[];
  returns: { label: string; quarter: string; authority: string; statute: string; due_date: string }[];
  gaps: string[];
}

/** GET /api/compliance/due-dates/calculate — the fields this app reads. The
 *  endpoint returns more (ITR, advance tax, and the gaps that go with them);
 *  those belong to the income-tax screens, not the GST filing tracker. */
export type GstDueDates = {
  period: string;              // "YYYY-MM"
  gstr1_due_date: string;      // CGST Act s.37 — 11th of the following month
  gstr3b_due_date: string;     // CGST Act s.39 — 20th of the following month
  gstr9_due_date: string;      // CGST Act s.44 — 31 December after the FY ends
};

/** One employee's §192 declaration, as the payroll API returns it.
 *  Every amount is integer paise. */
export type StatutoryRow = {
  employee_id: string;
  name: string | null;
  basic_paise: number;
  da_paise: number;
  gross_paise: number;
  pf_applicable: boolean;
  esi_applicable: boolean;
  pf_employee_paise: number;
  pf_employer_paise: number;
  pf_employer_eps_paise: number;
  pf_employer_epf_paise: number;
  edli_paise: number;
  pf_admin_paise: number;
  eps_eligible: boolean;
  esi_employee_paise: number;
  esi_employer_paise: number;
  joining_date: string | null;
  gratuity_payable_paise: number;
  gratuity_eligible: boolean;
  gratuity_years: number;
  /** Why no gratuity is payable — under five years, no joining date, no
   *  wages. A zero and "we do not know when they joined" must not look the
   *  same, which is exactly the bug this replaced. */
  gratuity_reasons: string[];
};

export type StatutorySummary = {
  month: string;
  financial_year: string | null;
  rows: StatutoryRow[];
  totals: Record<string, number>;
  gaps: string[];
};

export type ApplyStructureResult = {
  structure_id: string;
  structure_name?: string;
  effective_from?: string;
  preview: boolean;
  applied: number;
  employees: { employee_id: string; name?: string; monthly_gross_paise: number;
               [component: string]: string | number | undefined }[];
  /** Sentences the server composed — a two-decimal percentage that cannot
   *  express the structure's HRA exactly, or months already released and paid
   *  at the old figures, whose difference is arrears. */
  notes: string[];
};

// ── §37 amendments and the exception report (GST-13) ─────────────────────────
//
// CGST Act §37: a filed GSTR-1 can never be revised. A correction to it is
// declared in a LATER return's amendment tables — 9A for invoices, 9C for
// credit and debit notes, 10 for B2C-others — each naming the original
// document so GSTN knows which entry it supersedes.

/** The five money heads every GSTR-1 figure is reported under, in paise. */
export type GSTHeads = {
  taxable_paise: number; cgst_paise: number; sgst_paise: number;
  igst_paise: number; cess_paise: number;
};

export type GSTExceptionDoc = {
  doc_no?: string;
  kind?: string;
  section?: string;
  counterparty?: string;
  doc_date?: string;
  /** Which amendment table this correction is declared in — "9A", "9C", "10",
   *  or "current period" for something that was never declared at all and so
   *  has no filed entry to supersede. */
  declare_in?: string;
  filed?: GSTHeads;
  books?: GSTHeads;
  delta?: GSTHeads;
  filed_section?: string;
  books_section?: string;
} & Partial<GSTHeads>;

export type GSTR1ExceptionReport = {
  /** "ok" | "not_filed" | "payload_missing" — the last means the return was
   *  marked filed before its payload was recorded, so nothing can be compared
   *  and the drift for that period cannot be detected at all. */
  status: string;
  period: string;
  message?: string;
  gstin?: string;
  filed_at?: string;
  arn?: string;
  clean?: boolean;
  finding_count?: number;
  documents?: {
    /** In the books, never filed. Goes in the CURRENT period's ordinary
     *  table — there is no filed entry to amend. */
    missing_from_return: GSTExceptionDoc[];
    /** Filed, and no longer in the books. The most serious of the four. */
    missing_from_books: GSTExceptionDoc[];
    amount_changed: GSTExceptionDoc[];
    /** Now belongs to a different GSTR-1 table. Amending the value alone
     *  would leave it in the wrong one. */
    reclassified: GSTExceptionDoc[];
  };
  b2cs?: { changed: GSTExceptionDoc[]; note?: string };
  totals?: { filed: GSTHeads; books: GSTHeads; delta: GSTHeads };
  rule?: string;
  ca_review_required?: boolean;
};

export type GSTAmendmentWindow = {
  /** "open" | "closing_soon" | "expired" — §37(3)/§16(4): 30 November
   *  following the FY, or the date GSTR-9 was furnished, whichever is
   *  EARLIER. */
  status?: string;
  closes_on?: string;
  reason?: string;
  days_left?: number;
};

export type GSTR1AmendmentsReport = {
  period: string;
  source_periods: string[];
  /** The GSTN amendment sections this period would carry, ready to merge. */
  sections?: Record<string, unknown>;
  /** NOT amendments: raised after the period was filed, so never declared —
   *  they belong in this period's ordinary tables. */
  carry_forward: Array<Record<string, unknown>>;
  /** NOT amendments either: cancelled after filing, which has no single right
   *  answer (amend to nil, or raise a credit note). Surfaced for the CA. */
  needs_decision: Array<Record<string, unknown>>;
  /** Periods whose correction window has already closed. Real drift that can
   *  no longer be declared — surfaced because a CA needs to know what is
   *  beyond repair. */
  expired: Array<{ period: string; window?: GSTAmendmentWindow;
                   counts?: Record<string, number> }>;
  closing_soon: Array<{ period: string; window?: GSTAmendmentWindow;
                        counts?: Record<string, number> }>;
  as_of?: string;
  counts: {
    amendments?: number; carry_forward?: number; needs_decision?: number;
    source_periods?: number; expired_periods?: number; closing_soon_periods?: number;
  };
  ca_review_required?: boolean;
};

export type GSTR1WithAmendments = {
  payload?: Record<string, unknown>;
  amendments?: {
    sections: string[];
    counts: Record<string, number>;
    source_periods: string[];
    expired: GSTR1AmendmentsReport["expired"];
    needs_decision: Array<Record<string, unknown>>;
    carry_forward: Array<Record<string, unknown>>;
    closing_soon: GSTR1AmendmentsReport["closing_soon"];
  };
  ca_review_required?: boolean;
  [key: string]: unknown;
};

// ── The ITC register and Table 11 advances (GST-13) ──────────────────────────

/** The four heads a reversal or reclaim is declared under. NO taxable value:
 *  Table 4 is about CREDIT, not about the supply it came from. */
export type ITCHeads = {
  igst_paise: number; cgst_paise: number; sgst_paise: number; cess_paise: number;
};

export type ITCRegisterRow = {
  id: string;
  kind: "reversal" | "reclaim";
  period: string;
  journal_entry_id: string;
  /** rule_37 | rule_37a | section_16_2b | section_16_2c | other — the
   *  RECLAIMABLE reasons only. Rules 38/42/43 and §17(5) are permanent and
   *  belong in Table 4(B)(1), derived from the documents; registering one here
   *  would double-count it. */
  reason_code?: string;
  reverses_id?: string | null;
  purchase_bill_id?: string | null;
  notes?: string | null;
  created_at?: string;
} & Partial<ITCHeads>;

export type ITCRegisterPeriod = {
  period: string;
  /** -> GSTR-3B Table 4(B)(2) */
  reversals: ITCRegisterRow[];
  /** -> GSTR-3B Table 4(D)(1) */
  reclaims: ITCRegisterRow[];
  reversal_totals: Partial<ITCHeads>;
  reclaim_totals: Partial<ITCHeads>;
  ca_review_required?: boolean;
};

export type ITCReversalInput = {
  client_id: string;
  journal_entry_id: string;
  period: string;
  reason_code: string;
  purchase_bill_id?: string;
  notes?: string;
} & Partial<ITCHeads>;

export type ITCReclaimInput = {
  client_id: string;
  journal_entry_id: string;
  period: string;
  /** The reversal this brings back. */
  reverses_id: string;
  notes?: string;
} & Partial<ITCHeads>;

export type GSTR1Advances = {
  period: string;
  unadjusted_advances: Array<{
    receipt_id: string; receipt_no?: string; receipt_date?: string;
    customer_name?: string; customer_gstin?: string | null;
    amount_paise: number; unadjusted_paise: number;
  }>;
  count: number;
  total_unadjusted_paise: number;
  /** Whether Table 11 is computed FOR THIS CLIENT — the client's own
   *  `gst_advance_tax_applicable`, not a constant. A CA reading an empty
   *  Table 11 needs to know whether it is empty because there were no
   *  advances or because tax on advances is not switched on. It was hardcoded
   *  false long after `table_11_sections` began declaring real 11A rows. */
  table_11_computed: boolean;
  why?: string;
  rule?: string;
  ca_review_required?: boolean;
};

// ── The employee drawer's shapes (PAY-11) ────────────────────────────────────
//
// Mirrors of the router's Pydantic models. Every amount is integer paise and
// every computation is the server's — these types exist so the forms send what
// the endpoints read, not so anything can be worked out here.

/** What only a human knows about a departure: why they left, what the contract
 *  says about notice, and what they still owe. Everything else — length of
 *  service, wages, the gratuity and leave formulae — comes off the master. */
export type SettlementInput = {
  client_id: string;
  leaving_date: string;
  on_death_or_disablement?: boolean;
  /** Decides §10(10AA) entirely. */
  on_retirement?: boolean;
  is_government_employee?: boolean;
  salary_to_last_day_paise?: number;
  leave_days_encashed?: number;
  leave_encashment_paise?: number;
  bonus_accounting_year?: string | null;
  bonus_rate_bps?: number;
  bonus_months_worked?: number;
  bonus_working_days?: number;
  /** §12 of the Bonus Act computes on ₹7,000 OR the minimum wage, whichever is
   *  HIGHER. There is no table of minimum wages — supplying it is a human
   *  step, and treating ₹7,000 as a ceiling underpays by half in most states. */
  minimum_wage_monthly_paise?: number | null;
  notice_pay_recovered_paise?: number;
  loans_outstanding_paise?: number;
  other_recoveries_paise?: number;
  /** §10(10) and §10(10AA) are LIFETIME limits across employers. Absent, the
   *  full limit is assumed and the response says so. */
  gratuity_exemption_already_used_paise?: number | null;
  leave_exemption_already_used_paise?: number | null;
  gratuity_amount_actually_paid_paise?: number | null;
  average_last_ten_months_paise?: number | null;
};

export type SettlementComponent = {
  label: string; gross_paise: number; exempt_paise: number;
  taxable_paise: number; statute: string;
  tax_head: string; exempt_section: string | null;
};

export type SettlementResult = {
  employee_id: string;
  employee_name?: string;
  leaving_date?: string;
  components: SettlementComponent[];
  deductions: { label: string; gross_paise: number; statute: string }[];
  totals: {
    gross_paise?: number; exempt_paise?: number;
    /** A recovery reduces what the employer PAYS and never reduces §17(1) —
     *  taking notice pay back does not un-earn the salary. */
    taxable_paise?: number; deductions_paise?: number;
    net_payable_paise?: number;
    gross_17_1_paise?: number; gross_17_3_paise?: number;
  };
  exempt_by_section?: Record<string, number>;
  gratuity_detail?: {
    eligible: boolean; completed_years: number; years_counted: number;
    payable_paise: number; exempt_paise: number;
  };
  gaps: string[];
  problems: string[];
};

export type SalaryRevisionInput = {
  client_id: string;
  effective_from: string;
  basic_paise?: number;
  hra_percent?: number;
  da_percent?: number;
  lta_paise?: number;
  medical_paise?: number;
  special_allowance_paise?: number;
  other_allowances_paise?: number;
  reason?: string;
};

export type SalaryRevisionRow = SalaryRevisionInput & {
  id: string; employee_id: string; created_at?: string;
};

export type EmployeeLoanInput = {
  client_id: string;
  principal_paise: number;
  monthly_instalment_paise: number;
  /** Rule 3(7)(i): below the SBI rate for the same kind of loan the shortfall
   *  is a PERQUISITE. Zero means interest-free — and an employer who records
   *  only the recovery has an unvalued perquisite in the Form 16. */
  interest_rate_bps?: number;
  purpose?: string;
  started_on?: string | null;
};

export type EmployeeLoanRow = EmployeeLoanInput & {
  id: string; employee_id: string;
  outstanding_paise?: number; status?: string;
};

export type PerquisiteResult = {
  employee_id?: string;
  fy?: string;
  items?: { label: string; value_paise: number; rule: string; note?: string }[];
  total_paise?: number;
  /** What Rule 3 needs and payroll cannot supply — the SBI rate for a
   *  concessional loan, the actual running expenditure for a wholly private
   *  car. A gap, never a guessed number. */
  gaps?: string[];
  disclaimer?: string;
};

export type ArrearsReliefInput = {
  client_id: string;
  receipt_fy: string;
  total_income_receipt_year_paise: number;
  arrears: { fy: string; amount_paise: number;
             total_income_that_year_paise?: number | null }[];
  use_new_regime?: boolean;
  /** The proviso to §89 read with Rule 21AA: no Form 10E, no relief. */
  form_10e_acknowledgement?: string | null;
};

export type ArrearsReliefResult = {
  employee_id?: string;
  receipt_fy?: string;
  relief_paise?: number;
  /** False with a reason rather than a zero: no Form 10E (the proviso to §89
   *  with Rule 21AA), or a year the statutory rate registry does not hold —
   *  §89 compares years AT THEIR OWN RATES, so a substituted year makes the
   *  whole relief a fiction that looks entirely reasonable. */
  available?: boolean;
  blocked_reason?: string | null;
  tax_with_arrears_paise?: number;
  tax_without_arrears_paise?: number;
  difference_a_paise?: number;
  difference_b_paise?: number;
  per_year?: Record<string, unknown>[];
  gaps?: string[];
  disclaimer?: string;
};

/** One employee's row of 24Q Annexure II — the annual salary detail TRACES
 *  turns into Form 16 Part B (CBDT Notification 09/2019). Every figure is
 *  integer paise and every one of them is computed on the server: §16(iii)
 *  professional tax in particular is allowed only under the old regime
 *  (§115BAC(2)(i) permits clause (ia) and nothing else), which is why the
 *  allowable figure is a field of its own rather than something the screen
 *  works out. */
export type AnnexureIIRow = {
  employee_id: string;
  name: string;
  pan: string;
  months_paid: number;
  regime: "new" | "old";
  salary_17_1_paise: number;
  perquisites_17_2_paise: number;
  profits_in_lieu_17_3_paise: number;
  gross_salary_paise: number;
  exempt_under_10_paise: number;
  net_salary_paise: number;
  standard_deduction_16_ia_paise: number;
  professional_tax_16_iii_paise: number;
  allowable_professional_tax_paise: number;
  income_under_salaries_paise: number;
  chapter_vi_a_paise: number;
  tds_deducted_paise: number;
};

export type AnnexureIIResponse = {
  client_id: string;
  financial_year: string;
  rows: AnnexureIIRow[];
  /** Block filing. */
  problems: string[];
  /** Do NOT block — things only the employee holds (§17(2), the §10
   *  exemptions, Chapter VI-A). An annexure with no Chapter VI-A is correct
   *  for someone who declared none. */
  gaps: string[];
  totals: { employees?: number; gross_salary_paise?: number;
            income_under_salaries_paise?: number; tds_paise?: number };
  ready: boolean;
  form_16_note?: string;
  disclaimer?: string;
};

export type DeclarationItemRow = {
  id: string;
  section: string;
  label: string;
  amount_declared_paise: number;
  amount_verified_paise: number;
  status: "declared" | "verified" | "rejected";
  /** What the employee SAID they are producing — a policy number, a receipt
   *  number, often all there is for a proof handed over on paper. */
  proof_reference: string;
  /** What they actually PRODUCED (PAY-26, migration 410). Rule 26C's evidence
   *  half, which had nowhere to live, so a verifier set an amount against a
   *  memory of a document. The server parses and normalises every entry
   *  through `domain/attachments`: http/https only, because an employee's own
   *  upload is untrusted input; an uploaded document carries `document_id`
   *  and NO url, so a signed link cannot rot into a dead one. */
  proof_attachments: { name: string; url?: string; document_id?: string }[];
};

export type DeclarationRow = {
  id: string;
  employee_id: string;
  fy: string;
  /** The intimation to the EMPLOYER (CBDT Circular 04/2023) — withholding
   *  only. NOT the §115BAC(6) election, which is Form 10-IEA or the return. */
  regime: "new" | "old";
  status: "draft" | "submitted" | "verified";
  rent_paid_declared_paise: number;
  rent_paid_verified_paise: number;
  landlord_name: string;
  landlord_address: string;
  landlord_pan: string;
  rent_is_metro: boolean;
  lta_declared_paise: number;
  lta_verified_paise: number;
  home_loan_interest_declared_paise: number;
  home_loan_interest_verified_paise: number;
  lender_name: string;
  lender_pan: string;
  other_income_declared_paise: number;
  house_property_loss_declared_paise: number;
  proofs_verified: boolean;
  submitted_at: string | null;
  verified_at: string | null;
  items: DeclarationItemRow[];
  /** Reasons this claim cannot be allowed as it stands — a missing landlord
   *  PAN above the Rule 26C threshold, a section payroll cannot give effect
   *  to. Computed by the backend, which is where Rule 26C lives. */
  problems: string[];
  /** Things the CA must know that do NOT block — see the API docstring. */
  notices: string[];
};

/** A journal line as the editor reads and writes it. Integer paise only. */
export type JournalLineIO = {
  id?: string;
  account_id: string;
  debit_paise: number;
  credit_paise: number;
  narration?: string | null;
};

/** INV-08 — the physical stock count. */
export type StockCountSessionRow = {
  id: string;
  client_id: string;
  count_date: string;
  reference_no: string;
  status: "open" | "posted" | "abandoned";
  notes: string | null;
  posted_at: string | null;
};

export type StockCountLine = {
  service_catalogue_id: string;
  item_name: string;
  unit: string | null;
  /** What the books said when the sheet was opened… */
  system_qty_units: string;
  /** …and what they say as at the count date NOW. The variance is measured
   *  against this one: the count is a fact about the count date, and stock
   *  moves between opening a sheet and keying it in. */
  current_qty_units: string;
  counted_qty_units: string | null;
  variance_qty_units: string | null;
  direction: "increase" | "decrease" | null;
  reason: string | null;
  reverse_itc: boolean | null;
  itc_reversal_is_interstate: boolean;
  will_post: boolean;
  /** Why this line will not post. A blank count and an undecided s.17(5)(h)
   *  are the two, and both are per LINE — ninety-eight post and two are
   *  named. */
  gaps: string[];
  caveats: string[];
  notes: string;
};

export type StockCountSheet = {
  session: StockCountSessionRow;
  lines: StockCountLine[];
  counted_count: number;
  variance_count: number;
  postable_count: number;
  blocked_count: number;
  gaps: string[];
};

/** INV-04 — one item's units ON HAND, bucketed by how long they have been
 *  held. Migration 408. Everything here is the server's: the bands, the FIFO
 *  consumption, the value split and the four caveats. */
/** PAY-27 — one employee's movement between two payroll months. */
export type PayrollEmployeeVariance = {
  employee_id: string;
  name: string;
  /** `joined` | `left` | `changed` | `unchanged`. A leaver's name comes off
   *  the month that HAS them, so the one report that exists to name them
   *  never shows an unnamed row. */
  status: string;
  gross_paise: number;
  prior_gross_paise: number;
  gross_delta_paise: number;
  net_paise: number;
  prior_net_paise: number;
  net_delta_paise: number;
  /** EVERY component that moved, largest absolute first. No single cause is
   *  ever named — a payroll total moves for several reasons at once. */
  moved: { label: string; delta_paise: number }[];
  /** Days are not money and are reported apart. */
  days_moved: { label: string; delta: number }[];
  /** Gross moved with no component behind it: the figure is real and what
   *  explains it is not in the slip's own columns. */
  unexplained: boolean;
};

export type PayrollMonthOnMonth = {
  month: string;
  prior_month: string;
  /** False where the preceding month has no RELEASED run. The figures below
   *  are then this month's alone and the prior columns are nil — a draft is
   *  not a baseline, and an earlier month is not the preceding one. */
  comparable: boolean;
  gross_paise: number;
  prior_gross_paise: number;
  gross_delta_paise: number;
  net_paise: number;
  prior_net_paise: number;
  net_delta_paise: number;
  headcount: number;
  prior_headcount: number;
  employees: PayrollEmployeeVariance[];
  changed_count: number;
  notes: string[];
};

export type PayrollDepartmentCost = {
  month: string;
  rows: {
    department: string;
    headcount: number;
    gross_paise: number;
    employer_contribution_paise: number;
    cost_paise: number;
  }[];
  total_gross_paise: number;
  total_employer_contribution_paise: number;
  total_cost_paise: number;
  total_headcount: number;
  notes: string[];
};

export type PayrollBankAdvice = {
  month: string;
  /** The account number is MASKED here and whole in the FILE — a screen
   *  showing thirty account numbers in full is a shoulder-surfing surface for
   *  no gain. */
  rows: {
    employee_id: string; name: string; account_no_masked: string;
    ifsc: string; net_paise: number;
  }[];
  /** Held OUT of the file, each with what is missing. */
  excluded: {
    employee_id: string; name: string; reason: string; why: string;
    net_paise: number;
  }[];
  payable_count: number;
  excluded_count: number;
  total_paise: number;
  /** That this file moves no money, that the layout is generic, and — on an
   *  unreleased run — that a draft has paid nobody. Rendered, never
   *  re-worded here. */
  notes: string[];
};

export type ReorderLine = {
  service_catalogue_id: string;
  name: string;
  unit: string | null;
  group: string;
  /** NUMERIC(10,3) crosses the wire as a STRING and stays one. */
  on_hand_units: string;
  /** null is NOT zero — nobody has recorded a level. The server says so in
   *  `note`; do not render an absence as a number. */
  reorder_level_units: string | null;
  state: "below" | "at" | "above" | "not_set" | "unknown";
  shortfall_units: string;
  note: string | null;
};

export type ReorderGroup = {
  group: string;
  below_count: number;
  not_set_count: number;
  lines: ReorderLine[];
};

export type ReorderReport = {
  /** Worst first inside each group; the unrecorded group sorts last. */
  groups: ReorderGroup[];
  to_reorder: number;
  no_level_recorded: number;
  items_considered: number;
  note_when_no_level: string;
};

export type ExpiringEwayBill = {
  record_id: string;
  client_id: string;
  invoice_number: string;
  ewb_number: string | null;
  valid_upto: string | null;
  /** "recorded" (off the portal, authoritative) or "computed" (Rule 138(10)
   *  arithmetic on the distance). Shown, because the two are not the same
   *  claim. */
  source: "recorded" | "computed" | null;
  days_left: number | null;
  state: "expired" | "expires_today" | "expiring" | "unknown";
  /** Why the expiry could not be worked out at all. Such a bill is LISTED,
   *  never dropped — a silent omission reads as a clean answer. */
  gap: string | null;
};

export type ExpiringEwayBills = {
  as_of: string;
  horizon_days: number;
  bills: ExpiringEwayBill[];
  expired: number;
  expires_today: number;
  expiring: number;
  undeterminable: number;
  /** That the portal remains authoritative, and that the action is to EXTEND
   *  rather than to file. Rendered, never re-worded here. */
  caveats: string[];
};

export type StockAgeingItem = {
  service_catalogue_id: string;
  name: string;
  unit: string;
  /** NUMERIC(10,3) crosses the wire as a STRING and stays one — a quantity
   *  turned into a float is how a register stops footing. */
  qty_units: string;
  /** The carrying amount, which ties to the Inventory control account. */
  value_paise: number;
  band_qty: Record<string, string>;
  band_value_paise: Record<string, number>;
  oldest_holding_date: string | null;
  /** Position at or below nil: there is nothing to age, and the bands are
   *  empty for a REASON rather than because the stock is new. */
  nothing_on_hand: boolean;
};

export type StockAgeing = {
  as_of: string;
  /** Youngest to oldest. Rendered in THIS order — the server's — because the
   *  keys do not sort into it alphabetically. */
  bands: string[];
  band_labels: Record<string, string>;
  items: StockAgeingItem[];
  total_qty_by_band: Record<string, string>;
  total_value_by_band: Record<string, number>;
  total_value_paise: number;
  total_items: number;
  /** The bands are a convention, ageing is FIFO whatever the cost formula is,
   *  the value is pro-rated, and no provision is computed. Rendered, never
   *  re-worded here. */
  notes: string[];
};

export type StockCountPostResult = {
  session_id: string;
  reference_no: string;
  count_date: string;
  posted: { item: string; quantity: string; direction: string }[];
  posted_count: number;
  failed: { item: string; why: string }[];
  failed_count: number;
  not_posted_count: number;
};

/** One entry of GET /api/banking/account-types. */
export type WorthALookException = {
  code: string;
  severity: "high" | "medium" | "low";
  message: string;
  /** The rules' own judgement that this WOULD stop a posting if anything did.
   *  Nothing acts on it — domain/banking/exceptions.py is the authority on why
   *  the default is advisory. Shown, never enforced. */
  blocking: boolean;
  detail: Record<string, unknown>;
};

export type WorthALookRow = {
  transaction_id: string;
  transaction_date: string;
  description: string | null;
  payee_name: string | null;
  debit_paise: number;
  credit_paise: number;
  matched_document_no: string | null;
  exceptions: WorthALookException[];
};

export type WorthALook = {
  from_date: string;
  to_date: string;
  bank_account_id: string | null;
  reviewed_count: number;
  flagged: WorthALookRow[];
  /** What could NOT be asked, and why. A rule that did not run looks exactly
   *  like one that passed, so these are rendered rather than swallowed. */
  gaps: { code: string; message: string }[];
  policy: Record<string, number>;
};

export type BankAccountTypeInfo = {
  value: string;
  ledger_account_type: string;
  ledger_account_subtype: string;
  owed_to_the_bank: boolean;
  balance_label: string;
};

/** GET /api/currencies/policy. `gates` is the half that matters: `active`
 *  alone could not say WHICH of three switches was down, which is why the
 *  feature was unusable (ACC-19). */
/** One row of public.fx_rates. `rate` is a STRING: NUMERIC(18,8) is exact and
 *  a JS number is not — read it, show it, never arithmetic on it here. */
export type FxRate = {
  id?: string;
  base: string;
  quote: string;
  rate_date: string;
  rate_type: string;
  rate: string;
  source: string;
  created_at?: string;
};

export type FxRateList = {
  base: string; quote: string; rate_type: string; rates: FxRate[];
};

export type CurrencyPolicy = {
  active: boolean;
  functional_currency: string;
  gates: {
    platform: { on: boolean; settable: boolean; why?: string };
    firm: { on: boolean; settable: boolean };
    client: { on: boolean; settable: boolean };
    functional_currency_supported: boolean;
    functional_currency: string;
  };
};

/**
 * GET /api/accounting/journal/{id}. Beyond the row itself this carries the two
 * fields the editor is built around:
 *   `editable`    — may this be changed at all right now
 *   `lock_reason` — null when open; otherwise the sentence to show the CA
 *                   ("Financial year 2025-26 is locked…", "GSTR-3B covering
 *                   this date was filed on 18 Jul 2026…")
 * A reason beats a boolean because "locked year" and "return filed" call for
 * different actions — unlock, versus reverse and amend in the next return.
 */
export type JournalEntryDetail = {
  id: string;
  client_id: string;
  entry_date: string;
  reference_no: string | null;
  narration: string;
  entry_type: string;
  is_posted: boolean;
  is_reversed: boolean;
  source_type: string | null;
  created_at?: string;
  lines: JournalLineIO[];
  total_debit_paise: number;
  total_credit_paise: number;
  status: "posted" | "draft";
  editable: boolean;
  lock_reason: string | null;
  /** Supporting documents (migration 138). A name and EITHER a pasted
   *  http(s) link OR the id of a document in the firm's store — never both:
   *  the store's own URLs are signed and expire in an hour, so an uploaded
   *  document is referenced by id and a fresh link minted when someone opens
   *  it. `domain/attachments` is the rule and REFUSES anything else, including
   *  a `javascript:` or `data:` link, which is stored XSS delivered as a
   *  "receipt". */
  attachments?: JournalAttachment[];
};

export type JournalAttachment = {
  name: string;
  url?: string;
  document_id?: string;
};

/** PATCH body. Every field optional; `lines` replaces the whole set. */
export type JournalEntryUpdate = {
  entry_date?: string;
  reference_no?: string | null;
  narration?: string;
  entry_type?: string;
  lines?: JournalLineIO[];
  /** ACC-25. Omit to leave the documents alone; an EMPTY array removes them.
   *  Accepted on a DRAFT only — a posted entry's header is immutable outside
   *  `edit_posted_journal`, and the server refuses it with a sentence. */
  attachments?: { name: string; url: string }[];
};

// Phase 4.5.1 — a client_portal_users row (F22 fix: invite_token is single-use,
// never re-sent to the frontend once accepted — the field is present here only
// because inviteContact()'s response carries it once, to build the invite link).
export type PortalContact = {
  id: string; client_id: string; email: string; name: string | null;
  status: "invited" | "active" | "deactivated";
  auth_user_id?: string | null; invite_token?: string | null;
  invited_at?: string | null; activated_at?: string | null; deactivated_at?: string | null;
};

// Row shape of GET /api/reports/transactions. Mirrored (not imported) from
// lib/data/transactions.ts so this module stays free of app-layer imports;
// that file re-exports it as `Transaction` for its callers.
export type ReportTransaction = {
  id: string; client_id: string; transaction_type: string; transaction_date: string;
  reference_no?: string; party_name: string;
  taxable_amount_paise: number; cgst_paise: number; sgst_paise: number; igst_paise: number;
  tds_paise: number; tds_section?: string | null;
  total_paise: number; paid_paise: number; outstanding_paise: number;
  is_interstate: boolean; place_of_supply?: string | null; status: string;
};

// ── The Schedule III ageing schedules ────────────────────────────────────────
// MCA Notification G.S.R. 207(E) of 24 March 2021, Division I. Every amount is
// integer paise. The two tables have DIFFERENT columns — receivables age in five
// prescribed buckets from six months, payables in four from one year — so a
// renderer must read `buckets` rather than assume one shape.

export type AgeingBucket = { key: string; label: string; prescribed: boolean };

export type AgeingRow = {
  key: string; label: string;
  amounts: Record<string, number>;
  total_paise: number;
};

export type AgeingTable = {
  title: string;
  buckets: AgeingBucket[];
  rows: AgeingRow[];
  column_totals: Record<string, number>;
  total_paise: number;
  /** Disclosed SEPARATELY, never aged — both notes end "Unbilled dues shall be
   *  disclosed separately", and an unbilled due has no due date to age from.
   *
   *  null until somebody has reviewed the chart of accounts (see
   *  `unbilled_reviewed_on`). Not zero: a zero asserts the client has no
   *  unbilled dues, and until a human looks the truth is that nobody knows. */
  unbilled_dues_paise: number | null;
  /** The marked accounts behind that figure, largest first. Empty while the
   *  figure is null. A balance can be negative — an accrual account on the
   *  wrong side is shown at its real figure and flagged, not hidden. */
  unbilled_accounts: {
    account_id: string; account_code: string; account_name: string;
    balance_paise: number;
  }[];
};

export type AgeingPayablesTable = AgeingTable & {
  /** Balances owed to vendors nobody has classified under the MSMED Act. NOT
   *  included in any row: IT Act s.43B(h) makes micro/small a taxable-income
   *  question, so a guess would change the client's tax, not just the layout. */
  unclassified_paise: number;
  unclassified_vendors: { vendor_id: string | null; vendor_name: string; outstanding_paise: number }[];
};

export type AgeingSchedule = {
  as_of: string;
  division: string;
  statute: string;
  ageing_from: string;
  receivables: AgeingTable;
  payables: AgeingPayablesTable;
  /** The date somebody recorded that they had been through this client's chart
   *  of accounts and marked every account holding unbilled dues. null means
   *  nobody has, which is what makes both `unbilled_dues_paise` null. IST. */
  unbilled_reviewed_on: string | null;
  gaps: { code: string; message: string }[];
};

export type AgeingDocument = {
  invoice_id?: string; invoice_no?: string | null; invoice_date?: string | null;
  customer_id?: string | null; customer_name?: string | null;
  bill_id?: string; bill_no?: string | null; bill_date?: string | null;
  vendor_id?: string | null; vendor_name?: string | null;
  outstanding_paise: number; days_overdue: number; aging_bucket: string;
  /** The Schedule III marks (migration 303). `considered_doubtful` is absent on
   *  bills — that row exists only on the receivables table; the payables table
   *  splits on MSME/Others, which is a property of the VENDOR. */
  is_disputed?: boolean;
  considered_doubtful?: boolean;
};

/** One payment or receipt with money no document has absorbed (PUR-24).
 *  A supplier advance is an ASSET and a customer advance a LIABILITY, so
 *  neither is inside the ageing buckets — they are their own section, and
 *  what ties the report to the control account is the ageing total LESS
 *  them. `days_old` is AGE, not lateness: an advance has no due date. */
export type AgeingAdvance = {
  document_id: string;
  document_no: string | null;
  party_id: string | null;
  party_name: string | null;
  document_date: string | null;
  unapplied_paise: number;
  days_old: number;
  aging_bucket: string;
  /** Present only on a non-INR document. There is no stored
   *  transaction-currency counterpart to the base figure, so this is a label
   *  and the amount above stays the authoritative one. */
  txn_currency?: string;
};

/** The per-document ageing payload. `K` names which key carries the rows. */
export type AgeingDetail<K extends "invoices" | "bills"> = {
  as_of: string | null;
  buckets: Record<string, number>;
  total_outstanding_paise: number;
  advances: AgeingAdvance[];
  advance_buckets: Record<string, number>;
  total_advances_paise: number;
  /** Documents outstanding LESS the advances against no document — the figure
   *  that ties to Trade Receivables / Trade Payables. Computed server-side so
   *  one number means one thing. Exactly one of the two is present, named for
   *  the side it belongs to. */
  net_receivable_paise?: number;
  net_payable_paise?: number;
  /** A stored unapplied balance that disagrees with the document's own
   *  allocation rows, stated rather than absorbed. */
  advance_gaps: string[];
} & { [P in K]: AgeingDocument[] };

// ── The Schedule III ratios ──────────────────────────────────────────────────
// Division I, General Instructions, Additional Regulatory Information clause
// (Q) — MCA G.S.R. 207(E) of 24-03-2021. Amounts are integer paise; a ratio is
// basis points, 10,000 bps = 1.00, and `unit` says whether to read it as
// "x times" or as a percentage.

export type RatioComponent = { label: string; paise: number };

export type ScheduleIiiRatio = {
  key: string;
  clause: string;                       // (a) … (k), as Schedule III lists them
  label: string;
  unit: "times" | "percent";
  /** Both sides are disclosed with the ratio — clause (Q) requires explaining
   *  what went into each, so the labels are part of the filing, not commentary.
   *  Absent where the ratio could not be computed. */
  numerator: RatioComponent | null;
  denominator: RatioComponent | null;
  value_bps: number | null;
  prior_value_bps: number | null;
  /** Signed change against the preceding year, in bps of the prior magnitude.
   *  null where there is no prior year, or where the prior year was zero. */
  variance_bps: number | null;
  /** Clause (Q): a change of MORE than 25% needs its own explanation. */
  needs_explanation: boolean;
  unavailable_reason: string | null;
  explanation: string | null;
};

export type ScheduleIiiRatioNote = {
  fy: string;
  preceding_fy: string | null;
  period: { start: string; end: string };
  statute: string;
  variance_threshold_bps: number;
  has_prior_year: boolean;
  ratios: ScheduleIiiRatio[];
  needs_explanation_count: number;
  gaps: { code: string; message: string }[];
};

// ── Recurring journals ───────────────────────────────────────────────────────
// Templates the FIRM owns (`recurring_journal_templates`, migration 377).
// Generating produces a DRAFT manual journal through the one posting kernel
// and never posts one. Amounts are integer paise; each line is a debit OR a
// credit, never both.

export type RecurringJournalLine = {
  id?: string;
  account_id: string;
  debit_paise: number;
  credit_paise: number;
  narration?: string | null;
  sort_order?: number;
};

export type RecurringJournalTemplate = {
  id: string;
  client_id: string;
  name: string;
  frequency: string;
  day_of_month: number;
  narration: string | null;
  start_date: string;
  end_date: string | null;
  next_run_date: string;
  status: string;
  lines: RecurringJournalLine[];
};

export type RecurringJournalRun = {
  id: string;
  template_id: string;
  occurrence_date: string;
  journal_entry_id: string | null;
  status: string;
  detail: Record<string, unknown> | null;
  created_at?: string;
};

// ── Vendors — THE supplier master ────────────────────────────────────────────
// `public.vendors` (migration 049). Every purchase path reads it. The fields a
// CA sets on the Supplier Master screen are here and NOT on the retired
// `public.suppliers`, whose column names differed on three of them:
// supplier_name -> name, payment_terms_days -> credit_days, and
// tds_rate_percent -> tds_rate_bps, which is BASIS POINTS (1000 = 10.00%).
//
// `tds_rate_bps` IS READABLE AND NOT WRITABLE FROM A SCREEN (PUR-06 = TDS-13),
// which is why `Vendor` carries it and `VendorWrite` does not. Nothing in the
// withholding engine reads the vendor's own rate — it takes the section's rate
// for the bill's financial year out of the FY-versioned registry — so a rate
// recorded here was shown to a CA, stored, and then not used. A rate BELOW the
// section's is a s.197 certificate, which is four facts (section, rate, amount,
// period) recorded against the certificate, not one number on a master.

// ── Bills of Entry ───────────────────────────────────────────────────────────
// The customs assessment on an import of goods (PUR-18, migration 389).
// IGST and compensation cess here are INPUT TAX — CGST Act s.2(62)(a) with
// Rule 36(1)(d) — and reach GSTR-3B Table 4(A)(1). Basic customs duty and the
// social welfare surcharge are recoverable from nobody and are COST (AS-2
// paragraph 6). The browser does not know which is which and must not learn:
// `domain/gst/bill_of_entry.py` decides, and every derived figure below comes
// off the wire.

export type BillOfEntry = {
  id: string;
  firm_id?: string;
  client_id: string;
  be_number: string;
  be_date: string;
  port_code: string | null;
  vendor_id: string | null;
  purchase_bill_id: string | null;
  assessable_value_paise: number;
  basic_customs_duty_paise: number;
  social_welfare_surcharge_paise: number;
  other_duty_paise: number;
  igst_paise: number;
  cess_paise: number;
  ineligible_igst_paise: number;
  ineligible_cess_paise: number;
  is_sez: boolean;
  payment_account_id: string | null;
  duty_expense_account_id: string | null;
  status: string;
  journal_entry_id: string | null;
  notes: string | null;
  /** Derived by the server, never here. */
  total_paise: number;
  creditable_igst_paise: number;
  creditable_cess_paise: number;
  non_creditable_duty_paise: number;
  gstr2b_section: string;
  can_post: boolean;
  /** Stops a posting. */
  refusals: string[];
  /** True and worth saying; stops nothing. */
  caveats: string[];
};

export type BillOfEntryWrite = {
  client_id: string;
  be_number: string;
  be_date: string;
  port_code?: string | null;
  vendor_id?: string | null;
  purchase_bill_id?: string | null;
  assessable_value_paise?: number;
  basic_customs_duty_paise?: number;
  social_welfare_surcharge_paise?: number;
  other_duty_paise?: number;
  igst_paise?: number;
  cess_paise?: number;
  ineligible_igst_paise?: number;
  ineligible_cess_paise?: number;
  is_sez?: boolean;
  payment_account_id?: string | null;
  duty_expense_account_id?: string | null;
  notes?: string | null;
};

export type BillOfEntryAuthorities = {
  credit_authority: string;
  cost_authority: string;
  table_4a_row: string;
  gstr2b_sections: string[];
  not_modelled: string[];
};

// ── GST registrations ────────────────────────────────────────────────────────
// A client is one legal person and may hold several GSTINs (GST-20, migration
// 390). CGST Act s.25(1) makes registration state-wise and s.25(2) allows one
// per place of business. The PRIMARY is the GSTIN on the client record; this
// namespace manages the rest, and `domain/gst/registrations.py` presents the
// union — so the list below always starts with the primary.

// ── Opening documents ────────────────────────────────────────────────────────
// The bill-wise breakup of a client's opening balances (ACC-14, migration 391).
// The ledger's opening AR and AP are aggregates from the party masters, which
// have no dates — so on day one the whole opening receivable ages to nothing.
// An opening document supplies those dates. It posts NO journal: it is the
// breakup of the balance, not a second posting of it, so the two have to agree
// and the difference is NAMED where they do not.

// ── GSTR-9, consolidated from the year's own returns (GST-10) ───────────────
// CGST Act s.44 with Rule 80(1): the annual return consolidates the financial
// year's GSTR-1 and GSTR-3B, and the portal opens it once every one of them is
// furnished. `domain/gst/gstr9_builder.py` decides which figure belongs on
// which row and which rows it could not derive; this carries shapes only.

/** One month's Invoice Furnishing Facility — CGST Rule 59(2), GST-11.
 *
 *  `domain/gst/iff.py` decides every one of these; this carries shapes only.
 *  `available` is false for the THIRD month of a quarter, which has no
 *  facility because its documents are in the quarterly GSTR-1 itself — a
 *  refusal with a sentence, not an error. */
export type IffWorking = {
  period: string;
  gstin?: string;
  available: boolean;
  /** Present only when `available` is false. */
  reason?: string;
  month_in_quarter?: number;
  due_date?: string | null;
  window_opens_day?: number;
  window_closes_day?: number;
  payload: Record<string, unknown>;
  summary?: {
    counts?: { b2b?: number; credit_notes_registered?: number };
    cumulative_value_rupees?: number;
    cap_rupees?: number;
  };
  document_count: number;
  cumulative_value_paise?: number;
  cap_paise?: number;
  /** Reported, never enforced: Rule 59(2) lets the supplier furnish "as he may
   *  consider necessary", so WHICH documents fit is the CA's choice and
   *  nothing is trimmed. */
  cap_exceeded: boolean;
  excess_paise?: number;
  /** A GSTR-1 section this facility does not carry, with the reason — or a
   *  single document held out of one, which carries a `reference_no` too. */
  not_carried: { section: string; reason: string; reference_no?: string }[];
  notes: string[];
  verified?: boolean;
};

export type GSTR9Row = {
  code: string;
  label: string;
  txval_paise: number;
  igst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  cess_paise: number;
  /** Set where the figure could not be derived. A row with a note is NOT a
   *  declaration of nil — on an annual return a nil says nothing was owed. */
  note?: string;
};

export type GSTR9Working = {
  financial_year: string;
  gstin: string;
  tables: Record<string, GSTR9Row[]>;
  hsn: {
    hsn_sc: string; desc: string | null; uqc: string | null; qty: number;
    txval_paise: number; igst_paise: number; cgst_paise: number;
    sgst_paise: number; cess_paise: number;
  }[];
  months: {
    period: string; gstr1_status: string | null; gstr3b_status: string | null;
    gstr1_payload_held: boolean;
  }[];
  gaps: string[];
  /** True only when every month of the year has BOTH returns filed — the
   *  condition the portal opens FORM GSTR-9 on. */
  is_complete: boolean;
  not_built: Record<string, string>;
  source: string;
};

export type OpeningDocument = {
  id: string;
  kind: "receivable" | "payable";
  party_id: string;
  party_name: string | null;
  document_no: string;
  document_date: string | null;
  due_date: string | null;
  total_paise: number;
  paid_paise: number;
  outstanding_paise: number;
  status: string;
};

export type OpeningReconciliationRow = {
  party_id: string;
  party_name: string | null;
  opening_balance_paise: number;
  documents_paise: number;
  document_count: number;
  /** Balance less documents. POSITIVE means part of the balance will not age. */
  difference_paise: number;
  agrees: boolean;
  /** The server's own sentence. Null when the two agree. */
  sentence: string | null;
};

export type OpeningDocumentListing = {
  kind: "receivable" | "payable";
  documents: OpeningDocument[];
  documents_paise: number;
  opening_balance_paise: number;
  reconciliation: OpeningReconciliationRow[];
  unreconciled_parties: number;
};

export type DoubleOpening = {
  account_id: string;
  account_name: string | null;
  master_paise: number;
  trial_balance_paise: number;
  /** The server's own sentence. Which of the two figures is the mistake is the
   *  CA's answer, so no difference is offered. */
  sentence: string;
};

export type OpeningReconciliation = {
  receivable: OpeningDocumentListing;
  payable: OpeningDocumentListing;
  /** Accounts the opening position was posted into TWICE — once from the party
   *  and bank masters, once from an imported trial balance. The two journal
   *  families are deliberately separate and neither corrects the other. */
  double_openings: DoubleOpening[];
};

export type OpeningDocumentKinds = {
  kinds: { value: string; label: string; party: string; number: string }[];
  /** Why an opening bill contributes nothing to a section 194 FY aggregate. */
  section_194_aggregate: string;
};

export type ClientGstRegistration = {
  /** Null on the PRIMARY: it is `clients.gstin` and has no registration row. */
  id: string | null;
  gstin: string;
  state_code: string;
  registration_type: string;
  filing_frequency: string;
  is_primary: boolean;
  trade_name: string | null;
  effective_from: string | null;
  /** CGST Act s.29 cancellation or surrender. The periods it was live still
   *  owe their returns, so a cancelled registration is closed, never hidden. */
  effective_to: string | null;
  label: string;
  files_gstr1_and_3b: boolean;
  /** Set when this registration owes a DIFFERENT form — a composition dealer
   *  files CMP-08 and GSTR-4, an ISD files GSTR-6, and so on. Offering it a
   *  GSTR-3B screen offers a return it must not file. */
  other_return_form: string | null;
};

/** One financial year's CGST s.2(6) aggregate turnover, as the CA recorded it. */
export type ClientGstTurnoverYear = {
  id: string;
  /** The year the figure MEASURES, canonical "YYYY-YY". The preceding-year hop
   *  Notification 78/2020 requires is done server-side when the return is
   *  built, so this is not the year it governs. */
  financial_year: string;
  aggregate_turnover_paise: number;
  source_note: string | null;
  updated_at?: string | null;
};

export type ClientGstTurnover = {
  years: ClientGstTurnoverYear[];
  /** Which year's figure governs a return prepared today. */
  governing_financial_year: string;
  /** NULL means no row — nobody has recorded it. Never 0, which is a client
   *  who genuinely turned over nothing, and which would make the HSN
   *  requirement read as optional. */
  governing_turnover_paise: number | null;
  /** The server's own sentence when the governing year is unrecorded. */
  note: string | null;
};

export type GstRegistrationKinds = {
  registration_types: {
    value: string;
    files_gstr1_and_3b: boolean;
    other_return_form: string | null;
  }[];
  filing_frequencies: string[];
};

export type Vendor = {
  id: string;
  client_id: string;
  firm_id?: string;
  name: string;
  gstin: string | null;
  pan: string | null;
  state_code?: string | null;
  email?: string | null;
  phone?: string | null;
  tds_applicable: boolean;
  tds_section: string | null;
  tds_rate_bps: number | null;
  credit_days: number | null;
  /** Migration 378. Null = no limit recorded, which is NOT a recorded zero
   *  (that means no credit at all). Recorded, never enforced — nothing blocks
   *  or warns on a bill that would exceed it. */
  credit_limit_paise: number | null;
  /** Migration 388. Is this supplier registered under GST? NULL is a real
   *  THIRD state — nobody has recorded it — and CGST Act s.31(3)(f) turns on
   *  the answer, so the self-invoice path NAMES an unrecorded vendor as a gap
   *  rather than assuming either way. */
  gst_registration_status?: string | null;
  is_active: boolean;
  created_at?: string;
};

/** The subset the Supplier Master screen writes. Everything else on a vendor —
 *  residency, s.195 nature of income, the treaty fields, MSMED status — is set
 *  on the client workspace's Vendors tab, and a PATCH that omits a field leaves
 *  it alone. */
export type VendorWrite = {
  name?: string;
  gstin?: string | null;
  pan?: string | null;
  state_code?: string;
  tds_applicable?: boolean;
  tds_section?: string | null;
  credit_days?: number | null;
  credit_limit_paise?: number | null;
  /** 'registered' | 'unregistered'. Omit to leave it as it is — a PATCH drops
   *  nulls, so this cannot be cleared back to unrecorded from here. */
  gst_registration_status?: string | null;
  is_active?: boolean;
};

// ── Billing schedules ────────────────────────────────────────────────────────
// The practice's own fee arrangements (`billing_schedules`, migration 073).
// `arrangement` is 'retainer' | 'one_time' | 'package'; the Retainer Tracker
// reads the first. `gst_rate` is a PERCENTAGE, not basis points — that is the
// column's own unit.

export type BillingSchedule = {
  id: string;
  client_id: string;
  arrangement: string;
  cadence: string;
  amount_paise: number;
  gst_rate: number;
  service_id: string | null;
  next_run_date: string | null;
  description: string | null;
  is_active: boolean;
};

export type BillingGenerateResult = {
  invoice: { id?: string; invoice_no?: string } | null;
  period: string;
  created: boolean;
  idempotent: boolean;
};

// ── Budget versus actuals ────────────────────────────────────────────────────
// NOT a statutory statement — no return reads a budget and nothing is
// journalised from one. Amounts are integer paise.
//
// `budget_paise` is NULL where the CA has not budgeted that account, which is
// a DIFFERENT fact from a budget of zero: only the second produces a variance,
// and `variance_paise` is null alongside it. Revenue actuals arrive as
// POSITIVE magnitudes — the backend flips the debit-minus-credit sign once, by
// the account's own type — so a Revenue row and an Expense row can be compared
// against a budget typed the same way.

export type BudgetRow = {
  account_id: string;
  account_code: string | null;
  account_name: string | null;
  account_type: string | null;
  budget_paise: number | null;
  actuals: Record<string, number>;
  actual_paise: number;
  variance_paise: number | null;
};

export type BudgetVsActuals = {
  fy: string;
  client_id: string;
  quarters: { label: string; start: string; end: string }[];
  rows: BudgetRow[];
  totals: { budget_paise: number; actual_paise: number };
};

// ── The multi-year trend ─────────────────────────────────────────────────────
// NOT a statutory statement. Schedule III General Instructions para 5 requires
// the corresponding amounts for the IMMEDIATELY PRECEDING period only — one
// comparative, which the statements themselves carry. A five-year trend has no
// prescribed form and is unaudited, and `basis` says so on the document.
//
// Amounts are integer paise; ratio values are basis points (10,000 bps = 1.00);
// movements are one shorter than the values, because the first year has nothing
// to move from.

export type TrendSeries = {
  label: string;
  key: string;
  /** Presentation only — which direction to colour green. null where the
   *  answer depends on the business (borrowings are not bad). */
  higher_is_better: boolean | null;
  values_paise: number[];
  movement_paise: number[];
  /** null for a movement off a zero base: undefined, not infinite. */
  movement_bps: (number | null)[];
};

export type TrendRatioSeries = {
  key: string;
  label: string;
  unit: "times" | "percent";
  clause: string;
  values_bps: (number | null)[];
  movement_bps: (number | null)[];
  unavailable_reason: string | null;
};

export type MultiYearTrend = {
  fys: string[];
  requested_fys: string[];
  /** Years asked for that had nothing recorded. Left out rather than shown as
   *  zeros, which would assert nil revenue and nil assets. */
  dropped_fys: string[];
  /** Years that FAILED to read. Deliberately separate from dropped_fys: "the
   *  business had no 2024-25" and "2024-25 could not be read" look identical in
   *  a shortened table and mean opposite things, and only the first is a
   *  statement a CA should repeat to a client. */
  unreadable_fys: string[];
  basis: string;
  profit_and_loss: TrendSeries[];
  balance_sheet: TrendSeries[];
  ratios: TrendRatioSeries[];
  gaps: { code: string; message: string }[];
};

export type AgeingClassifyBody = {
  client_id: string;
  target: "invoice" | "bill" | "vendor" | "account";
  target_id: string;
  is_disputed?: boolean;
  considered_doubtful?: boolean;
  msme_status?: "micro" | "small" | "medium" | "not_registered" | null;
  msme_registration_no?: string | null;
  /** Marks a GL account as holding unbilled dues. 'receivable' is an ASSET
   *  balance (accrued income); 'payable' is a LIABILITY balance (accrued
   *  expenses). null un-marks it. The database CHECK also refuses a side that
   *  does not match the account's own type. */
  unbilled_dues_side?: "receivable" | "payable" | null;
};

export type ReportGSTSummary = {
  period: string;
  gstr1: { taxable: number; cgst: number; sgst: number; igst: number;
           total: number; lines: ReportTransaction[] };
  gstr3b: { output_cgst: number; output_sgst: number; output_igst: number;
            itc_cgst: number; itc_sgst: number; itc_igst: number;
            // The s.49(5) set-off result, per head.
            net_cgst: number; net_sgst: number; net_igst: number;
            // Reverse-charge tax under s.9(3)/(4), which the set-off cannot
            // touch: s.49(4) lets the credit ledger pay only "output tax", and
            // s.2(82) excludes "tax payable by him on reverse charge basis".
            // cash_payable is the challan figure — the set-off plus this.
            rcm_cash: number; cash_payable: number;
            // Nil tax payable is true both when liability and credit cancel out
            // and when credit exceeds liability by lakhs. This says which.
            itc_carried_forward: number };
  tds_deducted: number;
  ca_review_required: true;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// Perf/UX: bound every request so a cold-starting/unreachable backend fails
// fast with a clear message instead of hanging the UI indefinitely. 45s covers
// a Render cold start; the warm-up ping (AuthContext) usually avoids hitting it.
async function fetchWithTimeout(path: string, options: RequestInit | undefined, token: string | undefined): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 45_000);
  try {
    return await fetch(`${BASE_URL}${path}`, {
      ...options,
      signal: options?.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options?.headers ?? {}),
      },
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  let res: Response;
  try {
    res = await fetchWithTimeout(path, options, token);
  } catch (e) {
    // A sleeping Render free-tier instance takes 30-60s to cold-start, and the
    // connection fails outright before any response comes back (TypeError
    // "Failed to fetch" — the same underlying symptom the browser reports as
    // a misleading CORS error, since there's no response to carry a CORS
    // header). Nothing was processed server-side, so one retry after a short
    // delay is safe: by then the instance has usually finished waking up.
    //
    // A TIMEOUT IS NOT RETRIED, and that is a deliberate change.
    //
    // It used to be. In production /api/accounting/cash-flow takes 53-57s for a
    // client with a 12,836-entry ledger, which is longer than the 45s budget
    // above — so every call aborted at exactly 45.00s, slept 5s, and fired
    // again. The network panel showed it plainly: one cancelled request at
    // 45.00s followed by a successful one at 57.26s. The retry never had a
    // chance of being faster; all it did was put a second copy of the slowest
    // query in the app onto an already-struggling instance, which makes the
    // next caller slower still.
    //
    // A connection that never opened and a server that answered too slowly are
    // different failures. Only the first one is worth trying again.
    const isTimeout = e instanceof DOMException && e.name === "AbortError";
    const isNetworkFailure = e instanceof TypeError;
    if (isTimeout) {
      throw new Error(
        "This is taking longer than expected — the server didn't respond in time. Please try again.");
    }
    if (!isNetworkFailure) throw e;
    await sleep(5_000);
    try {
      res = await fetchWithTimeout(path, options, token);
    } catch {
      throw new Error("The server is taking too long to respond (it may be waking up). Please retry in a moment.");
    }
  }
  // A long-running bulk action (hundreds of sequential/concurrent calls) can
  // outlive the access token fetched at its start — refresh once and retry
  // rather than surfacing a raw "Token expired" mid-batch. Safe to retry: a
  // 401 means auth rejected the request before any handler ran, so nothing
  // was processed server-side.
  if (res.status === 401) {
    const { data: refreshed } = await supabase.auth.refreshSession();
    const newToken = refreshed.session?.access_token;
    if (newToken && newToken !== token) {
      res = await fetchWithTimeout(path, options, newToken);
    }
  }
  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }
  return res.json();
}

/**
 * The sentence out of an error response, without the envelope.
 *
 * FastAPI answers a refusal as {"detail": "..."} and the backend writes those
 * for the CA — "GSTR-3B covering this date was filed on 18 Jul 2026." Rendering
 * the raw body instead put that sentence inside a JSON blob behind a status
 * code, which is what a CA actually saw the first time a journal discard was
 * refused. A message someone has to excavate is a message that did not get read.
 *
 * Falls back to the raw text, then to the status line: an ugly error beats a
 * blank one, and this must never itself throw while reporting a failure.
 *
 * EXPORTED because a handful of screens still call `fetch` directly rather than
 * going through this module, and each of them had its own `j.error ?? "Failed"`
 * — which reads NOTHING out of a FastAPI refusal, because a 422 body is
 * `{"detail": "..."}` and carries no `error` key at all. The CA saw the word
 * "Failed" where the server had written a sentence naming the four months of
 * depreciation it was waiting for.
 */
export async function errorMessage(res: Response): Promise<string> {
  let body = "";
  try {
    body = await res.text();
  } catch {
    return `API error ${res.status}`;
  }
  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail ?? parsed?.error;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    // A validation error's detail is an array of {loc, msg, ...}.
    if (Array.isArray(detail)) {
      const msgs = detail.map((d) => d?.msg).filter((m) => typeof m === "string");
      if (msgs.length) return msgs.join(" · ");
    }
    if (detail && typeof detail === "object" && typeof detail.message === "string") {
      // A refusal that names WHICH rows is worth more than its headline. The
      // employee bulk import returns {message, problems[]} and the problems are
      // the whole point — a file fixed one error at a time is a file uploaded
      // nineteen times. Capped, because a fifty-row file of nonsense produces
      // fifty problems and a toast is not a report.
      const problems = Array.isArray(detail.problems)
        ? (detail.problems as unknown[]).filter((p): p is string => typeof p === "string")
        : [];
      if (problems.length) {
        const shown = problems.slice(0, 10).join(" · ");
        const rest = problems.length > 10 ? ` · and ${problems.length - 10} more` : "";
        return `${detail.message} ${shown}${rest}`;
      }
      return detail.message;
    }
  } catch {
    /* not JSON — fall through to the raw body */
  }
  return body.trim() ? `API error ${res.status}: ${body}` : `API error ${res.status}`;
}

/** A refusal the server sent as `{message, code}`, carrying its code.
 *
 *  `errorMessage` flattens a structured detail for DISPLAY, which is what most
 *  screens need. A screen that can offer the way past a refusal needs to know
 *  WHICH refusal it was, and matching on the wording of a sentence written for
 *  a human is how a message becomes unfixable — change the sentence and the
 *  behaviour silently changes with it. So the code travels beside the text. */
export class ApiRefusal extends Error {
  readonly code: string | null;
  constructor(message: string, code: string | null) {
    super(message);
    this.name = "ApiRefusal";
    this.code = code;
  }
}

/** Read a failed Response ONCE and produce the refusal it describes. */
export async function refusalFrom(res: Response): Promise<ApiRefusal> {
  const body = await res.text().catch(() => "");
  let message = body.trim() ? `API error ${res.status}: ${body}` : `API error ${res.status}`;
  let code: string | null = null;
  try {
    const detail = JSON.parse(body)?.detail;
    if (typeof detail === "string" && detail.trim()) message = detail.trim();
    else if (detail && typeof detail === "object") {
      if (typeof detail.message === "string") message = detail.message;
      if (typeof detail.code === "string") code = detail.code;
    }
  } catch {
    /* not JSON — the raw body is the best we have */
  }
  return new ApiRefusal(message, code);
}

/** Fetch a binary endpoint with auth and trigger a browser blob download. */
async function downloadFile(path: string, fallbackFilename: string, extraHeaders?: Record<string, string>): Promise<Headers> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;

  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(extraHeaders ?? {}),
    },
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(`API error ${res.status}: ${err}`);
  }

  // Prefer the filename from Content-Disposition, fall back to the provided one
  let filename = fallbackFilename;
  const disposition = res.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="?([^";]+)"?/);
  if (match?.[1]) filename = match[1];

  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  // The headers go back to the caller because a file body cannot carry a
  // message: the bulk-payslip zip reports the employees it could not render on
  // X-Payslip-Problems. Both that and Content-Disposition are only readable
  // because main.py names them in the CORS expose_headers list.
  return res.headers;
}

/**
 * A bank matching rule (Banking B.2.3). Mirrors models/banking.MatchingRuleIn.
 *
 * The backend requires at least one CONDITION (pattern, amount bound, or a
 * debit/credit restriction) and at least one SUGGESTION — a rule with neither
 * would fire on every transaction and propose nothing, masking every rule
 * created after it. Amounts are integer paise.
 */
export interface BankRuleInput {
  client_id: string;
  rule_name: string;
  description_pattern?: string | null;
  amount_min_paise?: number | null;
  amount_max_paise?: number | null;
  txn_type?: "debit" | "credit" | "any";
  suggested_account_id?: string | null;
  suggested_category?: string | null;
  suggested_narration?: string | null;
  /**
   * The GST hiding INSIDE a bank charge, in basis points (1800 = 18%). Charges
   * from a given bank always carry the same treatment, so it is stated once on
   * the rule instead of on every ₹590 debit. null means the rule says nothing
   * about GST; 0 means it says the charge carries none — a different answer, so
   * do not collapse the two. Requires suggested_account_id (the split books the
   * ex-tax amount there) and a rule that is not credit-only.
   */
  suggested_gst_rate_bps?: number | null;
  /** true when this bank's supply is inter-state for the client (IGST rather
   *  than CGST + SGST). Never inferred — an IFSC does not encode a state. */
  suggested_is_interstate?: boolean;
  is_active?: boolean;
  /** Migration 322 — a TRUSTED rule passes its lines with no click, as the
   *  person who trusted it. Promotion needs a Manager or Partner; the server
   *  refuses anyone else and refuses a rule that names no ledger. */
  is_trusted?: boolean;
}

/** One state of a bank line — docs/architecture/09-bank-entries.md. Maintained
 *  by a database trigger; the browser never decides it. */
export type EntryState = "needs_you" | "proposed" | "ready" | "covered" | "passed" | "set_aside";
export type EntryListState = EntryState | "to_do" | "all";

/** GST rates a bank charge can carry, in basis points. Mirrors the backend's
 *  domain/banking/charge_gst.ALLOWED_RATES_BPS and migration 254's CHECK. */
export const BANK_CHARGE_GST_RATES_BPS = [0, 500, 1200, 1800, 2800] as const;

/** One band of a firm-recorded professional-tax slab set (migration 327).
 *  `to_paise` null is the top band — "and above"; `months` null is every
 *  month. The notification is carried with the figure because that is the only
 *  reason a hand-entered number may drive a statutory deduction. */
export type PTSlabRow = {
  id: string;
  state: string;
  effective_from: string;
  basis: string;
  from_paise: number;
  to_paise: number | null;
  amount_paise: number;
  months: number[] | null;
  notification_reference: string;
  notification_date: string;
  note: string | null;
};

export interface TreatyRateRow {
  id: string;
  country_code: string;
  nature: string;
  rate_bps: number | null;
  /** The agreement has no article for this nature — several, including the UAE
   *  and Singapore, have no fees-for-technical-services article. That makes the
   *  income Article 7 business profits, not taxable in India without a PE, so
   *  it is an ANSWER rather than a missing rate. */
  no_article: boolean;
  article_ref: string | null;
  notes: string | null;
  verified_on: string | null;
}

/**
 * PATCH body for a GST return's status route (routers/gst_workspace.py's
 * UpdateStatusRequest).
 *
 * `ca_approved` is NOT a convenience flag: the backend refuses `ca_approved`
 * and `submitted` outright without it, because CLAUDE.md's rule is that a
 * return only moves on an explicit CA confirmation.
 * `acknowledge_stale` is the deliberate override when the books have moved
 * since the return was computed — it is never defaulted true, since the whole
 * point is that the refusal gets seen.
 * `filed_date` matters because marking a return here can lag the portal by
 * days and the period lock keys on the REAL filing date.
 */
export type GSTStatusUpdate = {
  status: "draft" | "validated" | "ca_approved" | "submitted";
  ca_approved?: boolean;
  acknowledge_stale?: boolean;
  arn?: string;
  filed_date?: string;
};

/** SALES-21 — the sales cycle before the tax invoice. */
export interface SalesCycleVocabulary {
  quote_kinds: { value: string; label: string }[];
  quote_statuses: string[];
  order_statuses: string[];
  challan_statuses: string[];
  challan_reasons: { value: string; label: string; is_a_supply: boolean }[];
  goods_kinds: { value: string; label: string }[];
  not_a_tax_invoice: string;
  no_tax_on_a_non_supply: string;
  job_work_exclusion: string;
  rule_55_5_steps: string[];
  copies: { copy: string; legend: string }[];
  itc_04: { decided: boolean; readings: string[]; refusal: string };
}

export interface PreInvoiceLine {
  description: string;
  hsn_sac?: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_percent: number;
  is_service?: boolean;
  discount_percent_bps?: number | null;
  discount_paise?: number | null;
  order_line_id?: string | null;
  quantity_is_provisional?: boolean;
}

export interface SalesQuotation {
  id: string;
  kind: string;
  title?: string;
  document_no: string;
  document_date: string;
  valid_until?: string | null;
  status: string;
  customer_id: string;
  customer_name?: string | null;
  taxable_paise: number;
  total_paise: number;
  is_expired: boolean | null;
}

export interface SalesOrder {
  id: string;
  document_no: string;
  document_date: string;
  status: string;
  customer_id: string;
  customer_name?: string | null;
  customer_po_no?: string | null;
  expected_delivery_date?: string | null;
  taxable_paise: number;
  total_paise: number;
}

export interface DeemedSupplyClock {
  applies: boolean;
  statute: string;
  months: number | null;
  sent_on: string | null;
  due_back_by: string | null;
  overdue: boolean | null;
  days_remaining: number | null;
  consequence: string;
  gaps: string[];
}

export interface DeliveryChallan {
  id: string;
  document_no: string;
  document_date: string;
  reason: string;
  reason_label?: string;
  status: string;
  goods_kind?: string | null;
  received_back_on?: string | null;
  consignee_name?: string | null;
  taxable_paise: number;
  total_paise: number;
  clock: DeemedSupplyClock;
}

export interface ChallanParticulars {
  challan: DeliveryChallan | null;
  lines: Record<string, unknown>[];
  rule: string;
  reason_label: string;
  particulars: { clause: string; label: string; value: string | null; required: boolean }[];
  missing: string[];
  copies: { copy: string; legend: string }[];
  clock: DeemedSupplyClock;
  rule_55_5: { steps: string[]; gaps: string[] };
  itc_04: { decided: boolean; readings: string[]; refusal: string };
  ca_review_required: boolean;
}

export interface OrderOpenLine {
  order_line_id: string;
  description: string;
  ordered_qty: string;
  delivered_qty: string;
  invoiced_qty: string;
  undelivered_qty: string;
  unbilled_qty: string;
}

export interface OrderPosition {
  order: SalesOrder | null;
  lines: OrderOpenLine[];
  status_would_be: string;
  gaps: string[];
}

/** PUR-25 — the purchase cycle before the bill. */
export interface PurchaseCycleVocabulary {
  order_statuses: string[];
  order_open_statuses: string[];
  receipt_statuses: string[];
  posts_nothing: string;
  section_16_2_b: string;
  bill_to_ship_to: string;
  msmed_acceptance: string;
  no_tolerance: string;
}

export interface PurchaseOrder {
  id: string;
  document_no: string;
  document_date: string;
  expected_date?: string | null;
  status: string;
  vendor_id: string;
  vendor_name?: string | null;
  taxable_paise: number;
  total_paise: number;
}

export interface GoodsReceipt {
  id: string;
  document_no: string;
  received_on: string;
  status: string;
  order_id?: string | null;
  vendor_id: string;
  vendor_challan_no?: string | null;
  objection_raised_on?: string | null;
  objection_removed_on?: string | null;
}

export interface PurchaseOrderOpenLine {
  order_line_id: string;
  description: string;
  ordered_qty: string;
  received_qty: string;
  billed_qty: string;
  unreceived_qty: string;
  unbilled_qty: string;
}

export interface PurchaseOrderPosition {
  order: PurchaseOrder | null;
  lines: PurchaseOrderOpenLine[];
  status_would_be: string;
  posts_nothing: string;
}

export interface ThreeWayMatchLine {
  bill_line_id: string;
  description: string;
  billed_qty: string;
  billed_rate_paise: number;
  order_line_id: string | null;
  ordered_qty: string | null;
  ordered_rate_paise: number | null;
  received_qty: string | null;
  quantity_difference: string | null;
  rate_difference_paise: number | null;
}

export interface ThreeWayMatch {
  bill_id: string;
  matched: boolean;
  has_order: boolean;
  has_receipt: boolean;
  lines: ThreeWayMatchLine[];
  differences: string[];
  gaps: string[];
  caveats: string[];
  acceptance_date: string | null;
  acceptance_source: string;
  ca_review_required: boolean;
}

/** A row of `public.fee_engagements`. `status` is migration 108's CHECK,
 *  verbatim — the billing screen used to declare `"Active" | "Paused"`, and
 *  "Paused" is not in it. */
export type FeeEngagementStatus =
  | "Draft" | "Active" | "In Progress" | "Review" | "Completed" | "Closed" | "Inactive";

export interface FeeEngagement {
  id: string;
  client_id: string;
  service_type: string;
  fee_paise: number;
  billing_cycle: string;
  start_date: string;
  end_date?: string | null;
  status: FeeEngagementStatus;
  notes?: string | null;
}

/** What `POST /{id}/transition` will accept from each status, mirroring
 *  `routers/engagements.ENGAGEMENT_TRANSITIONS`. The server is the authority
 *  and answers 422 with the permitted set; this exists so the screen offers
 *  the buttons that will work rather than a dropdown of seven, six of which
 *  are refused. Pinned to the Python map by
 *  `apps/api/tests/test_the_engagement_state_machine_has_one_map.py`. */
export const ENGAGEMENT_TRANSITIONS: Record<FeeEngagementStatus, FeeEngagementStatus[]> = {
  "Draft": ["Active", "Closed"],
  "Active": ["In Progress", "Closed", "Inactive"],
  "In Progress": ["Review", "Active", "Closed"],
  "Review": ["Completed", "In Progress"],
  "Completed": ["Closed"],
  "Closed": [],
  "Inactive": ["Active"],
};

export const api = {
  /** The firm's own reading of the DTAA rates it withholds under, per country
   *  and nature of income. Ships empty and is never seeded: India has
   *  agreements with over ninety countries, MFN clauses need their own §90(1)
   *  notification, and a wrong rate too low disallows the whole expenditure
   *  under IT Act §40(a)(i). */
  // The firm's own reading of the state professional-tax notifications
  // (migration 327). FIRM-scoped, not client-scoped, and that is the point:
  // PT is a state levy, so one recorded slab set serves every client of the
  // firm with staff in that state.
  statutoryValues: {
    list: () => request<ApiResp<{
      pt_slabs: PTSlabRow[];
      pt_levying_states: Record<string, string>;
      pt_modelled_states: string[];
      pt_recorded_states: string[];
      pt_conflicts: string[];
    }>>("/api/payroll/statutory-values"),
    // The WHOLE set in one call. The bands must start at zero and meet end to
    // start; a per-band call would let a half-recorded state exist between two
    // requests, and a wage in the hole would come out as a silent nil.
    savePtSlabs: (body: {
      state: string; effective_from: string;
      notification_reference: string; notification_date: string;
      bands: Array<{ from_paise: number; to_paise: number | null; amount_paise: number;
                     basis?: string; months?: number[] | null }>;
      note?: string | null;
    }) => request<ApiResp<{ state: string; effective_from: string; bands: number }>>(
      "/api/payroll/statutory-values/pt", { method: "PUT", body: JSON.stringify(body) }),
    removePtSlabs: (state: string, effectiveFrom: string) =>
      request<ApiResp<{ deleted: boolean }>>(
        `/api/payroll/statutory-values/pt?state=${encodeURIComponent(state)}` +
        `&effective_from=${encodeURIComponent(effectiveFrom)}`, { method: "DELETE" }),
  },
  treatyRates: {
    list: () => request<ApiResp<{ rates: TreatyRateRow[]; natures: string[] }>>(
      "/api/tds/treaty-rates"),
    upsert: (body: {
      country_code: string; nature: string; rate_bps?: number | null;
      no_article?: boolean; article_ref?: string | null; notes?: string | null;
    }) => request<ApiResp<TreatyRateRow>>("/api/tds/treaty-rates", {
      method: "PUT", body: JSON.stringify(body),
    }),
    remove: (id: string) => request<ApiResp<{ deleted: string }>>(
      `/api/tds/treaty-rates/${id}`, { method: "DELETE" }),
  },
  /** Firm-level analytics. `rbac("analytics", "read")` on every one, and each
   *  narrows its per-client rows to the caller's assigned book — so these are
   *  safe to render for any role that holds the permission, and a screen that
   *  gated them on Partner would throw that narrowing away. */
  analytics: {
    profitability: (period: string, opts?: { byClient?: boolean }) => {
      const q = new URLSearchParams({ period });
      if (opts?.byClient === false) q.set("include_by_client", "false");
      return request<ApiResp<ProfitabilityPayload>>(
        `/api/analytics/profitability?${q}`);
    },
    revenueVsEffort: (period: string) =>
      request<ApiResp<RealizationPayload>>(
        `/api/analytics/revenue-vs-effort?period=${encodeURIComponent(period)}`),
  },

  hub: {
    /** Every tile, with its figure, in ONE request — fifteen browser fetches
     *  would be fifteen Singapore-to-Mumbai round trips for fifteen numbers.
     *  Omit `clientId` for the firm hub. */
    get: (clientId?: string) =>
      request<ApiResp<HubPayload>>(
        `/api/hub${clientId ? `?client_id=${encodeURIComponent(clientId)}` : ""}`),
    /** Which clients need work on one tile. The firm hub's answer to "7 assets
     *  with depreciation outstanding" — WHICH seven. A tile with no firm-level
     *  worklist answers 422 with the reason. */
    worklist: (tile: string) =>
      request<ApiResp<HubWorklistPayload>>(
        `/api/hub/worklist?tile=${encodeURIComponent(tile)}`),
  },

  relatedParties: {
    /** A client's recorded entity roles, with the entity joined server-side.
     *  There was no endpoint for this at all, which is why the screen showed
     *  "Associated Entities (0)" on every client for ever. */
    roles: (clientId: string) =>
      request<ApiResp<ClientEntityRole[]>>(
        `/api/relationships/roles?client_id=${encodeURIComponent(clientId)}`),
    /** The AS 18 note. Prepare-only — nothing is filed, signed or posted. */
    disclosure: (clientId: string) =>
      request<ApiResp<RelatedPartyDisclosure>>(
        `/api/relationships/related-party-report?client_id=${encodeURIComponent(clientId)}`),
    /** The firm's entity register, for the picker. The role form used to ask a
     *  CA to paste a UUID copied from another screen. */
    entities: (search?: string) =>
      request<ApiResp<RelationshipEntity[]>>(
        `/api/relationships/entities?limit=200${search ? `&search=${encodeURIComponent(search)}` : ""}`),
    addRole: (entityId: string, body: unknown) =>
      request<ApiResp<ClientEntityRole>>(
        `/api/relationships/entities/${encodeURIComponent(entityId)}/roles`,
        { method: "POST", body: JSON.stringify(body) }),
    removeRole: (roleId: string) =>
      request<ApiResp<unknown>>(
        `/api/relationships/roles/${encodeURIComponent(roleId)}`, { method: "DELETE" }),
    detectMatches: () =>
      request<ApiResp<unknown>>("/api/relationships/cross-client-matches/detect",
        { method: "POST", body: JSON.stringify({}) }),
  },

  clients: {
    /** The caller's OWN clients: `rbac("client","read")` plus
     *  `effective_client_ids`, so an Executive or Reviewer gets the ones they
     *  are assigned to. Read straight from PostgREST the SELECT policy is
     *  firm-scoped with no assignment test, which is why the client switcher
     *  goes through here. Typed rather than `{}` so a caller is not free to
     *  read a field the endpoint does not serve. */
    list: () => request<ApiResp<{ clients: ClientSummary[]; total: number }>>("/api/clients"),
    getWorkspace: (id: string) => request(`/api/clients/${id}`),
    create: (body: unknown) => request("/api/clients", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) => request(`/api/clients/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    archive: (id: string) => request(`/api/clients/${id}/archive`, { method: "POST" }),
    restore: (id: string) => request(`/api/clients/${id}/restore`, { method: "POST" }),
    permanentDelete: (id: string) => request(`/api/clients/${id}`, { method: "DELETE" }),
  },
  // ── FEE ENGAGEMENTS (G2) ───────────────────────────────────────────────
  //
  // This namespace did not exist, and nothing under `apps/web` mentioned
  // `/api/engagements`, so all seven endpoints of `routers/engagements.py`
  // were unreachable from the product. The billing screen INSERTed and
  // SELECTed `fee_engagements` straight over PostgREST instead, which means
  // `rbac()` never ran and — this is the half that mattered — `POST
  // /{id}/transition`, which validates against ENGAGEMENT_TRANSITIONS and
  // writes both `audit_log` and the client timeline, had never been called.
  // An engagement was created `Active` and could never change.
  //
  // The screen's own TypeScript said `status: "Active" | "Paused"`, and
  // "Paused" is not a status `fee_engagements` can hold: migration 108's CHECK
  // allows Draft, Active, In Progress, Review, Completed, Closed and Inactive
  // and nothing else. So the one status the type offered besides Active was
  // one the database would have refused.
  engagements: {
    list: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams();
      if (params?.client_id) q.set("client_id", params.client_id);
      if (params?.status) q.set("status", params.status);
      const qs = q.toString();
      return request<ApiResp<{ engagements: FeeEngagement[]; total: number }>>(
        `/api/engagements${qs ? `?${qs}` : ""}`);
    },
    create: (body: {
      client_id: string; service_type: string; fee_paise: number;
      billing_cycle: string; start_date: string; status?: string;
      notes?: string | null;
    }) => request<ApiResp<{ engagement: FeeEngagement }>>("/api/engagements", {
      method: "POST", body: JSON.stringify(body),
    }),
    update: (id: string, body: Record<string, unknown>) =>
      request<ApiResp<{ engagement: FeeEngagement }>>(`/api/engagements/${id}`, {
        method: "PATCH", body: JSON.stringify(body),
      }),
    // The state machine's own door. `status` must be one the server allows
    // FROM the current one — it answers 422 naming the permitted set rather
    // than writing whatever it is sent, which is why the screen offers the
    // allowed set rather than a free dropdown.
    transition: (id: string, body: { status: string; notes?: string | null }) =>
      request<ApiResp<{ engagement: FeeEngagement }>>(
        `/api/engagements/${id}/transition`, {
          method: "POST", body: JSON.stringify(body),
        }),
  },
  compliance: {
    // Recording that a calendar obligation was filed — and, for a GST return,
    // closing its period.
    //
    // GST-14. /gst used to write filing_status / filed_date / arn_number
    // straight into compliance_calendar over PostgREST, single-row and bulk.
    // rbac() never ran, gst_filing_record_service.record_filing never ran, and
    // public.filings — the ONLY table journal_period_lock_reason (migration
    // 266) reads — stayed empty. A return marked filed from the tracker did
    // NOT lock its period, so the books could still move under a return
    // already at the portal, while the client GST workspace showed the same
    // return as a draft.
    markFiled: (recordId: string, body: { filed_date: string; arn?: string | null }) =>
      request<ApiResp<MarkFiledResult>>(
        `/api/compliance/calendar/${encodeURIComponent(recordId)}/filed`,
        { method: "PATCH", body: JSON.stringify(body) }),
    tasks: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/compliance/tasks${q ? `?${q}` : ""}`);
    },
    calendar: () => request("/api/compliance/calendar"),
    /** Every GST due date for one period, from services/compliance_engine.py —
     *  the single source CLAUDE.md names for every date in this product. The
     *  method existed and nothing called it, while app/gst/page.tsx computed
     *  its own; that copy had GSTR-9 a year late for January, February and
     *  March, because it read the calendar year off the period and a financial
     *  year is April to March. */
    /** Every statutory deposit one payroll month gives rise to, and the four
     *  TDS return dates of its financial year — from services/compliance_engine.py,
     *  the single source CLAUDE.md names for every date in this product.
     *
     *  The same story as calculateDueDates below, one subsystem over (PAY-19).
     *  Two payroll calendars built their own lists in the browser: both
     *  INVENTED a monthly Professional Tax row dated the last day of the month
     *  and labelled with Maharashtra's rule for every client — the engine
     *  deliberately has no PT date, because it is per state and this app models
     *  four states of twenty-two — and both OMITTED the ESI deposit (the 15th)
     *  and the salary TDS deposit (the 7th, 30 April for March), which are the
     *  two that attract interest. */
    payrollDepositDueDates: (year: number, month: number) =>
      request<ApiResp<PayrollDepositDueDates>>(
        `/api/compliance/payroll-deposit-due-dates?year=${year}&month=${month}`),
    /** The same, for a whole financial year — the firm payroll report's
     *  calendar is twelve months wide and would otherwise make twelve calls. */
    payrollDepositDueDatesForFy: (financialYear: string) =>
      request<ApiResp<PayrollDepositDueDates_FY>>(
        `/api/compliance/payroll-deposit-due-dates/fy?financial_year=${encodeURIComponent(financialYear)}`),
    calculateDueDates: (year: number, month: number) =>
      request<ApiResp<GstDueDates>>(
        `/api/compliance/due-dates/calculate?year=${year}&month=${month}`),
    /** When the §44AB audit report and the return that follows it are due.
     *
     *  TWO DATES, A MONTH APART: Explanation (ii) to §44AB makes the report's
     *  "specified date" one month BEFORE the §139(1) date — 30 September and
     *  31 October. The Tax Audit Tracker used to state "Due: 30 November" as a
     *  hardcoded string, wrong against both, and unfixable by any backend
     *  change because no backend was involved (IT-12). */
    taxAuditDueDates: (financialYear: string) =>
      request<ApiResp<TaxAuditDueDates>>(
        `/api/compliance/tax-audit-due-dates?financial_year=${encodeURIComponent(financialYear)}`),
  },
  incomeTax: {
    /** Does §44AB require an audit? Asked, never decided here — the browser
     *  copy of the thresholds (lib/income-tax/taxAuditThresholds.ts) is
     *  deleted, and with it the rule that read the nature of the activity off
     *  the amount.
     *
     *  The three cash figures are optional together: the proviso to §44AB(a)
     *  reads the clause as ₹10 crore only where cash receipts AND cash
     *  payments are each within 5% of their own aggregate, and the payments
     *  side has its own denominator that turnover cannot supply. Send none of
     *  them and the base figure applies, which is the safe direction. */
    /** GET /api/income-tax/regime-election — §115BAC(6) with Rule 21AGA.
     *
     *  What choosing the old regime actually REQUIRES, which is not the same
     *  question as which regime produces less tax. A client WITH business or
     *  professional income must file Form 10-IEA by the §139(1) due date and
     *  gets one return journey for life; a client without files in the return
     *  and may choose afresh every year.
     *
     *  Prior-year elections are an INPUT the CA supplies as repeated `prior`
     *  parameters (`2024-25:withdrew`). The product holds no filing history,
     *  and supplying none is answered as `history_unknown` — a different
     *  answer from "the option is available". */
    regimeElection: (q: {
      wants_old_regime: boolean;
      has_business_income: boolean;
      financial_year: string;
      form_10iea_filed_on?: string;
      is_audit?: boolean;
      has_transfer_pricing_report?: boolean;
      business_income_ceased?: boolean;
      prior?: string[];
    }) => {
      const p = new URLSearchParams({
        wants_old_regime: String(q.wants_old_regime),
        has_business_income: String(q.has_business_income),
        financial_year: q.financial_year,
      });
      if (q.form_10iea_filed_on) p.set("form_10iea_filed_on", q.form_10iea_filed_on);
      if (q.is_audit) p.set("is_audit", "true");
      if (q.has_transfer_pricing_report) p.set("has_transfer_pricing_report", "true");
      if (q.business_income_ceased) p.set("business_income_ceased", "true");
      for (const one of q.prior ?? []) p.append("prior", one);
      return request(`/api/income-tax/regime-election?${p.toString()}`);
    },
    taxAuditApplicability: (q: {
      nature: "business" | "profession";
      turnover_paise: number;
      financial_year?: string;
      cash_receipts_paise?: number;
      cash_payments_paise?: number;
      total_payments_paise?: number;
      is_company?: boolean;
    }) => {
      const p = new URLSearchParams({
        nature: q.nature,
        turnover_paise: String(q.turnover_paise),
      });
      if (q.financial_year) p.set("financial_year", q.financial_year);
      if (q.cash_receipts_paise != null) p.set("cash_receipts_paise", String(q.cash_receipts_paise));
      if (q.cash_payments_paise != null) p.set("cash_payments_paise", String(q.cash_payments_paise));
      if (q.total_payments_paise != null) p.set("total_payments_paise", String(q.total_payments_paise));
      if (q.is_company) p.set("is_company", "true");
      return request<ApiResp<TaxAuditApplicability>>(
        `/api/income-tax/tax-audit/applicability?${p.toString()}`);
    },
    /** The §43B(h) working for one client and one previous year.
     *
     *  Derived from purchase_bills, their payment allocations and
     *  vendors.msme_status — the screen renders it and computes nothing. The
     *  browser used to hold the whole rule and read a hand-keyed side table
     *  (PUR-15). */
    /** `bankRateBps` is the RBI Bank Rate over the delay, which MSMED §16
     *  charges THREE TIMES. It is the CA's own figure — nothing here holds it —
     *  and omitting it still returns the §16 working with the charge refused
     *  and named, rather than a nil that reads as "nothing is owed". */
    msme43bh: (client_id: string, fy: string, bankRateBps?: number) =>
      request<ApiResp<MSME43BHWorking>>(
        `/api/income-tax/msme-43bh?client_id=${encodeURIComponent(client_id)}` +
        `&fy=${encodeURIComponent(fy)}` +
        (bankRateBps === undefined ? "" : `&bank_rate_bps=${bankRateBps}`)),
  },
  documents: {
    list: (client_id?: string) => request(`/api/documents${client_id ? `?client_id=${client_id}` : ""}`),
    /** Put a file in the firm's store. Multipart, so the browser sets the
     *  boundary and Content-Type is not ours to send. */
    upload: async (form: FormData) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const res = await fetch(`${BASE_URL}/api/documents/upload`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error(await errorMessage(res));
      return res.json();
    },
    /** A signed link to a stored document, minted NOW.
     *
     *  The store's links expire within the hour, which is why nothing keeps
     *  one: an attachment holds the document's id and asks for a link at the
     *  moment somebody opens it. */
    downloadUrl: (docId: string) => request(`/api/documents/${docId}/download-url`),
    /** Same shape as upload above, and for the same reason: multipart, so the
     *  browser sets the boundary and Content-Type is not ours to send — which
     *  is why this cannot go through `request`.
     *
     *  It sent NO Authorization header at all. routers/documents.py::
     *  parse_document is Depends(rbac("document", "write")) and core/auth.py
     *  answers 401 without a Bearer header, so document parsing never once
     *  worked against a real deployment; the caller read `.json()` of the 401
     *  body and got {detail: …} with no `success`. */
    parse: async (formData: FormData) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const res = await fetch(`${BASE_URL}/api/documents/parse`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: formData,
      });
      if (!res.ok) throw new Error(await errorMessage(res));
      return res.json();
    },
  },
  assistant: {
    ask: (body: { question: string; conversation_history?: unknown[]; client_id?: string }) =>
      request("/api/assistant", { method: "POST", body: JSON.stringify(body) }),
  },
  insights: {
    list: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/insights${q ? `?${q}` : ""}`);
    },
    updateStatus: (id: string, status: string) =>
      request(`/api/insights/${id}/status?new_status=${status}`, { method: "PATCH" }),
  },
  tasks: {
    list: (params?: { client_id?: string; status?: string; assigned_to?: string; kanban?: boolean }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/tasks${q ? `?${q}` : ""}`);
    },
    kanban: () => request("/api/tasks?kanban=true"),
    create: (body: unknown) => request("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) => request(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    dashboardSummary: () => request("/api/tasks/summary/dashboard"),
  },
  team: {
    list: () => request("/api/team"),
  },
  reminders: {
    list: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams(params as Record<string, string>).toString();
      return request(`/api/reminders${q ? `?${q}` : ""}`);
    },
    create: (body: unknown) => request("/api/reminders", { method: "POST", body: JSON.stringify(body) }),
    markSent: (id: string) => request(`/api/reminders/${id}/sent`, { method: "PATCH" }),
  },
  mca: {
    // ADT-1 / AOC-4 / MGT-7 across the caller's clients, counted from each
    // company's REAL last_agm_date. The calendar built these in the browser off
    // an assumed 30 September AGM, a day early on both — see the endpoint's
    // docstring. A company with no AGM date recorded comes back in
    // `without_agm_date` rather than being given a plausible one.
    firmCalendar: () => request("/api/mca/calendar/firm"),
  },
  accounting: {
    accounts: () => request("/api/accounting/accounts"),
    createAccount: (data: unknown) => request("/api/accounting/accounts", { method: "POST", body: JSON.stringify(data) }),
    updateAccount: (id: string, data: unknown) => request(`/api/accounting/accounts/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    // The Schedule III captions a mapping may be set to, served by the module
    // that does the classifying. The mapping screen used to carry its own
    // hardcoded list, which had drifted in both directions — it offered five
    // captions the engine could not honour, and spelled five others
    // differently, which is how nine live mappings were being discarded.
    scheduleIiiCaptions: () => request("/api/accounting/schedule-iii/captions"),
    journal: (params?: Record<string, string>) => request(`/api/accounting/journal${params ? "?" + new URLSearchParams(params) : ""}`),
    createJournalEntry: (data: unknown) => request("/api/accounting/journal", { method: "POST", body: JSON.stringify(data) }),
    // One entry with its lines, plus whether it may still be edited. `editable`
    // and `lock_reason` are resolved by the same database function the write
    // path enforces with (journal_period_lock_reason, migration 266), so the
    // editor cannot show "open" for a period the ledger will refuse.
    getJournalEntry: (id: string) =>
      request<ApiResp<JournalEntryDetail>>(`/api/accounting/journal/${id}`),
    // Correct an entry, draft or posted. A POSTED entry must send its FULL set
    // of lines — the backend rewrites them wholesale inside edit_posted_journal
    // rather than diffing, so a partial line list would silently drop legs.
    updateJournalEntry: (id: string, data: JournalEntryUpdate) =>
      request<ApiResp<JournalEntryDetail>>(`/api/accounting/journal/${id}`, {
        method: "PATCH", body: JSON.stringify(data),
      }),
    ledger: (params: Record<string, string>) => request(`/api/accounting/ledger?${new URLSearchParams(params)}`),
    trialBalance: (params?: Record<string, string>) => request(`/api/accounting/trial-balance${params ? "?" + new URLSearchParams(params) : ""}`),
    // Bring an imported trial balance into a client's ledger as one balanced
    // opening journal. `preview: true` validates and returns totals without
    // writing anything, so the wizard can show what is wrong before committing.
    // Amounts are integer paise; the backend refuses an unbalanced trial balance.
    importTrialBalance: (data: {
      client_id: string;
      rows: { account_name: string; account_type: string;
              debit_paise: number; credit_paise: number; account_code?: string | null }[];
      opening_date?: string | null;
      preview?: boolean;
    }) => request<ApiResp<{
      posted?: boolean; reason?: string; journal_entry_id?: string;
      opening_date?: string; accounts?: number; adjustment_lines?: number;
      total_debit_paise?: number; total_credit_paise?: number;
      valid?: boolean; rows?: number;
    }>>("/api/accounting/trial-balance/import", { method: "POST", body: JSON.stringify(data) }),
    // First/last posted entry dates — what "All Time" resolves to on the
    // reporting screens, so a period split by month/quarter covers the books
    // rather than the 1900–2999 placeholder.
    ledgerSpan: (params?: Record<string, string>) => request(`/api/accounting/ledger-span${params ? "?" + new URLSearchParams(params) : ""}`),
    profitLoss: (params?: Record<string, string>) => request(`/api/accounting/profit-loss${params ? "?" + new URLSearchParams(params) : ""}`),
    balanceSheet: (params?: Record<string, string>) => request(`/api/accounting/balance-sheet${params ? "?" + new URLSearchParams(params) : ""}`),
    scheduleIii: (params?: Record<string, string>) => request(`/api/accounting/schedule-iii${params ? "?" + new URLSearchParams(params) : ""}`),
    /**
     * PUBLISH ONE STATEMENT TO A CLIENT'S PORTAL.
     *
     * The screen used to do both privileged writes itself — upload the workbook
     * to Supabase Storage and insert into `shared_reports` over PostgREST — so
     * `rbac()` ran on neither, and what it publishes is a client's P&L, Balance
     * Sheet or Trial Balance to that client's own portal. Both writes are the
     * server's now; the browser still BUILDS the workbook, which is formatting
     * of figures the server already computed.
     *
     * `report_id` is this screen's own id (pl / bs / trial). What the table
     * calls it is resolved in `domain/reporting/shared_report.py`, so the
     * browser cannot post a value the CHECK refuses — which is exactly what
     * made the Trial Balance button fail for as long as it existed.
     */
    shareReport: async (form: FormData) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const res = await fetch(`${BASE_URL}/api/accounting/shared-reports`, {
        method: "POST",
        // No Content-Type — the browser sets the multipart boundary.
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      // A 422 is a sentence written for the CA (an unknown report, an empty or
      // oversized workbook), so surface it rather than the status line.
      if (!res.ok) throw new Error(await errorMessage(res));
      return res.json();
    },
    /**
     * The Schedule III ageing schedules — the notes to the balance sheet added
     * by MCA Notification G.S.R. 207(E) of 24 March 2021. Twenty-four figures,
     * computed by public.schedule_iii_ageing (migration 303) rather than by
     * shipping every open document to the client. Division I row sets; the two
     * tables have DIFFERENT columns, so read them off `buckets` rather than
     * assuming one shape.
     */
    scheduleIiiAgeing: (clientId: string, asOf?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (asOf) q.set("as_of", asOf);
      return request<ApiResp<AgeingSchedule>>(`/api/accounting/schedule-iii/ageing?${q}`);
    },
    /**
     * Record the disputed / doubtful / MSMED classification the note needs.
     * Manager+ server-side: the MSMED one is a judgement with a tax consequence
     * under IT Act s.43B(h), not a display preference. Send msme_status: null to
     * put a vendor back into the unclassified gap.
     */
    classifyForAgeing: (body: AgeingClassifyBody) =>
      request<ApiResp<{ target: string; target_id: string; set: Record<string, unknown> }>>(
        "/api/accounting/schedule-iii/ageing/classify",
        { method: "POST", body: JSON.stringify(body) }),
    /**
     * Record — or withdraw — the review that lets the unbilled-dues disclosure
     * be printed at all. Marking accounts says "these hold unbilled dues"; only
     * this says "and there are no others", which is what the note claims and
     * what makes a nil printable.
     */
    reviewUnbilledDues: (body: { client_id: string; reviewed: boolean; note?: string | null }) =>
      request<ApiResp<{ reviewed: boolean; reviewed_on: string | null; note: string | null }>>(
        "/api/accounting/schedule-iii/ageing/unbilled-review",
        { method: "PUT", body: JSON.stringify(body) }),
    /**
     * The eleven Schedule III ratios (Division I clause (Q)). Both years are
     * computed server-side, so the 25% variance test the statute requires is a
     * fact rather than something the CA re-derives.
     */
    /**
     * Budget versus actuals for one client-year. The ACTUALS come from
     * `account_period_balances` server-side — one bucket read covering all
     * four quarters. The screen used to compute them itself with four unpaged
     * reads of `journal_lines`, which PostgREST truncates at ~1000 rows
     * without saying so, and it did that across every client at once (ACC-06).
     * `client_id` is required: the buckets are per client.
     */
    budgets: (clientId: string, fy?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (fy) q.set("fy", fy);
      return request<ApiResp<BudgetVsActuals>>(`/api/accounting/budgets?${q}`);
    },
    /**
     * Record or clear one account's budget. `budget_paise: null` DELETES it —
     * "not budgeted" and "budgeted at nil" are different statements and only
     * the second produces a variance.
     */
    saveBudget: (body: {
      client_id: string; fy: string; account_id: string; budget_paise: number | null;
    }) => request<ApiResp<{ account_id: string; fy: string; budget_paise: number | null }>>(
      "/api/accounting/budgets", { method: "PUT", body: JSON.stringify(body) }),
    scheduleIiiRatios: (clientId: string, fy?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (fy) q.set("fy", fy);
      return request<ApiResp<ScheduleIiiRatioNote>>(`/api/accounting/schedule-iii/ratios?${q}`);
    },
    /** Record why a ratio moved more than 25%. `explanation: null` clears it. */
    saveRatioExplanation: (body: {
      client_id: string; fy: string; ratio_key: string; explanation: string | null;
    }) => request<ApiResp<{ fy: string; ratio_key: string; explanation: string | null }>>(
      "/api/accounting/schedule-iii/ratios/explanation",
      { method: "PUT", body: JSON.stringify(body) }),
    /**
     * The principal repaid on long-term borrowings during the year — the one
     * figure Debt Service Coverage needs that the ledger cannot supply, because
     * the movement in the borrowing balance is drawdowns less repayments.
     * `null` puts the ratio back into its gap; 0 is a real answer.
     */
    saveRatioInputs: (body: {
      client_id: string; fy: string; principal_repaid_paise: number | null;
    }) => request<ApiResp<{ fy: string; principal_repaid_paise: number | null }>>(
      "/api/accounting/schedule-iii/ratios/inputs",
      { method: "PUT", body: JSON.stringify(body) }),
    /**
     * Several financial years of Schedule III captions and clause (Q) ratios
     * side by side. One backend call for the whole window: the service reads
     * the client's buckets once and projects every year from them, so ten years
     * costs what one costs. Asking for the years one at a time would undo that.
     */
    scheduleIiiTrend: (clientId: string, years?: number, toFy?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (years) q.set("years", String(years));
      if (toFy) q.set("to_fy", toFy);
      return request<ApiResp<MultiYearTrend>>(`/api/accounting/schedule-iii/trend?${q}`);
    },
    cashFlow: (params?: Record<string, string>) => request(`/api/accounting/cash-flow${params ? "?" + new URLSearchParams(params) : ""}`),
    statementAnalysis: (params: Record<string, string>) => request(`/api/accounting/statement-analysis?${new URLSearchParams(params)}`),
    // Phase 3.5 — journal approval queue (Draft → Approve → Post)
    journalsQueue: (params?: Record<string, string>) => request(`/api/accounting/journals${params ? "?" + new URLSearchParams(params) : ""}`),
    postDraftJournal: (journalId: string) => request(`/api/accounting/journals/${journalId}/post`, { method: "POST" }),
    /**
     * Delete a manual journal entry — a draft always, a POSTED one while its
     * period is still open (migration 275, the same gate that governs editing
     * one). The server refuses an auto-posted entry, or a period closed by a
     * lock or a filed return, each with a sentence written for the CA. Surface
     * that sentence; do not replace it.
     *
     * withPair deletes a reversed entry together with its reversal (migration
     * 276). The pair nets to zero, so no balance moves; half a pair alone is
     * refused either way round, because it would strand the other half.
     *
     * Returns deleted_ids — one call can remove two rows.
     */
    discardJournalEntry: (entryId: string, withPair = false) =>
      request(`/api/accounting/journal/${entryId}${withPair ? "?with_pair=true" : ""}`,
              { method: "DELETE" }),
    /**
     * Post an equal-and-opposite entry against a POSTED one; the original is
     * never modified. Partner-only (rbac accounting.approve). Refuses a
     * Receipt/Payment journal, which must be reversed through its own
     * document's cascade so the allocations roll back too.
     */
    reverseJournalEntry: (entryId: string, reversalDate: string, narration?: string) =>
      request(`/api/accounting/journal/${entryId}/reverse`, {
        method: "POST",
        body: JSON.stringify({ reversal_date: reversalDate, narration }),
      }),
    // Multi-Currency Phase 5 — read-only FX reports (empty for INR-only clients).
    fxReports: {
      realized: (params: Record<string, string>) => request(`/api/fx-reports/realized?${new URLSearchParams(params)}`),
      unrealized: (params: Record<string, string>) => request(`/api/fx-reports/unrealized?${new URLSearchParams(params)}`),
      exposure: (params: Record<string, string>) => request(`/api/fx-reports/exposure?${new URLSearchParams(params)}`),
      rateAudit: (params: Record<string, string>) => request(`/api/fx-reports/rate-audit?${new URLSearchParams(params)}`),
      openBalances: (params: Record<string, string>) => request(`/api/fx-reports/open-balances?${new URLSearchParams(params)}`),
    },
    /** AS 11 period-end revaluation of open foreign monetary items.
     *
     * A POST for the PREVIEW as well, because the closing rates are a map and
     * a query string is the wrong place for one — the same shape as
     * `/api/filing-demo/{flow}/preview`. The preview writes nothing; `run`
     * posts through the one kernel and auto-reverses on day 1 of the next
     * period. `closing_rates` may be omitted from the preview, which is the
     * useful first call: the answer names the currencies that need one. */
    fxRevaluation: {
      preview: (clientId: string, body: { period_end: string; closing_rates?: Record<string, string> }) =>
        request(`/api/fx-revaluation/preview?client_id=${encodeURIComponent(clientId)}`, {
          method: "POST", body: JSON.stringify(body),
        }),
      run: (clientId: string, body: { period_end: string; closing_rates: Record<string, string> }) =>
        request(`/api/fx-revaluation/run?client_id=${encodeURIComponent(clientId)}`, {
          method: "POST", body: JSON.stringify(body),
        }),
    },
  },
  // Stock register + per-item ledger (migration 188). Read-only — all
  // movements are written as a side effect of issuing/receiving documents.
  ewayBill: {
    /** SALES-28 — live bills at or past their Rule 138(10) validity, across
     *  the caller's own clients. Firm-wide by nature: the deadlines screen
     *  shows every client at once, so there is no client_id and the caller's
     *  assigned book is the scope.
     *
     *  NOT a compliance obligation and deliberately not rendered as one —
     *  nothing is FILED for an e-way bill, the action is to extend it on the
     *  NIC portal under the proviso to Rule 138(10). Which bills appear, which
     *  bucket each is in, whether the date was recorded off the portal or
     *  computed from the distance, and both caveats are all the server's. */
    expiring: (withinDays = 2) =>
      request<ApiResp<ExpiringEwayBills>>(
        `/api/eway-bill/expiring?within_days=${withinDays}`),
    /** RECORD an extension obtained on the NIC portal — this product reaches
     *  no portal. The endpoint has existed since the module was written and
     *  had no caller until 24-09-2026, so the one action the expiring panel
     *  exists to prompt could not be taken anywhere in the product.
     *
     *  The server refuses a date that does not extend the bill's own current
     *  validity, so this is not the place to re-check it. */
    extend: (recordId: string, newValidUpto: string, reason: string) =>
      request(`/api/eway-bill/records/${recordId}/extend`, {
        method: "POST",
        body: JSON.stringify({ new_valid_upto: newValidUpto, extension_reason: reason }),
      }),
  },

  inventory: {
    items: (params: Record<string, string>) => request(`/api/inventory/items?${new URLSearchParams(params)}`),
    /** Closing stock AS AT a date — the statement that ties to the Inventories
     *  line on the balance sheet. Distinct from `items`, which is the CURRENT
     *  position and takes no date: the two answer different questions, and only
     *  this one can answer for an earlier date, because the ledger's stored
     *  running totals are chained in insertion order. Migration 363. */
    stockSummary: (params: Record<string, string>) =>
      request(`/api/inventory/stock-summary?${new URLSearchParams(params)}`),
    /** INV-04 — the units ON HAND bucketed by how long they have been held,
     *  first-in-first-out. A DIFFERENT question from Days Idle, which is about
     *  the ITEM: an item selling steadily has a recent last-movement date and
     *  may still be carrying stock bought three years ago behind the units
     *  that keep turning over, and those are the AS-2 paragraph 24
     *  obsolescence the write-down endpoint exists for. Every band, every
     *  caveat and the value split are the server's. Migration 408. */
    stockAgeing: (params: Record<string, string>) =>
      request<ApiResp<StockAgeing>>(
        `/api/inventory/stock-ageing?${new URLSearchParams(params)}`),
    /** INV-03 — what is at or below its reorder level, grouped by item group.
     *  An ABSENT level is its own state and is never rendered as zero: zero is
     *  a real answer meaning "tell me when it runs out". The on-hand figure is
     *  the ledger's, not the cached `stock_qty_units`. Migration 409. */
    reorder: (params: Record<string, string>) =>
      request<ApiResp<ReorderReport>>(
        `/api/inventory/reorder?${new URLSearchParams(params)}`),
    /** The item groups this client already uses, most-used first — so the
     *  picker offers what exists rather than an empty box. A suggestion and
     *  never a constraint. */
    itemGroups: (params: Record<string, string>) =>
      request<ApiResp<{ groups: { group: string; items: number }[] }>>(
        `/api/inventory/item-groups?${new URLSearchParams(params)}`),
    ledger: (serviceCatalogueId: string, params: Record<string, string>) =>
      request(`/api/inventory/items/${serviceCatalogueId}/ledger?${new URLSearchParams(params)}`),
    adjust: (serviceCatalogueId: string, body: unknown) =>
      request(`/api/inventory/items/${serviceCatalogueId}/adjust`, { method: "POST", body: JSON.stringify(body) }),
    writedown: (serviceCatalogueId: string, body: unknown) =>
      request(`/api/inventory/items/${serviceCatalogueId}/writedown`, { method: "POST", body: JSON.stringify(body) }),
    // INV-08 — the physical count. One sheet, not a hundred adjustments. The
    // VARIANCE is derived on the server against the position as at the count
    // date and is never sent up; so is which line may post and why.
    openCountSession: (body: unknown) =>
      request<ApiResp<{ id: string }>>("/api/inventory/count-sessions",
        { method: "POST", body: JSON.stringify(body) }),
    countSessions: (params: Record<string, string>) =>
      request<ApiResp<StockCountSessionRow[]>>(
        `/api/inventory/count-sessions?${new URLSearchParams(params)}`),
    countSession: (sessionId: string) =>
      request<ApiResp<StockCountSheet>>(
        `/api/inventory/count-sessions/${encodeURIComponent(sessionId)}`),
    saveCountSession: (sessionId: string, body: unknown) =>
      request<ApiResp<StockCountSheet & { saved: number }>>(
        `/api/inventory/count-sessions/${encodeURIComponent(sessionId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    postCountSession: (sessionId: string) =>
      request<ApiResp<StockCountPostResult>>(
        `/api/inventory/count-sessions/${encodeURIComponent(sessionId)}/post`,
        { method: "POST" }),
    // INV-02 — which of AS-2 paragraph 14's two cost formulas prices an
    // issue. The formula is a per-CLIENT policy (AS-2 par. 16), the answer
    // for a client with nothing recorded is the weighted average, and a
    // change is prospective (AS-5 par. 29/32). Every sentence in the response
    // is the server's; nothing here decides.
    costingPolicy: (params: Record<string, string>) =>
      request<ApiResp<InventoryCostingPolicy>>(
        `/api/inventory/costing-policy?${new URLSearchParams(params)}`),
    setCostingPolicy: (body: {
      client_id: string; method: string; effective_from: string | null;
    }) =>
      request<ApiResp<InventoryCostingPolicy>>("/api/inventory/costing-policy",
        { method: "PUT", body: JSON.stringify(body) }),
  },
  // Multi-Currency (Phase 1/5) — currency master + resolved policy (gates FX UI).
  currencies: {
    list: (params?: Record<string, string>) => request(`/api/currencies${params ? "?" + new URLSearchParams(params) : ""}`),
    policy: (params: Record<string, string>) =>
      request<ApiResp<CurrencyPolicy>>(`/api/currencies/policy?${new URLSearchParams(params)}`),
    // ACC-19 — the two gates that were READ by six routers and WRITTEN BY
    // NOTHING. `setEntitlement` is the firm switch (L2), `setClientPolicy` the
    // per-client one (L3). The platform gate is an environment kill switch and
    // deliberately has no setter.
    // The firm gate on its own, with no client in the request — a firm with no
    // clients yet cannot read it off a client's policy, and that firm is
    // exactly the one a Partner is switching this on for.
    entitlement: () =>
      request<ApiResp<{ platform: { on: boolean; why?: string }; firm: { on: boolean } }>>(
        "/api/currencies/entitlement"),
    setEntitlement: (enabled: boolean) =>
      request<ApiResp<{ multi_currency_entitled: boolean }>>("/api/currencies/entitlement",
        { method: "PUT", body: JSON.stringify({ enabled }) }),
    /** The four rate types the fx_rates CHECK admits, and what each is for.
     *  Served rather than spelled here: a browser copy is a second vocabulary
     *  one migration away from disagreeing with the database. */
    rateTypes: () =>
      request<ApiResp<{ rate_types: { code: string; meaning: string }[] }>>(
        "/api/currencies/rate-types"),
    /** The most recent rates for one (base, quote, rate_type), newest first. */
    rates: (params: { base: string; quote: string; rate_type: string; limit?: string }) =>
      request<ApiResp<FxRateList>>(
        `/api/currencies/rates?${new URLSearchParams(params as Record<string, string>)}`),
    /** Record one rate. Partner-only, and SHARED ACROSS THE PLATFORM — a rate
     *  is a fact about the world, so the tenancy answer is on the write side.
     *  The rate travels as a STRING: the column is NUMERIC(18,8) precisely so
     *  it is exact, and a JSON number would put a float round trip in front of
     *  that. `source` is not settable — it is the provider identifier
     *  ManualRateProvider matches on and half the unique key. */
    recordRate: (body: { base: string; quote: string; rate_date: string;
                         rate: string; rate_type: string }) =>
      request<ApiResp<FxRate & { replaced: boolean }>>("/api/currencies/rates",
        { method: "PUT", body: JSON.stringify(body) }),
    setClientPolicy: (clientId: string, enabled: boolean) =>
      request<ApiResp<{ multi_currency_enabled: boolean }>>(
        `/api/currencies/policy?client_id=${encodeURIComponent(clientId)}`,
        { method: "PUT", body: JSON.stringify({ enabled }) }),
  },
  // Banking (Phase B.0): all bank mutations go through the backend banking
  // service — the frontend never writes bank rows or journals to Supabase.
  banking: {
    /** BANK — "Worth a look": the posted lines of ONE PERIOD carrying a reason
     *  for a partner to look, worst first, with what could not be asked.
     *  Read-only and advisory: nothing it returns blocks or reverses a posting.
     *  `from_date` and `to_date` are required by the server and are not
     *  defaulted here either — an optional period is how a report comes to read
     *  the whole ledger. */
    worthALook: (params: { client_id: string; from_date: string; to_date: string;
                           bank_account_id?: string }) =>
      request<ApiResp<WorthALook>>(
        `/api/banking/worth-a-look?${new URLSearchParams(params as Record<string, string>)}`),
    // BANK-21 — the five kinds of account and what each one is. The TYPE
    // decides whether the ledger is an asset or a liability and, for a card,
    // which way up its balance reads, so the form must not hold its own list.
    bankAccountTypes: () =>
      request<ApiResp<{ account_types: BankAccountTypeInfo[] }>>("/api/banking/account-types"),
    listBankAccounts: (params?: Record<string, string>) => request(`/api/banking/accounts${params ? "?" + new URLSearchParams(params) : ""}`),
    createBankAccount: (data: unknown) => request("/api/banking/accounts", { method: "POST", body: JSON.stringify(data) }),
    updateBankAccount: (id: string, data: unknown) => request(`/api/banking/accounts/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    /** Which bank accounts have no footprint and can be permanently deleted, and
     *  what is blocking the rest. Separate from the list so pickers stay cheap. */
    bankAccountsDeletable: (params: Record<string, string>) => request(`/api/banking/accounts/deletable?${new URLSearchParams(params)}`),
    /** Permanently delete a bank account. Refused (409) unless it has no
     *  statements, no reconciliations, no payroll and no posted journal lines. */
    deleteBankAccount: (id: string) => request(`/api/banking/accounts/${id}`, { method: "DELETE" }),
    /** Multi-Currency Phase 5 — derived base (+ foreign for FX accounts) balance. */
    accountBalance: (accountId: string, params: Record<string, string>) => request(`/api/banking/accounts/${accountId}/balance?${new URLSearchParams(params)}`),
    listStatements: (params?: Record<string, string>) => request(`/api/banking/statements${params ? "?" + new URLSearchParams(params) : ""}`),
    /** Store ALREADY-PARSED statement rows. No screen calls this and none may:
     *  the browser cannot parse a bank statement — domain/banking/normalizer.py
     *  holds the column adapters, the CA's saved mapping, the dedup and the
     *  tie-out against the statement's own printed totals, and a file turned
     *  into rows here reaches none of them. Use uploadStatement, which sends
     *  the FILE. Kept for a scripted import, and it requires bank_account_id
     *  since BANK-22.
     *  Guarded by scripts/a-statement-is-parsed-on-the-server-and-belongs-to-an-account.test.ts */
    importStatement: (data: unknown) => request("/api/banking/statements/import", { method: "POST", body: JSON.stringify(data) }),
    /** Remove a statement imported by mistake (BANK-06) — the wrong file, the
     *  wrong client, the wrong month. HARD, and the lines go with it, because
     *  the import dedupes on a unique (client_id, import_hash) and rows left
     *  behind would silently skip every line of the re-import.
     *
     *  Refused with a sentence where anything has been posted, matched,
     *  ignored or reconciled off it: a statement lines were posted off is the
     *  voucher for those entries, which Companies Act s. 128(5) reaches
     *  expressly (the same statute services/bank_erasure.py names). */
    deleteStatement: (id: string) => request(`/api/banking/statements/${id}`, { method: "DELETE" }),
    /** Upload a CSV/XLSX statement — parsed, normalized & deduped SERVER-SIDE (B.1). */
    uploadStatement: async (form: FormData) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const res = await fetch(`${BASE_URL}/api/banking/statements/upload`, {
        method: "POST",
        // No Content-Type — the browser sets the multipart boundary.
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      // A 422 here is an answer written for the CA — the statement does not add
      // up, the format is unmappable — and it used to reach the screen as the
      // raw JSON body inside "API error 422: {...}". It now arrives as its
      // sentence, with the server's code where there is one, so the import
      // dialog can offer the acknowledgement rather than leaving a dead end.
      if (!res.ok) throw await refusalFrom(res);
      return res.json();
    },
    /** Tier 3.2 — a multipart POST that returns JSON, same shape as uploadStatement. */
    postStatementForm: async (path: string, form: FormData) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const res = await fetch(`${BASE_URL}${path}`, {
        method: "POST",
        // No Content-Type — the browser sets the multipart boundary.
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      // A 422 here is a real answer (an unmappable file, a contradictory
      // mapping) and its message is written for the CA, so surface the body
      // rather than the status line.
      if (!res.ok) throw new Error(await errorMessage(res));
      return res.json();
    },
    /** Read a statement's header row + first rows so the CA can map the columns. */
    inspectStatement: (form: FormData) =>
      api.banking.postStatementForm("/api/banking/statements/inspect", form),
    /** Parse with a mapping and show the result WITHOUT importing. */
    previewStatement: (form: FormData) =>
      api.banking.postStatementForm("/api/banking/statements/preview", form),
    listColumnMappings: (params?: Record<string, string>) =>
      request(`/api/banking/statements/column-mappings${params ? "?" + new URLSearchParams(params) : ""}`),
    deleteColumnMapping: (id: string) =>
      request(`/api/banking/statements/column-mappings/${id}`, { method: "DELETE" }),
    listTransactions: (params?: Record<string, string>) => request(`/api/banking/transactions${params ? "?" + new URLSearchParams(params) : ""}`),
    setTransactionAccount: (txnId: string, data: unknown) => request(`/api/banking/transactions/${txnId}`, { method: "PATCH", body: JSON.stringify(data) }),
    ignoreTransaction: (txnId: string) => request(`/api/banking/transactions/${txnId}/ignore`, { method: "POST" }),
    /** Undo an ignore — the transaction returns to the work queue. */
    unignoreTransaction: (txnId: string) => request(`/api/banking/transactions/${txnId}/unignore`, { method: "POST" }),
    postTransaction: (txnId: string, data: unknown) => request(`/api/banking/transactions/${txnId}/post`, { method: "POST", body: JSON.stringify(data) }),
    // Bank ENTRIES (migration 322, docs/architecture/09-bank-entries.md): the
    // draft is on the row, the state is a stored column, and the verb is Pass.
    entries: {
      /** One page of lines in a state, with the total. */
      list: (params: { client_id: string; state?: EntryListState; bank_account_id?: string;
                       limit?: string; offset?: string; q?: string;
                       /** D19 — lines a rule flagged for a withholding decision that
                        *  nobody has answered. It REPLACES `state` rather than
                        *  narrowing it: a flagged line is always `passed`, so ANDing
                        *  the two would answer empty for every client. The server
                        *  decides that, not the caller. */
                       tds_pending?: string }) =>
        request(`/api/banking/entries?${new URLSearchParams(params as Record<string, string>)}`),
      /** One number per state, plus undrafted (redraft while non-zero) and
       *  trusted_pending (pass these with a progress bar). SQL counts. */
      counts: (params: { client_id: string; bank_account_id?: string }) =>
        request(`/api/banking/entries/counts?${new URLSearchParams(params as Record<string, string>)}`),
      /** The one line the CA opened: live candidates, history, transfer counterpart. */
      get: (txnId: string) => request(`/api/banking/entries/${txnId}`),
      /** Propose for one chunk of open lines; returns `remaining`. Pass the
       *  returned stale_before back on every chunk of a forced refresh. */
      redraft: (data: { client_id: string; limit?: number; stale_before?: string | null;
                        transaction_ids?: string[] }) =>
        request("/api/banking/entries/redraft", { method: "POST", body: JSON.stringify(data) }),
      /** One chunk of "Pass N ready". Every line comes back with its outcome. */
      passReady: (data: { client_id: string; limit?: number; only_trusted?: boolean;
                          bank_account_id?: string; transaction_ids?: string[] }) =>
        request("/api/banking/entries/pass-ready", { method: "POST", body: JSON.stringify(data) }),
      /** Pass ONE line — the click is the CA accepting its draft. A refusal is a 422. */
      pass: (txnId: string, data?: { gst_rate_bps?: number | null; is_interstate?: boolean }) =>
        request(`/api/banking/transactions/${txnId}/pass`, { method: "POST", body: JSON.stringify(data ?? {}) }),
      /** D19 — record that a person answered the withholding question on this
       *  line. NO BODY, deliberately: it records that somebody LOOKED, never
       *  what they decided. A section or a rate here would undo migration
       *  404's refusal to let a rule carry a TDS treatment. */
      resolveTdsDecision: (txnId: string) =>
        request(`/api/banking/transactions/${txnId}/tds-decision/resolve`, { method: "POST" }),
    },
    suggestions: (txnId: string) => request(`/api/banking/transactions/${txnId}/suggestions`),
    // B.1.6 — "Find other matches". suggestions() ranks the best five WITHIN an
    // amount band; this searches everything the direction permits, so a CA who
    // knows which invoice it is can simply find it. Read only — picking a result
    // still goes through matchEntity.
    candidateSearch: (txnId: string, params?: Record<string, string>) =>
      request(`/api/banking/transactions/${txnId}/candidate-search${params ? "?" + new URLSearchParams(params) : ""}`),
    categorize: (txnId: string, data: { category: string }) => request(`/api/banking/transactions/${txnId}/categorize`, { method: "POST", body: JSON.stringify(data) }),
    matchEntity: (txnId: string, data: { matched_entity_type: string; matched_entity_id: string; category?: string }) => request(`/api/banking/transactions/${txnId}/match`, { method: "POST", body: JSON.stringify(data) }),
    // Multi-invoice bank allocation — match ONE transaction to MULTIPLE sales
    // invoices / purchase bills in a single settlement. Immediately creates the
    // settling receipt/purchase_payment and posts its journal (unlike matchEntity,
    // which only links — posting is a separate later step for the 1:1 flow).
    matchMulti: (txnId: string, data: {
      entity_type: "sales_invoice" | "purchase_bill";
      allocations: { entity_id: string; allocated_paise: number }[];
      reference_no?: string; notes?: string; tds_paise?: number;
      currency?: string; exchange_rate?: string;
    }) => request(`/api/banking/transactions/${txnId}/match-multi`, { method: "POST", body: JSON.stringify(data) }),
    unmatch: (txnId: string) => request(`/api/banking/transactions/${txnId}/unmatch`, { method: "POST" }),
    /** Undo a POSTED transaction: reverses its journal, un-settles its document
     *  and puts the row back in the queue. `unmatch` refuses a posted row — it
     *  clears a MATCH, which is a different thing. */
    undoPost: (txnId: string) => request(`/api/banking/transactions/${txnId}/undo`, { method: "POST" }),
    // B.2.3 — matching rules. A rule annotates the work queue with a suggested
    // category / counter account / narration; it never posts and never writes to
    // a transaction on its own. Precedence is creation order. (These endpoints
    // existed server-side from the start but had no client method, so
    // bank_matching_rules could only ever be empty and the rule engine never
    // fired — see docs/audits/2026-08-02-bank-module-quickbooks-gap-audit.md.)
    rules: {
      list: (clientId: string) => request(`/api/banking/rules?client_id=${encodeURIComponent(clientId)}`),
      create: (data: BankRuleInput) => request("/api/banking/rules", { method: "POST", body: JSON.stringify(data) }),
      update: (ruleId: string, data: Partial<Omit<BankRuleInput, "client_id">>) =>
        request(`/api/banking/rules/${ruleId}`, { method: "PATCH", body: JSON.stringify(data) }),
      remove: (ruleId: string) => request(`/api/banking/rules/${ruleId}`, { method: "DELETE" }),
    },
    /** Tier 1.1 — the ledger view of ONE bank account: every line the bank
     *  sent, in bank order, with the running balance after each and its
     *  cleared status. Read-only; the running balance is computed server-side
     *  over the whole account, so a filtered view still shows true balances. */
    register: (params: {
      bank_account_id: string; client_id?: string;
      date_from?: string; date_to?: string;
      status?: "all" | "uncleared" | "pending" | "reconciled" | "unposted";
      q?: string; sort?: "date" | "amount" | "description" | "balance" | "cleared";
      desc?: string; limit?: string; offset?: string;
    }) => request(`/api/banking/register?${new URLSearchParams(params as Record<string, string>)}`),
    batchExclude: (transactionIds: string[]) =>
      request("/api/banking/transactions/batch-exclude", {
        method: "POST", body: JSON.stringify({ transaction_ids: transactionIds }),
      }),
    batchInclude: (transactionIds: string[]) =>
      request("/api/banking/transactions/batch-include", {
        method: "POST", body: JSON.stringify({ transaction_ids: transactionIds }),
      }),
    /** Tier 1.8 — supporting documents. The link must be http or https; the
     *  server refuses anything that could run code. */
    attachments: {
      list: (txnId: string) => request(`/api/banking/transactions/${txnId}/attachments`),
      /** EITHER a pasted link OR a document already in the firm's store, by
       *  id — never both. The store's own link expires within the hour, so a
       *  document is held by reference and resolved when it is opened. */
      add: (txnId: string, body: { name: string; url?: string; document_id?: string }) =>
        request(`/api/banking/transactions/${txnId}/attachments`, {
          method: "POST", body: JSON.stringify(body),
        }),
      remove: (txnId: string, body: { url?: string; document_id?: string }) =>
        request(`/api/banking/transactions/${txnId}/attachments/remove`, {
          method: "POST", body: JSON.stringify(body),
        }),
    },
    /** Confirm a transfer. `txnId` is the PRIMARY (outflow) side — the one that
     *  will carry the journal. The counterpart never posts one of its own. */
    pairTransfer: (txnId: string, counterpartId: string) =>
      request(`/api/banking/transactions/${txnId}/transfer-pair`, {
        method: "POST", body: JSON.stringify({ counterpart_id: counterpartId }),
      }),
    unpairTransfer: (txnId: string) =>
      request(`/api/banking/transactions/${txnId}/transfer-pair`, { method: "DELETE" }),
    /** Tier 1.3 — name who the money went to or came from, optionally linking
     *  a customer or vendor. An empty payee_name clears the payee AND its link. */
    setPayee: (txnId: string, data: { payee_name: string; payee_type?: string; payee_id?: string }) =>
      request(`/api/banking/transactions/${txnId}/payee`, { method: "PUT", body: JSON.stringify(data) }),
    /** Tier 1.2 — allocate ONE bank line across several GL accounts. The splits
     *  must sum exactly to what the bank moved; the server refuses anything else
     *  (there is no rounding plug). PUT with an empty list clears the split. */
    splits: {
      get: (txnId: string) => request(`/api/banking/transactions/${txnId}/splits`),
      replace: (txnId: string, splits: { account_id: string; amount_paise: number; narration?: string | null }[]) =>
        request(`/api/banking/transactions/${txnId}/splits`, {
          method: "PUT", body: JSON.stringify({ splits }),
        }),
    },
    postingPreview: (txnId: string, data: { bank_account_id?: string; account_id?: string; to_bank_account_id?: string; gst_rate_bps?: number; is_interstate?: boolean }) => request(`/api/banking/transactions/${txnId}/posting-preview`, { method: "POST", body: JSON.stringify(data) }),
    // B.4 — reconciliation engine (sessions, manual reconcile, tie-out, report)
    reconciliations: {
      list: (params?: Record<string, string>) => request(`/api/banking/reconciliations${params ? "?" + new URLSearchParams(params) : ""}`),
      create: (data: { client_id: string; bank_account_id: string; statement_start_date: string; statement_end_date: string; opening_balance_paise: number; closing_balance_paise: number }) => request("/api/banking/reconciliations", { method: "POST", body: JSON.stringify(data) }),
      /** Where a new reconciliation should start, plus the beginning-balance
       *  mismatch check. Read-only — opens nothing. */
      openingSuggestion: (params: { client_id: string; bank_account_id: string }) =>
        request(`/api/banking/reconciliations/opening-suggestion?${new URLSearchParams(params)}`),
      get: (id: string) => request(`/api/banking/reconciliations/${id}`),
      update: (id: string, data: { opening_balance_paise?: number; closing_balance_paise?: number }) => request(`/api/banking/reconciliations/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
      /** The documented difference the reconciled lines do not explain.
       *  MANAGER+ , and a reason is mandatory for any non-zero figure: this is
       *  the one number that can force a period to tie out, and it is printed
       *  on the certified reconciliation (BANK-05). Send 0 with no reason to
       *  clear it. */
      setAdjustment: (id: string, adjustments_paise: number, reason: string | null) =>
        request(`/api/banking/reconciliations/${id}/adjustment`,
                { method: "PUT", body: JSON.stringify({ adjustments_paise, reason }) }),
      report: (id: string) => request(`/api/banking/reconciliations/${id}/report`),
      /** The two-sided Bank Reconciliation Statement (BANK-04) — the document,
       *  as against `report`, which is the tie-out. Cash Book balance, cheques
       *  issued not presented, deposits not credited, the bank's own entries not
       *  yet in the books, and the Pass Book balance they reach. */
      brs: (id: string) => request(`/api/banking/reconciliations/${id}/brs`),
      reconcile: (id: string, transaction_ids: string[]) => request(`/api/banking/reconciliations/${id}/reconcile`, { method: "POST", body: JSON.stringify({ transaction_ids }) }),
      unreconcile: (id: string, transaction_ids: string[]) => request(`/api/banking/reconciliations/${id}/unreconcile`, { method: "POST", body: JSON.stringify({ transaction_ids }) }),
      complete: (id: string) => request(`/api/banking/reconciliations/${id}/complete`, { method: "POST" }),
      /** Undo a completion so a certified period can be corrected. Partner-only;
       *  a substantive reason is required and the frozen snapshot is preserved. */
      reopen: (id: string, reason: string) =>
        request(`/api/banking/reconciliations/${id}/reopen`, { method: "POST", body: JSON.stringify({ reason }) }),
      exportCsv: (id: string) => downloadFile(`/api/banking/reconciliations/${id}/report.csv`, `reconciliation-${id}.csv`),
      exportPdf: (id: string) => downloadFile(`/api/banking/reconciliations/${id}/report.pdf`, `reconciliation-${id}.pdf`),
      /** Tie-out AS IF these transactions were also reconciled. Read-only —
       *  computed by the same tie-out the real reconcile uses, so the preview
       *  can never disagree with the result. */
      preview: (id: string, transaction_ids: string[]) =>
        request(`/api/banking/reconciliations/${id}/preview`, { method: "POST", body: JSON.stringify({ transaction_ids }) }),
      /** Every certification this session has carried, newest first. */
      history: (id: string) => request(`/api/banking/reconciliations/${id}/history`),
    },
  },
  complianceRecords: {
    list: (params?: Record<string, string>) => request(`/api/compliance-records${params ? "?" + new URLSearchParams(params) : ""}`),
    get: (id: string) => request(`/api/compliance-records/${id}`),
    create: (data: unknown) => request("/api/compliance-records", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: unknown) => request(`/api/compliance-records/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    clientHealth: (clientId: string) => request(`/api/compliance-records/client/${clientId}/health`),
    firmSummary: () => request("/api/compliance-records/firm/summary"),
  },
  dashboard: {
    summary: () => request("/api/tasks/summary/dashboard"),
  },
  // Phase 4.4 — Compliance & Engagement operations (canonical = compliance_records).
  // Thin wrappers; all due-date/aggregation/workflow logic is server-side.
  // Never auto-submits to any government portal — markFiled records that a
  // CA has confirmed a return was filed, it never files anything itself.
  complianceOps: {
    dashboard: () => request("/api/compliance/dashboard"),
    obligations: (params?: Record<string, string>) =>
      request(`/api/compliance/obligations${params ? "?" + new URLSearchParams(params) : ""}`),
    calendar: (clientId?: string) =>
      request(`/api/compliance/obligations/calendar${clientId ? `?client_id=${clientId}` : ""}`),
    generate: (params?: Record<string, string>) =>
      request(`/api/compliance/obligations/generate${params ? "?" + new URLSearchParams(params) : ""}`, { method: "POST" }),
    assign: (id: string, body: { preparer_id?: string; reviewer_id?: string; approver_id?: string }) =>
      request(`/api/compliance/obligations/${id}/assign`, { method: "POST", body: JSON.stringify(body) }),
    transition: (id: string, status: string) =>
      request(`/api/compliance/obligations/${id}/transition`, { method: "POST", body: JSON.stringify({ status }) }),
    markFiled: (id: string, acknowledgementNo?: string) =>
      request(`/api/compliance/obligations/${id}/mark-filed`, {
        method: "POST", body: JSON.stringify({ acknowledgement_no: acknowledgementNo ?? null }),
      }),
    runEscalations: () => request("/api/compliance/run-escalations", { method: "POST" }),
  },
  // R3.13c — canonical client health engine (Product Bible Ch.16, routers/health.py).
  // Replaces the frontend's direct-Supabase health-score-compute.ts.
  health: {
    client: (clientId: string) => request(`/api/health/clients/${clientId}`),
    scores: () => request("/api/health/scores"),
    calculate: (clientId: string) => request(`/api/health/scores/${clientId}/calculate`, { method: "POST" }),
  },
  // Note: the unversioned `documentIntelligence` wrapper (client-side, unused
  // by any page) that pointed at /api/document-intelligence/* was removed in
  // the R2.8 fix phase — that backend router was a retired, undisclosed 4th
  // extraction generation serving hardcoded fabricated data. Real document
  // extraction lives at /api/document-intelligence-v1 and
  // /api/document-intelligence-v2 (called directly via fetch() from the
  // pages that use them, e.g. app/clients/[id]/purchases/page.tsx).
  risks: {
    list: (params?: Record<string, string>) => request(`/api/risks${params ? "?" + new URLSearchParams(params) : ""}`),
    stats: () => request("/api/risks/stats"),
    clientRisks: (clientId: string) => request(`/api/risks/client/${clientId}`),
    update: (riskId: string, data: unknown) => request(`/api/risks/${riskId}`, { method: "PATCH", body: JSON.stringify(data) }),
    firmScore: () => request("/api/risks/firm/score"),
    // The firm-wide statutory register. A SEPARATE endpoint from `list`, which
    // reads `document_risks`; see routers/risks.py for why they are not one.
    register: () => request("/api/risks/register"),
  },
  aiInsights: {
    list: (params?: Record<string, string>) => request(`/api/ai-insights${params ? "?" + new URLSearchParams(params) : ""}`),
    feed: () => request("/api/ai-insights/feed"),
    generate: (clientId: string) => request(`/api/ai-insights/generate/${clientId}`, { method: "POST" }),
    acknowledge: (id: string) => request(`/api/ai-insights/${id}/acknowledge`, { method: "PATCH" }),
    dismiss: (id: string) => request(`/api/ai-insights/${id}/dismiss`, { method: "PATCH" }),
  },
  automation: {
    rules: () => request("/api/automation/rules"),
    toggleRule: (id: string, enabled: boolean) => request(`/api/automation/rules/${id}/toggle`, { method: "PATCH", body: JSON.stringify({ enabled }) }),
    executions: () => request("/api/automation/executions"),
    stats: () => request("/api/automation/stats"),
  },
  notifications: {
    list: (unreadOnly?: boolean) => request(`/api/notifications${unreadOnly ? "?unread_only=true" : ""}`),
    count: () => request("/api/notifications/count"),
    markRead: (id: string) => request(`/api/notifications/${id}/read`, { method: "PATCH" }),
    markAllRead: () => request("/api/notifications/read-all", { method: "PATCH" }),
    stats: () => request("/api/notifications/stats"),
  },
  copilot: {
    chat: (body: { message: string; conversation_history: unknown[]; context?: string }) =>
      request("/api/ai-copilot/chat", { method: "POST", body: JSON.stringify(body) }),
    // clientChat was removed with the endpoint it called. That endpoint posted a
    // single client's name, GSTIN and PAN to Groq and now returns 410. The
    // wrapper had no callers, which is exactly why it had to go rather than be
    // left pointing at a dead route: an unused helper that still builds the URL
    // is the thing someone wires a button to next.
  },
  payroll: {
    /** PAY-23 — the annual statutory bonus register (Payment of Bonus Act
     *  1965). Who is owed, who is out and why, §19's due date and the
     *  employer's own §10/§11 rate. Every sentence is the server's; the
     *  browser spells no section and no threshold. */
    bonusRegister: (params: Record<string, string>) =>
      request<ApiResp<BonusRegister>>(
        `/api/payroll/bonus-register?${new URLSearchParams(params)}`),
    saveBonusDeclaration: (body: {
      client_id: string; accounting_year: string;
      /** null = apply the statutory minimum. §10's figure lives on the server
       *  only; a default here would be a second copy of it. */
      rate_bps: number | null;
      allocable_surplus_paise: number | null;
      minimum_wage_monthly_paise: number | null;
      scheduled_employment: string | null;
    }) =>
      request<ApiResp<unknown>>("/api/payroll/bonus-declaration",
        { method: "PUT", body: JSON.stringify(body) }),
    /** §9 — forfeiture of the WHOLE bonus on DISMISSAL for one of the Act's
     *  five grounds. The ground list comes back on the register as
     *  `section_9_grounds`; the browser holds none of its own. */
    saveBonusDisqualification: (body: {
      client_id: string; employee_id: string; accounting_year: string;
      ground: string; dismissed_on: string; notes?: string | null;
    }) =>
      request<ApiResp<unknown>>("/api/payroll/bonus-disqualification",
        { method: "PUT", body: JSON.stringify(body) }),
    removeBonusDisqualification: (params: Record<string, string>) =>
      request<ApiResp<unknown>>(
        `/api/payroll/bonus-disqualification?${new URLSearchParams(params)}`,
        { method: "DELETE" }),
    /** One employee's §192 projection for a financial year. Served, never
     *  computed here — the browser's own ladder went stale the day the
     *  Finance Act moved and said nothing. */
    tdsProjection: (clientId: string, employeeId: string, financialYear: string) =>
      request<ApiResp<PayrollTdsProjection>>(
        `/api/payroll/tds-projection?client_id=${encodeURIComponent(clientId)}` +
        `&employee_id=${encodeURIComponent(employeeId)}` +
        `&financial_year=${encodeURIComponent(financialYear)}`),
    // client_id omitted -> every client in the firm (firm-wide dashboard);
    // client_id given -> scoped to one client (per-client workspace).
    listEmployees: (clientId?: string, includeInactive?: boolean) => {
      const p = new URLSearchParams();
      if (clientId) p.set("client_id", clientId);
      if (includeInactive) p.set("include_inactive", "true");
      const qs = p.toString();
      return request(`/api/payroll/employees${qs ? `?${qs}` : ""}`);
    },
    createEmployee: (body: unknown) =>
      request("/api/payroll/employees", { method: "POST", body: JSON.stringify(body) }),
    updateEmployee: (id: string, body: unknown) =>
      request(`/api/payroll/employees/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    deleteEmployee: (id: string) =>
      request(`/api/payroll/employees/${id}`, { method: "DELETE" }),
    listRuns: (clientId?: string) =>
      request(`/api/payroll/runs${clientId ? `?client_id=${clientId}` : ""}`),
    createRun: (body: { client_id: string; month: string }) =>
      request("/api/payroll/runs", { method: "POST", body: JSON.stringify(body) }),
    getRunSlips: (runId: string) => request(`/api/payroll/runs/${runId}/slips`),
    /** The statutory table's five figures PER RUN, in one call.
     *
     *  What this replaced was one getRunSlips per run, issued concurrently on
     *  mount for a tab that is not the default, each returning every column of
     *  every payslip — to render a count, a gross, a TDS and two member
     *  counts. CLAUDE.md: what crosses the wire is the size of the ANSWER. */
    runSummaries: (params?: { client_id?: string; financial_year?: string }) => {
      const q = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return request<ApiResp<{ runs: PayrollRunSummary[] }>>(
        `/api/payroll/runs/summary${q ? `?${q}` : ""}`);
    },
    /** One row per EMPLOYEE for a financial year, aggregated by the server,
     *  plus the years the firm has payroll for.
     *
     *  The year-end tab used to build this in the browser from every payslip
     *  the firm had ever produced. It is the one report tab whose ANSWER is
     *  smaller than its rows: a hundred employees over twelve months is 1,200
     *  payslips to render a hundred lines. */
    yearEndSummary: (params: { financial_year: string; client_id?: string }) => {
      const q = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return request<ApiResp<{ rows: EmployeeYearTotalsRow[]; financial_years: string[] }>>(
        `/api/payroll/reports/year-end?${q}`);
    },
    /** Payslips for ONE run, ONE month or ONE employee.
     *
     *  Naming none of them is REFUSED with a 422 — see
     *  services/payroll_report_service.assert_narrowed. Both firm-level
     *  screens used to ask for every payslip the firm had ever produced. */
    slips: (params: {
      run_id?: string; month?: string; employee_id?: string;
      financial_year?: string; client_id?: string;
    }) => {
      const q = new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return request<ApiResp<{ slips: unknown[]; runs?: unknown[] }>>(
        `/api/payroll/slips?${q}`);
    },

    // Attendance goes through the API, not straight to PostgREST. The direct
    // write this replaced saved the page's WHOLE editor — which seeded a
    // confident 26/26 default row for every employee that had none — so one
    // Save asserted a full month for people nobody had looked at and
    // payroll_slips.attendance_entered (migration 324) then read true for all
    // of them. See domain/payroll/attendance.py.
    getAttendance: (clientId: string, month: string) =>
      request(`/api/payroll/attendance?client_id=${encodeURIComponent(clientId)}&month=${encodeURIComponent(month)}`),
    // `rows` must carry ONLY the employees the CA actually touched. lop_days is
    // omitted and derived server-side; sending one that contradicts the others
    // is refused rather than corrected.
    saveAttendance: (body: { client_id: string; month: string; rows: unknown[] }) =>
      request("/api/payroll/attendance", { method: "PUT", body: JSON.stringify(body) }),
    /** One-time and variable earnings — incentive, bonus, ex-gratia, arrears.
     *
     *  Through the API, never straight to PostgREST, because saving one is not
     *  saving a number: each row has to answer three separate questions that
     *  the browser must not guess — is it PF wages (EPF Act s.2(b)), is it ESI
     *  wages (ESI Act s.2(22), an INTERVAL test), is it salary (IT Act
     *  s.17(1)). `defaults` asks the server what the statute says; the row
     *  stores what was actually saved.
     */
    getOneTimeEarnings: (clientId: string, month: string) =>
      request(`/api/payroll/one-time-earnings?client_id=${encodeURIComponent(clientId)}&month=${encodeURIComponent(month)}`),
    /** Replaces the month's earnings FOR THE EMPLOYEES NAMED. An employee sent
     *  with no rows has theirs cleared; one not sent is untouched. */
    saveOneTimeEarnings: (body: { client_id: string; month: string; rows: unknown[] }) =>
      request("/api/payroll/one-time-earnings", { method: "PUT", body: JSON.stringify(body) }),
    oneTimeEarningDefaults: (kind: string, intervalMonths?: number | null) =>
      request(`/api/payroll/one-time-earnings/defaults?kind=${encodeURIComponent(kind)}`
        + (intervalMonths ? `&payment_interval_months=${intervalMonths}` : "")),
    /** Where every client of this firm stands on one payroll month.
     *
     *  The FIRM grain — every other payroll read answers for one client. Two
     *  queries server-side for the whole firm, and scoped to the caller's own
     *  clients rather than merely their firm, so an Executive assigned to four
     *  does not read the headcount and net pay of forty.
     */
    /** THE EXCEPTION INDEX — which employees will make a statutory output fail.
     *
     *  Every statutory file payroll builds already refuses the rows it cannot
     *  honestly carry (the ECR a member with no UAN, Form 24Q a deductee with
     *  no valid PAN under §206AA). Each refusal is correct and each lands at
     *  FILE-BUILD time — on the 7th, with the run finalised and the journal
     *  posted. The information was on the employee master all along.
     */
    payrollEmployeeExceptions: (financialYear?: string) =>
      request(`/api/payroll/employee-exceptions${financialYear ? `?financial_year=${encodeURIComponent(financialYear)}` : ""}`),
    payrollClientStates: (month?: string) =>
      request(`/api/payroll/client-states${month ? `?month=${encodeURIComponent(month)}` : ""}`),
    /** Switch payroll on or off for one client. PARTNER ONLY (migration 332).
     *
     *  Through the API and NOT PostgREST, and that is not a convention here —
     *  migration 332 revokes the column from `authenticated` outright, so a
     *  direct write is refused by PostgreSQL whatever the policies say. This is
     *  the only door, and rbac("payroll", "enable") is Partner-only behind it.
     */
    setPayrollEnabled: (body: { client_id: string; enabled: boolean; note?: string }) =>
      request("/api/payroll/enablement", { method: "PUT", body: JSON.stringify(body) }),
    savePayrollSettings: (body: { client_id: string; inputs_due_day?: number | null }) =>
      request("/api/payroll/attendance/settings", { method: "PUT", body: JSON.stringify(body) }),
    updateRunStatus: (runId: string, status: string) =>
      request(`/api/payroll/runs/${runId}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
    finalizeRun: (runId: string) =>
      request(`/api/payroll/runs/${runId}/finalize`, { method: "POST" }),
    disburseRun: (runId: string, body: { bank_account_id: string; payment_date?: string; payment_reference?: string }) =>
      request(`/api/payroll/runs/${runId}/disburse`, { method: "POST", body: JSON.stringify(body) }),
    /** Reverse a finalized or paid run. PARTNER ONLY.
     *
     *  The endpoint has existed and been complete since the payroll module was
     *  built — it reverses the disbursement journal, then the accrual, and
     *  reopens the run at 'review' — and NOTHING in the frontend called it. So
     *  every refusal that ends "Reverse the run first" (attendance, one-time
     *  earnings) pointed at something a CA had no way to do.
     */
    reverseRun: (runId: string) =>
      request(`/api/payroll/runs/${runId}/reverse`, { method: "POST" }),
    /** THE MONTH-END PACK, in one action.
     *
     *  downloadPayslip below is right for one employee asking for theirs. This
     *  is for the CA who has thirty and was clicking thirty times — and getting
     *  thirty files called `payslip-2026-08.pdf`, because that endpoint's
     *  filename carries the month and not the person.
     *
     *  Returns the employees whose payslip could not be rendered. The zip still
     *  holds the ones that worked — twenty-nine payslips are worth having — but
     *  a zip quietly one file short is a trap nobody counts their way out of,
     *  so the names come back and the caller has to say them.
     */
    downloadRunPayslips: async (runId: string, month?: string): Promise<string[]> => {
      const headers = await downloadFile(
        `/api/payroll/runs/${runId}/payslips.zip`,
        `payslips-${month ?? runId}.zip`);
      const problems = headers.get("X-Payslip-Problems");
      return problems ? problems.split("; ").filter(Boolean) : [];
    },
    /** The salary register as a file. It goes to the client, into the audit
     *  file, and beside the bank advice; the JSON endpoint could only be read
     *  on a screen and retyped. */
    downloadSalaryRegister: (clientId: string, month: string) =>
      downloadFile(
        `/api/payroll/reports/salary-register.csv?client_id=${encodeURIComponent(clientId)}&month=${encodeURIComponent(month)}`,
        `salary-register-${month}.csv`),
    /** PAY-27 — why is this month bigger than last month, and by whom. The
     *  BASELINE must be a released run and the month being looked at need not
     *  be; every reason, every threshold and the comparison itself are the
     *  server's. */
    monthOnMonth: (params: Record<string, string>) =>
      request<ApiResp<PayrollMonthOnMonth>>(
        `/api/payroll/reports/month-on-month?${new URLSearchParams(params)}`),
    /** PAY-27 — what each department cost. Gross and the EMPLOYER's own
     *  contributions apart, because they are two debits and two accounts
     *  (PAY-25); net pay is not cost and is deliberately absent. */
    departmentCost: (params: Record<string, string>) =>
      request<ApiResp<PayrollDepartmentCost>>(
        `/api/payroll/reports/department-cost?${new URLSearchParams(params)}`),
    /** PAY-27 — who this run pays and who it CANNOT. Prepare-only: the file
     *  below is uploaded to the firm's own bank by a person. */
    bankAdvice: (params: Record<string, string>) =>
      request<ApiResp<PayrollBankAdvice>>(
        `/api/payroll/reports/bank-advice?${new URLSearchParams(params)}`),
    /** The payment file itself. Only the payable rows: an employee who cannot
     *  be paid by transfer is named in `bankAdvice` above and is NOT a row
     *  with blanks, because some banks drop such a row silently and leave the
     *  CA believing everybody was paid. */
    downloadBankAdvice: (clientId: string, month: string) =>
      downloadFile(
        `/api/payroll/reports/bank-advice.csv?client_id=${encodeURIComponent(clientId)}&month=${encodeURIComponent(month)}`,
        `bank-advice-${month}.csv`),
    /** THE EMPLOYEE MASTER, AS ONE FILE AND ONE DECISION.
     *
     *  This replaces a browser-side validator (`buildEmployees`) and a loop
     *  that POSTed /employees once per row. Three problems with that, and the
     *  third is the one that hurt: business logic in the frontend; one
     *  Singapore-to-Mumbai round trip per employee; and IT ACCEPTED PART OF A
     *  FILE — thirty-one of fifty employees landed and the CA had no way to
     *  tell which nineteen were missing. Re-importing the corrected file then
     *  made a second copy of the thirty-one.
     *
     *  Migration 333's `employee_code` is what fixed that: a row whose code is
     *  already on file UPDATES rather than duplicates.
     *
     *  A refusal is a 422 whose message names every offending row. `dryRun`
     *  shows what a clean file would do before anything is written.
     */
    importEmployees: (clientId: string, rows: Record<string, string>[], dryRun = false) =>
      request<{ success: boolean; data: {
        ok: boolean; problems: string[];
        created?: number; updated?: number;
        would_create?: number; would_update?: number;
      } }>(`/api/payroll/employees/import`, {
        method: "POST",
        body: JSON.stringify({ client_id: clientId, rows, dry_run: dryRun }),
      }),
    /** THE 24Q WORKING PAPER, BUILT BY THE SERVER.
     *
     *  It used to be built in the browser — `generateTds24QData` on the payroll
     *  page — from whatever payslips that screen had loaded, and it disagreed
     *  with domain/payroll/form24q on the thing that matters: it wrote
     *  "PAN NOT AVAILABLE" into the PAN column and carried on. §206AA requires
     *  tax at the HIGHER of the specified rate or 20% where PAN is not
     *  furnished, so a row declaring tax deducted at slab rates against no PAN
     *  declares a SHORT deduction, and the employer carries it. It also never
     *  looked for a §192 challan and never checked the runs were finalised.
     *
     *  # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. A working paper, not a
     *  return; nothing here files anything.
     */
    download24QWorkingPaper: (clientId: string, financialYear: string, quarter: string) =>
      downloadFile(
        `/api/payroll/24q-source.csv?client_id=${encodeURIComponent(clientId)}`
        + `&financial_year=${encodeURIComponent(financialYear)}`
        + `&quarter=${encodeURIComponent(quarter)}`,
        `24Q-${financialYear}-${quarter}.csv`),
    downloadEmployeeImportTemplate: () =>
      downloadFile("/api/payroll/employees/import-template.csv",
                   "employee-import-template.csv"),
    downloadPayslip: (slipId: string, fallbackFilename = `payslip-${slipId}.pdf`) =>
      downloadFile(`/api/payroll/salary-slips/${slipId}/pdf`, fallbackFilename),

    /** The EPFO ECR and the ESIC return, BUILT BY THE SERVER.
     *
     *  Both used to be generated in the browser, and the browser's rules were
     *  the ones the backend had already fixed: NCP_DAYS hardcoded to 0, PAN in
     *  the MEMBER_ID field that wants a UAN, EPF wages on basic alone rather
     *  than basic + DA (EPF Act s.6), and ESI eligibility from the current
     *  month's gross instead of the Rule 50 contribution period. A statutory
     *  remittance file is the last place a second implementation belongs.
     *
     *  Neither returns a file. Both return the text WITH `problems` and
     *  `filable`, because a CA needs to see which members the file cannot
     *  carry BEFORE the portal rejects the batch — and a run that is not
     *  finalised is refused outright (409), since the ECR reports
     *  contributions actually made. */
    runEcr: (runId: string) => request(`/api/payroll/runs/${runId}/ecr`),
    runEsic: (runId: string) => request(`/api/payroll/runs/${runId}/esic`),

    /** THE HANDOFF (Track F, phase F3) — what a CA types, where, with the
     *  portal open in the next tab.
     *
     *  Of the seven steps between correct books and a closed obligation, six
     *  are ours; step 4 is this one and nothing did it. The CA used to open the
     *  register for the figures, Setup for the establishment code, Outputs for
     *  the file, three government portals and a spreadsheet to track which of
     *  them were done.
     *
     *  ASSEMBLED ON THE SERVER, and this client only renders it. Which
     *  obligations a month raises, in what order, with which warnings, is a
     *  statutory judgement: professional tax has no due date this product will
     *  state, ESI's period is not the wage month, and EPFO's blocking rule can
     *  make a correct file unacceptable today. See domain/payroll/handoff.py.
     *
     *  It carries NO credential field and NO OTP field, and both the domain
     *  tests and the endpoint tests assert that structurally. */
    runHandoff: (runId: string) =>
      request<ApiResp<StatutoryHandoff>>(`/api/payroll/runs/${runId}/handoff`),

    /** Record a remittance the CA made AT THE PORTAL, after they made it.
     *  Transmits nothing. Recording the payment updates the filing rather than
     *  adding a row: filing the return and paying the challan are two entries
     *  about one remittance. */
    recordRemittance: (clientId: string, body: {
      scheme: "esic" | "professional_tax"; wage_month: string;
      state?: string | null; status?: "submitted" | "paid";
      submitted_on?: string | null; paid_on?: string | null;
      challan_number?: string | null; challan_date?: string | null;
      amount_paise?: number; run_id?: string | null; notes?: string | null;
    }) => request<ApiResp<{ client_id: string; remittance: Remittance }>>(
      `/api/payroll/clients/${clientId}/remittances`,
      { method: "POST", body: JSON.stringify(body) }),

    /** Who ESIC has mapped, against who is in this month's file (Track F, F1).
     *
     *  ESIC's manual makes the upload ALL OR NOTHING — "successful transaction
     *  only when all the Employees' (who are currently mapped in the system)
     *  details are entered perfectly". A file missing one insured person is not
     *  partially imported; the whole thing is rejected, after the CA has
     *  assembled it and waited.
     *
     *  The list is PASTED TEXT, not a file. ESIC forbids uploading any sheet but
     *  the portal's own Excel 97-2003 template, and reading one would need
     *  xlrd/xlwt/xlutils — two without a release since 2017, one parsing an
     *  untrusted upload inside the service that holds every client's ledger.
     *  A list of insurance numbers is a list of numbers.
     *
     *  Nothing is stored: the list is compared and discarded. */
    esicMappedIpCheck: (runId: string, mappedIps: string) =>
      request<ApiResp<{ run_id: string; month: string;
                        reconciliation: EsicMappedIpCheck | null }>>(
        `/api/payroll/runs/${runId}/esic/mapped-ips`,
        { method: "POST", body: JSON.stringify({ mapped_ips: mappedIps }) }),

    /** THE MONTH-END LIST (Track F, phase F4). Every ESI / professional-tax
     *  remittance recorded as PAID with no journal entry tied to it, each with
     *  the entries that could be its payment.
     *
     *  The question it answers is the reason migration 365 carries a
     *  journal_entry_id at all: on the ledger, a statutory liability NOBODY HAS
     *  PAID and one that was PAID AND NEVER TIED BACK look identical — both sit
     *  uncleared on ESI Payable at year end.
     *
     *  Candidates are RANKED AND EXPLAINED on the server
     *  (domain/payroll/remittance_match.py). Each carries a grade — "exact" or
     *  "near" — and a sentence, never a score: a CA who paid two identical
     *  challans in one week has two exact candidates and is the only one who
     *  can say which is which. */
    remittanceReconciliation: (clientId: string) =>
      request<ApiResp<{ client_id: string; window_days: number;
                        unmatched: UnmatchedRemittance[] }>>(
        `/api/payroll/clients/${clientId}/remittance-reconciliation`),

    /** Tie a remittance to the journal entry that paid it. A LINK, never a
     *  posting: bank_posting_service already writes Dr liability / Cr Bank when
     *  the CA passes the bank statement line, and posting from here as well
     *  would debit the statutory liability twice. */
    linkRemittancePayment: (clientId: string, remittanceId: string,
                            journalEntryId: string) =>
      request<ApiResp<{ remittance_id: string; linked: boolean }>>(
        `/api/payroll/clients/${clientId}/remittances/${remittanceId}/payment`,
        { method: "PATCH",
          body: JSON.stringify({ journal_entry_id: journalEntryId }) }),

    /** Retract one recorded in error — a SOFT delete. The challan number, the
     *  date and the amount that left the bank are held nowhere else. */
    retractRemittance: (clientId: string, remittanceId: string) =>
      request<ApiResp<{ remittance_id: string; retracted: boolean }>>(
        `/api/payroll/clients/${clientId}/remittances/${remittanceId}`,
        { method: "DELETE" }),

    /** The revamped ECR (EPFO circulars 26-09-2025 and 08-10-2025) enforces
     *  MONTH-WISE SEQUENCE: October cannot be filed while September is pending.
     *  This is the client's queue — which wage months EPFO is still waiting
     *  for, oldest first, which is the order they must be filed in.
     *
     *  `note` is composed on the SERVER, in domain/payroll/ecr_sequence.py.
     *  Render it; do not rebuild the sentence here. It carries the limit that
     *  makes the list safe to read — only months run in PracticeSync are
     *  counted, and a month run elsewhere will still block the upload. */
    ecrSequence: (clientId: string) =>
      request(`/api/payroll/clients/${clientId}/ecr-sequence`),

    /** APPLY A NAMED STRUCTURE to a set of employees, from a date (PAY-11).
     *
     *  public.salary_structures has existed since migration 054 and nothing
     *  ever read it: a CA could create "Junior — 40/20", see it listed, and
     *  still key every employee's basic, HRA and DA in one at a time.
     *
     *  It writes a REVISION, not a link — so a structure applied from 1 October
     *  starts in October and does not restate September, which is posted to the
     *  ledger. `preview: true` computes and reports everything and writes
     *  nothing; the server refuses the whole request if it does not fit one
     *  employee, because half a roster on each scale is worse than neither.
     */
    applySalaryStructure: (structureId: string, body: {
      client_id: string; effective_from: string; reason?: string; preview?: boolean;
      assignments: { employee_id: string; monthly_gross_paise: number }[];
    }) =>
      request<{ success: boolean; data: ApplyStructureResult; error: string | null }>(
        `/api/payroll/salary-structures/${structureId}/apply`,
        { method: "POST", body: JSON.stringify(body) }),

    // ── The employee drawer (PAY-11) ──────────────────────────────────────
    //
    // Six finished capabilities that no screen reached. Each is a real
    // statutory computation living in apps/api; nothing below computes
    // anything, and the shapes are the router's own.

    /** What a leaver is owed. READ-ONLY — recording is a separate call,
     *  because settling ends employment, releases money, posts to the GL and
     *  fixes the employee's §17(1) for the year. */
    previewSettlement: (employeeId: string, body: SettlementInput) =>
      request<{ success: boolean; data: SettlementResult; error: string | null }>(
        `/api/payroll/employees/${employeeId}/settlement`,
        { method: "POST", body: JSON.stringify(body) }),

    /** Record it: store, withhold under §192, post to the ledger, close the
     *  employee. `payroll:finalize`, not `write`. */
    recordSettlement: (employeeId: string,
                       body: SettlementInput & { new_status?: string; payment_date?: string }) =>
      request<{ success: boolean; data: SettlementResult & { settlement_id?: string };
                error: string | null }>(
        `/api/payroll/employees/${employeeId}/settlement/record`,
        { method: "POST", body: JSON.stringify(body) }),

    listSalaryRevisions: (employeeId: string, clientId: string) =>
      request<{ success: boolean; data: { revisions: SalaryRevisionRow[] };
                error: string | null }>(
        `/api/payroll/employees/${employeeId}/salary-revisions`
        + `?client_id=${encodeURIComponent(clientId)}`),

    /** THE WHOLE COMPONENT SET as at a date, never a delta — deltas compose,
     *  and composing them across a backdated revision gives a different answer
     *  depending on the order they were entered. */
    addSalaryRevision: (employeeId: string, body: SalaryRevisionInput) =>
      request(`/api/payroll/employees/${employeeId}/salary-revisions`,
              { method: "POST", body: JSON.stringify(body) }),

    listEmployeeLoans: (employeeId: string, clientId: string) =>
      request<{ success: boolean; data: { loans: EmployeeLoanRow[] };
                error: string | null }>(
        `/api/payroll/employees/${employeeId}/loans`
        + `?client_id=${encodeURIComponent(clientId)}`),

    addEmployeeLoan: (employeeId: string, body: EmployeeLoanInput) =>
      request<{ success: boolean; data: { loan?: EmployeeLoanRow; notes?: string[] };
                error: string | null }>(
        `/api/payroll/employees/${employeeId}/loans`,
        { method: "POST", body: JSON.stringify(body) }),

    /** Rule 3 valuation. Computes only — recording it is the call below,
     *  because what Rule 3 says a benefit is worth and whether the firm
     *  accepts that valuation for the year are two decisions. */
    valuePerquisites: (employeeId: string, body: Record<string, unknown>) =>
      request<{ success: boolean; data: PerquisiteResult; error: string | null }>(
        `/api/payroll/employees/${employeeId}/perquisites/value`,
        { method: "POST", body: JSON.stringify(body) }),

    /** Replaces the YEAR'S SET wholesale rather than merging — a car returned
     *  in June must not stay valued for the full year. */
    recordPerquisites: (employeeId: string,
                        body: { client_id: string; fy: string; items: unknown[] }) =>
      request(`/api/payroll/employees/${employeeId}/perquisites`,
              { method: "PUT", body: JSON.stringify(body) }),

    /** §89(1) relief under Rule 21A(2). Refuses rather than guessing where the
     *  rate registry does not hold a year, or where no Form 10E was filed
     *  (the proviso to §89 with Rule 21AA). */
    arrearsRelief: (employeeId: string, body: ArrearsReliefInput) =>
      request<{ success: boolean; data: ArrearsReliefResult; error: string | null }>(
        `/api/payroll/employees/${employeeId}/arrears-relief`,
        { method: "POST", body: JSON.stringify(body) }),

    /** 24Q ANNEXURE II — THE YEAR-END DELIVERABLE, AND THE THING THAT MAKES
     *  FORM 16.
     *
     *  Not a Form 16 generator, deliberately: CBDT Notification 09/2019 makes
     *  Part B a TRACES download, so an employer who prints their own has
     *  issued nothing. TRACES builds Part B from exactly one input — this
     *  annexure, filed with Q4 — which is why it is the honest deliverable.
     *
     *  The endpoint has existed and finished since the payroll module was
     *  built and NO SCREEN CALLED IT (PAY-11). A CA closing a year had to do
     *  the annual salary detail somewhere else.
     */
    annexureII: (clientId: string, financialYear: string) =>
      request<{ success: boolean; data: AnnexureIIResponse; error: string | null }>(
        `/api/payroll/24q-annexure-ii?client_id=${encodeURIComponent(clientId)}`
        + `&financial_year=${encodeURIComponent(financialYear)}`),

    /** The same annexure as the file. Built on the SERVER — the column order
     *  and the §16 treatment are statutory, and a CSV assembled in the browser
     *  from the JSON above would be a second answer to "what is income under
     *  the head Salaries". */
    downloadAnnexureII: (clientId: string, financialYear: string) =>
      downloadFile(
        `/api/payroll/24q-annexure-ii.csv?client_id=${encodeURIComponent(clientId)}`
        + `&financial_year=${encodeURIComponent(financialYear)}`,
        `24Q-AnnexureII-${financialYear}.csv`),

    /** Record that a run's ECR was filed. This transmits NOTHING and files
     *  nothing: there is no EPFO API, so the product cannot observe a filing
     *  and can only be told about one, after a human did it on the portal.
     *  Without this the sequence never advances and every month stays
     *  outstanding for ever. */
    recordEcrFiled: (runId: string, body: {
      return_type: string; status: string;
      submitted_on?: string; approved_on?: string; trrn?: string;
    }) => request(`/api/payroll/runs/${runId}/ecr/filed`,
                  { method: "POST", body: JSON.stringify(body) }),

    // ── Employee portal provisioning ──────────────────────────────────────
    // The activation link is returned ONCE, here. Only its sha256 is stored,
    // so it cannot be fetched again — a caller that needs to re-send must
    // re-invite, which mints a fresh token and invalidates this one.
    invitePortal: (employeeId: string, email: string) =>
      request<ApiResp<{ employee_id: string; email: string;
                        token: string; activation_url: string }>>(
        `/api/payroll/employees/${employeeId}/portal-invite`,
        { method: "POST", body: JSON.stringify({ email }) }),
    revokePortal: (employeeId: string) =>
      request<ApiResp<{ employee_id: string; portal_enabled: boolean }>>(
        `/api/payroll/employees/${employeeId}/portal-revoke`, { method: "POST" }),
    portalStatus: (employeeId: string) =>
      request<ApiResp<{ employee_id: string; email: string | null;
                        portal_enabled: boolean; activated: boolean;
                        invite_pending: boolean; invited_at: string | null;
                        invite_expires_at: string | null;
                        activated_at: string | null }>>(
        `/api/payroll/employees/${employeeId}/portal-status`),

    // ── Employee income-tax declarations (§192, Rule 26C / Form 12BB) ──────
    // The `notices` on each row are the reason this list exists rather than a
    // plain table: they are where a CA sees who intimated the old regime and
    // may still need Form 10-IEA, who claimed something the new regime does
    // not allow, and whose proofs are outstanding with Q4 approaching.
    listDeclarations: (clientId: string, fy: string) =>
      request<ApiResp<{ declarations: DeclarationRow[] }>>(
        `/api/payroll/declarations?client_id=${encodeURIComponent(clientId)}` +
        `&fy=${encodeURIComponent(fy)}`),
    saveDeclaration: (body: unknown) =>
      request<ApiResp<{ declaration_id: string; problems: string[]; notices: string[] }>>(
        "/api/payroll/declarations", { method: "PUT", body: JSON.stringify(body) }),
    // PF, ESI and gratuity for a client's employees as at a month. Computed in
    // apps/api — the page used to carry its own TypeScript copies of all three,
    // which had drifted four ways (see the endpoint's docstring).
    statutoryPosition: (clientId: string, month: string) =>
      request<ApiResp<StatutorySummary>>(
        `/api/payroll/statutory-position?client_id=${encodeURIComponent(clientId)}` +
        `&month=${encodeURIComponent(month)}`),
    verifyDeclaration: (declarationId: string, body: unknown) =>
      request<ApiResp<{ declaration_id: string; problems: string[] }>>(
        `/api/payroll/declarations/${declarationId}/verify`,
        { method: "POST", body: JSON.stringify(body) }),
  },
  invoices: {
    downloadPdf: (id: string) => downloadFile(`/api/invoices/${id}/pdf`, `invoice-${id}.pdf`),
    runOverdueCheck: () => request("/api/invoices/run-overdue-check", { method: "POST" }),
  },
  timeEntries: {
    exportEntries: (params: { fmt: "csv" | "xlsx"; user_id?: string; client_id?: string; date_from?: string; date_to?: string }) => {
      const q = new URLSearchParams(
        Object.fromEntries(Object.entries(params).filter(([, v]) => v != null && v !== "")) as Record<string, string>
      ).toString();
      return downloadFile(`/api/time-entries/export?${q}`, `time-entries.${params.fmt}`);
    },
  },
  /** The CA practice's OWN profile — name, GSTIN, PAN, address.
   *
   *  It goes through the API rather than PostgREST because `public.firms`
   *  carries TWO columns for the GSTIN and both screens used to write the one
   *  no backend reader reads: the fee invoice then printed no supplier GSTIN
   *  (CGST Rule 46(a)) and the CGST/SGST-versus-IGST fallback put the whole tax
   *  on a LOCAL supply into IGST. The endpoint also runs the GSTIN CHECK DIGIT,
   *  which the column's own CHECK constraint cannot. `domain/firm/identity.py`
   *  is the authority; the served `gstin` is already resolved, so there is
   *  nothing here to choose between. */
  firm: {
    profile: () => request<ApiResp<FirmProfile>>("/api/firms/profile"),
    saveProfile: (body: Partial<FirmProfile>) =>
      request<ApiResp<FirmProfile>>("/api/firms/profile",
        { method: "PATCH", body: JSON.stringify(body) }),
  },
  onboarding: {
    /** Start a 10-step Product Bible Ch. 7 onboarding checklist for a client. */
    start: (body: { client_id: string; entity_type?: string; notes?: string }) =>
      request("/api/lifecycle/onboarding/checklist", { method: "POST", body: JSON.stringify(body) }),
    /** Get full onboarding progress for a specific checklist workflow. */
    get: (workflowId: string) =>
      request(`/api/lifecycle/onboarding/checklist/${workflowId}`),
    /** Update a single step in an onboarding checklist. */
    updateStep: (workflowId: string, stepNumber: number, data: { status: string; notes?: string }) =>
      request(`/api/lifecycle/onboarding/checklist/${workflowId}/step/${stepNumber}`, {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    /** Trigger go-live verification — completes the onboarding and activates the client. */
    complete: (workflowId: string) =>
      request(`/api/lifecycle/onboarding/checklist/${workflowId}/complete`, { method: "POST" }),
    /** List all active (non-completed) onboarding checklists for the firm. */
    listActive: (firmId?: string) =>
      request(`/api/lifecycle/onboarding/checklist/active${firmId ? `?firm_id=${firmId}` : ""}`),
  },
  workload: {
    capacityList: () => request("/api/workload/capacity"),
    setCapacity: (body: { user_id: string; weekly_capacity_hours: number; max_concurrent_tasks: number }) =>
      request("/api/workload/capacity", { method: "PUT", body: JSON.stringify(body) }),
    /* 3b-4. The FORWARD-looking half: `/api/workload` and
       `/api/intelligence/workload-insights` both describe today, and neither
       can say that the week of 8 December is four times an ordinary week. */
    capacityRisk: (weeksAhead = 13) =>
      request<ApiResp<CapacityRiskPayload>>(
        `/api/workload/capacity-risk?weeks_ahead=${weeksAhead}`),
  },
  /* 3b-2. Its own prefix rather than an /api/accounting/reports entry: that
     one serves the AS-3 cash flow STATEMENT (what happened), this is a
     projection (what is expected to). */
  cashFlowForecast: (clientId: string, months = 6) =>
    request<ApiResp<CashFlowForecastPayload>>(
      `/api/cash-flow-forecast?client_id=${encodeURIComponent(clientId)}&months=${months}`),

  intelligence: {
    /* Typed for the Insights screen (Phase 3a-5). The three client-facing
       reads narrow their rows to the caller's assigned book inside the router,
       each with its own comment saying why — every row NAMES its client. */
    complianceRisk: () =>
      request<ApiResp<ComplianceRiskPayload>>("/api/intelligence/compliance-risk"),
    relationshipHealth: () =>
      request<ApiResp<RelationshipHealthPayload>>("/api/intelligence/relationship-health"),
    recommendations: () =>
      request<ApiResp<RecommendationsPayload>>("/api/intelligence/recommendations"),
    /** The capacity engine's own judgements. Typed rather than `unknown`
     *  because one of them — the unassigned backlog — is the only thing on it
     *  that no other screen can say. */
    workloadInsights: () =>
      request<ApiResp<WorkloadInsightsPayload>>("/api/intelligence/workload-insights"),
    journalSuggestions: (client_id?: string) =>
      request(`/api/intelligence/journal-suggestions${client_id ? `?client_id=${client_id}` : ""}`),
    approveJournalSuggestion: (body: unknown) =>
      request("/api/intelligence/journal-suggestions/approve", { method: "POST", body: JSON.stringify(body) }),
  },
  taskExtras: {
    dependencies: (taskId: string) => request(`/api/tasks/${taskId}/dependencies`),
    addDependency: (taskId: string, dependsOnTaskId: string) =>
      request(`/api/tasks/${taskId}/dependencies`, { method: "POST", body: JSON.stringify({ depends_on_task_id: dependsOnTaskId }) }),
    removeDependency: (taskId: string, dependencyId: string) =>
      request(`/api/tasks/${taskId}/dependencies/${dependencyId}`, { method: "DELETE" }),
  },
  // Phase 10 — Workflow Automation Engine
  workflowEngine: {
    listTemplates: (params?: Record<string, string>) =>
      request(`/api/workflows/templates${params ? "?" + new URLSearchParams(params) : ""}`),
    getTemplate: (id: string) => request(`/api/workflows/templates/${id}`),
    createTemplate: (body: unknown) =>
      request("/api/workflows/templates", { method: "POST", body: JSON.stringify(body) }),
    updateTemplate: (id: string, body: unknown) =>
      request(`/api/workflows/templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    deleteTemplate: (id: string) =>
      request(`/api/workflows/templates/${id}`, { method: "DELETE" }),
    toggleTemplate: (id: string) =>
      request(`/api/workflows/templates/${id}/toggle`, { method: "POST" }),
    triggerTemplate: (id: string, body?: unknown) =>
      request(`/api/workflows/templates/${id}/trigger`, { method: "POST", body: JSON.stringify(body || {}) }),
    listInstances: (params?: Record<string, string>) =>
      request(`/api/workflows/instances${params ? "?" + new URLSearchParams(params) : ""}`),
    getInstance: (id: string) => request(`/api/workflows/instances/${id}`),
    cancelInstance: (id: string) =>
      request(`/api/workflows/instances/${id}/cancel`, { method: "POST" }),
    listApprovals: (params?: Record<string, string>) =>
      request(`/api/workflows/approvals${params ? "?" + new URLSearchParams(params) : ""}`),
    respondApproval: (id: string, body: { decision: string; response_notes?: string }) =>
      request(`/api/workflows/approvals/${id}/respond`, { method: "POST", body: JSON.stringify(body) }),
    listSchedules: (params?: Record<string, string>) =>
      request(`/api/workflows/schedules${params ? "?" + new URLSearchParams(params) : ""}`),
    createSchedule: (body: unknown) =>
      request("/api/workflows/schedules", { method: "POST", body: JSON.stringify(body) }),
    toggleSchedule: (id: string) =>
      request(`/api/workflows/schedules/${id}/toggle`, { method: "PATCH" }),
    deleteSchedule: (id: string) =>
      request(`/api/workflows/schedules/${id}`, { method: "DELETE" }),
    analytics: (params?: Record<string, string>) =>
      request(`/api/workflows/analytics${params ? "?" + new URLSearchParams(params) : ""}`),
    listFailures: (params?: Record<string, string>) =>
      request(`/api/workflows/failures${params ? "?" + new URLSearchParams(params) : ""}`),
    resolveFailure: (id: string) =>
      request(`/api/workflows/failures/${id}/resolve`, { method: "POST" }),
    executions: (params?: Record<string, string>) =>
      request(`/api/workflows/executions${params ? "?" + new URLSearchParams(params) : ""}`),
  },
  // Phase 13 — AI Memory & Intelligence
  memory: {
    getClientProfile: (clientId: string) =>
      request(`/api/memory/clients/${clientId}/profile`),
    computeClientProfile: (clientId: string) =>
      request(`/api/memory/clients/${clientId}/profile/compute`, { method: "POST" }),
    listProfiles: (params?: Record<string, string>) =>
      request("/api/memory/profiles", { params } as RequestInit),
    getFirmProfile: () =>
      request("/api/memory/firm/profile"),
    listTriggers: (params?: Record<string, string>) =>
      request(`/api/memory/triggers${params ? "?" + new URLSearchParams(params) : ""}`),
    acknowledgeTrigger: (id: string) =>
      request(`/api/memory/triggers/${id}/acknowledge`, { method: "POST" }),
    dismissTrigger: (id: string) =>
      request(`/api/memory/triggers/${id}/dismiss`, { method: "POST" }),
    detectClientTriggers: (clientId: string) =>
      request(`/api/memory/clients/${clientId}/detect`, { method: "POST" }),
    listAnomalies: (params?: Record<string, string>) =>
      request(`/api/memory/anomalies${params ? "?" + new URLSearchParams(params) : ""}`),
    updateAnomalyStatus: (id: string, status: string) =>
      request(`/api/memory/anomalies/${id}/status`, { method: "PATCH", body: JSON.stringify({ status }) }),
    listYearEndReports: () =>
      request("/api/memory/year-end-reports"),
    getYearEndReport: (clientId: string, fy: string) =>
      request(`/api/memory/year-end-reports/${clientId}/${fy}`),
    runPipeline: () =>
      request("/api/memory/pipeline/run", { method: "POST" }),
  },
  // Client Portal
  portal: {
    getDocumentRequests: (firmId: string, clientId: string) =>
      request(`/api/portal/document-requests?firm_id=${firmId}&client_id=${clientId}`),
    createDocumentRequest: (data: {
      firm_id: string;
      client_id: string;
      title: string;
      description?: string;
      due_date?: string;
      is_urgent?: boolean;
    }) =>
      request("/api/portal/document-requests", { method: "POST", body: JSON.stringify(data) }),
    completeDocumentRequest: (id: string) =>
      request(`/api/portal/document-requests/${id}/complete`, { method: "PUT" }),
    getMessages: (firmId: string, clientId: string) =>
      request(`/api/portal/messages?firm_id=${firmId}&client_id=${clientId}`),
    sendMessage: (data: {
      firm_id: string;
      client_id: string;
      text: string;
      from_ca?: boolean;
    }) =>
      request("/api/portal/messages", { method: "POST", body: JSON.stringify(data) }),
    getDues: (firmId: string, clientId: string) =>
      request(`/api/portal/dues?firm_id=${firmId}&client_id=${clientId}`),
    // Phase 4.5.1 — CA-side multi-contact management
    listContacts: (clientId: string) =>
      request<ApiResp<{ contacts: PortalContact[] }>>(`/api/portal/clients/${clientId}/contacts`),
    inviteContact: (clientId: string, body: { email: string; name?: string }) =>
      request<ApiResp<{ contact: PortalContact }>>(
        `/api/portal/clients/${clientId}/contacts`, { method: "POST", body: JSON.stringify(body) }),
    resendInvite: (contactId: string) =>
      request<ApiResp<{ contact: PortalContact }>>(`/api/portal/contacts/${contactId}/resend`, { method: "POST" }),
    deactivateContact: (contactId: string) =>
      request<ApiResp<{ contact: PortalContact }>>(`/api/portal/contacts/${contactId}/deactivate`, { method: "POST" }),
  },
  // Phase 4.5.1 — client-facing portal self surface (auth = the client's own
  // Supabase session, resolved server-side via get_current_portal_client).
  portalSelf: {
    // All client memberships for the signed-in identity (client switcher source).
    memberships: () => request("/api/portal/memberships"),
    // F22 fix: bind ONE client_portal_users invite by its single-use token.
    // Must be called before that client shows up in memberships().
    acceptInvite: (token: string) =>
      request<ApiResp<{ client_id: string; name?: string }>>(
        "/api/portal/accept-invite", { method: "POST", body: JSON.stringify({ token }) }),
    // The EMPLOYEE equivalent. A separate endpoint, not a variant of the one
    // above: an employee is neither firm staff nor a client contact, so it is
    // guarded by the JWT alone and the token is what authorises the bind.
    acceptEmployeeInvite: (token: string) =>
      request<ApiResp<{ employee_id: string; name?: string; client_id?: string }>>(
        "/api/portal/employee/accept-invite",
        { method: "POST", body: JSON.stringify({ token }) }),
    // me/dashboard select the active client explicitly via X-Portal-Client-Id when
    // the identity belongs to more than one client (no implicit switching).
    me: (clientId?: string) =>
      request("/api/portal/me", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    dashboard: (clientId?: string) =>
      request("/api/portal/dashboard", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    // Phase 4.5.2 — client-facing data surfaces. Each carries the active client
    // via X-Portal-Client-Id (explicit selection; no implicit switching). All
    // data is the firm↔client fee relationship + the client's compliance status.
    invoices: (clientId?: string) =>
      request("/api/portal/self/invoices", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    invoicePdf: (invoiceId: string, clientId?: string) =>
      downloadFile(`/api/portal/self/invoices/${invoiceId}/pdf`, `invoice-${invoiceId}.pdf`,
        clientId ? { "X-Portal-Client-Id": clientId } : undefined),
    dues: (clientId?: string) =>
      request("/api/portal/self/dues", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    statement: (clientId?: string, start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return request(`/api/portal/self/statement${qs ? `?${qs}` : ""}`,
        clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined);
    },
    statementPdf: (clientId?: string, start?: string, end?: string) => {
      const q = new URLSearchParams();
      if (start) q.set("start", start);
      if (end) q.set("end", end);
      const qs = q.toString();
      return downloadFile(`/api/portal/self/statement/pdf${qs ? `?${qs}` : ""}`, "statement.pdf",
        clientId ? { "X-Portal-Client-Id": clientId } : undefined);
    },
    reminders: (clientId?: string) =>
      request("/api/portal/self/reminders", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    compliance: (clientId?: string) =>
      request("/api/portal/self/compliance", clientId ? { headers: { "X-Portal-Client-Id": clientId } } : undefined),
    // Phase 4.6 — Pay Now: create/reuse a payment link for the client's own invoice.
    payInvoice: (invoiceId: string, clientId?: string) =>
      request(`/api/portal/self/invoices/${invoiceId}/pay`,
        { method: "POST", ...(clientId ? { headers: { "X-Portal-Client-Id": clientId } } : {}) }),
  },
  // Phase 4.6 — Online Payments (staff, accounting-gated). The gateway never does
  // accounting; receipts are created by the existing engine on a verified capture.
  payments: {
    createLink: (invoiceId: string) =>
      request("/api/payments/links", { method: "POST", body: JSON.stringify({ invoice_id: invoiceId }) }),
    listLinks: (invoiceId: string) => request(`/api/payments/links?invoice_id=${invoiceId}`),
    sendLink: (linkId: string) => request(`/api/payments/links/${linkId}/send`, { method: "POST" }),
    history: (invoiceId: string) => request(`/api/payments?invoice_id=${invoiceId}`),
  },
  // Phase 11 — AI Copilot Platform
  copilotV2: {
    listConversations: (params?: Record<string, string>) =>
      request(`/api/copilot/conversations${params ? "?" + new URLSearchParams(params) : ""}`),
    createConversation: (body: unknown) =>
      request("/api/copilot/conversations", { method: "POST", body: JSON.stringify(body) }),
    getConversation: (id: string) => request(`/api/copilot/conversations/${id}`),
    archiveConversation: (id: string) =>
      request(`/api/copilot/conversations/${id}/archive`, { method: "POST" }),
    sendMessage: (conversationId: string, body: unknown) =>
      request(`/api/copilot/conversations/${conversationId}/messages`, { method: "POST", body: JSON.stringify(body) }),
    rateMessage: (messageId: string, body: unknown) =>
      request(`/api/copilot/messages/${messageId}/feedback`, { method: "POST", body: JSON.stringify(body) }),
    quickChat: (body: unknown) =>
      request("/api/copilot/chat", { method: "POST", body: JSON.stringify(body) }),
    suggestions: (context_type?: string) =>
      request(`/api/copilot/suggestions${context_type ? `?context_type=${context_type}` : ""}`),
    clientIntelligence: (clientId: string) =>
      request(`/api/copilot/intelligence/client/${clientId}`),
    complianceIntelligence: () => request("/api/copilot/intelligence/compliance"),
    workflowIntelligence: () => request("/api/copilot/intelligence/workflows"),
    relationshipIntelligence: () => request("/api/copilot/intelligence/relationships"),
    executiveDashboard: () => request("/api/copilot/executive-dashboard"),
    listRecommendations: (params?: Record<string, string>) =>
      request(`/api/copilot/recommendations${params ? "?" + new URLSearchParams(params) : ""}`),
    actRecommendation: (id: string, body: unknown) =>
      request(`/api/copilot/recommendations/${id}/action`, { method: "POST", body: JSON.stringify(body) }),
    executeAction: (body: unknown) =>
      request("/api/copilot/actions", { method: "POST", body: JSON.stringify(body) }),
  },

  // ── Amendment v1.1 (Batch 7) — Practice / Revenue Operations / Knowledge ──
  // Thin fetch wrappers only. All computation (aging, GST, overdue, visibility)
  // is performed server-side; the frontend fetches + displays.
  practice: {
    get: () => request("/api/practice"),
    provision: () => request("/api/practice/provision", { method: "POST" }),
    /** Partner-only maintenance of the practice client's tax identity (PAN/GSTIN/state). */
    updateIdentity: (body: { pan?: string; gstin?: string; state?: string; state_code?: string }) =>
      request("/api/practice/identity", { method: "PATCH", body: JSON.stringify(body) }),
  },
  // Platform Admin (Super Admin) — cross-firm; gated server-side by the
  // platform_admins allowlist, completely separate from firm RBAC.
  platform: {
    me: () => request<ApiResp<{ is_platform_admin: boolean }>>("/api/platform/me"),
    stats: () => request<ApiResp<{ total_firms: number; active_firms: number; suspended_firms: number; total_users: number; total_clients: number }>>("/api/platform/stats"),
    firms: () => request<ApiResp<Array<{ id: string; name: string; created_at: string; users: number; clients: number; status: string }>>>("/api/platform/firms"),
    firm: (id: string) => request<ApiResp<{ id: string; name: string; email: string; created_at: string; status: string; users: number; clients: number }>>(`/api/platform/firms/${id}`),
    firmUsers: (id: string) => request<ApiResp<Array<{ name: string; email: string; role: string; status: string }>>>(`/api/platform/firms/${id}/users`),
    suspend: (id: string, reason: string) => request(`/api/platform/firms/${id}/suspend`, { method: "POST", body: JSON.stringify({ reason }) }),
    unsuspend: (id: string) => request(`/api/platform/firms/${id}/unsuspend`, { method: "POST" }),
    softDelete: (id: string) => request(`/api/platform/firms/${id}`, { method: "DELETE" }),
    /** PERMANENT hard delete — requires a fresh aal2 (MFA) token. Irreversible. */
    purge: (id: string) => request(`/api/platform/firms/${id}/permanent`, { method: "DELETE" }),
  },
  account: {
    /**
     * Bootstrap a brand-new firm + first Partner user. Runs server-side
     * (service-role) so it is not blocked by the firm-isolation RLS that forbids
     * a firm-less user from inserting a firms row. Seeds the master CoA and
     * provisions the internal client when a PAN is supplied.
     */
    createFirm: (body: {
      firm_name: string;
      firm_email: string;
      partner_name: string;
      pan?: string;
      gstin?: string;
      phone?: string;
      address?: string;
      city?: string;
      state?: string;
      entity_type?: string;
    }) => request<ApiResp<{ firm: { id: string; name: string } }>>(
      "/api/onboarding/firm",
      { method: "POST", body: JSON.stringify(body) },
    ),
    /** Idempotently seed the firm's canonical master CoA (backend = single source of truth). */
    seedCoa: () => request<ApiResp<{ seeded: number; skipped: boolean }>>(
      "/api/onboarding/seed-coa",
      { method: "POST" },
    ),
  },
  /**
   * Recurring journal templates (ACC-06). The screen used to keep these in
   * localStorage, work out the next due date in the browser, and post
   * nothing. Generating now raises a DRAFT manual journal through the one
   * posting kernel; nothing is ever posted unprompted.
   */
  recurringJournals: {
    list: (params?: { client_id?: string; status?: string }) => {
      const q = new URLSearchParams();
      if (params?.client_id) q.set("client_id", params.client_id);
      if (params?.status) q.set("status", params.status);
      const qs = q.toString();
      return request<ApiResp<RecurringJournalTemplate[]>>(
        `/api/recurring-journals${qs ? `?${qs}` : ""}`);
    },
    create: (body: unknown) =>
      request<ApiResp<RecurringJournalTemplate>>("/api/recurring-journals",
        { method: "POST", body: JSON.stringify(body) }),
    get: (id: string) =>
      request<ApiResp<RecurringJournalTemplate>>(`/api/recurring-journals/${id}`),
    update: (id: string, body: unknown) =>
      request<ApiResp<RecurringJournalTemplate>>(`/api/recurring-journals/${id}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    remove: (id: string) =>
      request<ApiResp<{ deleted: boolean; id: string }>>(`/api/recurring-journals/${id}`,
        { method: "DELETE" }),
    history: (id: string) =>
      request<ApiResp<RecurringJournalRun[]>>(`/api/recurring-journals/${id}/history`),
    /** The next few dates this template will generate on. Writes nothing. */
    preview: (id: string, count = 5) =>
      request<ApiResp<{ template_id: string; occurrences: string[] }>>(
        `/api/recurring-journals/${id}/preview?count=${count}`),
    /** One occurrence, on demand. Idempotent — a second call returns the first draft. */
    generate: (id: string, occurrence?: string) =>
      request<ApiResp<{ created: boolean; journal_entry_id: string | null; reason: string | null }>>(
        `/api/recurring-journals/${id}/generate${occurrence ? `?occurrence=${occurrence}` : ""}`,
        { method: "POST" }),
    /** Every due template. Idempotent; the daily sweep calls the same service. */
    runDue: (clientId?: string) =>
      request<ApiResp<{ generated_count: number; skipped_count: number; failed_count: number;
                        failed: { template_id: string; occurrence: string; error: string }[] }>>(
        `/api/recurring-journals/run${clientId ? `?client_id=${clientId}` : ""}`,
        { method: "POST" }),
  },
  billing: {
    listSchedules: (activeOnly?: boolean) =>
      request<ApiResp<BillingSchedule[]>>(
        `/api/billing/schedules${activeOnly ? "?active_only=true" : ""}`),
    createSchedule: (body: unknown) =>
      request<ApiResp<BillingSchedule>>("/api/billing/schedules",
        { method: "POST", body: JSON.stringify(body) }),
    /**
     * Change a schedule's fee, cadence, service or active flag. There was no
     * update path at all until ACC-06 — a retainer whose fee went up could
     * only be recorded as a SECOND schedule, which then bills twice.
     * `client_id` is deliberately not updatable.
     */
    updateSchedule: (scheduleId: string, body: unknown) =>
      request<ApiResp<BillingSchedule>>(`/api/billing/schedules/${scheduleId}`, {
        method: "PATCH", body: JSON.stringify(body),
      }),
    /**
     * The practice's OWN service catalogue — what a retainer can bill for.
     * `billing_schedules.service_id` is mandatory (migration 206) and the
     * catalogue is client-owned, so the server resolves the firm's internal
     * client and answers from that one. `internal_client_id: null` means the
     * practice client is not provisioned, which is what `generate` 409s on.
     */
    serviceOptions: () => request<ApiResp<{
      internal_client_id: string | null;
      services: { id: string; name: string; hsn_sac: string | null;
                  default_rate_paise: number | null; gst_rate_bps: number | null }[];
    }>>("/api/billing/service-options"),
    previewRun: (asOf?: string) =>
      request(`/api/billing/preview-run${asOf ? `?as_of=${asOf}` : ""}`, { method: "POST" }),
    generate: (scheduleId: string) =>
      request<ApiResp<BillingGenerateResult>>(
        `/api/billing/schedules/${scheduleId}/generate`, { method: "POST" }),
    run: () => request("/api/billing/run", { method: "POST" }),
    arAging: () => request("/api/billing/ar-aging"),
    dashboard: (params?: Record<string, string>) =>
      request(`/api/billing/collections/dashboard${params ? "?" + new URLSearchParams(params) : ""}`),
    sweep: () => request("/api/billing/collections/sweep", { method: "POST" }),
    // Flags the practice's OWN overdue fee invoices for internal follow-up. It
    // emails nobody — the customer-facing reminder is salesInvoices remind().
    // Named `sendReminders` against `/collections/send-reminders` until
    // 18-09-2026, when both were found to send nothing (migration 405).
    flagOverdueForFollowup: () =>
      request("/api/billing/collections/flag-followups", { method: "POST" }),
    unbilledWork: (clientId?: string) =>
      request(`/api/billing/unbilled-work${clientId ? `?client_id=${clientId}` : ""}`),
    listCostRates: () => request("/api/billing/staff-cost-rates"),
    setCostRate: (userId: string, costRatePaise: number | null) =>
      request(`/api/billing/staff-cost-rates/${userId}`, {
        method: "PUT", body: JSON.stringify({ cost_rate_paise: costRatePaise }),
      }),
    // Fee Billing (apps/web/app/billing/page.tsx) receipts — only marks the
    // invoice Paid once cumulative receipts cover its total.
    recordFeeReceipt: (invoiceId: string, data: unknown) =>
      request(`/api/billing/fee-invoices/${invoiceId}/receipts`, {
        method: "POST", body: JSON.stringify(data),
      }),
  },
  salesInvoices: {
    list: (clientId: string, params?: Record<string, string>) =>
      request(`/api/sales-invoices/?client_id=${clientId}${params ? "&" + new URLSearchParams(params) : ""}`),
    get: (id: string) => request(`/api/sales-invoices/${id}`),
    issue: (id: string) => request(`/api/sales-invoices/${id}/issue`, { method: "POST" }),
    unposted: (clientId?: string) =>
      request(`/api/sales-invoices/maintenance/unposted${clientId ? `?client_id=${clientId}` : ""}`),
    downloadPdf: (id: string, invoiceNo?: string) =>
      downloadFile(`/api/sales-invoices/${id}/pdf`, `invoice-${invoiceNo ?? id}.pdf`),
    send: (id: string, toEmail?: string) =>
      request(`/api/sales-invoices/${id}/send`, { method: "POST", body: JSON.stringify({ to_email: toEmail ?? null }) }),
    resend: (id: string, toEmail?: string) =>
      request(`/api/sales-invoices/${id}/resend`, { method: "POST", body: JSON.stringify({ to_email: toEmail ?? null }) }),
    deliveries: (id: string) => request(`/api/sales-invoices/${id}/deliveries`),
  },
  hsn: {
    // Smart HSN/SAC lookup — the firm's own library + firm history. Never
    // reads a Caflow-shipped master (HSN/SAC redesign). See routers/hsn.py.
    search: (q: string, opts?: { client_id?: string; type?: string; limit?: number }) => {
      const params = new URLSearchParams({ q });
      if (opts?.client_id) params.set("client_id", opts.client_id);
      if (opts?.type) params.set("type", opts.type);
      if (opts?.limit) params.set("limit", String(opts.limit));
      return request(`/api/hsn/search?${params.toString()}`);
    },
  },
  serviceCatalogue: {
    // Product & Service master (goods + services) — client-owned
    // (migration 182: "Client B must never inherit Client A's products").
    // hsn_sac must be a code from the firm-wide firmHsnLibrary. See
    // routers/service_catalogue.py.
    list: (clientId: string, opts?: { q?: string; include_archived?: boolean; limit?: number }) => {
      const p = new URLSearchParams({ client_id: clientId });
      if (opts?.q) p.set("q", opts.q);
      if (opts?.include_archived) p.set("include_archived", "true");
      if (opts?.limit) p.set("limit", String(opts.limit));
      return request(`/api/service-catalogue/?${p.toString()}`);
    },
    create: (body: unknown) =>
      request("/api/service-catalogue/", { method: "POST", body: JSON.stringify(body) }),
    // One request for a whole CSV import instead of one POST per row.
    // openingBalanceDate is ONE "as of" date for the whole batch (an
    // opening-stock import is a single conversion event, not N independent
    // ones) — omit to let the backend default to each row's client's
    // financial-year start.
    bulkCreate: (services: unknown[], openingBalanceDate?: string) =>
      request("/api/service-catalogue/bulk", {
        method: "POST",
        body: JSON.stringify({ services, opening_balance_date: openingBalanceDate || undefined }),
      }),
    update: (id: string, body: unknown) =>
      request(`/api/service-catalogue/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    // Only succeeds when the item has never been picked into a transaction
    // line (use_count === 0) — the backend rejects (success:false) otherwise
    // with a message pointing at Archive instead. See routers/service_catalogue.py.
    delete: (id: string) =>
      request(`/api/service-catalogue/${id}`, { method: "DELETE" }),
    recordUsed: (id: string) =>
      request(`/api/service-catalogue/${id}/used`, { method: "POST" }),
  },
  firmHsnLibrary: {
    // The firm's own CA-owned, CA-curated HSN/SAC codes — the only source
    // Products/Services and invoice lines select from. Caflow ships no
    // shared master here. See routers/firm_hsn_library.py.
    list: (opts?: { q?: string; hsn_type?: string; include_archived?: boolean; limit?: number }) => {
      const p = new URLSearchParams();
      if (opts?.q) p.set("q", opts.q);
      if (opts?.hsn_type) p.set("hsn_type", opts.hsn_type);
      if (opts?.include_archived) p.set("include_archived", "true");
      if (opts?.limit) p.set("limit", String(opts.limit));
      const qs = p.toString();
      return request(`/api/firm-hsn-library/${qs ? `?${qs}` : ""}`);
    },
    add: (body: unknown) =>
      request("/api/firm-hsn-library/", { method: "POST", body: JSON.stringify(body) }),
    // One request for a whole CSV import instead of one POST per row.
    bulkAdd: (codes: unknown[]) =>
      request("/api/firm-hsn-library/bulk", { method: "POST", body: JSON.stringify({ codes }) }),
    update: (id: string, body: unknown) =>
      request(`/api/firm-hsn-library/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    retire: (id: string) =>
      request(`/api/firm-hsn-library/${id}`, { method: "DELETE" }),
    // Permanent delete — blocked server-side if the code is still referenced
    // anywhere (Product/Service catalogue, any invoice/note/bill line).
    purge: (id: string) =>
      request(`/api/firm-hsn-library/${id}/purge`, { method: "DELETE" }),
    bulkPurge: (ids: string[]) =>
      request("/api/firm-hsn-library/bulk-delete", { method: "POST", body: JSON.stringify({ ids }) }),
  },
  firmHsnRateHistory: {
    // CA-entered, validity-dated GST rate versions per library code
    // (Decision D: mechanism only, never a Caflow-authoritative rate).
    // See routers/firm_hsn_rate_history.py.
    list: (firmHsnLibraryId: string) =>
      request(`/api/firm-hsn-rate-history/?firm_hsn_library_id=${encodeURIComponent(firmHsnLibraryId)}`),
    resolve: (firmHsnLibraryId: string, asOf: string) =>
      request(
        `/api/firm-hsn-rate-history/resolve?firm_hsn_library_id=${encodeURIComponent(firmHsnLibraryId)}&as_of=${encodeURIComponent(asOf)}`,
      ),
    add: (body: unknown) =>
      request("/api/firm-hsn-rate-history/", { method: "POST", body: JSON.stringify(body) }),
    remove: (id: string) =>
      request(`/api/firm-hsn-rate-history/${id}`, { method: "DELETE" }),
  },
  receipts: {
    create: (body: unknown) =>
      request("/api/receipts/", { method: "POST", body: JSON.stringify(body) }),

    /** APPLY AN ADVANCE TO INVOICES (SALES-14).
     *
     *  The endpoint has existed and been correct since task H3 — it reverses
     *  this receipt's prior allocations, re-validates each new one against the
     *  invoice's LIVE outstanding, re-applies, and rewrites
     *  `receipts.unallocated_paise` — and no screen called it. A customer who
     *  paid in advance had money in the books that could never be applied to
     *  the invoice it was for, from anywhere in the product.
     *
     *  It REPLACES the receipt's whole allocation set; send every line, not
     *  just the new one.
     */
    allocate: (receiptId: string, allocations: {
      sales_invoice_id: string; allocated_paise: number;
    }[]) =>
      request<{ success: boolean; data: { receipt_id: string; unallocated_paise?: number };
                error: string | null }>(
        `/api/receipts/${receiptId}/allocate`,
        { method: "PATCH", body: JSON.stringify({ allocations }) }),
  },
  purchasePayments: {
    /** APPLY A STRANDED VENDOR ADVANCE TO BILLS — the AP mirror of SALES-14.
     *
     *  `PATCH /api/purchase-payments/{id}/allocate` was written at the same
     *  time as the AR one — `update_allocations_core`'s own docstring calls
     *  itself "the AP mirror of receipts.py" — and no screen called it either.
     *  It exists for two cases the service names: an advance left over by a
     *  bank-match settlement that exceeded the bills it was told about, and a
     *  payment recorded before the bill it is meant for existed. Neither could
     *  be resolved anywhere in the product.
     *
     *  It REPLACES the payment's whole allocation set; send every line, not
     *  just the new one. The server reverses the prior allocations first, so a
     *  bill this payment already cleared still has room for it.
     */
    allocate: (paymentId: string, allocations: {
      purchase_bill_id: string; allocated_paise: number;
    }[]) =>
      request<{ success: boolean; data: { payment_id: string; unallocated_paise?: number };
                error: string | null }>(
        `/api/purchase-payments/${paymentId}/allocate`,
        { method: "PATCH", body: JSON.stringify({ allocations }) }),
  },
  knowledge: {
    listArticles: (params?: Record<string, string>) =>
      request(`/api/knowledge/articles${params ? "?" + new URLSearchParams(params) : ""}`),
    createArticle: (body: unknown) =>
      request("/api/knowledge/articles", { method: "POST", body: JSON.stringify(body) }),
    getArticle: (id: string) => request(`/api/knowledge/articles/${id}`),
    listVersions: (id: string) => request(`/api/knowledge/articles/${id}/versions`),
    editArticle: (id: string, content: string) =>
      request(`/api/knowledge/articles/${id}/versions`, { method: "POST", body: JSON.stringify({ content }) }),
    restoreVersion: (id: string, version: number) =>
      request(`/api/knowledge/articles/${id}/restore/${version}`, { method: "POST" }),
    archiveArticle: (id: string) =>
      request(`/api/knowledge/articles/${id}/archive`, { method: "POST" }),
    clientArticles: (clientId: string, query?: string) =>
      request(`/api/clients/${clientId}/knowledge${query ? `?query=${encodeURIComponent(query)}` : ""}`),
  },
  instructions: {
    list: (clientId: string) => request(`/api/clients/${clientId}/instructions`),
    create: (clientId: string, body: unknown) =>
      request(`/api/clients/${clientId}/instructions`, { method: "POST", body: JSON.stringify(body) }),
    update: (clientId: string, id: string, body: unknown) =>
      request(`/api/clients/${clientId}/instructions/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    archive: (clientId: string, id: string) =>
      request(`/api/clients/${clientId}/instructions/${id}/archive`, { method: "POST" }),
  },
  // M2: authorization-scoped global search (server enforces client assignment).
  search: (q: string) =>
    request(`/api/search?q=${encodeURIComponent(q)}`) as Promise<
      ApiResp<{ results: { id: string; category: string; title: string; subtitle?: string; href: string }[] }>
    >,
  // M3: client-assignment administration (Partner writes; Manager+ reads).
  assignments: {
    listForUser: (userId: string) =>
      request(`/api/assignments/users/${userId}`) as Promise<ApiResp<{ user_id: string; client_ids: string[] }>>,
    listForClient: (clientId: string) =>
      request(`/api/assignments/clients/${clientId}`) as Promise<ApiResp<{ client_id: string; user_ids: string[] }>>,
    create: (user_id: string, client_id: string) =>
      request("/api/assignments", { method: "POST", body: JSON.stringify({ user_id, client_id }) }),
    bulkCreate: (user_id: string, client_ids: string[]) =>
      request("/api/assignments/bulk", { method: "POST", body: JSON.stringify({ user_id, client_ids }) }),
    remove: (user_id: string, client_id: string) =>
      request(`/api/assignments?user_id=${encodeURIComponent(user_id)}&client_id=${encodeURIComponent(client_id)}`,
              { method: "DELETE" }),
  },
  // M4: governance approval workflows (maker-checker). Executive+ requests;
  // Partner approves/rejects; Manager+ reads.
  approvals: {
    list: (status?: string) =>
      request(`/api/approvals${status ? `?status=${status}` : ""}`) as Promise<
        ApiResp<{ requests: ApprovalRequest[] }>
      >,
    get: (id: string) => request(`/api/approvals/${id}`) as Promise<ApiResp<ApprovalRequest>>,
    create: (request_type: string, payload: Record<string, unknown>) =>
      request("/api/approvals", { method: "POST", body: JSON.stringify({ request_type, payload }) }),
    approve: (id: string) => request(`/api/approvals/${id}/approve`, { method: "POST" }),
    reject: (id: string, reason?: string) =>
      request(`/api/approvals/${id}/reject`, { method: "POST", body: JSON.stringify({ reason }) }),
    cancel: (id: string) => request(`/api/approvals/${id}/cancel`, { method: "POST" }),
  },
  // Module 9.0/M1: authoritative, append-only audit trail (Partner-only read).
  // Backed by the audit_log table, written server-side by audit_service.log_event
  // across every sensitive mutation (journals, invoices, compliance, clients,
  // users/roles, year-end, GST/TDS, platform actions, …).
  /** The Rule 3(1) edit log, queried.
   *
   *  Every filter is applied server-side and the log is paged with a cursor.
   *  What this replaced returned the most recent 200 rows firm-wide with no
   *  date range and no paging, and the screen filtered those 200 in the
   *  browser — so "show me April" showed whatever fell inside the last 200
   *  events. Dates are IST dates; the server converts the bounds.
   */
  audit: {
    list: (params?: {
      entity_type?: string; entity_id?: string; actor_id?: string;
      action?: string; date_from?: string; date_to?: string;
      cursor?: string; limit?: number;
    }) => {
      const q = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return request(`/api/audit${q ? `?${q}` : ""}`) as Promise<ApiResp<AuditPage>>;
    },
    /** Everything that ever happened to ONE row.
     *
     *  For a journal entry pass "journal_entry,journal_line": migration 266
     *  keys a LINE's audit row to its parent entry id, and an entry's history
     *  that omits its lines omits the amounts. */
    entityHistory: (entityType: string, entityId: string,
                    params?: { cursor?: string; limit?: number }) => {
      const q = new URLSearchParams(
        Object.entries(params ?? {})
          .filter(([, v]) => v != null && v !== "")
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      return request(
        `/api/audit/entity/${encodeURIComponent(entityType)}/` +
        `${encodeURIComponent(entityId)}${q ? `?${q}` : ""}`,
      ) as Promise<ApiResp<AuditPage>>;
    },
  },
  // "Verify Books" (task #244) — on-demand books-integrity check, mirroring
  // QuickBooks' Verify/Rebuild. Same engine as the nightly scheduled sweep
  // (services/reconciliation_service.py); this just triggers it live.
  reconciliation: {
    verify: (client_id: string) =>
      request(`/api/reconciliation/verify`, {
        method: "POST", body: JSON.stringify({ client_id }),
      }) as Promise<ApiResp<ReconciliationRunResult>>,
    listRuns: (client_id: string, limit = 20) =>
      request(`/api/reconciliation/runs?client_id=${client_id}&limit=${limit}`) as Promise<
        ApiResp<{ runs: ReconciliationRun[] }>
      >,
    getRun: (run_id: string) =>
      request(`/api/reconciliation/runs/${run_id}`) as Promise<
        ApiResp<{ run: ReconciliationRun; findings: ReconciliationFinding[] }>
      >,
    resolveFinding: (finding_id: string, resolution_note?: string) =>
      request(`/api/reconciliation/findings/${finding_id}/resolve`, {
        method: "POST", body: JSON.stringify({ resolution_note }),
      }) as Promise<ApiResp<{ finding: ReconciliationFinding }>>,
    checks: () =>
      request(`/api/reconciliation/checks`) as Promise<ApiResp<ReconciliationCheckCatalogue>>,
  },
  // Firm Branding & Document Customization
  branding: {
    get: () => request("/api/settings/branding"),
    update: (body: unknown) =>
      request("/api/settings/branding", { method: "PUT", body: JSON.stringify(body) }),
    uploadLogo: async (file: File) => {
      const { data: { session } } = await supabase.auth.getSession();
      const token = session?.access_token;
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`${BASE_URL}/api/settings/branding/logo`, {
        method: "POST",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      });
      if (!res.ok) throw new Error(`API error ${res.status}: ${await res.text()}`);
      return res.json();
    },
  },
  invoiceSettings: {
    get: () => request("/api/settings/invoice-settings"),
    update: (body: unknown) =>
      request("/api/settings/invoice-settings", { method: "PUT", body: JSON.stringify(body) }),
  },
  invoiceTemplates: {
    list: () => request("/api/settings/invoice-templates"),
    create: (body: unknown) =>
      request("/api/settings/invoice-templates", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) =>
      request(`/api/settings/invoice-templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request(`/api/settings/invoice-templates/${id}`, { method: "DELETE" }),
    setDefault: (id: string) =>
      request(`/api/settings/invoice-templates/${id}/set-default`, { method: "POST" }),
  },
  emailTemplates: {
    list: () => request("/api/settings/email-templates"),
    upsert: (body: unknown) =>
      request("/api/settings/email-templates", { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, body: unknown) =>
      request(`/api/settings/email-templates/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    delete: (id: string) =>
      request(`/api/settings/email-templates/${id}`, { method: "DELETE" }),
  },
  // M6: identity administration (audited, server-side; Partner-only writes).
  // The unified transaction feed replacing the `transactions` table migration
  // 139 dropped. Guarded by accounting:read server-side — the same permission
  // the sales-invoice and purchase-bill list endpoints use, so this is not a
  // looser route to the same rows.
  /**
   * Per-document ageing — the operational view behind the Schedule III note.
   * These endpoints have existed since migration 278 made outstanding_paise a
   * generated column (so the query returns what is OWED rather than everything
   * ever billed) and until now nothing in this app called them. Guarded by
   * accounting:read server-side, the same permission the invoice and bill list
   * endpoints use.
   *
   * Their buckets are OPERATIONAL (not due / 0-30 / 31-60 / 61-90 / 90+ days),
   * deliberately not the statutory ones — a collections view and a balance-sheet
   * note answer different questions.
   */
  ageing: {
    receivables: (clientId: string, asOf?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (asOf) q.set("as_of", asOf);
      return request<ApiResp<AgeingDetail<"invoices">>>(`/api/customers/ar-aging?${q}`);
    },
    payables: (clientId: string, asOf?: string) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (asOf) q.set("as_of", asOf);
      return request<ApiResp<AgeingDetail<"bills">>>(`/api/vendors/ap-aging?${q}`);
    },
  },

  /** THE supplier master. `public.suppliers` (migration 030) looked like a
   *  second one and was written only by /accounting/suppliers; migration 378
   *  retired it. Every purchase path — bill creation, TDS withholding, AP
   *  ageing, the Schedule III payables note, GSTR-2B matching, s.43B(h) —
   *  reads `vendors`, so a TDS section recorded anywhere else withholds nothing
   *  and s.40(a)(ia) disallows the whole expenditure. PUR-16. */
  customers: {
    /** The client's customers. `/api/customers/` has served this since the
     *  first sales work; the frontend reached it over PostgREST instead, which
     *  is why there was no helper here. */
    list: (clientId: string, includeInactive = false) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (includeInactive) q.set("include_inactive", "true");
      return request<ApiResp<{ id: string; name: string }[]>>(`/api/customers/?${q}`);
    },
  },

  vendors: {
    list: (clientId: string, includeInactive = false) => {
      const q = new URLSearchParams({ client_id: clientId });
      if (includeInactive) q.set("include_inactive", "true");
      return request<ApiResp<Vendor[]>>(`/api/vendors/?${q}`);
    },
    create: (body: VendorWrite & { client_id: string }) =>
      request<ApiResp<Vendor & { duplicate?: boolean }>>("/api/vendors/",
        { method: "POST", body: JSON.stringify(body) }),
    /** PATCH. NOTE: the server drops nulls (`model_dump(exclude_none=True)`),
     *  so an optional field cannot be CLEARED back to unset through here — a
     *  pre-existing property of every optional vendor field, not of this one. */
    update: (id: string, body: VendorWrite) =>
      request<ApiResp<Vendor>>(`/api/vendors/${id}`,
        { method: "PATCH", body: JSON.stringify(body) }),
  },

  /** One month's Invoice Furnishing Facility — CGST Rule 59(2), GST-11.
   *
   *  `period` is a CALENDAR MONTH (MMYYYY) and never the return period: a
   *  QRMP client's GSTR-1 period is the QUARTER, and the whole point of this
   *  facility is to furnish one month of it early. */
  iff: {
    compute: (clientId: string, period: string, gstin?: string) => {
      const q = new URLSearchParams({ client_id: clientId, period });
      if (gstin) q.set("gstin", gstin);
      return request<ApiResp<IffWorking>>(`/api/gst-workspace/iff/compute?${q}`);
    },
  },

  /** The annual return's working (GST-10). */
  gstr9: {
    compute: (clientId: string, financialYear: string, gstin?: string) => {
      const q = new URLSearchParams({ client_id: clientId,
                                      financial_year: financialYear });
      if (gstin) q.set("gstin", gstin);
      return request<ApiResp<GSTR9Working>>(`/api/gst-workspace/gstr9/compute?${q}`);
    },
  },

  /** The bill-wise breakup of a client's opening balances (ACC-14). */
  /** PUR-25 — purchase order, goods receipt, three-way match. */
  purchaseCycle: {
    vocabulary: () =>
      request<ApiResp<PurchaseCycleVocabulary>>("/api/purchase-cycle/vocabulary"),
    orders: (clientId: string, onlyOpen = false) =>
      request<ApiResp<PurchaseOrder[]>>(
        `/api/purchase-cycle/orders?client_id=${encodeURIComponent(clientId)}`
        + `&only_open=${onlyOpen ? "true" : "false"}`),
    orderLines: (id: string, clientId: string) =>
      request<ApiResp<Record<string, unknown>[]>>(
        `/api/purchase-cycle/orders/${id}/lines`
        + `?client_id=${encodeURIComponent(clientId)}`),
    orderPosition: (id: string, clientId: string) =>
      request<ApiResp<PurchaseOrderPosition>>(
        `/api/purchase-cycle/orders/${id}/position`
        + `?client_id=${encodeURIComponent(clientId)}`),
    createOrder: (body: Record<string, unknown>) =>
      request<ApiResp<PurchaseOrder>>("/api/purchase-cycle/orders",
        { method: "POST", body: JSON.stringify(body) }),
    updateOrder: (id: string, clientId: string, body: Record<string, unknown>) =>
      request<ApiResp<PurchaseOrder>>(
        `/api/purchase-cycle/orders/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    receipts: (clientId: string) =>
      request<ApiResp<GoodsReceipt[]>>(
        `/api/purchase-cycle/receipts?client_id=${encodeURIComponent(clientId)}`),
    receiptLines: (id: string, clientId: string) =>
      request<ApiResp<Record<string, unknown>[]>>(
        `/api/purchase-cycle/receipts/${id}/lines`
        + `?client_id=${encodeURIComponent(clientId)}`),
    createReceipt: (body: Record<string, unknown>) =>
      request<ApiResp<GoodsReceipt>>("/api/purchase-cycle/receipts",
        { method: "POST", body: JSON.stringify(body) }),
    updateReceipt: (id: string, clientId: string, body: Record<string, unknown>) =>
      request<ApiResp<GoodsReceipt>>(
        `/api/purchase-cycle/receipts/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    matchBill: (billId: string, clientId: string) =>
      request<ApiResp<ThreeWayMatch>>(
        `/api/purchase-cycle/bills/${billId}/match`
        + `?client_id=${encodeURIComponent(clientId)}`),
  },

  /** SALES-21 — quotation, proforma invoice, sales order, Rule 55 challan. */
  salesCycle: {
    vocabulary: () =>
      request<ApiResp<SalesCycleVocabulary>>("/api/sales-cycle/vocabulary"),
    quotations: (clientId: string, kind?: string) =>
      request<ApiResp<SalesQuotation[]>>(
        `/api/sales-cycle/quotations?client_id=${encodeURIComponent(clientId)}`
        + (kind ? `&kind=${encodeURIComponent(kind)}` : "")),
    quotationLines: (id: string, clientId: string) =>
      request<ApiResp<Record<string, unknown>[]>>(
        `/api/sales-cycle/quotations/${id}/lines`
        + `?client_id=${encodeURIComponent(clientId)}`),
    createQuotation: (body: Record<string, unknown>) =>
      request<ApiResp<SalesQuotation>>("/api/sales-cycle/quotations",
        { method: "POST", body: JSON.stringify(body) }),
    updateQuotation: (id: string, clientId: string, body: Record<string, unknown>) =>
      request<ApiResp<SalesQuotation>>(
        `/api/sales-cycle/quotations/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    orders: (clientId: string, onlyOpen = false) =>
      request<ApiResp<SalesOrder[]>>(
        `/api/sales-cycle/orders?client_id=${encodeURIComponent(clientId)}`
        + `&only_open=${onlyOpen ? "true" : "false"}`),
    orderPosition: (id: string, clientId: string) =>
      request<ApiResp<OrderPosition>>(
        `/api/sales-cycle/orders/${id}/position`
        + `?client_id=${encodeURIComponent(clientId)}`),
    createOrder: (body: Record<string, unknown>) =>
      request<ApiResp<SalesOrder>>("/api/sales-cycle/orders",
        { method: "POST", body: JSON.stringify(body) }),
    updateOrder: (id: string, clientId: string, body: Record<string, unknown>) =>
      request<ApiResp<SalesOrder>>(
        `/api/sales-cycle/orders/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    challans: (clientId: string) =>
      request<ApiResp<DeliveryChallan[]>>(
        `/api/sales-cycle/challans?client_id=${encodeURIComponent(clientId)}`),
    challan: (id: string, clientId: string) =>
      request<ApiResp<ChallanParticulars>>(
        `/api/sales-cycle/challans/${id}?client_id=${encodeURIComponent(clientId)}`),
    createChallan: (body: Record<string, unknown>) =>
      request<ApiResp<DeliveryChallan>>("/api/sales-cycle/challans",
        { method: "POST", body: JSON.stringify(body) }),
    updateChallan: (id: string, clientId: string, body: Record<string, unknown>) =>
      request<ApiResp<DeliveryChallan>>(
        `/api/sales-cycle/challans/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
  },

  openingDocuments: {
    kinds: () =>
      request<ApiResp<OpeningDocumentKinds>>("/api/opening-documents/kinds"),
    list: (clientId: string, kind: "receivable" | "payable") =>
      request<ApiResp<OpeningDocumentListing>>(
        `/api/opening-documents?client_id=${encodeURIComponent(clientId)}`
        + `&kind=${encodeURIComponent(kind)}`),
    create: (body: {
      client_id: string;
      kind: "receivable" | "payable";
      party_id: string;
      document_no: string;
      document_date: string;
      due_date?: string | null;
      outstanding_paise: number;
      notes?: string | null;
    }) => request<ApiResp<OpeningDocument>>("/api/opening-documents",
      { method: "POST", body: JSON.stringify(body) }),
    remove: (id: string, clientId: string, kind: "receivable" | "payable") =>
      request<ApiResp<{ id: string; deleted: boolean }>>(
        `/api/opening-documents/${id}?client_id=${encodeURIComponent(clientId)}`
        + `&kind=${encodeURIComponent(kind)}`,
        { method: "DELETE" }),
    /** Both sides at once — what the Opening Balances tab opens on. */
    reconciliation: (clientId: string) =>
      request<ApiResp<OpeningReconciliation>>(
        `/api/opening-documents/reconciliation?client_id=${encodeURIComponent(clientId)}`),
  },

  /** Which GST registrations a client holds (GST-20). */
  clientGstRegistrations: {
    kinds: () =>
      request<ApiResp<GstRegistrationKinds>>("/api/client-gst-registrations/kinds"),
    list: (clientId: string) =>
      request<ApiResp<ClientGstRegistration[]>>(
        `/api/client-gst-registrations?client_id=${encodeURIComponent(clientId)}`),
    create: (body: {
      client_id: string;
      gstin: string;
      registration_type?: string;
      filing_frequency?: string;
      trade_name?: string | null;
      effective_from?: string | null;
    }) => request<ApiResp<ClientGstRegistration>>("/api/client-gst-registrations",
      { method: "POST", body: JSON.stringify(body) }),
    /** Records a s.29 cancellation. NOT a delete — the returns for every period
     *  the registration was live are still owed. */
    close: (id: string, clientId: string, effectiveTo: string) =>
      request<ApiResp<ClientGstRegistration>>(
        `/api/client-gst-registrations/${id}/close`,
        { method: "POST",
          body: JSON.stringify({ client_id: clientId, effective_to: effectiveTo }) }),
    /** For a registration recorded in ERROR. The server refuses once a return
     *  has been prepared under it. */
    remove: (id: string, clientId: string) =>
      request<ApiResp<{ id: string; deleted: boolean }>>(
        `/api/client-gst-registrations/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "DELETE" }),
    /** The client's CGST s.2(6) aggregate turnover per financial year (GST-17).
     *
     *  Notification 78/2020-Central Tax sets the GSTR-1 Table 12 HSN digit
     *  requirement from the PRECEDING year's figure, and nothing in this
     *  product can derive it: s.2(6) is computed on the PAN, all-India, and
     *  includes exempt supplies and exports, so a second registration's
     *  supplies count toward it. `governing_turnover_paise` is `null` when
     *  nobody has recorded the year that governs — never 0, which is a client
     *  who genuinely turned over nothing. */
    turnover: (clientId: string) =>
      request<ApiResp<ClientGstTurnover>>(
        `/api/client-gst-registrations/turnover?client_id=${encodeURIComponent(clientId)}`),
    recordTurnover: (body: {
      client_id: string;
      financial_year: string;
      aggregate_turnover_paise: number;
      source_note?: string | null;
    }) => request<ApiResp<ClientGstTurnoverYear>>(
      "/api/client-gst-registrations/turnover",
      { method: "PUT", body: JSON.stringify(body) }),
  },

  /** The customs assessment on an import of goods (PUR-18).
   *
   *  A Bill of Entry is NOT the supplier's invoice under another name: the
   *  duty is assessed and collected by CUSTOMS (IGST Act s.5(1) proviso with
   *  Customs Tariff Act s.3(7)), so it touches no accounts payable. Which part
   *  of it is input tax and which is cost is the server's answer. */
  billsOfEntry: {
    authorities: () =>
      request<ApiResp<BillOfEntryAuthorities>>("/api/bills-of-entry/authorities"),
    list: (params: { client_id: string; date_from?: string; date_to?: string }) =>
      request<ApiResp<BillOfEntry[]>>(
        `/api/bills-of-entry?${new URLSearchParams(params as Record<string, string>)}`),
    create: (body: BillOfEntryWrite) =>
      request<ApiResp<BillOfEntry>>("/api/bills-of-entry",
        { method: "POST", body: JSON.stringify(body) }),
    update: (id: string, clientId: string, body: Partial<BillOfEntryWrite>) =>
      request<ApiResp<BillOfEntry>>(
        `/api/bills-of-entry/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "PATCH", body: JSON.stringify(body) }),
    post: (id: string, clientId: string) =>
      request<ApiResp<BillOfEntry>>(
        `/api/bills-of-entry/${id}/post?client_id=${encodeURIComponent(clientId)}`,
        { method: "POST" }),
    remove: (id: string, clientId: string) =>
      request<ApiResp<{ id: string; deleted: boolean }>>(
        `/api/bills-of-entry/${id}?client_id=${encodeURIComponent(clientId)}`,
        { method: "DELETE" }),
  },

  /** The two documents a reverse-charge purchase owes (PUR-19).
   *
   *  CGST Act s.31(3)(f) makes the RECIPIENT issue a self-invoice for a
   *  reverse-charge supply from an UNREGISTERED supplier; s.31(3)(g) makes them
   *  issue a payment voucher at the time of payment on EVERY s.9(3)/(4)
   *  liability, registered or not. The browser does not know that difference
   *  and must not learn it — `domain/gst/rcm_documents.py` decides, and the
   *  preview carries the answer with its reasons. */
  rcmDocuments: {
    kinds: () => request<ApiResp<RcmDocumentKind[]>>("/api/rcm-documents/kinds"),
    /** The three answers to "is this supplier registered". Served rather than
     *  spelled here: `unrecorded` is a real third state, and a screen that
     *  knows only two turns a named gap into a silent guess. */
    registrationStates: () =>
      request<ApiResp<string[]>>("/api/rcm-documents/registration-states"),
    list: (params: { client_id: string; kind?: string }) =>
      request<ApiResp<RcmDocumentRow[]>>(
        `/api/rcm-documents?${new URLSearchParams(params as Record<string, string>)}`),
    previewSelfInvoice: (params: { client_id: string; purchase_bill_id: string }) =>
      request<ApiResp<RcmDocumentPreview>>(
        `/api/rcm-documents/preview/self-invoice?${new URLSearchParams(params)}`),
    previewPaymentVoucher: (params: { client_id: string; purchase_payment_id: string }) =>
      request<ApiResp<RcmDocumentPreview>>(
        `/api/rcm-documents/preview/payment-voucher?${new URLSearchParams(params)}`),
    issue: (body: {
      client_id: string;
      kind: "self_invoice" | "payment_voucher";
      purchase_bill_id?: string;
      purchase_payment_id?: string;
      document_no?: string;
      document_date?: string;
      notes?: string;
    }) => request<ApiResp<RcmDocumentRow>>("/api/rcm-documents",
      { method: "POST", body: JSON.stringify(body) }),
  },

  reports: {
    transactions: (clientId?: string, dateFrom?: string, dateTo?: string) => {
      const q = new URLSearchParams();
      if (clientId) q.set("client_id", clientId);
      if (dateFrom) q.set("date_from", dateFrom);
      if (dateTo) q.set("date_to", dateTo);
      const qs = q.toString();
      return request<ApiResp<{ transactions: ReportTransaction[] }>>(
        `/api/reports/transactions${qs ? `?${qs}` : ""}`);
    },
    gstSummary: (clientId: string, month: string) =>
      request<ApiResp<ReportGSTSummary>>(
        `/api/reports/gst-summary?client_id=${encodeURIComponent(clientId)}` +
        `&month=${encodeURIComponent(month)}`),
  },
  /**
   * Moving a GST return's status. This is a BACKEND route and has to stay one.
   *
   * The screens used to write `status: "submitted"` straight into
   * gstr1_returns / gstr3b_returns over PostgREST. Two things were lost by
   * going round the API:
   *
   *   * `record_filing` never ran, so `public.filings` stayed empty — and that
   *     table is the ONLY thing journal_period_lock_reason (migrations 266 and
   *     267) reads to decide whether a filed return freezes the period behind
   *     it. A filed GSTR-3B locked nothing; entries inside a filed period
   *     stayed editable (CGST Act §37(3)/§39(9)).
   *   * `rbac()` never runs on a PostgREST call, so any role that could reach
   *     the screen could mark a return filed. The backend requires
   *     Manager-or-above plus an explicit `ca_approved` for submitted.
   *
   * The CA still files on gst.gov.in and records the ARN here afterwards; this
   * writes down what happened, it does not transmit anything.
   * # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
   */
  gstWorkspace: {
    /** Every GSTR-1 / GSTR-3B row for a client — the read that turns a
     *  (client, period) into the return id the status route addresses. */
    listReturns: (clientId: string, returnType?: "gstr1" | "gstr9") => {
      const q = new URLSearchParams({ client_id: clientId, limit: "500" });
      if (returnType) q.set("return_type", returnType);
      return request<ApiResp<{
        gstr1: Array<Record<string, unknown>>;
        gstr3b: Array<Record<string, unknown>>;
      }>>(`/api/gst-workspace/returns?${q.toString()}`);
    },
    setGstr1Status: (returnId: string, body: GSTStatusUpdate) =>
      request<ApiResp<Record<string, unknown>>>(
        `/api/gst-workspace/gstr1/${encodeURIComponent(returnId)}/status`,
        { method: "PATCH", body: JSON.stringify(body) }),
    setGstr3bStatus: (returnId: string, body: GSTStatusUpdate) =>
      request<ApiResp<Record<string, unknown>>>(
        `/api/gst-workspace/gstr3b/${encodeURIComponent(returnId)}/status`,
        { method: "PATCH", body: JSON.stringify(body) }),

    // ── §37: a filed GSTR-1 can never be revised (GST-13) ─────────────────
    //
    // Three finished capabilities that no screen reached. The corrections a
    // filed period needs are declared in a LATER return's amendment tables —
    // 9A for invoices, 9C for notes, 10 for B2C-others — and until now a CA
    // could neither see the drift nor produce the return that carries it.

    /** What the books say NOW against what the filed GSTR-1 actually said.
     *  Reports drift; drafts no amendment and alters no return. */
    gstr1Exceptions: (clientId: string, period: string) =>
      request<ApiResp<GSTR1ExceptionReport>>(
        `/api/gst-workspace/gstr1/exceptions?client_id=${encodeURIComponent(clientId)}`
        + `&period=${encodeURIComponent(period)}`),

    /** What THIS period's GSTR-1 must carry from earlier filed periods. */
    gstr1Amendments: (clientId: string, period: string) =>
      request<ApiResp<GSTR1AmendmentsReport>>(
        `/api/gst-workspace/gstr1/amendments?client_id=${encodeURIComponent(clientId)}`
        + `&period=${encodeURIComponent(period)}`),

    // ── The reclaimable half of Table 4 (GST-13) ──────────────────────────
    //
    // Table 4(B)(2) reversals and their 4(D)(1) reclaims. The register does
    // NOT post anything: giving credit back is a real movement and it goes
    // through the one posting kernel like every other entry. What was missing
    // was never a way to POST the reversal — it was a way to say WHAT IT WAS,
    // because a journal crediting GST Input could be a Rule 37 reversal, a
    // cancelled bill or a plain correction, and the return has to tell them
    // apart.

    itcRegister: (clientId: string, period: string) =>
      request<ApiResp<ITCRegisterPeriod>>(
        `/api/gst-workspace/itc/register?client_id=${encodeURIComponent(clientId)}`
        + `&period=${encodeURIComponent(period)}`),

    /** Classify an ALREADY-POSTED journal as a Table 4(B)(2) reversal.
     *  Refused if it claims more than that journal actually moved — a return
     *  figure the ledger cannot support is the failure this prevents. */
    itcRegisterReversal: (body: ITCReversalInput) =>
      request<ApiResp<Record<string, unknown>>>(
        "/api/gst-workspace/itc/register/reversal",
        { method: "POST", body: JSON.stringify(body) }),

    /** Classify an already-posted journal as a Table 4(D)(1) reclaim.
     *  Refused if it would reclaim more than the reversal it names still has
     *  outstanding — credit can only come back once. */
    itcRegisterReclaim: (body: ITCReclaimInput) =>
      request<ApiResp<Record<string, unknown>>>(
        "/api/gst-workspace/itc/register/reclaim",
        { method: "POST", body: JSON.stringify(body) }),

    /** Advances received against no invoice — GSTR-1 Table 11.
     *  NAMES them and computes no tax; see `why` on the response. */
    gstr1Advances: (clientId: string, period: string) =>
      request<ApiResp<GSTR1Advances>>(
        `/api/gst-workspace/gstr1/advances?client_id=${encodeURIComponent(clientId)}`
        + `&period=${encodeURIComponent(period)}`),
  },

  gstReturns: {
    /** GSTR-1 from the books WITH the amendment tables this period carries.
     *
     *  The route's own docstring records why it exists: the amendment service
     *  had worked out which corrections were outstanding since it was built,
     *  and merge_into_payload had been able to fold them into a payload for
     *  just as long — and NOTHING CONNECTED THE TWO. The route was added to
     *  connect them and still had no caller, so a CA could see an amendment
     *  was due and had no way to file it.
     */
    gstr1WithAmendments: (body: {
      client_id: string; period: string; aggregate_turnover_paise?: number;
    }) =>
      request<ApiResp<GSTR1WithAmendments>>(
        "/api/gst/gstr1/with-amendments",
        { method: "POST", body: JSON.stringify(body) }),
  },
  identity: {
    listUsers: () => request<ApiResp<{
      users: Array<{
        id: string; full_name: string; email: string; role: string;
        is_active?: boolean; created_at?: string; auth_user_id?: string; firm_id?: string;
      }>;
    }>>("/api/identity/users"),
    createUser: (full_name: string, email: string, role: string) =>
      request<ApiResp<{ id: string; invite_token: string }>>(
        "/api/identity/users", { method: "POST", body: JSON.stringify({ full_name, email, role }) }),
    // F21 fix: the only way a users row's auth_user_id can be set — token comes
    // from createUser's response, never from URL params.
    acceptInvite: (token: string) =>
      request<ApiResp<{ firm_id: string; role: string; full_name?: string }>>(
        "/api/identity/accept-invite", { method: "POST", body: JSON.stringify({ token }) }),
    changeRole: (userId: string, role: string) =>
      request(`/api/identity/users/${userId}/role`, { method: "PATCH", body: JSON.stringify({ role }) }),
    suspend: (userId: string) => request(`/api/identity/users/${userId}/suspend`, { method: "POST" }),
    reactivate: (userId: string) => request(`/api/identity/users/${userId}/reactivate`, { method: "POST" }),
    forceLogout: (userId: string) => request(`/api/identity/users/${userId}/force-logout`, { method: "POST" }),
    forceLogoutAll: () => request("/api/identity/force-logout-all", { method: "POST" }),
    loginHistory: () =>
      request("/api/identity/login-history") as Promise<ApiResp<{ events: LoginEvent[] }>>,
    recordLoginEvent: (event: "login" | "logout") =>
      request("/api/identity/login-event", { method: "POST", body: JSON.stringify({ event }) }),
    // The caller's own display name. Deliberately takes no user id — the row is
    // addressed server-side from the verified token, so this can only ever edit
    // the caller's own profile.
    updateMyProfile: (full_name: string) =>
      request<ApiResp<{ id: string; full_name: string }>>(
        "/api/identity/me", { method: "PATCH", body: JSON.stringify({ full_name }) }),
    // The caller's own resource→actions map, served straight from the backend's
    // PERMISSIONS matrix. Consumed by AuthContext so the UI has one source of
    // truth for action gating instead of role lists copied beside each button.
    myPermissions: () =>
      request<ApiResp<{ role: string | null; permissions: Record<string, string[]> }>>(
        "/api/identity/permissions"),
    /** What EVERY role can reach — the Team screen's access matrix.
     *
     *  myPermissions above answers for the caller, which is what a screen
     *  needs to decide whether to render a control. This answers for all five
     *  roles, which is what a Partner needs to see what each member's role
     *  actually grants.
     *
     *  `app/team/page.tsx` carried its own copy of this and it had drifted
     *  badly in the direction that matters: it told a Partner an Executive
     *  could reach only Clients and Tasks, when the backend grants them
     *  Accounting, GST, Income Tax, MCA, Reports and TDS as well. */
    roleMatrix: () =>
      request<ApiResp<{ roles: string[]; matrix: Record<string, Record<string, string[]>> }>>(
        "/api/identity/role-matrix"),

    /** Every (resource, action) pair that exists, with the two flags a grid needs.
     *
     *  Served rather than spelled here for the reason roleMatrix is: the last
     *  hardcoded copy of a backend vocabulary in this app drifted in BOTH
     *  directions at once and nine of fifty mapped accounts were silently
     *  discarded as a result. */
    permissionVocabulary: () =>
      request<ApiResp<{ permissions: Array<{
        resource: string; action: string;
        privilege_changing: boolean; unrevokable_for_partner: boolean;
      }> }>>("/api/identity/permission-vocabulary"),

    /** One member's access: the role template, the stored overrides, the effective answer.
     *
     *  All three, because showing only the last makes an inherited permission
     *  and a deliberately granted one look identical — so a Partner could not
     *  tell which of their firm's access was a decision. */
    memberPermissions: (userId: string) =>
      request<ApiResp<MemberAccessGrid>>(`/api/identity/users/${userId}/permissions`),

    /** Change one member's access. Partner-only, audited, validated before any write.
     *
     *  `changes` is {"resource:action": true | false | null}. **null DELETES the
     *  override**, which is not the same as false: absence means "whatever the
     *  role says" and false means "refused however senior". A caller that could
     *  only send the second could never hand a permission back to the role. */
    setMemberPermissions: (userId: string, changes: Record<string, boolean | null>) =>
      request<ApiResp<MemberAccessGrid>>(`/api/identity/users/${userId}/permissions`,
        { method: "PUT", body: JSON.stringify({ changes }) }),
  },
  /** The Annual Information Statement — IT Act §285BB.
   *
   *  Everything here is server-side on purpose. The screen used to parse the
   *  portal's JSON in the browser and hold the whole reconciliation in React
   *  state, so it was gone on refresh; migration 352 and
   *  services/ais_service.py keep it. The browser sends the file's TEXT and
   *  renders what comes back — there is no second parser.
   */
  ais: {
    meta: () => request<ApiResp<{ transaction_types: string[]; statuses: string[] }>>(
      "/api/ais/meta"),
    // assessment_year, not financial year: AIS is published per AY.
    statement: (clientId: string, assessmentYear: string, uploadId?: string) =>
      request<ApiResp<AISStatement>>(
        `/api/ais/statement?client_id=${encodeURIComponent(clientId)}` +
        `&assessment_year=${encodeURIComponent(assessmentYear)}` +
        (uploadId ? `&upload_id=${encodeURIComponent(uploadId)}` : "")),
    upload: (body: { client_id: string; assessment_year: string; raw: string;
                     file_name?: string }) =>
      request<ApiResp<AISStatement>>(
        "/api/ais/uploads", { method: "POST", body: JSON.stringify(body) }),
    // books_amount_paise NULL is "nobody has looked" and is NOT 0. The server
    // derives matched/amount_mismatch from the two figures and refuses a
    // status that contradicts them.
    saveWorking: (recordId: string, body: {
      client_id: string; books_amount_paise: number | null;
      status?: string | null; note?: string | null;
    }) => request<ApiResp<AISWorking>>(
      `/api/ais/records/${recordId}/working`,
      { method: "PUT", body: JSON.stringify(body) }),
    addRecord: (body: {
      client_id: string; upload_id: string; transaction_type: string;
      payer: string; amount_paise: number; tds_deducted_paise?: number;
      information_label?: string | null;
    }) => request<ApiResp<AISLine>>(
      "/api/ais/records", { method: "POST", body: JSON.stringify(body) }),
    deleteRecord: (recordId: string) =>
      request<ApiResp<{ deleted: string }>>(
        `/api/ais/records/${recordId}`, { method: "DELETE" }),
  },
};

/** One line of the statement, with the CA's working against it. */
export type AISLine = {
  id: string;
  information_source: string | null;
  information_label: string | null;
  transaction_type: string;
  payer: string | null;
  amount_paise: number;
  tds_deducted_paise: number;
  source: "json" | "manual";
  /** NULL means nobody has looked. It is not nil. */
  books_amount_paise: number | null;
  status: "not_reviewed" | "matched" | "amount_mismatch" | "not_in_books" | "explained";
  note: string | null;
  reviewed_at: string | null;
};

export type AISWorking = {
  record_id: string;
  books_amount_paise: number | null;
  status: string;
  note: string | null;
  reviewed_at: string | null;
};

export type AISUpload = {
  id: string;
  assessment_year: string;
  pan: string | null;
  taxpayer_name: string | null;
  file_name: string | null;
  record_count: number;
  total_amount_paise: number;
  total_tds_paise: number;
  /** Sentences about what the parser could not read. A file that parsed with
   *  problems is not a file that parsed. */
  problems: string[];
  created_at: string | null;
};

/** NOTE THE ABSENCE. There is no tax figure on this type and there is not
 *  meant to be: the screen this replaced showed "Est. Tax Impact (30%)" in
 *  rupees, and nothing here knows the client's regime, entity type or slab.
 *  `tax_impact_refused` is the sentence the screen prints instead. */
export type AISSummary = {
  line_count: number;
  total_amount_paise: number;
  total_tds_paise: number;
  by_status: Record<string, number>;
  not_reviewed_count: number;
  not_in_books_paise: number;
  shortfall_paise: number;
  open_paise: number;
  tax_impact_refused: string;
  by_type: Array<{ transaction_type: string; line_count: number;
                   amount_paise: number; tds_paise: number }>;
};

export type AISStatement = {
  upload: AISUpload | null;
  records: AISLine[];
  summary: AISSummary;
  uploads: AISUpload[];
};

/** One page of the log. NO total, deliberately: a COUNT over the whole log to
 *  render one page is the cost the server-side query exists to remove, and
 *  `has_more` is what a "Load more" control needs. */
/** One run's aggregate — the shape the statutory table renders.
 *  `pf_count` and `esi_count` are slips that CARRIED the contribution, never a
 *  re-derived ceiling test: ESI Rule 50 keeps a member in past the ceiling
 *  until the contribution period ends, and re-applying the rule afterwards
 *  read "no ESI-applicable employees" for people the firm had deducted from. */
export type PayrollRunSummary = {
  id: string;
  client_id: string;
  month: string;
  status: string;
  financial_year: string | null;
  slip_count: number;
  gross_paise: number;
  net_paise: number;
  tds_paise: number;
  pf_count: number;
  esi_count: number;
  pf_employee_paise: number;
  pf_employer_paise: number;
  esi_employee_paise: number;
  esi_employer_paise: number;
};

/** One employee's whole financial year, summed server-side. Mirrors
 *  lib/payroll/types.EmployeeYearTotals — declared here because this module is
 *  where the wire shapes live. */
export type EmployeeYearTotalsRow = {
  employee_id: string;
  employee: { name: string; pan: string; designation: string } | null;
  months: number;
  gross_paise: number;
  net_paise: number;
  tds_paise: number;
  pt_paise: number;
  pf_employee_paise: number;
  esi_employee_paise: number;
};

export type AuditPage = {
  entries: AuditEntry[];
  next_cursor: string | null;
  has_more: boolean;
  limit: number;
  /** The UTC instants the IST dates were converted to, for display. */
  window: { from: string | null; to: string | null };
};

export type AuditEntry = {
  id: string;
  firm_id: string;
  actor_id?: string | null;
  actor_email?: string | null;
  entity_type: string;
  entity_id?: string | null;
  action: string;
  old_data?: Record<string, unknown> | null;
  new_data?: Record<string, unknown> | null;
  metadata?: Record<string, unknown> | null;
  created_at: string;
};

export type ReconciliationFinding = {
  id: string;
  run_id: string;
  check_name: string;
  severity: "critical" | "warning";
  summary: string;
  details: Record<string, unknown>;
  amount_paise: number | null;
  created_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  resolution_note?: string | null;
};

export type ReconciliationRun = {
  id: string;
  firm_id: string;
  client_id: string;
  trigger: "scheduled" | "manual";
  status: "running" | "completed" | "failed";
  started_at: string;
  completed_at?: string | null;
  checks_run: number;
  findings_count: number;
  triggered_by?: string | null;
  error?: string | null;
};

/**
 * One entry of the Verify Books check catalogue, served by
 * `GET /api/reconciliation/checks`.
 *
 * SERVED, NOT SPELLED HERE. The accounting tab used to keep its own
 * `CHECK_LABEL` map — six entries against the sixteen check names the engine
 * emits — so a CA reading a real finding on a bank reconciliation, an orphan
 * money journal or the fixed-asset register got the raw snake_case identifier.
 * The Schedule III caption lesson: the module that owns the checks is the only
 * place that can stay right about their names.
 */
/** One week of `GET /api/workload/capacity-risk`. */
export type CapacityWeek = {
  week_start: string;
  items_due: number;
  tasks_due: number;
  compliance_due: number;
  /** Recorded effort only — `workflow_steps.estimated_hours`. Never imputed
   *  across the tasks below, which carry none. */
  estimated_hours: number;
  items_without_an_estimate: number;
  /** Against the practice's own median week. Null where too few weeks carried
   *  work for a median to mean anything. */
  vs_median_pct: number | null;
  is_peak: boolean;
};

export type CapacityRiskPayload = {
  weeks: CapacityWeek[];
  /** Already late. Not in any week — it is on top of all of them. */
  overdue_items: number;
  undated_items: number;
  obligations_folded_into_tasks: number;
  median_week_items: number | null;
  peak_weeks: string[];
  /** Headcount and configured hours, BESIDE the load and never multiplied into
   *  it: `max_concurrent_tasks` is a limit on what may be open, not a weekly
   *  throughput. */
  people: number;
  configured_weekly_hours: number;
  peak_multiple: number;
  not_forecast: string[];
};

export type ReconciliationCheck = {
  check_name: string;
  label: string;
  looks_for: string;
  /** Three of the sixteen say "go and look" rather than asserting an
   *  invariant. A CA shown sixteen equal chips reads the judgement calls as
   *  defects and then discounts the invariants too. */
  is_heuristic: boolean;
};

export type ReconciliationCheckCatalogue = {
  checks: ReconciliationCheck[];
  /** What the scan cannot see, so a clean run is not read as clean books. */
  not_checked: string[];
};

export type ReconciliationRunResult = {
  run_id: string;
  status: "completed" | "failed";
  checks_run?: number;
  findings_count?: number;
  findings?: ReconciliationFinding[];
  error?: string;
};

export type LoginEvent = {
  id: string; user_id?: string; email?: string; event: string;
  ip?: string; user_agent?: string; created_at?: string;
};

/** One staff member's access, as the server resolves it (migration 403).
 *
 *  THREE maps, and they answer three different questions. `role_defaults` is
 *  what the person's ROLE gives them — the template. `overrides` is what the
 *  firm decided about this person specifically, keyed "resource:action".
 *  `effective` is what rbac() will actually do, which is the first with the
 *  second applied. A screen that rendered only `effective` could not show
 *  which of the firm's access was a decision and which was inherited. */
export type MemberAccessGrid = {
  user_id: string;
  full_name?: string | null;
  email?: string | null;
  role: string | null;
  role_defaults: Record<string, string[]>;
  overrides: Record<string, boolean>;
  effective: Record<string, string[]>;
};

export type ApprovalRequest = {
  id: string;
  request_type: string;
  summary?: string;
  status: "pending" | "approved" | "rejected" | "cancelled";
  payload?: Record<string, unknown>;
  requested_by_email?: string;
  decided_by_email?: string;
  reason?: string;
  created_at?: string;
};

export type UnmatchedRemittance = Remittance & {
  candidates: RemittanceCandidate[];
};

/** ESIC's mapped-IP list against this month's contribution file. The two
 *  directions are DIFFERENT PROBLEMS: `missing_from_file` fails the whole
 *  upload, `not_mapped_at_esic` is a number to check or somebody to get mapped.
 *  `what_it_means` is composed on the server — render it. */
export type EsicMappedIpCheck = {
  mapped_count: number;
  file_count: number;
  missing_from_file: string[];
  not_mapped_at_esic: string[];
  matched: string[];
  would_be_rejected: boolean;
  what_it_means: string;
};

// ── The two documents a reverse-charge purchase owes (PUR-19) ───────────────
//
// Shapes only. Which document is due, what it says and what could not be
// stated are `domain/gst/rcm_documents.py`'s answers — in particular the one
// difference that matters, that s.31(3)(f) reaches only an UNREGISTERED
// supplier while s.31(3)(g) reaches every reverse-charge payment, is nowhere
// in this file and must not be.

export type RcmDocumentKind = {
  kind: "self_invoice" | "payment_voucher";
  section: string;
  rule: string;
  hangs_off: "purchase_bill" | "purchase_payment";
  only_when_supplier_unregistered: boolean;
};

export type RcmParty = {
  name: string;
  address: string;
  gstin: string | null;
  state_code: string | null;
};

export type RcmParticulars = {
  kind: string;
  section: string;
  rule: string;
  document_no: string;
  document_date: string;
  supplier: RcmParty;
  recipient: RcmParty;
  lines: {
    description: string;
    hsn_sac: string | null;
    quantity: string | null;
    unit: string | null;
    taxable_paise: number;
  }[];
  taxable_paise: number;
  amount_paid_paise: number;
  taxes: { head: string; amount_paise: number }[];
  total_tax_paise: number;
  place_of_supply: [string, string];
  tax_payable_on_reverse_charge: boolean;
  gaps: string[];
  caveats: string[];
};

export type RcmDocumentRow = {
  id: string;
  kind: string;
  document_no: string;
  document_date: string;
  purchase_bill_id: string | null;
  purchase_payment_id: string | null;
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  cess_paise: number;
  amount_paid_paise: number;
};

export type RcmDocumentPreview = {
  kind: "self_invoice" | "payment_voucher";
  section: string;
  rule: string;
  /** The Act asks for this document. */
  due: boolean;
  /** Why it is NOT due — a settled answer about the statute. */
  reasons: string[];
  /** What nobody has recorded yet. DIFFERENT from `reasons`: this one is
   *  actionable, and a screen that renders the two the same way turns a named
   *  gap into a refusal. */
  gaps: string[];
  vendor_registration: "registered" | "unregistered" | "unrecorded";
  existing: RcmDocumentRow | null;
  particulars: RcmParticulars | null;
};


/** INV-02 — a client's cost formula and what changing it would mean.
 *
 *  `method` is always one of the two AS-2 paragraph 14 permits and is never
 *  null: a client with nothing recorded IS on the weighted average, because
 *  it was the only formula this product had. `is_recorded` is the separate
 *  fact of whether anybody has chosen, and `unrecorded_means` carries the
 *  sentence saying so — present only when they have not.
 *
 *  `methods_used` is DERIVED from `inventory_stock_ledger.costing_method`,
 *  the stamp on every movement, which is what makes the AS-5 paragraph 32
 *  disclosure a property of the ledger rather than something remembered.
 */
export type InventoryCostingPolicy = {
  client_id: string;
  method: string;
  label: string;
  is_recorded: boolean;
  unrecorded_means: string | null;
  methods: { value: string; label: string }[];
  standard_cost_refused: string;
  as5_disclosure: string;
  earliest_date_a_change_can_take_effect: string | null;
  methods_used: {
    method: string; label: string;
    first_movement: string; last_movement: string;
  }[];
};


/** PAY-23 — the annual statutory bonus register for one client-year.
 *
 *  `rate_is_the_statutory_minimum` is a SEPARATE fact from the rate: 8.33% is
 *  both §10's floor and what applies when no allocable surplus has been
 *  declared, and a CA needs to see which of those it is.
 *
 *  `working_days` is `null` where the year's attendance is not recorded — NOT
 *  zero. §8 needs thirty working days, and reading absence as nil would
 *  disqualify every employee at a client who runs payroll without attendance,
 *  hiding a debt. The server computes the figure and names the employee.
 */
export type BonusRegister = {
  accounting_year: string;
  rate_bps: number;
  rate_is_the_statutory_minimum: boolean;
  minimum_wage_monthly_paise: number | null;
  scheduled_employment: string | null;
  due_date: string;
  employees: {
    employee_id: string;
    employee_name: string;
    monthly_salary_paise: number;
    months_worked: number;
    working_days: number | null;
    eligible: boolean;
    payable_paise: number;
    minimum_paise: number;
    maximum_paise: number;
    calculation_base_monthly_paise: number;
    reasons: string[];
    gaps: string[];
  }[];
  total_payable_paise: number;
  total_minimum_paise: number;
  total_maximum_paise: number;
  eligible_count: number;
  excluded_count: number;
  gaps: string[];
  notes: string[];
  declaration: {
    id: string;
    accounting_year: string;
    rate_bps: number;
    allocable_surplus_paise: number | null;
    minimum_wage_monthly_paise: number | null;
    scheduled_employment: string | null;
    notes: string | null;
  } | null;
  section_9_grounds: { value: string; label: string }[];
};
