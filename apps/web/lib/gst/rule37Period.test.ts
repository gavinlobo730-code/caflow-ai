// Which return a Rule 37 reversal belongs in. Run with:
//   node --experimental-strip-types --test lib/gst/rule37Period.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { chronoKey, splitRule37Bills, periodEndDate } from "./rule37Period.ts";

const bill = (reverse_in_period: string, no = reverse_in_period) =>
  ({ reverse_in_period, no });

test("a January reversal is not treated as older than the December before it", () => {
  // The bug this function exists to prevent. As raw MMYYYY strings, "012026"
  // sorts below "122025", so a plain comparison would call January 2026 an
  // EARLIER period than December 2025 — and quietly move a reversal out of the
  // return that has to carry it.
  assert.ok(chronoKey("012026") > chronoKey("122025"));
  const { due, earlier } = splitRule37Bills(
    [bill("122025"), bill("012026")], "012026");
  assert.deepEqual(due.map(b => b.no), ["012026"]);
  assert.deepEqual(earlier.map(b => b.no), ["122025"]);
});

test("only the bills Rule 37(1) puts in THIS return are due", () => {
  const { due } = splitRule37Bills(
    [bill("052026"), bill("062026"), bill("062026", "b2"), bill("072026")],
    "062026");
  assert.deepEqual(due.map(b => b.no), ["062026", "b2"]);
});

test("a later period is in neither bucket", () => {
  // Reversing early is a real error — the credit is still available in this
  // period — so a future finding must not be shown as due now.
  const { due, earlier } = splitRule37Bills([bill("072026")], "062026");
  assert.deepEqual(due, []);
  assert.deepEqual(earlier, []);
});

test("nothing overdue produces two empty buckets, not a crash", () => {
  const { due, earlier } = splitRule37Bills([], "062026");
  assert.deepEqual(due, []);
  assert.deepEqual(earlier, []);
});

test("every bill lands in exactly one bucket or none — never both", () => {
  const bills = ["012025", "122025", "012026", "062026", "122026"].map(p => bill(p));
  for (const period of ["012026", "122025", "062026"]) {
    const { due, earlier } = splitRule37Bills(bills, period);
    const seen = [...due, ...earlier].map(b => b.no);
    assert.equal(new Set(seen).size, seen.length,
      `a bill appeared in both buckets for ${period}`);
  }
});

test("the period end is the last day of the month, not the first of the next", () => {
  assert.equal(periodEndDate("2026-06"), "2026-06-30");
  assert.equal(periodEndDate("2026-07"), "2026-07-31");
  assert.equal(periodEndDate("2026-12"), "2026-12-31");
  assert.equal(periodEndDate("2026-01"), "2026-01-31");
});

test("February knows about leap years", () => {
  // Asking one day early in February would move a bill that crosses 180 days
  // on the 29th into the following month's return.
  assert.equal(periodEndDate("2024-02"), "2024-02-29");
  assert.equal(periodEndDate("2026-02"), "2026-02-28");
  assert.equal(periodEndDate("2100-02"), "2100-02-28");  // century, not a leap year
});

test("the answer does not shift with the machine's timezone", () => {
  // A local-time Date on a host behind UTC rolls the last instant of the month
  // back into the previous day. Built in UTC, so it cannot.
  const prev = process.env.TZ;
  try {
    for (const tz of ["UTC", "America/Los_Angeles", "Asia/Kolkata", "Pacific/Kiritimati"]) {
      process.env.TZ = tz;
      assert.equal(periodEndDate("2026-06"), "2026-06-30", `wrong under TZ=${tz}`);
      assert.equal(periodEndDate("2024-02"), "2024-02-29", `wrong under TZ=${tz}`);
    }
  } finally {
    if (prev === undefined) delete process.env.TZ; else process.env.TZ = prev;
  }
});
