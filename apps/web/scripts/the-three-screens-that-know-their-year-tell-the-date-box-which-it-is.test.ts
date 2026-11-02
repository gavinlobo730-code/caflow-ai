// A short date typed on a screen that is about one financial year is read inside THAT year (POST-A-126, the last of its listed gaps).
//
// WHAT WAS WRONG
//   A bare `15/3` is resolved inside a financial year. A date box that is not told which year reads it against the year of TODAY, so on a
//   screen that is about another year the typed date came out a year away from the books it belongs to. Three screens were converted last
//   without being told: the year-end adjustment's date (its engagement has a year), ITC-04's "came back on" and job-worker challan dates
//   (the statement is for the year chosen above them) and the renewal date on the lifecycle screen (the renewal form has a financial-year
//   field). Each now passes `financialYear`.
//
// WHAT THIS HOLDS
//   * the three sites pass the year their screen already knows; the engagement's year reaches the adjustments stage through one context
//     the workspace provides from the engagement it loaded;
//   * the reading rule, which this does not change, resolves `15/3` inside the year it is given and not inside today's.
//
// Run with: node --experimental-strip-types --test scripts/the-three-screens-that-know-their-year-tell-the-date-box-which-it-is.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import { loadModule } from "./tsxHarness.ts";

const WEB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const YE = "app/clients/[id]/year-end/[engagementId]";

test("the year-end adjustment's date box is told the engagement's year, through one context the workspace provides", () => {
  const form = read(`${YE}/adjustments/_page.tsx`);
  assert.ok(/<DateInput\s+aria-label="Adjustment date"\s+value=\{adjDate\}\s+financialYear=\{financialYear\}/.test(form), "the adjustment date is not told its year");
  assert.ok(/const financialYear = useEngagementFinancialYear\(\)/.test(form), "the stage does not read the engagement's year");
  assert.ok(/<AdjustmentForm\s+engagementId=\{engagementId\}\s+financialYear=\{financialYear\}/.test(form), "the form is not handed the year");
  const ws = read(`${YE}/_workspace.tsx`);
  assert.ok(/<EngagementYearProvider value=\{engagement\?\.financial_year \|\| undefined\}>\s*<ActiveStage \/>/.test(ws), "the workspace does not provide the engagement's year to its stages");
  const ctx = read(`${YE}/_engagementYear.tsx`);
  assert.ok(/createContext<string \| undefined>\(undefined\)/.test(ctx), "the year is not optional while the engagement loads");
});

test("ITC-04's two dates are told the statement's financial year, and the one anchored to the return takes its year from the return", () => {
  const panel = read("components/gst/Itc04Panel.tsx");
  const boxes = panel.match(/<DateInput\b[^>]*>/g) ?? [];
  assert.ok(boxes.length >= 2, "the panel's date boxes were not found");
  const anchored = boxes.filter((b) => /anchor=\{lot\.returned_on/.test(b));
  const free = boxes.filter((b) => !/anchor=\{lot\.returned_on/.test(b));
  assert.ok(anchored.length >= 1 && free.length >= 1, "the anchored and the unanchored date boxes were not both found");
  for (const box of free) assert.ok(/financialYear=\{year\}/.test(box), `an ITC-04 date box is not told the year: ${box.slice(0, 80)}`);
  // A short date typed beside a return date that is set belongs to THAT return's year, which can differ from the year shown above the panel;
  // the panel's year applies only while the return date is blank (a review of 2-11-2026 found the explicit year overriding the anchor's).
  for (const box of anchored) assert.ok(/financialYear=\{lot\.returned_on \? undefined : year\}/.test(box), `the anchored ITC-04 date box overrides its anchor's year: ${box.slice(0, 120)}`);
});

test("the renewal date is read inside the financial year the renewal form chose", () => {
  const page = read("app/clients/[id]/lifecycle/page.tsx");
  assert.ok(/value=\{renewalForm\.renewal_date\}\s+financialYear=\{renewalForm\.financial_year \|\| undefined\}/.test(page), "the renewal date is not told its year");
});

test("the reading rule puts a short date inside the year it is given, not inside today's", () => {
  const { parseTypedDate } = loadModule<{ parseTypedDate: (raw: string, ctx?: Record<string, unknown>) => { iso?: string | null } }>("lib/dates/typedDate");
  assert.equal(parseTypedDate("15/3", { financialYear: "2024-25" }).iso, "2025-03-15");
  assert.equal(parseTypedDate("15/6", { financialYear: "2024-25" }).iso, "2024-06-15");
  assert.equal(parseTypedDate("15/3", { financialYear: "2031-32" }).iso, "2032-03-15", "a year that is not today's was not honoured");
});
