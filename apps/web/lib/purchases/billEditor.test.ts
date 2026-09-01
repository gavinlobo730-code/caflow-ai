// Purchase Bill editor domain tests. Run with:
//   node --experimental-strip-types --test lib/purchases/billEditor.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidBillLine, previewBillTotals, validateBillEditor, findBlockedCreditHits,
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
