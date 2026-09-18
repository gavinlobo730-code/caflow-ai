/**
 * `isServiceCode` classifies a line off the tariff chapter, and until today it
 * was the ONLY implementation of that rule in the repository.
 *
 * Same defect as SALES-17 (the e-way threshold, measured on the pre-GST taxable
 * value and left that way for months) and SALES-18 (the Rule 48(4) scope test):
 * a statutory classification living in the browser with nothing pinning it.
 * `apps/api/domain/gst/goods_or_services.py` is the twin now.
 *
 * The FIXTURE is shared and lives on the Python side, because that is where the
 * authority is — a guard here asserting the browser against a copy of itself
 * passes whenever both drift together.
 *
 * ONE DELIBERATE DIFFERENCE. This function returns a BOOLEAN and the Python
 * rule returns a tri-state. That is right for this caller: the e-way split
 * counts unclassified lines separately, on the HSN being ABSENT rather than on
 * this function, so folding "cannot tell" into false loses nothing here. The
 * fixture's `browser` column records what this returns and its `python` column
 * the tri-state, and the two must agree on every code either can read.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

import { isServiceCode } from "../lib/invoices/compliance.ts";

const FIXTURE = path.resolve(
  import.meta.dirname, "..", "..", "api", "tests", "fixtures",
  "goods_or_services.json",
);
const CASES = JSON.parse(fs.readFileSync(FIXTURE, "utf8")).cases as {
  code: string; python: boolean | null; browser: boolean; why: string;
}[];

test("the fixture is shared with the python suite and is not empty", () => {
  assert.ok(CASES.length >= 10, "too few cases to pin anything");
  assert.ok(fs.existsSync(FIXTURE));
});

for (const c of CASES) {
  test(`isServiceCode(${JSON.stringify(c.code)}) — ${c.why}`, () => {
    assert.equal(isServiceCode(c.code), c.browser);
  });
}

test("the two agree on every code BOTH can read", () => {
  for (const c of CASES) {
    if (c.python === null) continue;
    assert.equal(
      isServiceCode(c.code), c.python,
      `${c.code}: the browser and domain/gst/goods_or_services disagree`,
    );
  }
});

test("null and undefined do not throw", () => {
  assert.equal(isServiceCode(null), false);
  assert.equal(isServiceCode(undefined), false);
});
