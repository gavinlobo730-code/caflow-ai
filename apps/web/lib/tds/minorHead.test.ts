// Run with: node --experimental-strip-types --test lib/tds/minorHead.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { MINOR_HEAD_LABEL, minorHeadLabel } from "./minorHead.ts";

test("200 and 400 are told apart in words", () => {
  assert.equal(minorHeadLabel("200"), MINOR_HEAD_LABEL["200"]);
  assert.equal(minorHeadLabel("400"), MINOR_HEAD_LABEL["400"]);
  assert.notEqual(MINOR_HEAD_LABEL["200"], MINOR_HEAD_LABEL["400"]);
  assert.ok(MINOR_HEAD_LABEL["400"].includes("against a demand"));
});

test("a head that is neither is shown as stored, and an absent one is a dash, never 200", () => {
  assert.equal(minorHeadLabel("300"), "300");
  assert.equal(minorHeadLabel(undefined), "—");
  assert.equal(minorHeadLabel(null), "—");
  assert.equal(minorHeadLabel("  "), "—");
  assert.notEqual(minorHeadLabel(null), MINOR_HEAD_LABEL["200"]);
});
