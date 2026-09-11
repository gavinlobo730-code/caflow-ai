/**
 * Pure Sales-Invoice domain primitives — types, the GST preview math, the Indian
 * state master, and status/delivery label maps. NO framework or browser imports, so
 * this module is unit-testable under `node --test` and safe to import anywhere.
 *
 * computeGst() delegates every per-line amount to lib/money/gstLine.ts, which
 * mirrors the backend's arithmetic exactly (integer paise, floor-then-split,
 * exact-decimal taxable). The preview therefore shows the same figures the
 * server will store — it is not an approximation. The backend remains the
 * authority; this just stops the two from ever disagreeing.
 */

import { bpsFromPercentInput } from "../money/rupeeInput.ts";
import { applyDiscountsToLines, computeLineGst, taxablePaise,
         quantityFromInput, ratePaiseFromRupees, splitLineGst,
         gstRateBpsFromPercent } from "../money/gstLine.ts";

/** GST rate slabs (%) offered in the invoice/credit-note line editors. */
export const GST_RATES = [0, 0.1, 0.25, 1, 1.5, 3, 5, 6, 7.5, 12, 18, 28];

// ── Types ────────────────────────────────────────────────────────────────────
export type InvoiceStatus = "draft" | "issued" | "partially_paid" | "paid" | "cancelled";

export interface Customer {
  id: string;
  name: string;
  gstin: string | null;
  state_code: string | null;
  pan: string | null;
  // IT Act §203A — set only when this customer DEDUCTS TDS on what it pays the
  // client. Form 26AS names a deductor by TAN alone, so it is what lets the
  // 26AS reconciliation match on identity rather than on the company name.
  tan: string | null;
  email: string | null;
  phone: string | null;
  city: string | null;
  state: string | null;
  opening_balance_paise: number;
  credit_days: number;
  is_active: boolean;
}

export interface SalesInvoice {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  customer_id: string;
  customer_name?: string;
  taxable_paise: number;
  gst_paise: number;
  total_paise: number;
  paid_paise?: number;
  /**
   * What is still recoverable: total + debit notes − paid − credited.
   *
   * A GENERATED column (migration 278), so it cannot drift from its parts, and
   * the only figure any screen should treat as "outstanding". `total_paise −
   * paid_paise` looks like the same thing and is not: it ignores §34 credit
   * notes entirely, so a ₹10,00,000 invoice with ₹8,00,000 collected and
   * ₹50,000 credited reads as ₹2,00,000 owing instead of ₹1,50,000 (SALES-05).
   *
   * Optional because older callers select it and some do not; `outstandingOf`
   * below is the one place that decides what to do when it is absent.
   */
  outstanding_paise?: number;
  status: InvoiceStatus;
  supply_state_code: string | null;
  is_interstate: boolean;
  // Collections metadata (server-maintained by the overdue sweep / reminders).
  is_overdue?: boolean;
  days_overdue?: number;
  reminder_count?: number;
  last_reminded_at?: string | null;
  // Multi-Currency (Phase 3 backend) — undefined/"INR" for a domestic invoice.
  /** CGST Rule 138(1) with Explanation 2, decided server-side and served with
   *  the invoice. See ComplianceInvoice.eway_assessment in lib/invoices/
   *  compliance.ts — the browser has a mirror, but only as a fallback. */
  eway_assessment?: import("@/lib/invoices/compliance").ServedEwayAssessment | null;
  txn_currency?: string | null;
  exchange_rate?: string | null;
  txn_total?: number | null;
  paid_txn?: number | null;
}

/**
 * What an invoice still has owing, from the server's own generated column.
 *
 * ONE PLACE, because the fallback is the interesting part. When
 * `outstanding_paise` was not selected we fall back to `total − paid`, which is
 * the OLD, wrong arithmetic — so the fallback is a bug waiting to be reached,
 * and having it in one named function means a screen that hits it can be found
 * by looking here rather than by re-reading five subtractions. Every caller in
 * the sales screen selects the column.
 */
export function outstandingOf(inv: Pick<SalesInvoice, "total_paise" | "paid_paise" | "outstanding_paise">): number {
  if (typeof inv.outstanding_paise === "number") return inv.outstanding_paise;
  return inv.total_paise - (inv.paid_paise ?? 0);
}

