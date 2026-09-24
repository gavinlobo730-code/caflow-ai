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
//
// EXPORTED so lib/invoices/gst.ts's editor validation uses this one rather than
// a third list. There are already two in the browser and they differ for a
// reason: lib/gst/gstin.ts's set is GSTIN PREFIXES (99, Centre Jurisdiction, is
// one; 96 never is), and this one is PLACES OF SUPPLY (96, outside India, is one
// on an export; 99 never is). They are not the same question, so they are not
// merged — but there must not be a third.
export function isValidStateCode(code: string): boolean {
  if (!/^\d{2}$/.test(code)) return false;
  const n = Number(code);
  return (n >= 1 && n <= 38) || n === 96 || n === 97;
}
// CGST Act §25 GSTIN: 2-digit state + PAN(10) + entity + Z + check.
//
// SHAPE ONLY, DELIBERATELY, AND THIS IS THE ONE PLACE IN THE BROWSER THAT MAY
// SAY SO. Everywhere a human TYPES or an importer READS a GSTIN now goes
// through `lib/gst/gstin.gstinProblem`, which tests the check digit. Here the
// question is not "is this the right registration" but "is the recipient a
// registered person at all" — Rule 48(4)'s supply limb and Rule 138's — and
// `apps/api/domain/gst/irn_scope.py` answers it on the shape for a recorded
// reason: a checksum would put the two implementations in disagreement on a
// transposition, which says nothing about WHO the customer is. The parity
// vectors in shared/irn-parity-vectors.json pin that agreement, so tightening
// this regex breaks them. `tests/test_one_gstin_rule_in_the_browser.py` carries
// the exemption with this reason.
const GSTIN_RE = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/;

/** E-Way Bill threshold — Rule 138(1), ₹50,000 of CONSIGNMENT value. In paise.
 *
 *  Not the taxable value. Explanation 2 to Rule 138(1) measures it including
 *  the tax and cess charged in the document; see `assessEway` below and
 *  apps/api/domain/gst/eway.py, which is the authority. */
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
  /** The document's own lines, which is what Rule 138's consignment value is
   *  measured on — per line, including tax, excluding exempt goods where the
   *  invoice carries both. `taxable_amount_paise` above cannot answer it. */
  lines?: EwayLine[];
  /** What the SERVER decided — `eway_assessment` off GET /api/sales-invoices/
   *  {id}, computed by apps/api/domain/gst/eway.py, which is the authority.
   *  `assessEway` below is a FALLBACK for the window where this frontend has
   *  redeployed ahead of the backend, and is pinned to that module by
   *  shared/eway-parity-vectors.json. Same arrangement, and same reason, as
   *  lib/accounting/scheduleIiiCaptions.ts. */
  eway_assessment?: ServedEwayAssessment | null;
  /** The invoice's own date, ISO YYYY-MM-DD. Rule 48(4)'s threshold has been
   *  notified downward six times, and it is the DATE OF THE DOCUMENT that
   *  decides which one governs — a 2021 invoice keeps 2021's threshold for
   *  ever. Only the browser FALLBACK reads it; the served answer carries the
   *  threshold it already resolved. */
  invoice_date?: string | null;
  /** What the SERVER decided about Rule 48(4) — `irn_assessment` off
   *  GET /api/sales-invoices/{id}, computed by apps/api/domain/gst/irn_scope.py,
   *  which is the authority. `assessIrnScope` below is a FALLBACK for the
   *  window where this frontend has redeployed ahead of the backend, and is
   *  pinned to that module by shared/irn-parity-vectors.json. Same arrangement,
   *  and same reason, as `eway_assessment` above. */
  irn_assessment?: ServedIrnScope | null;
}

