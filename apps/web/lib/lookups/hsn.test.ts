// Batch 5 — HSN/SAC lookup presentation helpers. Run with:
//   node --experimental-strip-types --test lib/lookups/hsn.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  hsnGroupOf, hsnTypeBadge, orderHsnResults, formatHsnRate, hsnSecondaryLine,
  type HsnRow,
} from "./hsn.ts";

const row = (over: Partial<HsnRow> = {}): HsnRow => ({
  hsn_code: "998212", description: "Financial auditing services",
  gst_rate_bps: 1800, uqc: "OTH", hsn_type: "services", source: "master", ...over,
});

test("hsnGroupOf: history leads, then services/goods, else other", () => {
  assert.equal(hsnGroupOf(row({ source: "history", hsn_type: null })), "history");
  assert.equal(hsnGroupOf(row({ hsn_type: "services" })), "services");
  assert.equal(hsnGroupOf(row({ hsn_type: "goods" })), "goods");
  assert.equal(hsnGroupOf(row({ hsn_type: null, source: "master" })), "other");
});

test("hsnTypeBadge distinguishes SAC vs HSN, incl. code-shape fallback", () => {
  assert.equal(hsnTypeBadge(row({ hsn_type: "services" })), "SAC");
  assert.equal(hsnTypeBadge(row({ hsn_type: "goods", hsn_code: "8471" })), "HSN");
  // History rows carry no hsn_type; a 99xxxx code still reads as a service.
  assert.equal(hsnTypeBadge(row({ hsn_type: null, source: "history", hsn_code: "998212" })), "SAC");
  assert.equal(hsnTypeBadge(row({ hsn_type: null, source: "history", hsn_code: "8471" })), null);
});

test("orderHsnResults groups history→services→goods, stable within group", () => {
  const rows: HsnRow[] = [
    row({ hsn_code: "8471", hsn_type: "goods", source: "master" }),
    row({ hsn_code: "998212", hsn_type: "services", source: "master" }),
    row({ hsn_code: "998311", hsn_type: null, source: "history" }),
    row({ hsn_code: "9401", hsn_type: "goods", source: "master" }),
    row({ hsn_code: "998213", hsn_type: "services", source: "master" }),
  ];
  const ordered = orderHsnResults(rows).map((r) => r.hsn_code);
  assert.deepEqual(ordered, ["998311", "998212", "998213", "8471", "9401"]);
});

test("orderHsnResults does not drop or duplicate rows", () => {
  const rows = [row({ hsn_code: "a" }), row({ hsn_code: "b" }), row({ hsn_code: "c" })];
  assert.equal(orderHsnResults(rows).length, 3);
  assert.equal(orderHsnResults([]).length, 0);
});

test("formatHsnRate: integer, fractional, and unknown", () => {
  assert.equal(formatHsnRate(1800), "18% GST");
  assert.equal(formatHsnRate(300), "3% GST");
  assert.equal(formatHsnRate(250), "2.50% GST");
  assert.equal(formatHsnRate(null), "");
  assert.equal(formatHsnRate(undefined), "");
});

test("hsnSecondaryLine joins present parts, drops blanks", () => {
  assert.equal(
    hsnSecondaryLine(row()),
    "Financial auditing services · 18% GST · OTH",
  );
  assert.equal(
    hsnSecondaryLine(row({ gst_rate_bps: null, uqc: null })),
    "Financial auditing services",
  );
});
