// GST-20 — the worklist of invoices that need an IRN and have none: wording only.
//
// Run with:
//   node --experimental-strip-types --test lib/gst/irnWorklist.test.ts
//
// The server decides everything about a row; what is asserted here is that the
// FIVE window states are worded as five different things. In particular that an
// invoice with no IRP limit never reads as fine and never gets a deadline.
import { test } from "node:test";
import assert from "node:assert/strict";
import { irnStateText, isActionable, windowText, windowTone } from "./irnWorklist.ts";

type W = Parameters<typeof windowText>[0];
const w = (over: Partial<W>): W => ({
  status: "within_window", days: 30, deadline: "2026-10-02", days_left: 1,
  assumed: false, applies: true, ...over,
});

test("a window with days left says how many, to what date", () => {
  assert.equal(windowText(w({})), "1 day left, until 2026-10-02");
  assert.equal(windowText(w({ days_left: 12, deadline: "2026-10-13" })),
    "12 days left, until 2026-10-13");
});

test("the last day is its own state", () => {
  assert.match(windowText(w({ status: "last_day", days_left: 0, deadline: "2026-10-01" })),
    /Last day to report to the IRP — 2026-10-01/);
});

test("a lapsed window says the IRP's limit, in days past", () => {
  assert.equal(windowText(w({ status: "past_window", days_left: -1 })),
    "1 day past the IRP's 30-day limit");
  assert.equal(windowText(w({ status: "past_window", days_left: -9 })),
    "9 days past the IRP's 30-day limit");
});

test("no reporting limit is NOT fine and carries NO deadline", () => {
  const text = windowText(w({ status: "no_reporting_limit", deadline: null,
                              days_left: null, applies: false }));
  assert.match(text, /an IRN is still owed/);
  assert.doesNotMatch(text, /\d/, "a client with no IRP limit must not be shown a date or a count");
});

test("an assumed window says so", () => {
  assert.match(windowText(w({ assumed: true, applies: null })), /\(assumed\)$/);
  assert.match(windowText(w({ status: "past_window", days_left: -3, assumed: true })), /\(assumed\)$/);
});

test("only a lapsed window is a problem, and only today's last day is attention", () => {
  assert.equal(windowTone(w({ status: "past_window", days_left: -1 })), "problem");
  assert.equal(windowTone(w({ status: "last_day", days_left: 0 })), "attention");
  assert.equal(windowTone(w({})), "neutral");
  // Not "ready" either: an invoice with no limit still owes an IRN.
  assert.equal(windowTone(w({ status: "no_reporting_limit" })), "neutral");
});

test("what a CA can still do at the IRP", () => {
  assert.equal(isActionable(w({})), true);
  assert.equal(isActionable(w({ status: "last_day" })), true);
  assert.equal(isActionable(w({ status: "no_reporting_limit" })), true);
  assert.equal(isActionable(w({ status: "past_window" })), false);
});

test("the three kinds of 'no IRN' read differently", () => {
  const three = new Set([irnStateText("none"), irnStateText("irn_cancelled"),
                         irnStateText("record_prepared_not_generated")]);
  assert.equal(three.size, 3);
  assert.match(irnStateText("irn_cancelled"), /cancelled/);
});
