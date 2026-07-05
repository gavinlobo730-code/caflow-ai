// Unit tests for the shared calendar-date helpers used by Journal Entry,
// Recurring "Post Now", and the Receivables/Billing aging reports (Phase 1 —
// Critical Accounting & Financial Date Correctness). These pin the exact
// regression each of those was fixed for: reading "today" must never round-
// trip through UTC (Date#toISOString), and a days-overdue diff must never mix
// a UTC-midnight-parsed date-only string with a live `new Date()` instant —
// both silently disagree with the true IST calendar date for IST users
// (UTC+5:30) between local midnight and 05:29 local time. Run with:
//   node --experimental-strip-types --test lib/dateMath.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  toLocalISO,
  todayLocalISO,
  daysBetweenLocalISO,
  computeOverdueStatus,
  currentFinancialYearLabel,
} from "./dateMath.ts";

const ORIGINAL_TZ = process.env.TZ;

/** Run `fn` with process.env.TZ temporarily set, always restoring it after —
 * even on assertion failure — so one test's timezone never leaks into another.
 * process.env can only hold strings, so `process.env.TZ = undefined` would
 * coerce to the literal string "undefined" (an invalid IANA zone) rather than
 * clearing it — delete the key instead when TZ was originally unset. */
function withTZ(tz: string, fn: () => void): void {
  process.env.TZ = tz;
  try {
    fn();
  } finally {
    if (ORIGINAL_TZ === undefined) delete process.env.TZ;
    else process.env.TZ = ORIGINAL_TZ;
  }
}

// ── toLocalISO / todayLocalISO ──────────────────────────────────────────────

test("toLocalISO: formats local calendar components, never via toISOString", () => {
  withTZ("Asia/Kolkata", () => {
    // 2026-03-31 23:45 IST is 2026-03-31 18:15 UTC — same calendar day in
    // both zones, so this alone wouldn't catch a UTC round-trip bug; the
    // point is toLocalISO must read LOCAL components regardless.
    assert.equal(toLocalISO(new Date(2026, 2, 31, 23, 45)), "2026-03-31");
  });
});

test("toLocalISO: local midnight on 1 Apr reads as 1 Apr under IST, not 31 Mar (the exact FY-boundary bug)", () => {
  withTZ("Asia/Kolkata", () => {
    // Constructed via local Y/M/D/H/M — this is what `new Date()` would read
    // at 00:01 local time on the FY-rollover day.
    const localMidnightPlusOneMin = new Date(2026, 3, 1, 0, 1);
    assert.equal(toLocalISO(localMidnightPlusOneMin), "2026-04-01");
  });
});

test("toLocalISO: identical result under IST and UTC for the same local wall-clock construction", () => {
  for (const tz of ["Asia/Kolkata", "UTC"]) {
    withTZ(tz, () => {
      assert.equal(toLocalISO(new Date(2026, 3, 1, 0, 1)), "2026-04-01");
    });
  }
});

test("todayLocalISO: matches toLocalISO(new Date()) at call time (wiring check, not a frozen-clock test)", () => {
  withTZ("Asia/Kolkata", () => {
    // No fake-timers library in this project's test runner; assert the two
    // expressions agree within the same tick rather than mocking `now`.
    assert.equal(todayLocalISO(), toLocalISO(new Date()));
  });
});

// ── daysBetweenLocalISO — the aging / days-overdue diff ─────────────────────

test("daysBetweenLocalISO: current (due today) is 0", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(daysBetweenLocalISO("2026-07-05", "2026-07-05"), 0);
  });
});

test("daysBetweenLocalISO: 1 day overdue — the exact IST-boundary regression this fix closes", () => {
  withTZ("Asia/Kolkata", () => {
    // Previously `new Date(dueDateStr)` (parsed as UTC midnight) was diffed
    // against a live `new Date()` instant, undercounting by 1 whenever "now"
    // fell in 00:00-05:29 IST (the evaluating instant's time-of-day leaked
    // into the result). Here both sides are plain date strings — there is no
    // "now" instant for a time-of-day to leak from, so the result is the
    // same 1 regardless of what wall-clock time this test happens to run at.
    assert.equal(daysBetweenLocalISO("2026-07-04", "2026-07-05"), 1);
  });
});

