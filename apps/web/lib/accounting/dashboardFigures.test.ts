// POST-A-515 (d): a report that did not answer is not a client with nothing in the books. The dashboard's profit-and-loss and cash-flow
// calls each had a `.catch` that left their figures at 0, and the tiles printed ₹0. These pin the reading the page now asks of each answer.
import assert from "node:assert/strict";
import test from "node:test";
import { figureText, netReading, reportReading, unreadReportsSentence, UNKNOWN_FIGURE, type FigureReading } from "./dashboardFigures.ts";

const known = (paise: number): FigureReading => ({ kind: "known", paise });
const unknown: FigureReading = { kind: "unknown" };
const rupees = (paise: number) => `₹${paise / 100}`;

test("no answer, a refusal and an answer without the figure are unknown, never zero", () => {
  assert.deepEqual(reportReading(null, () => 0), unknown);
  assert.deepEqual(reportReading(undefined, () => 0), unknown);
  assert.deepEqual(reportReading({ success: false, data: { x: 1 } }, () => 1), unknown);
  assert.deepEqual(reportReading({ success: true }, () => 1), unknown);
  assert.deepEqual(reportReading({ success: true, data: {} as { x?: number } }, (d) => d.x), unknown);
  assert.deepEqual(reportReading({ success: true, data: { x: Number.NaN } }, (d) => d.x), unknown);
  assert.deepEqual(reportReading({ success: true, data: { x: "5" as unknown as number } }, (d) => d.x), unknown);
  assert.deepEqual(reportReading({ success: true, data: null }, () => 1), unknown);
});

test("a figure the picker cannot read (it throws) is unknown", () => {
  assert.deepEqual(reportReading({ success: true, data: {} as { a: { b: number } } }, (d) => d.a.b), unknown);
});

test("a genuine zero is a reading, and prints as a figure", () => {
  const r = reportReading({ success: true, data: { total_paise: 0 } }, (d) => d.total_paise);
  assert.deepEqual(r, known(0));
  assert.equal(figureText(r, rupees), "₹0");
});

test("a negative figure is a reading too (a net loss, an overdrawn account)", () => {
  assert.deepEqual(reportReading({ success: true, data: { v: -12_345 } }, (d) => d.v), known(-12_345));
});

test("an unknown prints as a dash", () => {
  assert.equal(figureText(unknown, rupees), UNKNOWN_FIGURE);
  assert.equal(UNKNOWN_FIGURE, "—");
});

test("the profit is unknown unless both revenue and expenses are known", () => {
  assert.deepEqual(netReading(known(500_00), known(200_00)), known(300_00));
  assert.deepEqual(netReading(known(100_00), known(250_00)), known(-150_00));
  assert.deepEqual(netReading(known(0), known(0)), known(0));
  assert.deepEqual(netReading(unknown, known(200_00)), unknown);
  assert.deepEqual(netReading(known(500_00), unknown), unknown);
  assert.deepEqual(netReading(unknown, unknown), unknown);
});

test("the sentence names which report did not answer, and says the figures are not nil", () => {
  assert.equal(unreadReportsSentence(known(1), known(1)), null);
  const pl = unreadReportsSentence(unknown, known(1));
  const cf = unreadReportsSentence(known(1), unknown);
  const both = unreadReportsSentence(unknown, unknown);
  assert.match(pl!, /profit and loss report did not answer/);
  assert.match(pl!, /not nil/);
  assert.doesNotMatch(pl!, /cash-flow/);
  assert.match(cf!, /cash-flow report did not answer/);
  assert.match(cf!, /not nil/);
  assert.doesNotMatch(cf!, /profit and loss/);
  assert.match(both!, /profit and loss report and the cash-flow report/);
});
