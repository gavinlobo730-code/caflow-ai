import assert from "node:assert/strict";
import test from "node:test";
import { chosenCompany, preselectedYear, readFilingChoices } from "./filingChoices.ts";

const TWO = {
  companies: [{ id: "c1", company_name: "Alpha Pvt Ltd", cin: "U1" }, { id: "c2", company_name: "Beta Pvt Ltd", cin: null }],
  company_required: true,
  has_obligation: true,
  periods: [{ financial_year: "2025-26", due_date: "2026-10-30", status: "Not Started" }, { financial_year: "2024-25", due_date: null, status: "Overdue" }],
  periods_note: null,
};

test("the server's answer is read as it is sent", () => {
  const got = readFilingChoices(TWO);
  assert.deepEqual(got, TWO);
});

test("anything that is not that shape is null, so the screen falls back to typed boxes", () => {
  for (const bad of [null, [], "x", {}, { companies: "x", periods: null }, { companies: [], periods: "x" },
    { companies: [{ company_name: "No id" }], periods: null }, { companies: [], periods: [{ due_date: "2026-10-30" }] }]) {
    assert.equal(readFilingChoices(bad), null, JSON.stringify(bad));
  }
});

test("a choice is required when there is more than one company, whatever the payload claims", () => {
  assert.equal(readFilingChoices({ ...TWO, company_required: false })?.company_required, true);
  assert.equal(readFilingChoices({ ...TWO, companies: [TWO.companies[0]], company_required: true })?.company_required, false);
});

test("the form stands for an obligation only when the server says exactly so", () => {
  assert.equal(readFilingChoices({ ...TWO, has_obligation: false })?.has_obligation, false);
  assert.equal(readFilingChoices({ ...TWO, has_obligation: "yes" })?.has_obligation, false);
  const without: Record<string, unknown> = { ...TWO };
  delete without.has_obligation;
  assert.equal(readFilingChoices(without)?.has_obligation, false);
});

test("no year offered is null with the server's sentence", () => {
  const got = readFilingChoices({ companies: [], periods: null, periods_note: "No year." });
  assert.equal(got?.periods, null);
  assert.equal(got?.periods_note, "No year.");
});

test("the company a filing names: the one chosen, the only one, or none", () => {
  const two = readFilingChoices(TWO);
  assert.equal(chosenCompany(two, "c2")?.company_name, "Beta Pvt Ltd");
  assert.equal(chosenCompany(two, ""), null);
  assert.equal(chosenCompany(two, "not-theirs"), null);
  const one = readFilingChoices({ ...TWO, companies: [TWO.companies[0]] });
  assert.equal(chosenCompany(one, "")?.id, "c1");
  assert.equal(chosenCompany(readFilingChoices({ ...TWO, companies: [] }), "c1"), null);
  assert.equal(chosenCompany(null, "c1"), null);
});

test("a year is preselected only when the calendar holds exactly one open", () => {
  assert.equal(preselectedYear(readFilingChoices(TWO)), "");
  assert.equal(preselectedYear(readFilingChoices({ ...TWO, periods: [TWO.periods[0]] })), "2025-26");
  assert.equal(preselectedYear(readFilingChoices({ ...TWO, periods: null })), "");
  assert.equal(preselectedYear(null), "");
});
