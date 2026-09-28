// The one overdue predicate for compliance obligations. Run with:
//   node --experimental-strip-types --test lib/compliance/overdue.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isOverdue } from "./overdue.ts";

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
