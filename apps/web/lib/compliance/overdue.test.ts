// The one overdue predicate for compliance obligations. Run with:
//   node --experimental-strip-types --test lib/compliance/overdue.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { isOverdue, isUpcoming, filingTrackerStatus, calendarWordForMcaStatus } from "./overdue.ts";

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

// ── the word the GST and MCA filing trackers print (POST-A-280) ─────────────────────────────────────────────────────────────
const tracker = (due_date: string, filing_status: string | null, filed_date: string | null = null) =>
  filingTrackerStatus({ due_date, filing_status, filed_date }, TODAY);

test("a tracker row recorded as not applicable says so, however old its date: it is neither Overdue nor Pending", () => {
  // The defect: the trackers decided from the dates alone, so this row read Overdue (and counted in the Overdue tile).
  assert.equal(tracker("2025-01-01", "na"), "Not applicable");
  assert.equal(tracker("2026-12-01", "na"), "Not applicable");
});

test("a filed word or a filed date is a filing, and wins over a not-applicable or overdue word", () => {
  assert.equal(tracker("2025-01-01", "filed"), "Filed");
  assert.equal(tracker("2025-01-01", "pending", "2025-02-01"), "Filed");
  assert.equal(tracker("2025-01-01", "overdue", "2025-02-01"), "Filed");
  assert.equal(tracker("2025-01-01", "na", "2025-02-01"), "Filed");
});

test("a row somebody moved to overdue by hand reads Overdue even with its date ahead, as on the Deadlines screen", () => {
  assert.equal(tracker("2026-12-01", "overdue"), "Overdue");
});

test("an open obligation is Overdue strictly after its due date and Pending on it (the day is not out)", () => {
  assert.equal(tracker("2026-09-26", "pending"), "Overdue");
  assert.equal(tracker(TODAY, "pending"), "Pending");
  assert.equal(tracker("2026-09-28", "in_progress"), "Pending");
});

test("no stored word is read as pending, and no due date cannot be late", () => {
  assert.equal(tracker("2026-09-26", null), "Overdue");
  assert.equal(tracker("", "pending"), "Pending");
});

test("the tracker and the Deadlines rule never disagree about an open obligation", () => {
  for (const status of ["pending", "in_progress", "overdue"]) {
    for (const due of ["2025-01-01", "2026-09-26", TODAY, "2026-09-28", "2099-01-01"]) {
      assert.equal(tracker(due, status) === "Overdue", isOverdue(row(due, status), TODAY), `${status} due ${due}`);
    }
  }
});

test("the MCA table's stored words map to the calendar's, in any case, and an unknown word is the open state", () => {
  assert.equal(calendarWordForMcaStatus("filed"), "filed");
  assert.equal(calendarWordForMcaStatus("Overdue"), "overdue");
  assert.equal(calendarWordForMcaStatus("not_applicable"), "na");
  assert.equal(calendarWordForMcaStatus("NA"), "na");
  for (const open of ["not_started", "in_progress", "pending", "", null, undefined, "something new"]) {
    assert.equal(calendarWordForMcaStatus(open as string | null | undefined), "pending", String(open));
  }
});

test("an MCA filing recorded as not applicable is not printed Overdue by its date, and one marked overdue by hand is, with its date ahead", () => {
  const print = (stored: string, due: string, filed: string | null = null) =>
    filingTrackerStatus({ due_date: due, filing_status: calendarWordForMcaStatus(stored), filed_date: filed }, TODAY);
  assert.equal(print("not_applicable", "2025-01-01"), "Not applicable");
  assert.equal(print("overdue", "2026-12-01"), "Overdue");
  assert.equal(print("not_started", "2026-09-26"), "Overdue");
  assert.equal(print("filed", "2025-01-01"), "Filed");
});
