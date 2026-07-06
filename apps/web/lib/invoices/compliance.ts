/**
 * GST compliance — pure derivation & validation (Batch 7). No framework/browser
 * deps, so it lives beside the pure domain (./gst) and is unit-testable under
 * `node --test`. It NEVER computes tax or touches posting: it derives the GST
 * treatment, validates eligibility for the IRN / E-Way workflows, and reads the
 * status of the existing e-invoice / e-way records. The accounting engine and
 * the immutable ledger are untouched.
 */
import type { InvoiceStatus } from "./gst";

// A valid GST state code is a 2-digit number 01–38 (states/UTs, up to Ladakh),
// or 96/97 (foreign / other territory). Kept self-contained so this pure module
// has no cross-module value imports (node --test strips only type imports).
function isValidStateCode(code: string): boolean {
  if (!/^\d{2}$/.test(code)) return false;
  const n = Number(code);
  return (n >= 1 && n <= 38) || n === 96 || n === 97;
}
// CGST Act §25 GSTIN: 2-digit state + PAN(10) + entity + Z + check.
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

/** E-Way Bill threshold: ₹50,000 taxable value (Rule 138). In paise. */
export const EWAY_THRESHOLD_PAISE = 5_000_000;

// ── GST treatment ─────────────────────────────────────────────────────────────
export type GstTreatment =
  | "regular"
  | "export_with_payment"
  | "export_without_payment"
  | "sez_with_payment"
  | "sez_without_payment"
  | "deemed_export";

export interface ComplianceInvoice {
  status: InvoiceStatus;
  is_interstate: boolean;
  supply_state_code: string | null;
  recipient_gstin?: string | null;   // customer GSTIN (null = unregistered / B2C)
  is_reverse_charge?: boolean | null;
  /** Explicit treatment captured on the e-invoice record, if any. */
  gst_treatment?: GstTreatment | null;
  taxable_amount_paise: number;
  line_hsn_codes?: (string | null | undefined)[]; // to hint goods vs services
}

export interface TreatmentSummary {
  treatment: GstTreatment;
  label: string;
  /** B2B when the recipient is registered (has a GSTIN), else B2C. */
  registered: boolean;
  interstate: boolean;
  reverseCharge: boolean;
}

const TREATMENT_LABEL: Record<GstTreatment, string> = {
  regular: "Regular",
  export_with_payment: "Export with payment (IGST)",
  export_without_payment: "Export under LUT/Bond",
  sez_with_payment: "SEZ with payment (IGST)",
  sez_without_payment: "SEZ under LUT/Bond",
  deemed_export: "Deemed export",
};

/** Label a treatment code for display. */
export function treatmentLabel(t: GstTreatment): string {
  return TREATMENT_LABEL[t];
}

/**
 * Derive the GST treatment summary. An explicit treatment (captured on the
 * e-invoice record for exports/SEZ) wins; otherwise it is a regular supply and
 * B2B/B2C follows from whether the recipient is GST-registered.
 */
export function gstTreatment(inv: ComplianceInvoice): TreatmentSummary {
  const registered = !!inv.recipient_gstin && GSTIN_RE.test(inv.recipient_gstin.trim().toUpperCase());
  const treatment: GstTreatment = inv.gst_treatment ?? "regular";
  const base = TREATMENT_LABEL[treatment];
  const scope = treatment === "regular"
    ? `${registered ? "B2B" : "B2C"} · ${inv.is_interstate ? "Inter-state (IGST)" : "Intra-state (CGST+SGST)"}`
    : "";
  return {
    treatment,
    label: [base, scope].filter(Boolean).join(" · "),
    registered,
    interstate: inv.is_interstate,
    reverseCharge: !!inv.is_reverse_charge,
  };
}

// ── Validation ────────────────────────────────────────────────────────────────
export interface ValidationIssue {
  field: string;
  message: string;
  severity: "error" | "warning";
}

