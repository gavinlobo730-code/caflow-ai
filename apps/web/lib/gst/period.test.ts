// GST return periods. Run with:
//   node --experimental-strip-types --test lib/gst/period.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { gstPeriodFinancialYear, gstPeriodLabel, isGstPeriod } from "./period.ts";

test("MMYYYY, not YYYY-MM", () => {
  // The transposition is the point. "202606" is a well-formed six-digit string
  // and GSTN reads its first two characters as the month — 20, which is not a
  // month. Every other period in this product is YYYY-MM, so the two get
  // swapped, and a bare /^\d{6}$/ would accept the swap silently.
  assert.equal(isGstPeriod("062026"), true);
  assert.equal(isGstPeriod("202606"), false);
  assert.equal(isGstPeriod("002026"), false);
  assert.equal(isGstPeriod("132026"), false);
});

test("anything that is not six digits is not a period", () => {
  for (const bad of ["", "6202", "6/2026", "06-2026", "0620266", "abcdef", null, undefined]) {
    assert.equal(isGstPeriod(bad), false, String(bad));
  }
});

test("every month reads back as its own name", () => {
  const names = ["January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December"];
  names.forEach((name, i) => {
    assert.equal(gstPeriodLabel(`${String(i + 1).padStart(2, "0")}2026`), `${name} 2026`);
  });
});

test("an unparseable period is shown as itself, not as a wrong month", () => {
  // Returning "undefined 2026" or silently picking a month would put a made-up
  // period on a screen about corrections to a FILED return.
  assert.equal(gstPeriodLabel("202606"), "202606");
  assert.equal(gstPeriodLabel(""), "");
});

test("the financial year runs April to March", () => {
  assert.equal(gstPeriodFinancialYear("042026"), "2026-27");
  assert.equal(gstPeriodFinancialYear("032027"), "2026-27");
  assert.equal(gstPeriodFinancialYear("122026"), "2026-27");
  assert.equal(gstPeriodFinancialYear("012027"), "2026-27");
  // …which is what decides the §37(3) correction window: 30 November
  // FOLLOWING the financial year, or the date GSTR-9 was furnished, whichever
  // is earlier. March and April are one month and two windows apart.
  assert.notEqual(gstPeriodFinancialYear("032027"), gstPeriodFinancialYear("042027"));
});

test("a period that is not one has no financial year", () => {
  assert.equal(gstPeriodFinancialYear("202606"), null);
  assert.equal(gstPeriodFinancialYear(""), null);
});
