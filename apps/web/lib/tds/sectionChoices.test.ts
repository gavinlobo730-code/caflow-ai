// Run with: node --experimental-strip-types --test lib/tds/sectionChoices.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { NO_SECTIONS, sectionChoices, sectionOptionText } from "./sectionChoices.ts";
import type { TDSSection } from "../data/tds.ts";

const row = (section: string, extra: Partial<TDSSection> = {}): TDSSection => ({
  section, threshold_paise: 0, aggregate_threshold_paise: null, rate_individual_pct: 1, rate_company_pct: 2, ...extra,
});

const SERVED = {
  sections: [
    row("192", { label: "Salary", vendor_eligible: false }),
    row("194J", { label: "Professional / technical fees" }),
    row("194J(A)", { label: "Professional / technical fees", parent_section: "194J" }),
    row("194T", { label: "Payments to partners of a firm" }),
    row("206C", { label: "TCS on sale of goods", vendor_eligible: false }),
  ],
  challan_sections: [
    { section: "192", label: "Salary" }, { section: "194J", label: "Professional / technical fees" },
    { section: "194T", label: "Payments to partners of a firm" }, { section: "206C", label: "TCS on sale of goods" },
    { section: "195", label: "Payments to non-residents" },
  ],
};

test("a deduction is offered only the sections the server does not mark unavailable", () => {
  assert.deepEqual(sectionChoices(SERVED).deductible, ["194J", "194J(A)", "194T"]);
});

test("a challan is offered the server's own list, §195 and §194T included, in the server's order", () => {
  assert.deepEqual(sectionChoices(SERVED).challan.map((c) => c.section), ["192", "194J", "194T", "206C", "195"]);
});

test("the names are the server's, for the sections and for the challan list", () => {
  const { labels } = sectionChoices(SERVED);
  assert.equal(labels["195"], "Payments to non-residents");
  assert.equal(labels["194J(A)"], "Professional / technical fees");
});

test("a section with no name is shown by its code, and one with a name by both", () => {
  assert.equal(sectionOptionText("194X", { "194J": "Fees" }), "194X");
  assert.equal(sectionOptionText("194J", { "194J": "Fees" }), "194J — Fees");
});

test("a server one deploy behind sends no challan list: the parents of its sections stand in, and §195 is not invented", () => {
  const unnamed = (s: TDSSection): TDSSection => ({ ...s, label: undefined });
  const old = sectionChoices({ sections: SERVED.sections.map(unnamed) });
  assert.deepEqual(old.challan.map((c) => c.section), ["192", "194J", "194T", "206C"]);
  assert.deepEqual(old.labels, {});
});

test("the Section filter can select every section a recorded deduction carries: a limb the form offers, a section only a challan names, one the form no longer offers", () => {
  const { filterable } = sectionChoices(SERVED);
  assert.deepEqual(filterable, ["194J", "194J(A)", "194T", "192", "206C", "195"]);
  assert.equal(new Set(filterable).size, filterable.length, "a section is offered once");
  // a limb ("194J(A)") is on a deduction row and is not among the parents a challan names
  assert.ok(filterable.includes("194J(A)") && !sectionChoices(SERVED).challan.some((c) => c.section === "194J(A)"));
});

test("against a server one deploy behind the filter still lists every section it served", () => {
  const unnamed = (s: TDSSection): TDSSection => ({ ...s, label: undefined });
  const { filterable } = sectionChoices({ sections: SERVED.sections.map(unnamed) });
  assert.deepEqual(filterable, ["194J", "194J(A)", "194T", "192", "206C"]);
});

test("nothing is offered before the server has answered", () => {
  assert.deepEqual(NO_SECTIONS, { labels: {}, deductible: [], challan: [], filterable: [] });
});