/** The server's own answer, in its wire spelling. */
export interface ServedEwayAssessment {
  consignment_value_paise: number;
  threshold_paise: number;
  exceeds_threshold: boolean;
  goods_lines: number;
  service_lines: number;
  unclassified_lines: number;
  excluded_exempt_paise: number;
  verdict: "required" | "not_required" | "undetermined";
  reason: string;
  gaps: string[];
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
 * IRN eligibility (CGST Rule 48(4)).
 *
 * THE SCOPE TEST IS THE SERVER'S. apps/api/domain/gst/irn_scope.py is the
 * authority and `assessIrnScope` below is a FALLBACK for the window where this
 * frontend has redeployed ahead of the backend, pinned to it by
 * shared/irn-parity-vectors.json — the same arrangement, and the same reason,
 * as `assessEway` above and lib/accounting/scheduleIiiCaptions.ts.
 *
 * Until SALES-18 this function WAS the only implementation of Rule 48(4) in the
 * repository, which is the defect: a statutory rule in the browser bundle has
 * no Python twin to disagree with it and no parity vector to fail. It also
 * declined the entire person-side limb with one fixed sentence on every
 * invoice — "E-invoicing applies only above your firm's turnover threshold" —
 * because nothing held an aggregate turnover. Migration 401 does now, so the
 * server answers that limb and the sentence is a real figure.
 *
 * WHAT BLOCKS AND WHAT MERELY WARNS. The SUPPLY limb blocks: preparing an IRN
 * record for a B2C invoice is meaningless and the IRP rejects it. The PERSON
 * limb only warns — the recorded turnover may be stale or absent, this is a
 * prepare-only workflow, and refusing on a figure a CA has not got round to
 * recording would stop them doing the one thing the screen is for.
 */
export function irnEligibility(inv: ComplianceInvoice, alreadyGenerated: boolean): Eligibility {
  const blockers: string[] = [];
  const warnings: string[] = [];
  if (!isPosted(inv.status)) blockers.push("Issue the invoice before generating an IRN.");
  if (alreadyGenerated) blockers.push("An active IRN already exists for this invoice.");

  // THE SERVER'S ANSWER FIRST; the `??` reaches the mirror only where the
  // backend has not redeployed yet. The mirror passes `null` for the turnover
  // because the browser holds none — which `assessIrnScope` reports as the
  // strict reading with a named gap rather than as "below the threshold".
  const scope = fromServedIrn(inv.irn_assessment) ?? assessIrnScope({
    treatment: gstTreatment(inv).treatment,
    recipient_gstin: inv.recipient_gstin ?? null,
    invoice_date: inv.invoice_date ?? "",
    highest_aato_paise: null,
  });

  if (!scope.supplyInScope) blockers.push(scope.supplyReason);
  else warnings.push(scope.reason);
  for (const gap of scope.gaps) warnings.push(gap);

  for (const i of validateMandatoryGstFields(inv)) {
    (i.severity === "error" ? blockers : warnings).push(i.message);
  }
  return { eligible: blockers.length === 0, blockers, warnings };
}

// ── Rule 48(4): must this supply carry an IRN? ───────────────────────────────
//
// MIRRORS apps/api/domain/gst/irn_scope.py, WHICH IS THE AUTHORITY. The rule
// exists twice because this panel recomputes on every keystroke and a round
// trip per keystroke is not a panel — the same reason `assessEway` above
// mirrors domain/gst/eway.py. The two are pinned by
// shared/irn-parity-vectors.json, read by apps/api/tests/test_irn_parity.py
// there and scripts/irn-parity.test.ts here. Change one without the other and
// both suites fail, which is the point.
//
// ⚠️ EVERY THRESHOLD AND DATE BELOW IS [S]-GRADED — written from knowledge
// because egress to .gov.in is refused at this environment's proxy. The Python
// module carries the full reasoning and
// tests/test_which_supplies_must_carry_an_irn.py pins each figure exactly.

/** No class of registered person was notified under Rule 48(4) before this. */
export const IRN_COMMENCEMENT = "2020-10-01";

/** (in force from, threshold in paise, notification), oldest first. */
export const IRN_THRESHOLDS: ReadonlyArray<readonly [string, number, string]> = [
  ["2020-10-01", 500_00_00_000_00, "Notification 61/2020-Central Tax"],
  ["2021-01-01", 100_00_00_000_00, "Notification 88/2020-Central Tax"],
  ["2021-04-01",  50_00_00_000_00, "Notification 05/2021-Central Tax"],
  ["2022-04-01",  20_00_00_000_00, "Notification 01/2022-Central Tax"],
  ["2022-10-01",  10_00_00_000_00, "Notification 17/2022-Central Tax"],
  ["2023-08-01",   5_00_00_000_00, "Notification 10/2023-Central Tax"],
];

/** The first proviso to Rule 48(4), named rather than guessed either way. */
export const IRN_EXEMPTED_CLASSES = [
  "a Special Economic Zone UNIT (as the supplier — a supply MADE TO an SEZ unit or developer is in scope)",
  "an insurer, a banking company or a financial institution including an NBFC",
  "a goods transport agency supplying services in relation to transportation of goods by road in a goods carriage",
  "a supplier of passenger transportation service",
  "a supplier of services by way of admission to the exhibition of cinematograph films in multiplex screens",
  "a government department or a local authority",
];

export const IRN_TURNOVER_NOT_RECORDED =
  "No aggregate turnover is recorded for this client, so the strictest " +
  "reading of Rule 48(4) is shown. CGST §2(6) aggregate turnover is " +
  "all-India on the PAN and includes exempt supplies, exports and " +
  "inter-State supplies between distinct persons, so it cannot be derived " +
  "from one client's books — record it on the client's GST settings.";

export const IRN_GSTIN_MALFORMED =
  "The customer's GSTIN is recorded but is not a well-formed GSTIN, so " +
  "whether this is a B2B supply cannot be read off the invoice. It is " +
  "treated as B2B, which is the direction that cannot omit a required IRN — " +
  "correct the customer's GSTIN.";

/** One value the e-invoice portal would refuse, in the server's wire spelling.
 *
 *  A SECOND AUTHORITY, NOT MORE `gaps` (GST-32). `gaps` are about Rule 48(4) —
 *  what this module could not decide about whether an IRN is owed. These are
 *  the IRP's own published acceptance rules, which are STRICTER than the Act:
 *  its `Document_Num` expression takes a first character of a letter or 1-9
 *  only, so `0001` is a lawful CGST Rule 46(b) number the portal rejects.
 *  `domain/gst/irp_validations.py` is the authority and there is deliberately
 *  no mirror of it here — this is a fact about a portal, not about an invoice,
 *  and the browser has nothing to decide. */
export interface ServedIrpFinding {
  /** The IRP's own name for the field, so it lines up with the portal's error. */
  field: string;
  value: string;
  reason: string;
  source: string;
}

/** The server's own answer, in its wire spelling. */
export interface ServedIrnScope {
  verdict: "required" | "not_required";
  supply_in_scope: boolean;
  supply_reason: string;
  threshold_paise: number | null;
  threshold_citation: string;
  turnover_paise: number | null;
  turnover_exceeds: boolean | null;
  turnover_unknown: boolean;
  reason: string;
  gaps: string[];
  irp_findings?: ServedIrpFinding[];
}

export interface IrnScope {
  verdict: "required" | "not_required";
  supplyInScope: boolean;
  supplyReason: string;
  thresholdPaise: number | null;
  thresholdCitation: string;
  turnoverPaise: number | null;
  turnoverExceeds: boolean | null;
  turnoverUnknown: boolean;
  reason: string;
  gaps: string[];
  /** Empty where the backend has not redeployed, which reads the same as a
   *  document with nothing wrong — safe, because these only ever ADD a
   *  warning to a verdict the Act's own rule has already decided. */
  irpFindings: ServedIrpFinding[];
}

/** The served answer in this module's own vocabulary, or null where the
 *  backend did not send one. */
export function fromServedIrn(served: ServedIrnScope | null | undefined): IrnScope | null {
  if (!served) return null;
  return {
    verdict: served.verdict,
    supplyInScope: served.supply_in_scope,
    supplyReason: served.supply_reason,
    thresholdPaise: served.threshold_paise,
    thresholdCitation: served.threshold_citation,
    turnoverPaise: served.turnover_paise,
    turnoverExceeds: served.turnover_exceeds,
    turnoverUnknown: served.turnover_unknown,
    reason: served.reason,
    gaps: served.gaps ?? [],
    irpFindings: served.irp_findings ?? [],
  };
}

export const IRN_INVOICE_DATE_NOT_RECORDED =
  "This invoice carries no date, so which of Rule 48(4)'s six notified " +
  "thresholds governs it cannot be resolved. The STRICTEST (most recent) is " +
  "shown, because an absent date is not a pre-2020 date and reading it as " +
  "one would report that no IRN is owed — the direction Rule 48(5) makes " +
  "expensive.";

/** The Rule 48(4) threshold in force on this invoice's own DATE. A 2021
 *  invoice keeps 2021's threshold for ever — the fork shape.
 *
 *  AN ABSENT DATE IS NOT A PRE-COMMENCEMENT DATE. Collapsing the two would
 *  report an undated invoice as owing no IRN, which Rule 48(5) makes the
 *  expensive direction — so a missing date takes the STRICTEST threshold and
 *  flags itself, and only a real date before commencement answers null. */
export function irnThresholdFor(
  invoiceDate: string,
): { paise: number | null; citation: string; dateMissing: boolean } {
  const day = (invoiceDate ?? "").trim().slice(0, 10);
  if (!day) {
    const latest = IRN_THRESHOLDS[IRN_THRESHOLDS.length - 1];
    return { paise: latest[1], citation: latest[2], dateMissing: true };
  }
  if (day < IRN_COMMENCEMENT) {
    return {
      paise: null,
      citation: `Rule 48(4) — no class of registered person was notified before ${IRN_COMMENCEMENT}`,
      dateMissing: false,
    };
  }
  let chosen = IRN_THRESHOLDS[0];
  for (const step of IRN_THRESHOLDS) {
    if (day >= step[0]) chosen = step;
    else break;
  }
  return { paise: chosen[1], citation: chosen[2], dateMissing: false };
}

/** Is the recipient a registered person? THREE states, and the third is named
 *  rather than guessed — reading a mistyped GSTIN as "unregistered" takes the
 *  invoice out of Rule 48(4) and Rule 48(5) then voids it. Shape only: this
 *  decides B2B-vs-B2C, not whether a human typed a valid check digit. */
export function irnRegistrationState(
  recipientGstin: string | null | undefined,
): "registered" | "unregistered" | "malformed" {
  const clean = (recipientGstin ?? "").trim().toUpperCase();
  if (!clean) return "unregistered";
  return GSTIN_RE.test(clean) ? "registered" : "malformed";
}

/** ₹ with Indian digit grouping, whole rupees. */
function rupeesGrouped(paise: number): string {
  return "₹" + new Intl.NumberFormat("en-IN").format(Math.floor(Math.abs(paise) / 100));
}

function exemptedClassesSentence(): string {
  return (
    "The first proviso to Rule 48(4) exempts some classes of registered " +
    "person from e-invoicing however large their turnover, and this " +
    "product does not record which class a client is in: " +
    IRN_EXEMPTED_CLASSES.join("; ") +
    ". Confirm the client is not one of them."
  );
}

export interface IrnScopeInput {
  treatment: GstTreatment | null;
  recipient_gstin: string | null;
  invoice_date: string;
  /** The HIGHEST aggregate turnover across every qualifying financial year —
   *  Rule 48(4) latches ("any preceding financial year from 2017-18 onwards").
   *  `null` means nobody has recorded one, which is NOT zero. */
  highest_aato_paise: number | null;
}

export function assessIrnScope(input: IrnScopeInput): IrnScope {
  const out: IrnScope = {
    verdict: "not_required", supplyInScope: false, supplyReason: "",
    thresholdPaise: null, thresholdCitation: "", turnoverPaise: null,
    turnoverExceeds: null, turnoverUnknown: false, reason: "", gaps: [],
    // ALWAYS EMPTY IN THE FALLBACK, and that is the honest answer rather than
    // a gap: whether the e-invoice PORTAL would accept a value is a fact about
    // the portal's own published rules, which live in
    // `domain/gst/irp_validations.py` and are deliberately not mirrored here.
    // This function exists for the window where the browser has redeployed
    // ahead of the backend; in that window there is no served answer, and
    // inventing one would be the second implementation SALES-18 removed.
    irpFindings: [],
  };

  // ── The SUPPLY limb. The treatment is asked FIRST: an export or an SEZ
  // supply is in scope whatever the buyer's registration, so collapsing this
  // into a single GSTIN test would take every export out of scope.
  const kind = (input.treatment ?? "regular").trim().toLowerCase();
  if (kind !== "regular") {
    out.supplyInScope = true;
    out.supplyReason =
      `Rule 48(4) reaches this supply on its own footing (${kind.replace(/_/g, " ")}): ` +
      "the sub-rule names exports, and a supply to a Special Economic Zone is a " +
      "zero-rated supply under IGST §16(1)(b). The recipient's registration does " +
      "not enter it.";
  } else {
    const state = irnRegistrationState(input.recipient_gstin);
    if (state === "registered") {
      out.supplyInScope = true;
      out.supplyReason =
        "Rule 48(4) reaches a supply made to a REGISTERED person, and the " +
        "customer's GSTIN is recorded on this invoice (B2B).";
    } else if (state === "malformed") {
      out.supplyInScope = true;
      out.supplyReason =
        "The customer's GSTIN is not well-formed, so this is read as a B2B " +
        "supply — the direction that cannot omit a required IRN.";
      out.gaps.push(IRN_GSTIN_MALFORMED);
    } else {
      out.supplyInScope = false;
      out.supplyReason =
        "Rule 48(4) reaches a supply to a registered person, an export or a " +
        "supply to an SEZ. This is an ordinary domestic supply to an " +
        "unregistered recipient (B2C), which the sub-rule does not reach.";
    }
  }

  const threshold = irnThresholdFor(input.invoice_date);
  out.thresholdPaise = threshold.paise;
  out.thresholdCitation = threshold.citation;
  out.turnoverPaise = input.highest_aato_paise;

  // The supply limb SHORT-CIRCUITS. A B2C invoice is outside Rule 48(4) at any
  // turnover, so reporting on the person limb beside it would be true and
  // irrelevant — and naming the exempted classes there would send a CA to
  // check a proviso that cannot change the answer.
  if (!out.supplyInScope) {
    out.verdict = "not_required";
    out.reason = out.supplyReason;
    return out;
  }

  // Named only once the supply limb has passed, for the same reason the
  // exempted classes are: on a B2C invoice the threshold decides nothing, so
  // the missing date decides nothing either.
  if (threshold.dateMissing) out.gaps.push(IRN_INVOICE_DATE_NOT_RECORDED);

  if (threshold.paise === null) {
    out.verdict = "not_required";
    out.reason =
      `Rule 48(4) notified no class of registered person before ${IRN_COMMENCEMENT}, ` +
      `so an invoice dated ${input.invoice_date} owes no IRN whatever the turnover.`;
    return out;
  }

  if (input.highest_aato_paise === null || input.highest_aato_paise === undefined) {
    out.turnoverUnknown = true;
    out.turnoverExceeds = null;
    out.verdict = "required";
    out.reason =
      `${out.supplyReason} The threshold on this invoice's date is ` +
      `${rupeesGrouped(threshold.paise)} (${threshold.citation}), and no aggregate ` +
      "turnover is recorded for this client — the strictest reading is shown.";
    out.gaps.push(IRN_TURNOVER_NOT_RECORDED);
    out.gaps.push(exemptedClassesSentence());
    return out;
  }

  // "EXCEEDS" — a strict inequality, as in Rule 138(1)'s ₹50,000.
  out.turnoverExceeds = input.highest_aato_paise > threshold.paise;
  if (!out.turnoverExceeds) {
    out.verdict = "not_required";
    out.reason =
      `The highest aggregate turnover recorded for this client is ` +
      `${rupeesGrouped(input.highest_aato_paise)}, which does not exceed the ` +
      `${rupeesGrouped(threshold.paise)} threshold in force on this invoice's date ` +
      `(${threshold.citation}).`;
    return out;
  }

  out.verdict = "required";
  out.reason =
    `${out.supplyReason} The client's recorded aggregate turnover reaches ` +
    `${rupeesGrouped(input.highest_aato_paise)}, above the ` +
    `${rupeesGrouped(threshold.paise)} threshold in force on this invoice's date ` +
    `(${threshold.citation}). Rule 48(5): an invoice this sub-rule reaches, issued ` +
    "without an IRN, is not treated as an invoice — the recipient's input tax " +
    "credit goes with it.";
  out.gaps.push(exemptedClassesSentence());
  return out;
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

  // THE THRESHOLD IS MEASURED ON THE CONSIGNMENT VALUE (SALES-17). This read
  // `inv.taxable_amount_paise < EWAY_THRESHOLD_PAISE`, i.e. the value BEFORE
  // GST, and told the CA a ₹48,000 + 18% = ₹56,640 consignment was "usually
  // not required". Explanation 2 to Rule 138(1) includes the tax and cess in
  // the figure; §129 detention and a penalty of the tax plus an equal amount
  // follow goods that move without a bill.
  // THE SERVER'S ANSWER FIRST. apps/api/domain/gst/eway.py is the authority and
  // is what the invoice detail serves; the `??` reaches the browser mirror only
  // where the backend has not redeployed yet.
  const eway = fromServed(inv.eway_assessment) ?? assessEway(inv.lines ?? []);
  if (eway.verdict === "required") {
    warnings.push(
      `Consignment value ${rupees(eway.consignmentValuePaise)} exceeds ₹50,000 — ` +
      `an E-Way Bill is required (Rule 138(1); Explanation 2 measures it ` +
      `including the tax charged in the document).`);
  } else if (eway.verdict === "not_required") {
    warnings.push(eway.reason);
  } else {
    warnings.push(eway.reason);
  }
  for (const gap of eway.gaps) warnings.push(gap);

  return { eligible: blockers.length === 0, blockers, warnings };
}

// ── Rule 138: is an e-way bill required? ─────────────────────────────────────
//
// MIRRORS apps/api/domain/gst/eway.py, WHICH IS THE AUTHORITY. The rule exists
// twice because this panel recomputes on every keystroke and a round trip per
// keystroke is not a panel — the same reason lib/money/gstLine.ts mirrors the
// Python GST line maths. The two are pinned by shared/eway-parity-vectors.json,
// read by scripts/eway-parity.test.ts here and tests/test_eway_parity.py there.
// Change one without the other and both suites fail, which is the point.

export interface EwayLine {
  hsn_sac?: string | null;
  taxable_amount_paise?: number | null;
  cgst_paise?: number | null;
  sgst_paise?: number | null;
  igst_paise?: number | null;
  /** GST compensation cess. A sales line does not carry one today (SALES-20);
   *  the field exists because Explanation 2 names it. */
  cess_paise?: number | null;
  /** Basis points: 1800 = 18%, 0 = nil-rated or exempt. */
  gst_rate_bps?: number | null;
}

export interface EwayAssessment {
  consignmentValuePaise: number;
  thresholdPaise: number;
  exceedsThreshold: boolean;
  goodsLines: number;
  serviceLines: number;
  unclassifiedLines: number;
  excludedExemptPaise: number;
  verdict: "required" | "not_required" | "undetermined";
  reason: string;
  gaps: string[];
}

/** A SAC — Chapter 99 of the tariff — is a service. The HSN of goods never
 *  starts 99, so this is the classification the invoice itself carries. */
export function isServiceCode(code: string | null | undefined): boolean {
  const c = (code ?? "").trim();
  return c.length >= 2 && c.slice(0, 2) === "99" && /^\d+$/.test(c);
}

function lineValuePaise(l: EwayLine): number {
  return (l.taxable_amount_paise ?? 0) + (l.cgst_paise ?? 0) + (l.sgst_paise ?? 0)
       + (l.igst_paise ?? 0) + (l.cess_paise ?? 0);
}

function rupees(paise: number): string {
  return "₹" + new Intl.NumberFormat("en-IN").format(Math.round(paise / 100));
}

/** The served answer in this module's own vocabulary, or null where the
 *  backend did not send one. */
export function fromServed(
  served: ServedEwayAssessment | null | undefined,
): EwayAssessment | null {
  if (!served) return null;
  return {
    consignmentValuePaise: served.consignment_value_paise,
    thresholdPaise: served.threshold_paise,
    exceedsThreshold: served.exceeds_threshold,
    goodsLines: served.goods_lines,
    serviceLines: served.service_lines,
    unclassifiedLines: served.unclassified_lines,
    excludedExemptPaise: served.excluded_exempt_paise,
    verdict: served.verdict,
    reason: served.reason,
    gaps: served.gaps ?? [],
  };
}

export function assessEway(lines: EwayLine[]): EwayAssessment {
  const out: EwayAssessment = {
    consignmentValuePaise: 0, thresholdPaise: EWAY_THRESHOLD_PAISE,
    exceedsThreshold: false, goodsLines: 0, serviceLines: 0,
    unclassifiedLines: 0, excludedExemptPaise: 0,
    verdict: "undetermined", reason: "", gaps: [],
  };

  const goods: EwayLine[] = [];
  for (const l of lines) {
    if (isServiceCode(l.hsn_sac)) { out.serviceLines += 1; continue; }
    if (!(l.hsn_sac ?? "").trim()) out.unclassifiedLines += 1;
    else out.goodsLines += 1;
    goods.push(l);
  }

  // Rule 138 is about the MOVEMENT OF GOODS. An invoice of pure services is not
  // a small consignment; the threshold never arises.
  if (!goods.length) {
    out.verdict = "not_required";
    out.reason = "Every line is a service (SAC 99xxxx). Rule 138 governs the "
               + "movement of goods, so no E-Way Bill arises.";
    return out;
  }

  const taxable = goods.filter((l) => (l.gst_rate_bps ?? 0) > 0);
  const exempt = goods.filter((l) => (l.gst_rate_bps ?? 0) <= 0);

  // Explanation 2's closing limb — exclude the value of exempt goods "where the
  // invoice is issued in respect of BOTH exempt and taxable supply of goods".
  // The condition is part of the rule: on a wholly exempt invoice the limb does
  // not apply by its own terms.
  if (taxable.length && exempt.length) {
    out.excludedExemptPaise = exempt.reduce((t, l) => t + lineValuePaise(l), 0);
    out.consignmentValuePaise = taxable.reduce((t, l) => t + lineValuePaise(l), 0);
  } else {
    out.consignmentValuePaise = goods.reduce((t, l) => t + lineValuePaise(l), 0);
  }

  // "EXCEEDING fifty thousand rupees" — strict. At exactly ₹50,000 no E-Way
  // Bill is required, and `taxable < THRESHOLD` made the boundary required.
  out.exceedsThreshold = out.consignmentValuePaise > EWAY_THRESHOLD_PAISE;

  if (out.unclassifiedLines) {
    out.gaps.push(
      `${out.unclassifiedLines} line(s) carry no HSN/SAC, so whether they are ` +
      `goods cannot be read off the invoice. They are counted in the ` +
      `consignment value, which is the direction that cannot advise a missing ` +
      `E-Way Bill.`);
  }

  if (exempt.length && !taxable.length) {
    out.verdict = "undetermined";
    out.reason = `Every goods line is nil-rated or exempt. The consignment `
               + `value is ${rupees(out.consignmentValuePaise)}, but Rule 138(14) `
               + `lists cases where no E-Way Bill is required whatever the value.`;
    out.gaps.push(
      "Rule 138(14) — including the goods specified in the Annexure to " +
      "Rule 138 — is not modelled. Check the Annexure before deciding a " +
      "wholly exempt consignment.");
    return out;
  }

  if (out.exceedsThreshold) {
    out.verdict = "required";
    out.reason = `Consignment value ${rupees(out.consignmentValuePaise)} exceeds `
               + `the ₹50,000 limit in Rule 138(1). Explanation 2 measures it `
               + `INCLUDING the tax and cess charged in the document, not on the `
               + `taxable value alone.`;
  } else {
    out.verdict = "not_required";
    out.reason = `Consignment value ${rupees(out.consignmentValuePaise)} does not `
               + `exceed the ₹50,000 limit in Rule 138(1), measured including the `
               + `tax charged in the document (Explanation 2).`;
  }
  return out;
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
