/**
 * Verify Books run-history chips and the Approvals "Posted At" column
 * rendered raw UTC timestamps with `String(x).slice(0, 16).replace("T", " ")`
 * and no timezone label (apex-accounting-reports-18) — silently showing the
 * wrong calendar DATE for anything in the 00:00-05:30 IST window (CLAUDE.md's
 * "Reporting times to the user").
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { formatIst, formatIstLabelled } from "./formatIst.ts";

test("a UTC timestamp just after 18:30 UTC prints the NEXT calendar day in IST", () => {
  // 2026-03-31T19:00:00Z is 2026-04-01 00:30 IST — the exact window the raw
  // slice-and-replace got wrong, since it would print "2026-03-31 19:00".
  const out = formatIst("2026-03-31T19:00:00Z");
  assert.ok(out, "expected a formatted string");
  assert.match(out!, /1 Apr 2026/, `expected 1 Apr 2026 in IST, got: ${out}`);
});

test("an ordinary UTC timestamp is shown 5:30 ahead, in IST", () => {
  // 2026-06-15T10:00:00Z is 2026-06-15 15:30 IST.
  const out = formatIst("2026-06-15T10:00:00Z");
  assert.ok(out);
  assert.match(out!, /3:30\s*pm/i, `expected 3:30 pm IST, got: ${out}`);
});

test("null, undefined and unparseable values return null", () => {
  assert.equal(formatIst(null), null);
  assert.equal(formatIst(undefined), null);
  assert.equal(formatIst(""), null);
  assert.equal(formatIst("not a date"), null);
});

test("formatIstLabelled appends the IST label", () => {
  const out = formatIstLabelled("2026-06-15T10:00:00Z");
  assert.match(out, /IST$/, `expected the label "IST" at the end, got: ${out}`);
  assert.match(out, /3:30\s*pm/i);
});

test("formatIstLabelled falls back to the given default (or em dash) when absent", () => {
  assert.equal(formatIstLabelled(null), "—");
  assert.equal(formatIstLabelled(undefined, "not posted"), "not posted");
});
