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
import { parseLineAmounts } from "../money/lineInput.ts";
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
  /** CGST Act §17(5) — false means this line's GST is BLOCKED input tax credit.
   *
   *  NEVER INFERRED, and defaulted true (migration 240's own rule): the
   *  heuristic below only prompts, and a line the CA has not looked at must
   *  behave exactly as every line did before this field existed.
   *
   *  Optional in the type because a line built before this field existed —
   *  a duplicate seed, a draft rehydrated from the server — has neither key,
   *  and `undefined` has to mean eligible rather than "unknown".
   */
  itc_eligible?: boolean;
  /** The §17(5) clause, when itc_eligible is false. Free text by design
   *  (migration 240): the CA-facing wording may change without a migration. */
  blocked_credit_reason?: string;
}

/** A line is "valid" (postable) when it has positive qty & rate and a linked
 * Product/Service (mandatory on every line — migration 206). Description is
 * deliberately NOT required here — it's an optional field on the line. */
export function isValidBillLine(l: PurchaseBillLine): boolean {
  // parseLineAmounts REFUSES what parseFloat coerced. The old test was
  // `(parseFloat(l.rate) || 0) > 0`, and parseFloat("1,25,000") is 1 — so a
  // rate typed the way Indian amounts are grouped passed as a valid ONE RUPEE
  // line, previewed at ₹1 and saved at ₹1 with nothing said.
  return parseLineAmounts(l.qty, l.rate) !== null && !!l.service_catalogue_id;
}

/** ONE LINE PAYLOAD, sent to the TDS preview AND to the save.
 *
 *  The preview exists to show the CA the figure the save will produce, so it
 *  has to send the same lines; building them twice is how the two start
 *  disagreeing on the taxable base as well as on the rate.
 *
 *  It lives HERE rather than in the editor component so it can be tested under
 *  `node --test` — which is how PUR-05 was caught: `itc_eligible` had been on
 *  the API model, the column and the GSTR-3B computation since migration 240,
 *  and the payload builder simply did not carry it, with nothing able to say so.
 */
export interface BillLinePayload {
  description: string;
  hsn_sac?: string;
  quantity: number;
  unit?: string;
  rate_paise: number;
  gst_rate_percent: number;
  expense_account_id?: string;
  service_catalogue_id?: string;
  itc_eligible?: boolean;
  blocked_credit_reason?: string;
}

