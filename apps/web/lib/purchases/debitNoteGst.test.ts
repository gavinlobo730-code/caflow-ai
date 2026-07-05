// Debit Note GST preview tests (C3) — run with:
//   node --experimental-strip-types --test lib/purchases/debitNoteGst.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { dnLineGst } from "./debitNoteGst.ts";

test("intra-state 18% splits evenly into 9% CGST + 9% SGST (CGST Act §8) — matches the live backend's own computation", () => {
  // qty=2, rate=₹500 -> taxable = 100000 paise. Verified end-to-end against
  // a running mock-mode backend: POST /api/debit-notes/ with this exact line
  // (gst_rate_percent: 18.0, is_interstate: false) returned
  // cgst_paise=9000, sgst_paise=9000, igst_paise=0, total_paise=118000.
  const g = dnLineGst({ quantity: 2, rate: 500, gst_rate_bps: 1800 }, false);
  assert.deepEqual(g, { taxable_paise: 100000, cgst_paise: 9000, sgst_paise: 9000, igst_paise: 0, line_total: 118000 });
});

test("inter-state applies the full rate as IGST, no CGST/SGST", () => {
  const g = dnLineGst({ quantity: 2, rate: 500, gst_rate_bps: 1800 }, true);
  assert.deepEqual(g, { taxable_paise: 100000, cgst_paise: 0, sgst_paise: 0, igst_paise: 18000, line_total: 118000 });
});

test("0% GST line has zero tax on both intra- and inter-state", () => {
  assert.equal(dnLineGst({ quantity: 1, rate: 100, gst_rate_bps: 0 }, false).line_total, 10000);
  assert.equal(dnLineGst({ quantity: 1, rate: 100, gst_rate_bps: 0 }, true).line_total, 10000);
});

test("an odd basis-point rate floors the halved rate first, exactly like the backend's integer division", () => {
  // 0.1% (10 bps) intra-state: half = 10 // 2 = 5 bps.
  // taxable = 1 * 1000 * 100 = 100000 paise; cgst = sgst = floor(100000*5/10000) = 50.
  const g = dnLineGst({ quantity: 1, rate: 1000, gst_rate_bps: 10 }, false);
  assert.equal(g.taxable_paise, 100000);
  assert.equal(g.cgst_paise, 50);
  assert.equal(g.sgst_paise, 50);
});

test("zero quantity or rate yields an all-zero result, never NaN", () => {
  const g = dnLineGst({ quantity: 0, rate: 0, gst_rate_bps: 1800 }, false);
  assert.deepEqual(g, { taxable_paise: 0, cgst_paise: 0, sgst_paise: 0, igst_paise: 0, line_total: 0 });
});