/** Validate the place of supply: present, a real state code, GSTIN-consistent. */
export function validatePlaceOfSupply(inv: ComplianceInvoice): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const pos = (inv.supply_state_code ?? "").trim();
  if (!pos) {
    issues.push({ field: "place_of_supply", message: "Place of supply is missing.", severity: "error" });
    return issues;
  }
  if (!isValidStateCode(pos)) {
    issues.push({ field: "place_of_supply", message: `“${pos}” is not a valid GST state code.`, severity: "error" });
  }
  const g = (inv.recipient_gstin ?? "").trim().toUpperCase();
  if (g && GSTIN_RE.test(g) && g.slice(0, 2) !== pos && !inv.is_interstate) {
    issues.push({
      field: "place_of_supply",
      message: `Place of supply (${pos}) differs from the recipient GSTIN state (${g.slice(0, 2)}) on an intra-state invoice.`,
      severity: "warning",
    });
  }
  return issues;
}

/** Validate the mandatory GST fields needed before any compliance action. */
export function validateMandatoryGstFields(inv: ComplianceInvoice): ValidationIssue[] {
  const issues: ValidationIssue[] = [...validatePlaceOfSupply(inv)];
  const g = (inv.recipient_gstin ?? "").trim().toUpperCase();
  if (g && !GSTIN_RE.test(g)) {
    issues.push({ field: "recipient_gstin", message: "Recipient GSTIN format is invalid.", severity: "error" });
  }
  const hsn = inv.line_hsn_codes ?? [];
  if (hsn.length && hsn.some((h) => !h || !String(h).trim())) {
    issues.push({ field: "hsn", message: "One or more lines are missing an HSN/SAC code.", severity: "warning" });
  }
  return issues;
}

export interface Eligibility {
  eligible: boolean;
  blockers: string[];   // hard reasons it cannot proceed
  warnings: string[];   // advisory notes
}

const isPosted = (s: InvoiceStatus) => s === "issued" || s === "partially_paid" || s === "paid";

/**
 * IRN eligibility (CGST Rule 48(4)). E-invoicing applies to B2B / export / SEZ
 * supplies of eligible taxpayers; B2C is out of scope. Firm turnover-threshold
 * eligibility is a firm-level setting surfaced as an advisory, never a blocker.
 */
export function irnEligibility(inv: ComplianceInvoice, alreadyGenerated: boolean): Eligibility {
  const blockers: string[] = [];
  const warnings: string[] = [];
  if (!isPosted(inv.status)) blockers.push("Issue the invoice before generating an IRN.");
  if (alreadyGenerated) blockers.push("An active IRN already exists for this invoice.");

  const t = gstTreatment(inv);
  const isExportOrSez = t.treatment !== "regular";
  if (!t.registered && !isExportOrSez) {
    blockers.push("IRN applies to B2B/export/SEZ supplies; this is a B2C invoice.");
  }
  for (const i of validateMandatoryGstFields(inv)) {
    (i.severity === "error" ? blockers : warnings).push(i.message);
  }
  warnings.push("E-invoicing applies only above your firm's turnover threshold — confirm before generating.");
  return { eligible: blockers.length === 0, blockers, warnings };
}

/**
 * E-Way Bill eligibility (Rule 138): required for the movement of GOODS worth
 * ≥ ₹50,000. Pure-service invoices (all SAC 99xxxx lines) do not move goods, so
 * that is surfaced as a strong advisory rather than a hard block (the CA decides).
 */
export function ewayEligibility(inv: ComplianceInvoice, alreadyGenerated: boolean): Eligibility {
  const blockers: string[] = [];
  const warnings: string[] = [];
  if (!isPosted(inv.status)) blockers.push("Issue the invoice before generating an E-Way Bill.");
  if (alreadyGenerated) blockers.push("An active E-Way Bill already exists for this invoice.");
  if (inv.taxable_amount_paise < EWAY_THRESHOLD_PAISE) {
    warnings.push("Taxable value is below ₹50,000 — an E-Way Bill is usually not required.");
  }
  const hsn = inv.line_hsn_codes ?? [];
  if (hsn.length && hsn.every((h) => /^99\d{4}$/.test(String(h ?? "")))) {
    warnings.push("All lines are services (SAC) — an E-Way Bill is generally not required for services.");
  }
  return { eligible: blockers.length === 0, blockers, warnings };
}