test("daysBetweenLocalISO: 30 / 60 / 90 day bucket boundaries", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(daysBetweenLocalISO("2026-06-05", "2026-07-05"), 30);
    assert.equal(daysBetweenLocalISO("2026-05-06", "2026-07-05"), 60);
    assert.equal(daysBetweenLocalISO("2026-04-06", "2026-07-05"), 90);
    assert.equal(daysBetweenLocalISO("2026-04-05", "2026-07-05"), 91); // just past the 90+ bucket
  });
});

test("daysBetweenLocalISO: not due yet is negative", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(daysBetweenLocalISO("2026-07-10", "2026-07-05"), -5);
  });
});

test("daysBetweenLocalISO: identical result under IST and UTC for the same date-string inputs (the fixed UTC offset cancels)", () => {
  for (const tz of ["Asia/Kolkata", "UTC"]) {
    withTZ(tz, () => {
      assert.equal(daysBetweenLocalISO("2026-06-05", "2026-07-05"), 30);
    });
  }
});

test("daysBetweenLocalISO: null on empty/malformed input", () => {
  assert.equal(daysBetweenLocalISO("", "2026-07-05"), null);
  assert.equal(daysBetweenLocalISO("2026-07-05", ""), null);
  assert.equal(daysBetweenLocalISO("nonsense", "2026-07-05"), null);
});

// ── daysBetweenLocalISO vs the pre-consolidation loans-page formula ────────
// app/accounting/loans/page.tsx::daysToDate() (FD/loan maturity countdown)
// now delegates its arithmetic to daysBetweenLocalISO (Phase 3). Its old body
// parsed both operands as bare `new Date(isoString)` (UTC midnight, since
// neither string carries a time component) and used Math.ceil; this proves
// that formula and daysBetweenLocalISO agree on every whole-day diff, because
// a fixed (non-DST) offset cancels identically in a subtraction regardless of
// whether both sides are anchored to UTC midnight or local midnight, and a
// midnight-to-midnight diff is always an exact multiple of a day (so
// Math.ceil and daysBetweenLocalISO's Math.round always agree).
function oldLoansPageDaysToDate(fromISO: string, toISO: string): number {
  const target = new Date(toISO).getTime();
  const now = new Date(fromISO).getTime();
  return Math.ceil((target - now) / (24 * 60 * 60 * 1000));
}

test("daysBetweenLocalISO: matches the pre-consolidation loans-page formula across leap years and month/year boundaries", () => {
  withTZ("Asia/Kolkata", () => {
    const pairs: [string, string][] = [
      ["2026-07-05", "2026-07-05"],   // same day
      ["2026-07-05", "2026-08-04"],   // ordinary month gap
      ["2026-02-01", "2026-03-01"],   // Feb (non-leap, 2026) -> Mar
      ["2024-02-01", "2024-03-01"],   // Feb (leap, 2024) -> Mar, one extra day
      ["2023-12-15", "2024-01-15"],   // year boundary
      ["2026-03-31", "2026-04-01"],   // FY boundary, 1 day
      ["2026-08-04", "2026-07-05"],   // past (negative)
    ];
    for (const [from, to] of pairs) {
      assert.equal(daysBetweenLocalISO(from, to), oldLoansPageDaysToDate(from, to));
    }
  });
});

// ── computeOverdueStatus — shared GST/MCA filing-tracker status ─────────────
// (Phase 2 — Compliance & Statutory Date Correctness). GST's and MCA's filing
// trackers each independently compared a live `new Date()`/module-frozen
// instant against a due date; both are now this one function so the fix is
// tested once instead of twice.

test("computeOverdueStatus: due today is Pending, NOT Overdue (the exact bug this closes)", () => {
  // The old `TODAY > new Date(dueDate)` shape flips to Overdue the instant any
  // time has passed since the due date's midnight — i.e. on the due date
  // itself, up to a full day early.
  assert.equal(computeOverdueStatus("2026-07-05", null, "2026-07-05"), "Pending");
});

test("computeOverdueStatus: 1 day past due is Overdue", () => {
  assert.equal(computeOverdueStatus("2026-07-04", null, "2026-07-05"), "Overdue");
});

