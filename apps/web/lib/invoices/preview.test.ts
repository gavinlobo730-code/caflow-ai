// Batch 3 — invoice totals preview + round-off mirror. Run with:
//   node --experimental-strip-types --test lib/invoices/preview.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { previewRoundOffPaise, previewTotals } from "./gst.ts";
import type { InvoiceLine } from "./gst.ts";

const line = (rate: string, gst: number, qty = "1"): InvoiceLine => ({
  description: "svc", hsn_sac: "", qty, rate, gst_rate: gst,
});

test("previewRoundOffPaise mirrors the backend nearest-rupee rule", () => {
  assert.equal(previewRoundOffPaise(10_000), 0);
  assert.equal(previewRoundOffPaise(10_030), -30);
  assert.equal(previewRoundOffPaise(10_050), 50);
  assert.equal(previewRoundOffPaise(10_099), 1);
  assert.equal(previewRoundOffPaise(10_049), -49);
});

test("intra-state totals split CGST+SGST and round to a whole rupee", () => {
  const t = previewTotals([line("105.55", 18)], false);
  assert.equal(t.taxable_paise, 10_555);
  assert.equal(t.cgst_paise + t.sgst_paise, t.gst_paise);
  assert.equal(t.igst_paise, 0);
  assert.equal(t.grand_total_paise % 100, 0, "grand total must be a whole rupee");
  assert.equal(t.grand_total_paise, t.taxable_paise + t.gst_paise + t.round_off_paise);
});

test("full tax is computed first, then split — SGST carries any odd paise (matches routers/sales_invoices.py's _compute_line_gst)", () => {
  // taxable = 28 paise, 18% -> full_gst = floor(28*1800/10000) = 5. Splitting
  // the RATE first (half = 9%) and rounding each leg independently gives
  // cgst=Math.round(28*9/1000)=3, sgst=3 -> 6, one paise MORE than the
  // backend's actual 5 (2+3). The old computeGst had this exact divergence.
  const t = previewTotals([line("0.28", 18)], false, false);
  assert.equal(t.taxable_paise, 28);
  assert.equal(t.cgst_paise, 2);
  assert.equal(t.sgst_paise, 3);
  assert.equal(t.gst_paise, 5);
});

test("inter-state uses IGST only", () => {
  const t = previewTotals([line("1000", 18)], true);
  assert.equal(t.cgst_paise, 0);
  assert.equal(t.sgst_paise, 0);
  assert.equal(t.igst_paise, t.gst_paise);
});

test("foreign invoices are not rupee-rounded (applyRoundOff=false)", () => {
  const t = previewTotals([line("105.55", 18)], false, false);
  assert.equal(t.round_off_paise, 0);
  assert.equal(t.grand_total_paise, t.taxable_paise + t.gst_paise);
});