export interface InvoiceLine {
  description: string;
  hsn_sac: string;
  qty: string;
  rate: string; // in rupees
  gst_rate: number; // 0,5,12,18,28
  /** Unit of measure (UQC), e.g. "NOS", "KGS", "HRS". Blank = server default "NOS". */
  unit: string;
  /** service_catalogue pick for this line — mandatory on every line (migration 206). */
  serviceCatalogueId?: string | null;
  /**
   * A discount recorded in the invoice — CGST §15(3)(a) — as a PERCENTAGE, as
   * typed. Excluded from the value of supply, so the GST is charged on the net.
   *
   * The editor offers a percentage per line because a trade discount comes off
   * a price list; the API also accepts a flat `discount_paise` for an importer
   * or an integration, which is why the payload carries both shapes.
   *
   * Absent on a credit or debit note, which use this same type: §15(3)(b) — a
   * discount AFTER the supply — needs a pre-supply agreement and the
   * recipient's ITC reversal, and is the §34 note itself, not a field on it.
   */
  discountPercent?: string;
}

/** A document-level discount, already resolved to the units the server takes. */
export interface DocumentDiscount {
  percentBps?: number | null;
  amountPaise?: number | null;
}

/** Server line shape (from GET /api/sales-invoices/{id}). */
export interface ServerInvoiceLine {
  id?: string;
  description: string;
  hsn_sac: string | null;
  quantity: number;
  unit?: string | null;
  rate_paise: number;
  gst_rate_bps: number;
  taxable_amount_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  line_total_paise: number;
  /** Which service_catalogue preset (if any) this line was picked from — see
   * lib/invoices/lineItemPayload.ts's InvoiceLineInput.serviceCatalogueId. */
  service_catalogue_id?: string | null;
  /** §15(3)(a), migration 364. `discount_paise` includes this line's pro-rata
   *  share of any document-level discount; the percentage is only what was
   *  typed on the line itself, which is why an edit rehydrates that one. */
  discount_paise?: number | null;
  discount_percent_bps?: number | null;
}

/** Full invoice detail (header + lines + accounting + customer embed). */
export interface InvoiceDetail {
  id: string;
  invoice_no: string;
  invoice_date: string;
  due_date: string | null;
  credit_days?: number | null;
  customer_id: string;
  reference_no?: string | null;
  supply_state_code: string | null;
  is_interstate: boolean;
  // GSTR-1 classification (migration 268) — what the return is built from.
  // domain/gst/classifier.py branches on these to pick the table; see
  // lib/invoices/classification.ts for the vocabulary and its defaults.
  // Optional here because a duplicate seed may be older JSON, not because the
  // column is nullable — it is NOT NULL with a default.
  supply_type?: string | null;
  invoice_type?: string | null;
  is_reverse_charge?: boolean | null;
  // The shipping bill an export is refunded against (migration 349) — GSTR-1
  // Table 6A's sbnum / sbdt / sbpcode. Null on everything that is not an
  // export, which is most invoices, and null on an export whose shipping bill
  // customs has not issued yet.
  shipping_bill_no?: string | null;
  shipping_bill_date?: string | null;
  port_code?: string | null;
  notes: string | null;
  // Invoice-level round-off to the nearest ₹1 is opt-in (migration 247);
  // absent/false means the invoice carries its exact calculated amount.
  round_off_enabled?: boolean | null;
  round_off_paise?: number | null;
  taxable_amount_paise: number;
  /** §15(3)(a) totals for the whole invoice, migration 364. */
  discount_paise?: number | null;
  discount_percent_bps?: number | null;
  total_gst_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  paid_paise: number;
  // Sub-ledger corrections applied against this invoice (CGST Act §34) — a
  // credit note REDUCES the receivable, a (sales) debit note INCREASES it:
  //   net outstanding = (total_paise + debit_note_paise) - paid_paise - credited_paise
  credited_paise?: number;
  debit_note_paise?: number;
  status: InvoiceStatus;
  journal_entry_id: string | null;
  issued_at: string | null;
  created_by_name: string | null;
  customers?: { id: string; name: string; email: string | null; gstin: string | null; phone: string | null } | null;
  lines: ServerInvoiceLine[];
  // Multi-Currency (Phase 3 backend) — optional; absent/undefined or "INR" means
  // an ordinary INR invoice. Set once at creation, never editable afterward.
  /** CGST Rule 138(1) with Explanation 2, decided server-side and served with
   *  the invoice. See ComplianceInvoice.eway_assessment in lib/invoices/
   *  compliance.ts — the browser has a mirror, but only as a fallback. */
  eway_assessment?: import("@/lib/invoices/compliance").ServedEwayAssessment | null;
  txn_currency?: string | null;
  exchange_rate?: string | null;
  txn_total?: number | null;
  rate_overridden?: boolean | null;
}