export function buildLinePayload(lines: PurchaseBillLine[]): BillLinePayload[] {
  return lines.filter(isValidBillLine).map((l) => ({
    description: l.description,
    hsn_sac: l.hsn_sac || undefined,
    quantity: parseLineAmounts(l.qty, l.rate)!.quantity,
    unit: l.unit || undefined,
    // Non-null by construction: the filter above is isValidBillLine, which is
    // parseLineAmounts itself. The old form was
    // Math.round((parseFloat(l.rate) || 0) * 100) — exact for a plain decimal
    // and silently 100 paise for "1,25,000".
    rate_paise: parseLineAmounts(l.qty, l.rate)!.ratePaise,
    gst_rate_percent: l.gst_rate,
    expense_account_id: l.expense_account_id || undefined,
    service_catalogue_id: l.service_catalogue_id || undefined,
    // CGST Act §17(5). Sent EXPLICITLY rather than omitted when true, so a line
    // the CA un-blocked reaches the server as eligible instead of keeping
    // whatever the stored row said.
    itc_eligible: lineIsItcEligible(l),
    blocked_credit_reason: lineIsItcEligible(l)
      ? undefined : (l.blocked_credit_reason || undefined),
  }));
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
    const parsed = parseLineAmounts(l.qty, l.rate);
    if (!parsed || !l.service_catalogue_id) continue;
    const g = dnLineGst(
      // quantity comes from the strict parse. The RATE stays the string
      // parseFloat'd, deliberately: dnLineGst takes rupees and delegates to
      // gstLine.ratePaiseFromRupees, which shared/gst-parity-vectors.json pins
      // to the Python backend on exactly these strings. Converting to paise and
      // dividing back would put a float round-trip inside the one calculation
      // that is pinned. What HAS changed is that parseLineAmounts above has
      // already refused anything but a plain decimal, so parseFloat can no
      // longer see "1,25,000" and answer 1.
      { quantity: parsed.quantity, rate: parseFloat(l.rate), gst_rate_bps: Math.round(l.gst_rate * 100) },
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
    /** CGST Act §17(5) — a line marked blocked with no clause named. */
    itc?: string;
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
  // §17(5) blocks the SAVE, not just the display. A line marked blocked with no
  // clause is a reversal in GSTR-3B Table 4(B)(1) that nobody can justify in an
  // assessment — and the flag would still reduce the claim, so letting it save
  // trades one unsupported figure for another.
  const itc = blockedCreditProblems(input.lines);
  if (itc.length) {
    errors.itc = itc.map((p) => `Line ${p.lineIndex + 1}: ${p.message}`).join(" ");
  }
  return { errors, ok: Object.keys(errors).length === 0 };
}

// ── CGST Act §17(5) — the clauses a CA picks from ───────────────────────────
//
// DATA, NOT LOGIC. Nothing here decides whether a line is blocked; it is the
// list of reasons §17(5) actually gives, so a CA who has decided says WHICH
// clause. The code is stored as free text on purpose (migration 240) because
// the CA-facing wording changes more often than the schema should.
//
// WHERE THE FIGURE GOES, since it is easy to assume: blocked credit is in
// GSTR-3B Table 4(A) GROSS — 4(A) is auto-populated from 2B and netting it
// would break the tie-up — and reversed in 4(B)(1) as a reversal "absolute in
// nature and not reclaimable". It is NOT repeated in 4(D). Notification
// 14/2022 with Circular 170/02/2022-GST; domain/gst/gstr3b_computer.py is the
// authority and already does this.

export interface BlockedCreditReason {
  code: string;
  clause: string;
  label: string;
  note?: string;
}

export const BLOCKED_CREDIT_REASONS: BlockedCreditReason[] = [
  { code: "17_5_a_motor_vehicle", clause: "§17(5)(a)",
    label: "Motor vehicle for transporting persons (≤13 seats)",
    note: "Unless used for further supply of such vehicles, passenger transport, or driving instruction." },
  { code: "17_5_aa_vessel_aircraft", clause: "§17(5)(aa)",
    label: "Vessel or aircraft",
    note: "Same exceptions, plus transport of goods." },
  { code: "17_5_ab_service_on_those", clause: "§17(5)(ab)",
    label: "Insurance, servicing or repair of the above" },
  { code: "17_5_b_food_beverage", clause: "§17(5)(b)(i)",
    label: "Food, beverages, outdoor catering, health services",
    note: "Unless the inward supply is used to make the same taxable outward supply." },
  { code: "17_5_b_club_membership", clause: "§17(5)(b)(ii)",
    label: "Club, health or fitness centre membership" },
  { code: "17_5_b_insurance", clause: "§17(5)(b)(iii)",
    label: "Life or health insurance",
    note: "Unless obligatory for the employer under a law in force." },
  { code: "17_5_b_travel_benefit", clause: "§17(5)(b)(iv)",
    label: "Travel benefit to employees on vacation (LTC)" },
  { code: "17_5_c_works_contract_immovable", clause: "§17(5)(c)",
    label: "Works contract for immovable property",
    note: "Unless it is an input service for a further works contract, or is plant and machinery." },
  { code: "17_5_d_own_account_immovable", clause: "§17(5)(d)",
    label: "Construction of immovable property on own account",
    note: "Including where it is used in the course of business. Plant and machinery is excepted." },
  { code: "17_5_e_composition", clause: "§17(5)(e)",
    label: "Supplies on which the supplier paid composition tax" },
  { code: "17_5_f_non_resident", clause: "§17(5)(f)",
    label: "Received by a non-resident taxable person",
    note: "Except goods imported by them." },
  { code: "17_5_g_personal_consumption", clause: "§17(5)(g)",
    label: "Goods or services for personal consumption" },
  { code: "17_5_h_gifts_samples_lost", clause: "§17(5)(h)",
    label: "Lost, stolen, destroyed, written off, or given as a gift or free sample" },
  { code: "17_5_i_demand", clause: "§17(5)(i)",
    label: "Tax paid on a demand under §74, §129 or §130" },
  { code: "other", clause: "§17(5)",
    label: "Other — recorded in the bill's notes" },
];

const REASON_CODES = new Set(BLOCKED_CREDIT_REASONS.map((r) => r.code));

/** A line is eligible unless it has been explicitly marked otherwise.
 *
 *  `undefined` is eligible, not unknown: migration 240 defaults the column to
 *  true so no bill written before the field existed changes meaning, and the
 *  editor has to agree with the column or a re-saved draft would flip. */
export function lineIsItcEligible(l: PurchaseBillLine): boolean {
  return l.itc_eligible !== false;
}

export interface BlockedCreditProblem { lineIndex: number; message: string }

/** A line marked ineligible must say under which clause.
 *
 *  Not decoration: `blocked_credit_reason` is what a CA reads back in an
 *  assessment two years later to justify the reversal, and §17(5) has fourteen
 *  clauses with different exceptions. "Blocked" with no clause is a figure
 *  nobody can defend.
 */
export function blockedCreditProblems(lines: PurchaseBillLine[]): BlockedCreditProblem[] {
  const out: BlockedCreditProblem[] = [];
  lines.forEach((l, i) => {
    if (lineIsItcEligible(l)) return;
    const reason = (l.blocked_credit_reason ?? "").trim();
    if (!reason) {
      out.push({ lineIndex: i, message: "Blocked ITC needs the §17(5) clause it is blocked under." });
    } else if (!REASON_CODES.has(reason)) {
      out.push({ lineIndex: i, message: `"${reason}" is not a §17(5) clause this form offers.` });
    }
  });
  return out;
}

/** The GST on the ineligible lines — what will be reversed in Table 4(B)(1).
 *
 *  A PREVIEW, computed the same way previewBillTotals computes the rest, so
 *  the CA sees the reversal before saving. The server recomputes it from the
 *  same lines; this never decides anything.
 */
export function ineligibleGstPaise(lines: PurchaseBillLine[], isInterstate: boolean): number {
  // previewBillTotals over the blocked lines, NOT a second GST calculation.
  // The rate string it passes to dnLineGst is pinned to the Python backend by
  // shared/gst-parity-vectors.json, and a copy here would be a second answer to
  // the one thing that is pinned.
  return previewBillTotals(lines.filter((l) => !lineIsItcEligible(l)), isInterstate).gst_paise;
}

/** The reason code a heuristic hit suggests, so the prompt and the control the
 *  CA then uses agree. Undefined where the hint has no single clause. */
export function reasonForHintLabel(label: string): string | undefined {
  return {
    "Motor vehicle": "17_5_a_motor_vehicle",
    "Food & beverages": "17_5_b_food_beverage",
    "Club / fitness membership": "17_5_b_club_membership",
    "Life / health insurance": "17_5_b_insurance",
    "Employee travel benefit": "17_5_b_travel_benefit",
  }[label];
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
