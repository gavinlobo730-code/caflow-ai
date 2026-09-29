// The Register tab's slip table TOTAL row sums every column it has, not just
// Gross and Net.
//
// WHY THIS EXISTS. Expanding a run on the Register tab lists every slip with
// Gross, PF (Emp), ESI (Emp), PT, TDS and Net, and the TOTAL row underneath it
// filled in Gross and Net from the run's own aggregates and left the other
// four columns as a single blank `colSpan={4}` — although every row above it
// carries a figure in each of those columns. A CA totting up PF, ESI, PT or
// TDS for the month had nothing to read off the screen it was already open
// to.
//
// Run with: node --experimental-strip-types --test scripts/payroll-register-slip-totals.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/payroll/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE), "utf8");

// The slip table's own TOTAL row, from "TOTAL" to the closing </tr>.
const footStart = src.indexOf('text-ps-ink text-3xs">TOTAL</td>');
const footEnd = src.indexOf("</tr>", footStart);
const foot = src.slice(footStart, footEnd);

test("the slip table's TOTAL row is found where this test expects it", () => {
  assert.ok(footStart > -1 && footEnd > footStart,
    "the Register tab's slip TOTAL row moved or was renamed");
});

test("the TOTAL row no longer leaves PF/ESI/PT/TDS as one blank colSpan", () => {
  assert.ok(!foot.includes("colSpan={4}"),
    "the four statutory columns are still one blank cell in the TOTAL row");
});

test("PF, ESI, PT and TDS are each summed from the slips already on screen", () => {
  for (const field of ["pf_employee_paise", "esi_employee_paise", "pt_paise", "tds_paise"]) {
    assert.match(foot, new RegExp(
      `slips\\.reduce\\(\\(sum, s\\) => sum \\+ s\\.${field}, 0\\)`),
      `the TOTAL row does not sum ${field} the way Gross and Net are summed`);
  }
});

test("Gross and Net still come from the run's own aggregate, unchanged", () => {
  // The fix is additive — it must not have moved the two columns that already
  // worked onto a client-side sum of their own, which could disagree with the
  // server's figure by a rounding edge a per-slip sum would not share.
  assert.match(foot, /fmt\(r\.total_gross_paise\)/);
  assert.match(foot, /fmt\(r\.total_net_paise\)/);
});
