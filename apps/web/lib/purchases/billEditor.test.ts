// Purchase Bill editor domain tests. Run with:
//   node --experimental-strip-types --test lib/purchases/billEditor.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidBillLine, previewBillTotals, validateBillEditor, findBlockedCreditHits,
  BLOCKED_CREDIT_REASONS, blockedCreditProblems, ineligibleGstPaise,
  buildLinePayload, lineIsItcEligible, reasonForHintLabel,
  type PurchaseBillLine,
} from "./billEditor.ts";

function line(over: Partial<PurchaseBillLine> = {}): PurchaseBillLine {
  return {
    description: "Test line", hsn_sac: "998221", qty: "1", rate: "1000", gst_rate: 18,
    unit: "NOS", expense_account_id: "", service_catalogue_id: "SVC-1",
    ...over,
  };
}

test("isValidBillLine requires positive qty, positive rate and a Product/Service — description is optional", () => {
  assert.equal(isValidBillLine(line()), true);
  assert.equal(isValidBillLine(line({ description: "" })), true);
  assert.equal(isValidBillLine(line({ qty: "0" })), false);
  assert.equal(isValidBillLine(line({ rate: "" })), false);
  assert.equal(isValidBillLine(line({ service_catalogue_id: "" })), false);
});

test("previewBillTotals: intra-state splits 18% into 9% CGST + 9% SGST, no round-off", () => {
  const t = previewBillTotals([line({ qty: "2", rate: "500", gst_rate: 18 })], false);
  assert.deepEqual(t, { taxable_paise: 100000, cgst_paise: 9000, sgst_paise: 9000, igst_paise: 0, gst_paise: 18000, grand_total_paise: 118000 });
});

test("previewBillTotals: inter-state applies the full rate as IGST", () => {
  const t = previewBillTotals([line({ qty: "2", rate: "500", gst_rate: 18 })], true);
  assert.deepEqual(t, { taxable_paise: 100000, cgst_paise: 0, sgst_paise: 0, igst_paise: 18000, gst_paise: 18000, grand_total_paise: 118000 });
});

test("previewBillTotals sums multiple valid lines and skips invalid ones", () => {
  const t = previewBillTotals([line({ qty: "1", rate: "1000", gst_rate: 18 }), line({ service_catalogue_id: "" }), line({ qty: "1", rate: "500", gst_rate: 0 })], false);
  assert.equal(t.taxable_paise, 150000);
  assert.equal(t.gst_paise, 18000); // 18% on 100000 only, 0% line contributes nothing
});

test("validateBillEditor: requires vendor, bill date, and at least one valid line", () => {
  const v = validateBillEditor({ vendorId: "", billDate: "", lines: [line({ service_catalogue_id: "" })], isForeign: false, exchangeRate: "" });
  assert.equal(v.ok, false);
  assert.match(v.errors.vendor ?? "", /vendor/i);
  assert.match(v.errors.billDate ?? "", /bill date/i);
  assert.match(v.errors.lines ?? "", /at least one line/i);
});

test("validateBillEditor: passes with a vendor, date and one valid line", () => {
  const v = validateBillEditor({ vendorId: "v1", billDate: "2026-07-12", lines: [line()], isForeign: false, exchangeRate: "" });
  assert.equal(v.ok, true);
  assert.deepEqual(v.errors, {});
});

test("validateBillEditor: foreign currency requires a positive exchange rate", () => {
  const v = validateBillEditor({ vendorId: "v1", billDate: "2026-07-12", lines: [line()], isForeign: true, exchangeRate: "" });
  assert.match(v.errors.exchangeRate ?? "", /exchange rate/i);
  const ok = validateBillEditor({ vendorId: "v1", billDate: "2026-07-12", lines: [line()], isForeign: true, exchangeRate: "83.5" });
  assert.equal(ok.errors.exchangeRate, undefined);
});

test("findBlockedCreditHits flags a motor vehicle line by description", () => {
  const hits = findBlockedCreditHits([line({ description: "Purchase of company car" })], new Map());
  assert.equal(hits.length, 1);
  assert.equal(hits[0].label, "Motor vehicle");
  assert.match(hits[0].note, /§17\(5\)\(a\)/);
});

test("findBlockedCreditHits flags via the expense account name when the description is generic", () => {
  const hits = findBlockedCreditHits(
    [line({ description: "Monthly bill", expense_account_id: "acc-1" })],
    new Map([["acc-1", "Staff Club Membership"]]),
  );
  assert.equal(hits.length, 1);
  assert.equal(hits[0].label, "Club / fitness membership");
});

test("findBlockedCreditHits returns nothing for an ordinary line", () => {
  const hits = findBlockedCreditHits([line({ description: "Office stationery" })], new Map());
  assert.equal(hits.length, 0);
});

test("findBlockedCreditHits reports the correct line index in a multi-line bill", () => {
  const hits = findBlockedCreditHits(
    [line({ description: "Office stationery" }), line({ description: "Team lunch catering" })],
    new Map(),
  );
  assert.deepEqual(hits.map((h) => h.lineIndex), [1]);
});

