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

test("full tax is computed first, then split — SGST carries any odd paise (matches the backend exactly, not the old halve-bps-first approach)", () => {
  // 28 paise taxable @ 18%: full_gst = floor(28*1800/10000) = floor(5.04) = 5
  // (odd) -> cgst = 5//2 = 2, sgst = 5-2 = 3, total 5. The old "halve the bps
  // first" method computed floor(28*900/10000)=2 for BOTH legs — total 4,
  // silently 1 paise short of what the backend actually posts.
  const g = dnLineGst({ quantity: 1, rate: 0.28, gst_rate_bps: 1800 }, false);
  assert.equal(g.taxable_paise, 28);
  assert.equal(g.cgst_paise, 2);
  assert.equal(g.sgst_paise, 3);
  assert.equal(g.line_total, 33);
});

test("an even-paise total still splits CGST/SGST identically either way (regression guard)", () => {
  const g = dnLineGst({ quantity: 1, rate: 1000, gst_rate_bps: 10 }, false);
  assert.equal(g.taxable_paise, 100000);
  assert.equal(g.cgst_paise, 50);
  assert.equal(g.sgst_paise, 50);
});

test("zero quantity or rate yields an all-zero result, never NaN", () => {
  const g = dnLineGst({ quantity: 0, rate: 0, gst_rate_bps: 1800 }, false);
  assert.deepEqual(g, { taxable_paise: 0, cgst_paise: 0, sgst_paise: 0, igst_paise: 0, line_total: 0 });
});
