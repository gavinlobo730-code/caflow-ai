// Purchase Debit Note editor domain tests. Run with:
//   node --experimental-strip-types --test lib/purchases/debitNoteEditor.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidDebitNoteLine, previewDebitNoteTotals, validateDebitNoteEditor,
  type DebitNoteEditorLine,
} from "./debitNoteEditor.ts";

function line(over: Partial<DebitNoteEditorLine> = {}): DebitNoteEditorLine {
  return {
    description: "Test line", hsn_sac: "998221", qty: "1", rate: "1000", gst_rate: 18,
    unit: "NOS", service_catalogue_id: "SVC-1",
    ...over,
  };
}

test("isValidDebitNoteLine requires positive qty, positive rate and a Product/Service — description is optional", () => {
  assert.equal(isValidDebitNoteLine(line()), true);
  assert.equal(isValidDebitNoteLine(line({ description: "" })), true);
  assert.equal(isValidDebitNoteLine(line({ qty: "0" })), false);
  assert.equal(isValidDebitNoteLine(line({ rate: "" })), false);
  assert.equal(isValidDebitNoteLine(line({ service_catalogue_id: "" })), false);
});

test("previewDebitNoteTotals: intra-state splits 18% into 9% CGST + 9% SGST", () => {
  const t = previewDebitNoteTotals([line({ qty: "2", rate: "500", gst_rate: 18 })], false);
  assert.deepEqual(t, { taxable_paise: 100000, cgst_paise: 9000, sgst_paise: 9000, igst_paise: 0, gst_paise: 18000, cess_paise: 0, grand_total_paise: 118000 });
});

test("previewDebitNoteTotals: inter-state applies the full rate as IGST", () => {
  const t = previewDebitNoteTotals([line({ qty: "2", rate: "500", gst_rate: 18 })], true);
  assert.deepEqual(t, { taxable_paise: 100000, cgst_paise: 0, sgst_paise: 0, igst_paise: 18000, gst_paise: 18000, cess_paise: 0, grand_total_paise: 118000 });
});

test("previewDebitNoteTotals sums multiple valid lines and skips invalid ones", () => {
  const t = previewDebitNoteTotals([line({ qty: "1", rate: "1000", gst_rate: 18 }), line({ service_catalogue_id: "" }), line({ qty: "1", rate: "500", gst_rate: 0 })], false);
  assert.equal(t.taxable_paise, 150000);
  assert.equal(t.gst_paise, 18000); // 18% on 100000 only, 0% line contributes nothing
});

test("previewDebitNoteTotals: full-tax-then-split matches the backend on an odd-paise line (regression guard)", () => {
  // 28 paise taxable @ 18% -> full_gst floor(5.04)=5 (odd) -> cgst=2, sgst=3.
  const t = previewDebitNoteTotals([line({ qty: "1", rate: "0.28", gst_rate: 18 })], false);
  assert.equal(t.taxable_paise, 28);
  assert.equal(t.cgst_paise, 2);
  assert.equal(t.sgst_paise, 3);
});

test("validateDebitNoteEditor: requires vendor, date, and at least one valid line", () => {
  const v = validateDebitNoteEditor({ vendorId: "", debitNoteDate: "", lines: [line({ service_catalogue_id: "" })] });
  assert.equal(v.ok, false);
  assert.match(v.errors.vendor ?? "", /vendor/i);
  assert.match(v.errors.debitNoteDate ?? "", /date/i);
  assert.match(v.errors.lines ?? "", /at least one line/i);
});

test("validateDebitNoteEditor: passes with a vendor, date and one valid line", () => {
  const v = validateDebitNoteEditor({ vendorId: "VEND1", debitNoteDate: "2026-07-17", lines: [line()] });
  assert.equal(v.ok, true);
  assert.deepEqual(v.errors, {});
});

test("previewDebitNoteTotals: a line's compensation cess is its own figure and in the total (migration 615)", () => {
  // ₹1,000 x 3 at 18%, cess 12% ad valorem plus ₹4 a unit: 36,000 + 1,200 paise, the server's own arithmetic (compensation_cess.py).
  const t = previewDebitNoteTotals([line({ qty: "3", rate: "1000", gst_rate: 18, cessPercent: "12", cessPerUnit: "4" })], false);
  assert.equal(t.cess_paise, 37200);
  assert.equal(t.gst_paise, 54000, "the cess is never part of the GST");
  assert.equal(t.grand_total_paise, 300000 + 54000 + 37200);
  assert.equal(previewDebitNoteTotals([line({ cessPercent: "abc" })], false).cess_paise, 0, "a box that is not a number adds nothing");
});
