/**
 * GSTR-1 classification on a sales invoice — the three facts the return is
 * built from, and the vocabulary the form offers for them.
 *
 * WHY THIS MODULE EXISTS
 *     domain/gst/classifier.py routes every outward supply to its GSTR-1 table
 *     by branching on supply_type, invoice_type and is_reverse_charge. Migration
 *     268 gave client_sales_invoices those columns and the API accepts them, but
 *     until now no screen set any of them, so every invoice went out carrying
 *     the defaults: an ordinary domestic taxable sale.
 *
 *     That was correct code with no path to it. The classifier could not be
 *     wrong, because it was never asked.
 *
 * WHAT IS AND ISN'T HERE
 *     Option lists, defaults, and normalisation. No tax logic: which GSTR-1
 *     table a supply lands in is the backend's decision (CLAUDE.md — zero
 *     business logic in the frontend), and nothing here computes or infers it.
 *     This module only makes sure the value a CA picks survives the trip.
 *
 * THE VALUES ARE NOT FREE TEXT
 *     They are CHECK-constrained in migration 268, matching migration 036's
 *     constraints on public.transactions. A value that drifts from that set is
 *     rejected by the database, not by a form validator, so the failure would
 *     reach the CA as an opaque save error. classification.test.ts reads the
 *     migration and asserts these lists are exactly the constrained sets.
 */

/** CGST §23 / GSTR-1 table 8 — how the supply itself is taxed. */
export type SupplyType = "taxable" | "zero_rated" | "nil_rated" | "exempt" | "non_gst";

/** CGST §16(1)(a) and §16(3) — zero-rated routes to an SEZ or deemed export. */
export type InvoiceType = "Regular" | "SEZ_with_payment" | "SEZ_without_payment" | "Deemed_export";

// The defaults are what every invoice was implicitly treated as before migration
// 268, and what the columns default to. Changing either changes the meaning of
// an invoice saved without touching these controls.
export const DEFAULT_SUPPLY_TYPE: SupplyType = "taxable";
export const DEFAULT_INVOICE_TYPE: InvoiceType = "Regular";

export interface ClassificationOption<T> {
  value: T;
  /** What the CA reads in the dropdown. */
  label: string;
  /** The statutory reason, shown as help text under the control. */
  note: string;
}

export const SUPPLY_TYPES: ReadonlyArray<ClassificationOption<SupplyType>> = [
  { value: "taxable",    label: "Taxable",    note: "An ordinary supply carrying GST." },
  { value: "zero_rated", label: "Zero-rated", note: "Export or SEZ supply — CGST §16(1)(a)." },
  { value: "nil_rated",  label: "Nil-rated",  note: "Taxable at 0%. Declared in GSTR-1 table 8, not as taxable turnover." },
  { value: "exempt",     label: "Exempt",     note: "Exempted under CGST §11. Declared in GSTR-1 table 8." },
  { value: "non_gst",    label: "Non-GST",    note: "Outside GST altogether (e.g. petrol, alcohol). GSTR-1 table 8." },
];

export const INVOICE_TYPES: ReadonlyArray<ClassificationOption<InvoiceType>> = [
  { value: "Regular",             label: "Regular",                 note: "A normal domestic supply." },
  { value: "SEZ_with_payment",    label: "SEZ with payment (IGST)", note: "Supply to an SEZ on payment of IGST — CGST §16(3)." },
  { value: "SEZ_without_payment", label: "SEZ under LUT/Bond",      note: "Supply to an SEZ without payment of tax — CGST §16(3)." },
  { value: "Deemed_export",       label: "Deemed export",           note: "Notified deemed export. Declared zero-rated." },
];

/** Editor state, before it becomes a payload. */
export interface ClassificationState {
  supplyType: SupplyType;
  invoiceType: InvoiceType;
  isReverseCharge: boolean;
}

/** What the create / draft-update endpoints receive. */
export interface ClassificationPayload {
  supply_type: SupplyType;
  invoice_type: InvoiceType;
  is_reverse_charge: boolean;
}

function isSupplyType(v: unknown): v is SupplyType {
  return SUPPLY_TYPES.some((o) => o.value === v);
}

function isInvoiceType(v: unknown): v is InvoiceType {
  return INVOICE_TYPES.some((o) => o.value === v);
}

/**
 * Read the classification off a loaded invoice (or a duplicate seed).
 *
 * Anything unrecognised falls back to the default rather than being passed
 * through. A duplicate seed is JSON out of localStorage and an invoice row may
 * predate a vocabulary change, so an unknown string here is plausible — and
 * sending one back would fail migration 268's CHECK constraint at save time,
 * turning a stale value into an unexplained error on an unrelated edit.
 */
export function classificationFrom(row: {
  supply_type?: string | null;
  invoice_type?: string | null;
  is_reverse_charge?: boolean | null;
} | null | undefined): ClassificationState {
  return {
    supplyType: isSupplyType(row?.supply_type) ? row.supply_type : DEFAULT_SUPPLY_TYPE,
    invoiceType: isInvoiceType(row?.invoice_type) ? row.invoice_type : DEFAULT_INVOICE_TYPE,
    isReverseCharge: !!row?.is_reverse_charge,
  };
}

/**
 * Editor state → API payload.
 *
 * All three are sent every time, including at their defaults. Omitting them
 * would leave the server to fall back — which is exactly the behaviour that
 * made every invoice look like a plain taxable sale — and it would mean a CA
 * who corrected an SEZ draft back to Regular could not save that correction.
 */
export function toClassificationPayload(state: ClassificationState): ClassificationPayload {
  return {
    supply_type: isSupplyType(state.supplyType) ? state.supplyType : DEFAULT_SUPPLY_TYPE,
    invoice_type: isInvoiceType(state.invoiceType) ? state.invoiceType : DEFAULT_INVOICE_TYPE,
    is_reverse_charge: !!state.isReverseCharge,
  };
}

/**
 * True when this invoice is anything other than a plain domestic taxable sale.
 *
 * Presentational only — it decides whether the form draws attention to the
 * classification, never what the invoice means.
 */
export function isNonStandard(state: ClassificationState): boolean {
  return state.supplyType !== DEFAULT_SUPPLY_TYPE
    || state.invoiceType !== DEFAULT_INVOICE_TYPE
    || state.isReverseCharge;
}
