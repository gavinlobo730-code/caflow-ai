// Purchase Credit Note editor domain tests. Run with:
//   node --experimental-strip-types --test lib/purchases/purchaseCreditNoteEditor.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  isValidPurchaseCreditNoteLine, previewPurchaseCreditNoteTotals, validatePurchaseCreditNoteEditor,
  type PurchaseCreditNoteEditorLine,
} from "./purchaseCreditNoteEditor.ts";

function line(over: Partial<PurchaseCreditNoteEditorLine> = {}): PurchaseCreditNoteEditorLine {
  return {
    description: "Test line", hsn_sac: "998221", qty: "1", rate: "1000", gst_rate: 18,
    unit: "NOS", service_catalogue_id: "SVC-1",
    ...over,
  };
}

test("isValidPurchaseCreditNoteLine requires positive qty, positive rate and a Product/Service", () => {
  assert.equal(isValidPurchaseCreditNoteLine(line()), true);
  assert.equal(isValidPurchaseCreditNoteLine(line({ description: "" })), true);
  assert.equal(isValidPurchaseCreditNoteLine(line({ qty: "0" })), false);
  assert.equal(isValidPurchaseCreditNoteLine(line({ rate: "" })), false);
  assert.equal(isValidPurchaseCreditNoteLine(line({ service_catalogue_id: "" })), false);
});

test("previewPurchaseCreditNoteTotals: intra-state splits 18% into 9% CGST + 9% SGST", () => {
  const t = previewPurchaseCreditNoteTotals([line({ qty: "2", rate: "500", gst_rate: 18 })], false);
  assert.deepEqual(t, { taxable_paise: 100000, cgst_paise: 9000, sgst_paise: 9000, igst_paise: 0, gst_paise: 18000, grand_total_paise: 118000 });
});

test("previewPurchaseCreditNoteTotals: inter-state applies the full rate as IGST", () => {
  const t = previewPurchaseCreditNoteTotals([line({ qty: "2", rate: "500", gst_rate: 18 })], true);
  assert.deepEqual(t, { taxable_paise: 100000, cgst_paise: 0, sgst_paise: 0, igst_paise: 18000, gst_paise: 18000, grand_total_paise: 118000 });
});

test("previewPurchaseCreditNoteTotals sums multiple valid lines and skips invalid ones", () => {
  const t = previewPurchaseCreditNoteTotals([line({ qty: "1", rate: "1000", gst_rate: 18 }), line({ service_catalogue_id: "" }), line({ qty: "1", rate: "500", gst_rate: 0 })], false);
  assert.equal(t.taxable_paise, 150000);
  assert.equal(t.gst_paise, 18000);
});

test("validatePurchaseCreditNoteEditor: requires vendor, date, and at least one valid line", () => {
  const v = validatePurchaseCreditNoteEditor({ vendorId: "", creditNoteDate: "", lines: [line({ service_catalogue_id: "" })] });
  assert.equal(v.ok, false);
  assert.match(v.errors.vendor ?? "", /vendor/i);
  assert.match(v.errors.creditNoteDate ?? "", /date/i);
  assert.match(v.errors.lines ?? "", /at least one line/i);
});

test("validatePurchaseCreditNoteEditor: passes with a vendor, date and one valid line", () => {
  const v = validatePurchaseCreditNoteEditor({ vendorId: "VEND1", creditNoteDate: "2026-07-17", lines: [line()] });
  assert.equal(v.ok, true);
  assert.deepEqual(v.errors, {});
});