// ── Reading the typed rate and quantity ──────────────────────────────────────
// The validator used to be `(parseFloat(l.rate) || 0) > 0`, which is TRUE for
// "1,25,000" because parseFloat reads it as 1. A bill line typed the way Indian
// amounts are grouped was accepted as a valid one-rupee line, previewed at ₹1
// and saved at ₹1, with nothing anywhere saying so.

test("a rate typed with Indian digit grouping is refused, not read as one rupee", () => {
  assert.equal(isValidBillLine(line({ rate: "1,25,000" })), false);
  assert.equal(isValidBillLine(line({ qty: "1,000" })), false);
});

test("text parseFloat would read as a number is refused", () => {
  assert.equal(isValidBillLine(line({ rate: "12abc" })), false);   // parseFloat -> 12
  assert.equal(isValidBillLine(line({ rate: "1e3" })), false);     // parseFloat -> 1000
  assert.equal(isValidBillLine(line({ qty: "2abc" })), false);
});

test("a rate finer than a paise is refused rather than silently truncated", () => {
  assert.equal(isValidBillLine(line({ rate: "1.005" })), false);
});

test("ordinary rates and quantities still pass", () => {
  assert.equal(isValidBillLine(line({ rate: "125000", qty: "2" })), true);
  assert.equal(isValidBillLine(line({ rate: "105.55", qty: "0.335" })), true);
});

test("a refused line contributes nothing to the preview totals", () => {
  // Not merely "is not valid": the number on screen must not include it either,
  // or the CA is shown a total the invoice will not carry.
  const good = previewBillTotals([line({ rate: "1000", qty: "1" })], false);
  const withBad = previewBillTotals(
    [line({ rate: "1000", qty: "1" }), line({ rate: "1,25,000", qty: "1" })], false);
  assert.equal(withBad.taxable_paise, good.taxable_paise);
  assert.equal(withBad.grand_total_paise, good.grand_total_paise);
});


// ── CGST Act §17(5), blocked input tax credit (PUR-05) ───────────────────────
//
// `itc_eligible` and `blocked_credit_reason` have been on the API models, the
// database columns and the GSTR-3B computation since migration 240, and NO
// SCREEN COULD SET THEM. So every purchase bill in the product claimed full
// credit — §17(5) or not — and the reversal the return is meant to make in
// Table 4(B)(1) was always nil.

function base(over: Partial<PurchaseBillLine> = {}): PurchaseBillLine {
  return line({ rate: "1000", qty: "1", gst_rate: 18, ...over });
}

test("a line nobody has touched is eligible, because the column defaults true", () => {
  // The trap: `undefined` must mean ELIGIBLE, not unknown. Migration 240
  // defaults the column true so no bill written before the field existed
  // changes meaning, and the editor has to agree with the column — otherwise
  // re-saving an old draft would silently block its credit.
  assert.equal(lineIsItcEligible(base()), true);
  assert.equal(lineIsItcEligible(base({ itc_eligible: undefined })), true);
  assert.equal(lineIsItcEligible(base({ itc_eligible: true })), true);
  assert.equal(lineIsItcEligible(base({ itc_eligible: false })), false);
});

test("a blocked line must name the clause it is blocked under", () => {
  // §17(5) has fourteen clauses with different exceptions, and this figure is
  // what a CA reads back in an assessment two years later. "Blocked" with no
  // clause is a reversal nobody can defend.
  const problems = blockedCreditProblems([base({ itc_eligible: false })]);
  assert.equal(problems.length, 1);
  assert.equal(problems[0].lineIndex, 0);
  assert.match(problems[0].message, /clause/i);
});

test("an invented clause is refused, not stored", () => {
  const problems = blockedCreditProblems(
    [base({ itc_eligible: false, blocked_credit_reason: "because_i_said_so" })]);
  assert.equal(problems.length, 1);
  assert.match(problems[0].message, /not a §17\(5\) clause/);
});

test("a blocked line with a real clause is fine", () => {
  assert.deepEqual(
    blockedCreditProblems([base({ itc_eligible: false,
                                  blocked_credit_reason: "17_5_g_personal_consumption" })]),
    []);
});

test("an eligible line is never asked for a clause", () => {
  assert.deepEqual(blockedCreditProblems([base(), base({ itc_eligible: true })]), []);
});

test("the whole save is refused while a blocked line has no clause", () => {
  // Not merely a message under the table. The flag WOULD still reduce the
  // claim if it saved, so allowing it trades one unsupported figure for
  // another.
  const v = validateBillEditor({
    vendorId: "V1", billDate: "2026-09-01", isForeign: false, exchangeRate: "",
    lines: [base({ itc_eligible: false })],
  });
  assert.equal(v.ok, false);
  assert.match(v.errors.itc ?? "", /Line 1/);
});

test("an ordinary bill still validates", () => {
  const v = validateBillEditor({
    vendorId: "V1", billDate: "2026-09-01", isForeign: false, exchangeRate: "",
    lines: [base()],
  });
  assert.equal(v.ok, true);
  assert.equal(v.errors.itc, undefined);
});