test("computeOverdueStatus: due in the future is Pending (upcoming)", () => {
  assert.equal(computeOverdueStatus("2026-07-10", null, "2026-07-05"), "Pending");
});

test("computeOverdueStatus: Filed wins even when the due date is long past", () => {
  assert.equal(computeOverdueStatus("2026-01-01", "2026-01-15", "2026-07-05"), "Filed");
});

test("computeOverdueStatus: month boundary — due last day of month, checked 1st of next month", () => {
  assert.equal(computeOverdueStatus("2026-06-30", null, "2026-07-01"), "Overdue");
  assert.equal(computeOverdueStatus("2026-06-30", null, "2026-06-30"), "Pending"); // due today
});

test("computeOverdueStatus: FY boundary — due 31 Mar, checked 1 Apr (new FY) is Overdue", () => {
  assert.equal(computeOverdueStatus("2026-03-31", null, "2026-04-01"), "Overdue");
});

test("computeOverdueStatus: IST boundary — due 31 Mar, 'today' resolved via toLocalISO at 1 Apr 00:01 IST", () => {
  withTZ("Asia/Kolkata", () => {
    // Mirrors how a page actually derives its `today` argument: toLocalISO of
    // a live Date, not a raw toISOString() (which would still read 31 Mar
    // here and wrongly report Pending for an invoice that's already overdue).
    const today = toLocalISO(new Date(2026, 3, 1, 0, 1));
    assert.equal(computeOverdueStatus("2026-03-31", null, today), "Overdue");
  });
});

test("computeOverdueStatus: default third argument uses todayLocalISO() (wiring check)", () => {
  withTZ("Asia/Kolkata", () => {
    const farFuture = "2099-01-01";
    assert.equal(computeOverdueStatus(farFuture, null), "Pending");
  });
});

// ── currentFinancialYearLabel — shared FY-label helper (Phase 3) ───────────
// Previously three independent, identical implementations in
// lib/workspace/ClientNavContext.tsx::getCurrentFinancialYear(),
// lib/data/income-tax.ts::currentFinancialYear() and
// lib/data/tds.ts::currentFinancialYear() — all now thin delegates to this
// one function. These pin the exact label each produced before the
// consolidation, including the `.slice(2)` vs `.slice(-2)` variant the two
// implementations used (equivalent for any 4-digit year, verified below).

/** The formula all three call sites independently implemented before Phase 3
 * — kept here (not imported) so this test proves the shared helper still
 * matches it, rather than trivially checking the helper against itself. */
function oldFormulaSliceNegative2(d: Date): string {
  const year = d.getFullYear();
  const month = d.getMonth() + 1;
  const fyStart = month >= 4 ? year : year - 1;
  const fyEnd = (fyStart + 1).toString().slice(-2);
  return `${fyStart}-${fyEnd}`;
}

function oldFormulaSlice2(d: Date): string {
  const yr = d.getFullYear();
  const mo = d.getMonth() + 1;
  return mo >= 4 ? `${yr}-${String(yr + 1).slice(2)}` : `${yr - 1}-${String(yr).slice(2)}`;
}

test("currentFinancialYearLabel: matches both pre-consolidation formulas across every month", () => {
  for (const year of [2023, 2024, 2025, 2026]) {
    for (let month = 0; month < 12; month++) {
      const d = new Date(year, month, 15);
      const got = currentFinancialYearLabel(d);
      assert.equal(got, oldFormulaSliceNegative2(d));
      assert.equal(got, oldFormulaSlice2(d));
    }
  }
});

test("currentFinancialYearLabel: FY boundary — 31 Mar is the outgoing FY", () => {
  assert.equal(currentFinancialYearLabel(new Date(2026, 2, 31)), "2025-26");
});

test("currentFinancialYearLabel: FY boundary — 1 Apr is the new FY", () => {
  assert.equal(currentFinancialYearLabel(new Date(2026, 3, 1)), "2026-27");
});

test("currentFinancialYearLabel: leap day (29 Feb 2024) falls in FY 2023-24", () => {
  assert.equal(currentFinancialYearLabel(new Date(2024, 1, 29)), "2023-24");
});

test("currentFinancialYearLabel: default argument uses `new Date()` (wiring check)", () => {
  assert.equal(currentFinancialYearLabel(), currentFinancialYearLabel(new Date()));
});