// ── Record status ─────────────────────────────────────────────────────────────
export interface EInvoiceRecord {
  id: string;
  sales_invoice_id?: string | null;
  status?: string | null;         // draft | generated | cancelled
  irn?: string | null;
  ack_number?: string | null;
  ack_date?: string | null;
  qr_data?: string | null;
  cancellation_reason?: string | null;
  cancelled_at?: string | null;
  gst_treatment?: GstTreatment | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface EWayRecord {
  id: string;
  sales_invoice_id?: string | null;
  status?: string | null;
  ewb_number?: string | null;
  ewb_date?: string | null;
  ewb_valid_upto?: string | null;
  cancellation_reason?: string | null;
  cancelled_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export type ComplianceState = "none" | "draft" | "generated" | "cancelled";

/** The single most-relevant record for an invoice: prefer a live (generated)
 * record, else the newest by creation. */
function pickLatest<T extends { sales_invoice_id?: string | null; status?: string | null; created_at?: string | null }>(
  invoiceId: string, records: T[],
): T | null {
  const mine = records.filter((r) => r.sales_invoice_id === invoiceId);
  if (!mine.length) return null;
  const live = mine.find((r) => r.status === "generated");
  if (live) return live;
  return [...mine].sort((a, b) => ((a.created_at ?? "") < (b.created_at ?? "") ? 1 : -1))[0];
}

export interface IrnStatus {
  state: ComplianceState;
  record: EInvoiceRecord | null;
  irn: string | null;
  qrData: string | null;
}

export function irnStatus(invoiceId: string, records: EInvoiceRecord[]): IrnStatus {
  const rec = pickLatest(invoiceId, records);
  const state = (rec?.status as ComplianceState) ?? "none";
  return {
    state: rec ? state : "none",
    record: rec,
    irn: rec?.irn ?? null,
    qrData: rec?.qr_data ?? null,
  };
}

export interface EwayStatusResult {
  state: ComplianceState;
  record: EWayRecord | null;
  ewbNumber: string | null;
  validUpto: string | null;
}

export function ewayStatus(invoiceId: string, records: EWayRecord[]): EwayStatusResult {
  const rec = pickLatest(invoiceId, records);
  const state = (rec?.status as ComplianceState) ?? "none";
  return {
    state: rec ? state : "none",
    record: rec,
    ewbNumber: rec?.ewb_number ?? null,
    validUpto: rec?.ewb_valid_upto ?? null,
  };
}

// ── Compliance timeline items (for the Hub activity feed) ─────────────────────
export interface ComplianceTimelineItem {
  at: string;
  title: string;
  detail?: string;
  kind: "compliance";
}

/** Derive newest-first-ready timeline entries from the invoice's compliance
 * records (creation, IRN/EWB generation, cancellation) — merged by the Hub. */
export function complianceTimelineItems(
  invoiceId: string,
  einvoices: EInvoiceRecord[],
  eways: EWayRecord[],
): ComplianceTimelineItem[] {
  const items: ComplianceTimelineItem[] = [];
  for (const r of einvoices.filter((r) => r.sales_invoice_id === invoiceId)) {
    if (r.status === "generated" && r.ack_date) {
      items.push({ at: r.ack_date, title: "IRN generated", detail: r.irn ?? undefined, kind: "compliance" });
    }
    if (r.status === "cancelled" && r.cancelled_at) {
      items.push({ at: r.cancelled_at, title: "IRN cancelled", detail: r.cancellation_reason ?? undefined, kind: "compliance" });
    }
  }
  for (const r of eways.filter((r) => r.sales_invoice_id === invoiceId)) {
    if (r.status === "generated" && r.ewb_date) {
      items.push({ at: r.ewb_date, title: "E-Way Bill generated", detail: r.ewb_number ?? undefined, kind: "compliance" });
    }
    if (r.status === "cancelled" && r.cancelled_at) {
      items.push({ at: r.cancelled_at, title: "E-Way Bill cancelled", detail: r.cancellation_reason ?? undefined, kind: "compliance" });
    }
  }
  return items;
}