/** ISO 4217 currency master row (Multi-Currency Phase 1 — GET /api/currencies). */
export interface CurrencyOption {
  code: string;
  symbol: string | null;
  display_name: string | null;
  minor_unit: number;
}

export const STATUS_BADGE: Record<string, string> = {
  draft: "bg-[#F1F5F9] text-[#64748B]",
  issued: "bg-blue-100 text-blue-700",
  partially_paid: "bg-amber-100 text-amber-700",
  paid: "bg-green-100 text-green-700",
  cancelled: "bg-red-100 text-red-600",
};

export interface InvoiceDelivery {
  id: string;
  invoice_id: string;
  sent_to: string;
  sent_by_email: string | null;
  status: "queued" | "sending" | "sent" | "failed" | "bounced";
  provider_message_id: string | null;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  kind?: "invoice" | "reminder";
}

/** Human labels for invoice_deliveries.status. */
export const DELIVERY_STATUS_LABEL: Record<string, string> = {
  queued: "Queued", sending: "Sending", sent: "Sent", failed: "Failed", bounced: "Bounced",
};

/**
 * Sum a document's lines into stored-shape paise.
 *
 * The per-line arithmetic lives in lib/money/gstLine.ts, which mirrors the
 * backend operation for operation — so this is an exact projection of what the
 * server will persist, not an approximation of it. Do not inline GST math here.
 */
export function computeGst(
  lines: InvoiceLine[],
  isInterstate: boolean,
  discount?: DocumentDiscount,
): {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  total_paise: number;
  /** Gross before any §15(3)(a) discount — taxable + discount, by construction. */
  gross_paise: number;
  discount_paise: number;
} {
  let taxable_paise = 0;
  let cgst_paise = 0;
  let sgst_paise = 0;
  let igst_paise = 0;
  let gross_paise = 0;
  let discount_paise = 0;

  // §15(3)(a): the discount is excluded from the VALUE of supply, so it comes
  // off before the tax. Resolved for the whole document at once because a
  // document-level discount is allocated pro-rata and a line cannot know its
  // own share until every line's own discount is settled — the same reason,
  // and the same module, as apps/api/routers/sales_invoices.py.
  const gross = lines.map((l) =>
    taxablePaise(quantityFromInput(l.qty), ratePaiseFromRupees(l.rate)));
  const resolved = applyDiscountsToLines(
    lines.map((l, i) => ({
      gross_paise: gross[i],
      discount_percent_bps: percentBpsOf(l.discountPercent),
    })),
    discount?.percentBps,
    discount?.amountPaise,
  );

  lines.forEach((line, i) => {
    gross_paise += gross[i];
    if (resolved) {
      // The discounted path. splitLineGst rather than computeLineGst, because
      // the taxable value has already been settled above.
      const r = resolved[i];
      const h = splitLineGst(r.taxable_paise, gstRateBpsFromPercent(line.gst_rate), isInterstate);
      discount_paise += r.discount_paise;
      taxable_paise += r.taxable_paise;
      cgst_paise += h.cgst_paise;
      sgst_paise += h.sgst_paise;
      igst_paise += h.igst_paise;
      return;
    }
    // The server would refuse this discount (larger than the line, or than the
    // bill). Preview the UNDISCOUNTED figures rather than an invented capped
    // one: the editor's validation is what tells the CA, and a preview that
    // quietly applied a different discount would be the drift this whole
    // module exists to prevent.
    const g = computeLineGst(line, isInterstate);
    taxable_paise += g.taxable_paise;
    cgst_paise    += g.cgst_paise;
    sgst_paise    += g.sgst_paise;
    igst_paise    += g.igst_paise;
  });

  const gst_paise = igst_paise + cgst_paise + sgst_paise;
  const total_paise = taxable_paise + gst_paise;
  return { taxable_paise, cgst_paise, sgst_paise, igst_paise, total_paise,
           gross_paise, discount_paise };
}

/**
 * A typed discount percentage → basis points, or null for "no discount".
 *
 * Delegates to lib/money/rupeeInput.bpsFromPercentInput, which is the one
 * parser: "5" is 500 bps, "2.5" is 250, and anything that is not a number at
 * all is refused rather than silently becoming 0. A blank cell means no
 * discount, which is not the same as a 0% one — but both compute to nothing,
 * so they are one value here.
 */
