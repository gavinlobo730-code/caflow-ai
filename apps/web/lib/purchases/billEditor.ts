/**
 * Pure Purchase-Bill editor domain primitives — types, GST preview totals,
 * validation, and the CGST Act §17(5) blocked-credit heuristic. NO
 * framework/browser imports, so this is unit-testable under `node --test`.
 *
 * GST math reuses dnLineGst (debitNoteGst.ts) rather than re-deriving it —
 * that function already mirrors the backend's floor-based
 * `_compute_line_gst` (routers/purchase_bills.py) exactly. Purchase bills
 * carry no round-off (unlike sales invoices' Rule 46 presentation rounding
 * — see lib/invoices/gst.ts's previewRoundOffPaise, deliberately not
 * mirrored here since the backend purchase_bills schema has no
 * round_off_paise column).
 */
import { dnLineGst } from "./debitNoteGst.ts";

export interface PurchaseBillLine {
  description: string;
  hsn_sac: string;
  qty: string; // string-typed input, parsed on use (avoids controlled-input NaN churn)
  rate: string; // rupees
  gst_rate: number; // percent, e.g. 18
  unit: string;
  expense_account_id: string;
  service_catalogue_id: string;
}

/** A line is "valid" (postable) when it has positive qty & rate and a linked
 * Product/Service (mandatory on every line — migration 206). Description is
 * deliberately NOT required here — it's an optional field on the line. */
export function isValidBillLine(l: PurchaseBillLine): boolean {
  return (
    (parseFloat(l.qty) || 0) > 0 &&
    (parseFloat(l.rate) || 0) > 0 &&
    !!l.service_catalogue_id
  );
}

export interface BillPreviewTotals {
  taxable_paise: number;
  cgst_paise: number;
  sgst_paise: number;
  igst_paise: number;
  gst_paise: number;
  grand_total_paise: number;
}

export function previewBillTotals(lines: PurchaseBillLine[], isInterstate: boolean): BillPreviewTotals {
  let taxable = 0, cgst = 0, sgst = 0, igst = 0;
  for (const l of lines) {
    if (!isValidBillLine(l)) continue;
    const g = dnLineGst(
      { quantity: parseFloat(l.qty) || 0, rate: parseFloat(l.rate) || 0, gst_rate_bps: Math.round(l.gst_rate * 100) },
      isInterstate,
    );
    taxable += g.taxable_paise; cgst += g.cgst_paise; sgst += g.sgst_paise; igst += g.igst_paise;
  }
  const gst_paise = cgst + sgst + igst;
  return { taxable_paise: taxable, cgst_paise: cgst, sgst_paise: sgst, igst_paise: igst, gst_paise, grand_total_paise: taxable + gst_paise };
}

// ── Editor validation ────────────────────────────────────────────────────────
// Mirrors the minimums the backend enforces so the UI can block + explain
// BEFORE calling the API. The server remains authoritative.
export interface BillEditorValidationInput {
  vendorId: string;
  billDate: string;
  lines: PurchaseBillLine[];
  isForeign: boolean;
  exchangeRate: string;
}

export interface BillEditorValidation {
  errors: {
    vendor?: string;
    billDate?: string;
    lines?: string;
    exchangeRate?: string;
  };
  ok: boolean;
}

export function validateBillEditor(input: BillEditorValidationInput): BillEditorValidation {
  const errors: BillEditorValidation["errors"] = {};
  if (!input.vendorId) errors.vendor = "Select a vendor.";
  if (!input.billDate) errors.billDate = "Bill date is required.";
  if (input.lines.filter(isValidBillLine).length === 0) {
    errors.lines = "Add at least one line with a Product/Service, quantity and rate.";
  }
  if (input.isForeign && (!input.exchangeRate.trim() || !(parseFloat(input.exchangeRate) > 0))) {
    errors.exchangeRate = "Enter a valid exchange rate.";
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}

// ── CGST Act §17(5) blocked-credit heuristic ────────────────────────────────
// NOT a legal determination — a keyword heuristic against text the CA/vendor
// already typed (line description, picked expense account name), surfaced as
// a review prompt so a common blocked-ITC category doesn't slip through
// unnoticed. The CA can still save; this never blocks the save itself.
const BLOCKED_CREDIT_HINTS: { pattern: RegExp; label: string; note: string }[] = [
  {
    pattern: /\b(car|motor\s*vehicle|two[- ]?wheeler|scooter|motorcycle)\b/i,
    label: "Motor vehicle",
    note: "ITC on motor vehicles for transporting persons is blocked under §17(5)(a) unless used for further supply, passenger transport, or driving training.",
  },
  {
    pattern: /\b(food|beverage|catering|restaurant|canteen)\b/i,
    label: "Food & beverages",
    note: "ITC on food, beverages and outdoor catering is blocked under §17(5)(b)(i) unless it's an inward supply used to make the same taxable outward supply.",
  },
  {
    pattern: /\b(club|health\s*club|fitness|gym)\b/i,
    label: "Club / fitness membership",
    note: "ITC on club, health and fitness centre membership is blocked under §17(5)(b)(ii).",
  },
  {
    pattern: /\b(life\s*insurance|health\s*insurance|medical\s*insurance)\b/i,
    label: "Life / health insurance",
    note: "ITC on life and health insurance is blocked under §17(5)(b)(iii) unless notified as obligatory for employees or used to make the same outward supply.",
  },
  {
    pattern: /\b(travel|vacation|leave\s*travel|\bLTC\b|home\s*travel)\b/i,
    label: "Employee travel benefit",
    note: "ITC on travel benefits extended to employees on vacation (LTC) is blocked under §17(5)(b)(iv).",
  },
];

export interface BlockedCreditHit {
  lineIndex: number;
  label: string;
  note: string;
}

export function findBlockedCreditHits(
  lines: PurchaseBillLine[],
  expenseAccountNameById: Map<string, string>,
): BlockedCreditHit[] {
  const hits: BlockedCreditHit[] = [];
  lines.forEach((l, i) => {
    const haystack = `${l.description} ${expenseAccountNameById.get(l.expense_account_id) ?? ""}`;
    for (const h of BLOCKED_CREDIT_HINTS) {
      if (h.pattern.test(haystack)) { hits.push({ lineIndex: i, label: h.label, note: h.note }); break; }
    }
  });
  return hits;
}
