// What the CA is told after Mark Filed — composed from the server's answer.
//   node --experimental-strip-types --test lib/compliance/filingOutcome.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { describeFilingOutcome } from "./filingOutcome.ts";

const OBL = { obligation: {} };

test("a recorded filing says the period is locked, from when to when", () => {
  const o = describeFilingOutcome({
    ...OBL, filing_recorded: true, filing_not_recorded_reason: null,
    period_locked_from: "2026-06-01", period_locked_to: "2026-06-30",
  }, "GSTR-3B");
  assert.equal(o.locked, true);
  assert.match(o.title, /period locked/);
  assert.match(o.description, /1 Jun 2026 – 30 Jun 2026/);
});

test("a quarter reads as a quarter", () => {
  const o = describeFilingOutcome({
    ...OBL, filing_recorded: true, period_locked_from: "2026-04-01", period_locked_to: "2026-06-30",
  }, "GSTR-1");
  assert.match(o.description, /1 Apr 2026 – 30 Jun 2026/);
});

test("a filing that locked nothing says the server's reason, verbatim", () => {
  const reason = "GSTR-9 is the annual return. Furnishing it closes the CORRECTION WINDOW.";
  const o = describeFilingOutcome({ ...OBL, filing_recorded: false, filing_not_recorded_reason: reason }, "GSTR-9");
  assert.equal(o.locked, false);
  assert.equal(o.description, reason);
  assert.doesNotMatch(o.title, /locked/);
});

test("an answer with no lock information is NOT rendered as 'nothing was locked'", () => {
  // A backend one deploy behind sends neither key. Unknown is not a value.
  for (const r of [{ ...OBL }, null, undefined]) {
    const o = describeFilingOutcome(r, "GSTR-3B");
    assert.equal(o.locked, false);
    assert.match(o.description, /did not say/);
    assert.doesNotMatch(o.description, /No period was locked/);
  }
});

test("a locked answer with no bounds still says locked, without inventing a window", () => {
  const o = describeFilingOutcome({ ...OBL, filing_recorded: true }, "GSTR-3B");
  assert.equal(o.locked, true);
  assert.doesNotMatch(o.description, /undefined|null/);
});

test("the browser holds no list of which returns lock", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync(new URL("./filingOutcome.ts", import.meta.url), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  assert.doesNotMatch(src, /GSTR1|GSTR3B|GSTR-3B|GSTR-1/);
});