export function percentBpsOf(typed?: string | null): number | null {
  if (typed === undefined || typed === null || typed.trim() === "") return null;
  const bps = bpsFromPercentInput(typed.trim());
  return bps === null ? null : bps;
}

// ── Indian state master (GST state codes) ────────────────────────────────────
// RE-EXPORTED, not redefined. This file used to hold its own thirty-entry copy
// — missing Goa, Puducherry, Ladakh, DNH&DD, Lakshadweep and Andaman &
// Nicobar — and InvoiceEditor and CustomerFormModal passed it to StateLookup
// explicitly, so it OVERRODE the complete list StateLookup defaults to. Two
// lists in one tree is how a picker silently loses six states and UTs.
//
// Relative path on purpose: this module is the pure layer (see ./shared's
// header) and must stay importable under node with no "@/" alias.
export { INDIAN_STATES, type IndianState } from "../constants/indianStates.ts";


// ── Totals preview (Batch 3) ─────────────────────────────────────────────────
// Live totals for the editor summary. Preview only — the backend is authoritative.
// The round-off mirror matches the Batch 1 rule (nearest ₹1, half-up) so the grand
// total previews on a whole rupee, exactly as the posted invoice will.
export function previewRoundOffPaise(amountPaise: number): number {
  const remainder = ((amountPaise % 100) + 100) % 100; // safe for negatives
  if (remainder === 0) return 0;
  return remainder < 50 ? -remainder : 100 - remainder;
}

export interface PreviewTotals {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  gst_paise: number;
  round_off_paise: number;
  grand_total_paise: number;
  /** Gross before any §15(3)(a) discount. Absent on callers that predate it. */
  gross_paise?: number;
  discount_paise?: number;
}

/**
 * Compute previewed totals for the summary panel. `applyRoundOff` mirrors what
 * the backend will actually do, so the preview never disagrees with the saved
 * invoice. It is true ONLY for an INR invoice whose round_off_enabled flag is
 * on — round-off became opt-in per invoice in migration 247. Foreign-currency
 * documents, and sales credit/debit notes, are never rupee-rounded.
 *
 * Defaults to FALSE (exact amount) so a caller that omits it gets the safe,
 * un-rounded total rather than silently re-introducing mandatory rounding.
 */
export function previewTotals(
  lines: InvoiceLine[],
  isInterstate: boolean,
  applyRoundOff: boolean = false,
  discount?: DocumentDiscount,
): PreviewTotals {
  const g = computeGst(lines, isInterstate, discount);
  const gst = g.cgst_paise + g.sgst_paise + g.igst_paise;
  const round_off = applyRoundOff ? previewRoundOffPaise(g.total_paise) : 0;
  return {
    taxable_paise: g.taxable_paise,
    cgst_paise: g.cgst_paise,
    sgst_paise: g.sgst_paise,
    igst_paise: g.igst_paise,
    gst_paise: gst,
    round_off_paise: round_off,
    grand_total_paise: g.total_paise + round_off,
    gross_paise: g.gross_paise,
    discount_paise: g.discount_paise,
  };
}


// ── Editor validation (Batch 3) ──────────────────────────────────────────────
// Mirrors the minimums the backend enforces so the UI can block + explain BEFORE
// calling the API. The server remains authoritative.
// The place-of-supply code set, from the module that already owns it. See the
// note on isValidStateCode for why this is NOT lib/gst/gstin.ts's list.
import { isValidStateCode } from "./compliance.ts";

export interface EditorValidationInput {
  customerId: string;
  invoiceNo: string;
  invoiceDate: string;
  lines: InvoiceLine[];
  isForeign: boolean;
  exchangeRate: string;
  /** The 2-digit place of supply as the editor has it, blank if unset. CGST
   *  Rule 46(n) requires it on a tax invoice and GSTR-1 is rejected without a
   *  valid state code, so it is checked HERE — the CA is at the keyboard now,
   *  and the alternative is meeting the error at the return build weeks later
   *  on an invoice already issued, posted and sent (SALES-29). */
  supplyStateCode?: string | null;
  /** What the invoice declares about the supply (migration 268). */
  supplyType?: string | null;
  isReverseCharge?: boolean | null;
}

export interface EditorValidation {
  errors: {
    customer?: string;
    invoiceNo?: string;
    invoiceDate?: string;
    lines?: string;
    exchangeRate?: string;
    supplyState?: string;
    supplyType?: string;
  };
  /** Number of lines that carry a description + positive qty + positive rate. */
  validLineCount: number;
  ok: boolean;
}