test("the blocked total is the GST on the blocked lines and nothing else", () => {
  const lines = [
    base({ rate: "1000" }),                                    // eligible
    base({ rate: "2000", itc_eligible: false,
           blocked_credit_reason: "17_5_g_personal_consumption" }),
  ];
  const all = previewBillTotals(lines, false);
  const blocked = ineligibleGstPaise(lines, false);
  const eligibleOnly = previewBillTotals([lines[0]], false);
  assert.equal(blocked, all.gst_paise - eligibleOnly.gst_paise);
  assert.equal(blocked, 2000_00 * 18 / 100);
  // …and it is the same figure whichever way the supply is split, because
  // §17(5) blocks the credit, not one head of it.
  assert.equal(ineligibleGstPaise(lines, true), blocked);
});

test("nothing blocked is nothing to reverse", () => {
  assert.equal(ineligibleGstPaise([base(), base()], false), 0);
});

test("every clause the picker offers has a code, a clause number and a label", () => {
  assert.ok(BLOCKED_CREDIT_REASONS.length >= 10, "the section has fourteen clauses");
  const codes = new Set<string>();
  for (const r of BLOCKED_CREDIT_REASONS) {
    assert.ok(r.code.trim(), JSON.stringify(r));
    assert.match(r.clause, /^§17\(5\)/, r.code);
    assert.ok(r.label.trim().length > 5, r.code);
    assert.equal(codes.has(r.code), false, `duplicate code ${r.code}`);
    codes.add(r.code);
  }
  // The residual. §17(5) is not the only way credit is blocked, and a CA who
  // cannot find their case must not be pushed into the nearest wrong clause.
  assert.ok(codes.has("other"));
});

test("every heuristic hint points at a clause the picker offers", () => {
  // The prompt and the control it points at must agree, or marking a line from
  // the warning would store a code the select cannot display.
  const codes = new Set(BLOCKED_CREDIT_REASONS.map((r) => r.code));
  for (const label of ["Motor vehicle", "Food & beverages", "Club / fitness membership",
                       "Life / health insurance", "Employee travel benefit"]) {
    const code = reasonForHintLabel(label);
    assert.ok(code, `no clause for the hint "${label}"`);
    assert.ok(codes.has(code!), `${label} -> ${code} is not in the picker`);
  }
});

test("the heuristic still only warns — it never blocks a line by itself", () => {
  // It reads text a vendor typed. Marking a line off a keyword would reverse
  // credit on "Food Corporation of India" for supplying grain.
  const lines = [base({ description: "Team lunch at the canteen" })];
  const hits = findBlockedCreditHits(lines, new Map());
  assert.equal(hits.length, 1);
  assert.equal(lineIsItcEligible(lines[0]), true, "the hint must not have marked it");
  assert.equal(ineligibleGstPaise(lines, false), 0);
});


// ── What actually leaves the browser ─────────────────────────────────────────
//
// THE GUARD THAT WOULD HAVE CAUGHT PUR-05. `itc_eligible` existed on the API
// model, the column and the GSTR-3B computation, every backend test passed,
// and the payload builder simply did not carry the key — with nothing able to
// say so, because the builder lived in a .tsx file that no unit test could
// import. Moving it here is half the fix; these are the other half.

test("the payload carries the §17(5) marking", () => {
  const [payload] = buildLinePayload([base({
    itc_eligible: false, blocked_credit_reason: "17_5_b_club_membership" })]);
  assert.equal(payload.itc_eligible, false);
  assert.equal(payload.blocked_credit_reason, "17_5_b_club_membership");
});

test("an eligible line says so EXPLICITLY rather than omitting the key", () => {
  // Omitting it would leave a line the CA just un-blocked carrying whatever the
  // stored row said, on a PATCH that replaces the lines.
  const [payload] = buildLinePayload([base()]);
  assert.equal(payload.itc_eligible, true);
  assert.equal(payload.blocked_credit_reason, undefined);
});

test("un-blocking clears the clause, so no line contradicts itself", () => {
  const [payload] = buildLinePayload([base({
    itc_eligible: true, blocked_credit_reason: "17_5_b_club_membership" })]);
  assert.equal(payload.itc_eligible, true);
  assert.equal(payload.blocked_credit_reason, undefined);
});

test("the payload still carries everything it carried before", () => {
  const [payload] = buildLinePayload([base({
    description: "Audit fee", hsn_sac: "998221", qty: "2", rate: "1500.50",
    unit: "NOS", expense_account_id: "ACC-1", service_catalogue_id: "SVC-1" })]);
  assert.deepEqual(payload, {
    description: "Audit fee", hsn_sac: "998221", quantity: 2, unit: "NOS",
    rate_paise: 150050, gst_rate_percent: 18,
    expense_account_id: "ACC-1", service_catalogue_id: "SVC-1",
    itc_eligible: true, blocked_credit_reason: undefined,
  });
});

test("an invalid line never reaches the payload", () => {
  // parseFloat("1,25,000") is 1. The filter is isValidBillLine, which refuses
  // it outright rather than sending a one-rupee line.
  assert.equal(buildLinePayload([base({ rate: "1,25,000" })]).length, 0);
});
