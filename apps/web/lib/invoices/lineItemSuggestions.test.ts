import test from "node:test";
import assert from "node:assert/strict";
import {
  mergeLineItemSuggestions, suggestionToLinePatch, type HsnSuggestionRow,
} from "./lineItemSuggestions.ts";
import type { ServiceCatalogueItem } from "../catalogue/service.ts";

function catalogueItem(overrides: Partial<ServiceCatalogueItem> = {}): ServiceCatalogueItem {
  return {
    id: "svc-1", name: "Accounting & Bookkeeping Services", description: null,
    hsn_sac: "998222", gst_rate_bps: 1800, default_rate_paise: 500000,
    unit: "NOS", notes: null, is_active: true, use_count: 3, last_used_at: null,
    ...overrides,
  };
}

function hsnRow(overrides: Partial<HsnSuggestionRow> = {}): HsnSuggestionRow {
  return {
    hsn_code: "998222", description: "Accounting and bookkeeping services",
    gst_rate_bps: 1800, uqc: "NOS", hsn_type: "services", source: "master", reason: null,
    ...overrides,
  };
}

test("catalogue items map with a Catalogue source badge, SAC code type, price and use-count reason", () => {
  const [s] = mergeLineItemSuggestions([catalogueItem()], []);
  assert.equal(s.id, "catalogue:svc-1");
  assert.equal(s.source, "Catalogue");
  assert.equal(s.codeType, "SAC");
  assert.equal(s.description, "Accounting & Bookkeeping Services");
  assert.equal(s.hsn_sac, "998222");
  assert.equal(s.gst_rate_bps, 1800);
  assert.equal(s.rate_paise, 500000);
  assert.equal(s.reason, "Used 3 times");
});

test("a catalogue item's own description wins over its name when present", () => {
  const [s] = mergeLineItemSuggestions(
    [catalogueItem({ description: "Monthly bookkeeping retainer" })], [],
  );
  assert.equal(s.description, "Monthly bookkeeping retainer");
});

test("an unused catalogue item (use_count 0/null) has no reason badge", () => {
  const [a] = mergeLineItemSuggestions([catalogueItem({ use_count: 0 })], []);
  assert.equal(a.reason, null);
  const [b] = mergeLineItemSuggestions([catalogueItem({ use_count: null })], []);
  assert.equal(b.reason, null);
});

test("singular vs plural use-count phrasing", () => {
  const [s] = mergeLineItemSuggestions([catalogueItem({ use_count: 1 })], []);
  assert.equal(s.reason, "Used 1 time");
});

test("HSN rows map with the SAC code type, an HSN Master source badge, and no price", () => {
  const [s] = mergeLineItemSuggestions([], [hsnRow()]);
  assert.equal(s.id, "hsn:998222");
  assert.equal(s.codeType, "SAC");
  assert.equal(s.source, "HSN Master");
  assert.equal(s.rate_paise, null);
  assert.equal(s.catalogueId, null);
});

test("a goods HSN code gets the HSN code type, a bare 99-prefixed code falls back to SAC", () => {
  const [goods] = mergeLineItemSuggestions([], [hsnRow({ hsn_code: "847130", hsn_type: "goods" })]);
  assert.equal(goods.codeType, "HSN");
  const [bare] = mergeLineItemSuggestions([], [hsnRow({ hsn_code: "998221", hsn_type: null })]);
  assert.equal(bare.codeType, "SAC");
});

test("source badge distinguishes firm history (Recent) from the canonical master (HSN Master)", () => {
  const [recent] = mergeLineItemSuggestions([], [hsnRow({ source: "history", reason: "Used 4 times" })]);
  assert.equal(recent.source, "Recent");
  const [master] = mergeLineItemSuggestions([], [hsnRow({ source: "master" })]);
  assert.equal(master.source, "HSN Master");
});

test("a catalogue item with no code at all gets no code type", () => {
  const [s] = mergeLineItemSuggestions([catalogueItem({ hsn_sac: null })], []);
  assert.equal(s.codeType, null);
});

test("catalogue results always come first, in their given order, ahead of HSN rows", () => {
  const rows = mergeLineItemSuggestions(
    [catalogueItem({ id: "a", hsn_sac: "111111" }), catalogueItem({ id: "b", hsn_sac: "222222" })],
    [hsnRow({ hsn_code: "333333" })],
  );
  assert.deepEqual(rows.map((r) => r.id), ["catalogue:a", "catalogue:b", "hsn:333333"]);
});

test("an HSN row whose code exactly matches a catalogue item's code is dropped (catalogue wins)", () => {
  const rows = mergeLineItemSuggestions(
    [catalogueItem({ hsn_sac: "998222" })],
    [hsnRow({ hsn_code: "998222" }), hsnRow({ hsn_code: "998233" })],
  );
  assert.deepEqual(rows.map((r) => r.id), ["catalogue:svc-1", "hsn:998233"]);
});

test("a codeless catalogue item never dedupes an unrelated HSN row", () => {
  const rows = mergeLineItemSuggestions(
    [catalogueItem({ hsn_sac: null })],
    [hsnRow({ hsn_code: "998222" })],
  );
  assert.equal(rows.length, 2);
});

test("suggestionToLinePatch fills every field a catalogue pick carries", () => {
  const [s] = mergeLineItemSuggestions([catalogueItem()], []);
  const patch = suggestionToLinePatch(s);
  assert.deepEqual(patch, {
    description: "Accounting & Bookkeeping Services",
    hsn_sac: "998222",
    gst_rate: 18,
    unit: "NOS",
    rate: "5000",
  });
});

test("suggestionToLinePatch omits rate/unit/gst_rate an HSN-only pick doesn't carry", () => {
  const [s] = mergeLineItemSuggestions([], [hsnRow({ gst_rate_bps: null, uqc: null })]);
  const patch = suggestionToLinePatch(s);
  assert.equal(patch.description, "Accounting and bookkeeping services");
  assert.equal(patch.hsn_sac, "998222");
  assert.equal("gst_rate" in patch, false);
  assert.equal("unit" in patch, false);
  assert.equal("rate" in patch, false);
});

test("a description-less HSN row falls back to its own code as the label", () => {
  const [s] = mergeLineItemSuggestions([], [hsnRow({ description: null })]);
  assert.equal(s.description, "998222");
});