/** CGST Rule 46(b): a tax invoice's serial number must be a consecutive serial
 * number not exceeding sixteen characters, using only alphabets, numerals,
 * and the special characters '-' and '/'. Numbering itself is fully manual
 * (the CA types it) — this only enforces the structural shape the law
 * requires; per-client uniqueness is checked server-side (the client can't
 * see every other draft/issued number to check itself). */
const INVOICE_NO_RE = /^[A-Za-z0-9\-/]{1,16}$/;

export function validateInvoiceNo(invoiceNo: string): string | undefined {
  const v = invoiceNo.trim();
  if (!v) return "Invoice number is required.";
  if (!INVOICE_NO_RE.test(v)) {
    return "Only letters, digits, '-' and '/' are allowed, up to 16 characters (CGST Rule 46(b)).";
  }
  return undefined;
}

/** A line is "valid" (postable) when it has positive qty & rate and a linked
 * Product/Service (mandatory on every line — migration 206). Description is
 * deliberately NOT required here — it's an optional field on the line. */
export function isValidLine(l: InvoiceLine): boolean {
  return (
    (parseFloat(l.qty) || 0) > 0 &&
    (parseFloat(l.rate) || 0) > 0 &&
    !!l.serviceCatalogueId
  );
}

/** Nil-rated, exempt and non-GST all assert that no tax is chargeable.
 *  ZERO-RATED IS DELIBERATELY ABSENT: §16(3)(b) lets an exporter or SEZ
 *  supplier supply ON PAYMENT of IGST and reclaim it under §54, so a
 *  zero-rated invoice carrying tax is lawful. Mirrors
 *  apps/api/domain/gst/supply_classification.UNTAXED_SUPPLY_TYPES. */
const UNTAXED_SUPPLY_TYPES = new Set(["nil_rated", "exempt", "non_gst"]);

function isUntaxedSupplyType(t: string | null | undefined): boolean {
  return UNTAXED_SUPPLY_TYPES.has((t ?? "taxable").trim().toLowerCase());
}

function hasTaxOnAnUntaxedSupply(input: EditorValidationInput): boolean {
  if (!isUntaxedSupplyType(input.supplyType) && !input.isReverseCharge) return false;
  return input.lines.some((l) => isValidLine(l) && Number(l.gst_rate ?? 0) > 0);
}

export function validateInvoiceEditor(input: EditorValidationInput): EditorValidation {
  const errors: EditorValidation["errors"] = {};
  if (!input.customerId) errors.customer = "Select a customer.";
  errors.invoiceNo = validateInvoiceNo(input.invoiceNo);
  if (!errors.invoiceNo) delete errors.invoiceNo;
  if (!input.invoiceDate) errors.invoiceDate = "Invoice date is required.";

  const validLineCount = input.lines.filter(isValidLine).length;
  if (validLineCount === 0) {
    errors.lines = "Add at least one line with a Product/Service, quantity and rate.";
  }

  if (input.isForeign && (!input.exchangeRate.trim() || !(parseFloat(input.exchangeRate) > 0))) {
    errors.exchangeRate = "Enter a valid exchange rate.";
  }

  // A place of supply — CGST Rule 46(n). The server requires a valid one at
  // ISSUE; stopping the CA here means they fix it while the invoice is still a
  // draft rather than after it has gone to the customer.
  const pos = (input.supplyStateCode ?? "").trim();
  if (pos && !isValidStateCode(pos)) {
    errors.supplyState = `"${pos}" is not a valid GST state code.`;
  }

  // The classification must not contradict the tax the lines carry (SALES-16).
  // apps/api/domain/gst/supply_classification.py is the authority and refuses
  // the same invoice; this is the same message at the point of entry.
  if (hasTaxOnAnUntaxedSupply(input)) {
    errors.supplyType = input.isReverseCharge && !isUntaxedSupplyType(input.supplyType)
      ? "Reverse charge means the recipient pays the tax (CGST §9(3)/(4), Rule 46(p)) — set the line rates to 0% or untick reverse charge."
      : "A nil-rated, exempt or non-GST supply attracts no tax (CGST §2(47)/§2(78)) — set the line rates to 0% or change the supply type to Taxable.";
  }

  return { errors, validLineCount, ok: Object.keys(errors).length === 0 };
}
