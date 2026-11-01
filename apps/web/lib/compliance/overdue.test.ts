// The one overdue predicate for compliance obligations. Run with:
//   node --experimental-strip-types --test lib/compliance/overdue.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isOverdue, isUpcoming } from "./overdue.ts";

const TODAY = "2026-09-27";
const row = (due_date: string, filing_status: string) => ({ due_date, filing_status });

test("a pending obligation past its due date is overdue — whatever the stored status says", () => {
  // The defect: /deadlines compared the stored filing_status to "overdue",
  // which nothing writes, so this row was invisible to the filter.
  assert.equal(isOverdue(row("2026-09-20", "pending"), TODAY), true);
  assert.equal(isOverdue(row("2026-09-20", "in_progress"), TODAY), true);
});

test("due TODAY is not yet late; due tomorrow is not late", () => {
  assert.equal(isOverdue(row(TODAY, "pending"), TODAY), false);
  assert.equal(isOverdue(row("2026-09-28", "pending"), TODAY), false);
});

test("filed and not-applicable owe nothing however old", () => {
  assert.equal(isOverdue(row("2025-01-01", "filed"), TODAY), false);
  assert.equal(isOverdue(row("2025-01-01", "na"), TODAY), false);
});

test("a row somebody moved to overdue by hand is overdue", () => {
  assert.equal(isOverdue(row("2026-10-20", "overdue"), TODAY), true);
});

test("a timestamp-shaped due date is compared on its calendar date", () => {
  assert.equal(isOverdue(row("2026-09-26T00:00:00", "pending"), TODAY), true);
  assert.equal(isOverdue(row("2026-09-27T23:59:59", "pending"), TODAY), false);
});

test("no due date is not overdue", () => {
  assert.equal(isOverdue(row("", "pending"), TODAY), false);
});

// ── isUpcoming: the open obligations that are not late, so the two lists never share a row ───────────────────────────────────────────


test("an open obligation due today or later is upcoming; one due before today, or moved to overdue by hand, is not", () => {
  const today = "2026-10-20";
  assert.equal(isUpcoming({ due_date: "2026-10-20", filing_status: "pending" }, today), true, "due today is not late until the day is out");
  assert.equal(isUpcoming({ due_date: "2026-10-21", filing_status: "in_progress" }, today), true);
  assert.equal(isUpcoming({ due_date: "2026-10-19", filing_status: "pending" }, today), false);
  assert.equal(isUpcoming({ due_date: "2026-11-30", filing_status: "overdue" }, today), false, "moved to overdue by hand with a date ahead");
});

test("a settled obligation is neither upcoming nor overdue, and a missing date is neither", () => {
  const today = "2026-10-20";
  for (const filing_status of ["filed", "na"]) {
    assert.equal(isUpcoming({ due_date: "2026-12-01", filing_status }, today), false, filing_status);
    assert.equal(isOverdue({ due_date: "2026-01-01", filing_status }, today), false, filing_status);
  }
  assert.equal(isUpcoming({ due_date: "", filing_status: "pending" }, today), false);
  assert.equal(isOverdue({ due_date: "", filing_status: "pending" }, today), false);
});

test("no open obligation is in both lists or in neither, for any date", () => {
  const today = "2026-10-20";
  for (const filing_status of ["pending", "in_progress", "overdue"]) {
    for (const due_date of ["2026-09-01", "2026-10-19", "2026-10-20", "2026-10-21", "2027-03-31"]) {
      const e = { due_date, filing_status };
      assert.equal(Number(isOverdue(e, today)) + Number(isUpcoming(e, today)), 1, `${filing_status} ${due_date}`);
    }
  }
});
