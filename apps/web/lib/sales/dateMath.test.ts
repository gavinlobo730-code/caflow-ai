// Unit tests for the sales-invoice due-date arithmetic (payment terms ⇄ due
// date). These pin the regression this module was extracted to fix: addDaysISO
// must return the LOCAL calendar date, never one shifted a day early by a UTC
// round-trip (the old Date#toISOString().slice(0, 10) implementation) — which
// happens for every positive-UTC-offset timezone, including IST (UTC+5:30),
// i.e. every real user of this product. Run with:
//   node --experimental-strip-types --test lib/sales/dateMath.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { addDaysISO, diffDaysISO } from "./dateMath.ts";

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

// ── addDaysISO: IST (the reported-bug timezone) ─────────────────────────────

test("addDaysISO: Net 30 from 12-Mar-2026 lands on 11-Apr-2026 under IST", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2026-03-12", 30), "2026-04-11");
  });
});

test("addDaysISO: Net 15 from 12-Mar-2026 lands on 27-Mar-2026 under IST", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2026-03-12", 15), "2026-03-27");
  });
});

test("addDaysISO: Due on Receipt (0 days) stays same-day under IST", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2026-03-12", 0), "2026-03-12");
  });
});

test("addDaysISO: Net 45 and Net 60 (month rollover) are correct under IST", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2026-03-12", 45), "2026-04-26");
    assert.equal(addDaysISO("2026-03-12", 60), "2026-05-11");
  });
});

test("addDaysISO: year rollover is correct under IST", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2026-12-20", 45), "2027-02-03");
  });
});

// ── addDaysISO: UTC (must match IST exactly — no timezone dependency) ──────

test("addDaysISO: every preset matches under UTC too", () => {
  withTZ("UTC", () => {
    assert.equal(addDaysISO("2026-03-12", 0), "2026-03-12");
    assert.equal(addDaysISO("2026-03-12", 15), "2026-03-27");
    assert.equal(addDaysISO("2026-03-12", 30), "2026-04-11");
    assert.equal(addDaysISO("2026-03-12", 45), "2026-04-26");
    assert.equal(addDaysISO("2026-03-12", 60), "2026-05-11");
  });
});

test("addDaysISO: identical result under IST and UTC for the same input", () => {
  for (const days of [0, 15, 30, 45, 60]) {
    let istResult = "";
    let utcResult = "";
    withTZ("Asia/Kolkata", () => { istResult = addDaysISO("2026-03-12", days); });
    withTZ("UTC", () => { utcResult = addDaysISO("2026-03-12", days); });
    assert.equal(istResult, utcResult, `mismatch at +${days}d: IST=${istResult} UTC=${utcResult}`);
  }
});

// ── addDaysISO: negative days and leap years ────────────────────────────────

test("addDaysISO: negative days rolls the calendar backward across month/year boundaries", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2026-03-01", -5), "2026-02-24");
    assert.equal(addDaysISO("2026-01-01", -1), "2025-12-31");
  });
});

test("addDaysISO: crosses Feb 29 correctly in a leap year, and skips it in a non-leap year", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(addDaysISO("2028-02-28", 1), "2028-02-29"); // 2028 is a leap year
    assert.equal(addDaysISO("2027-02-28", 1), "2027-03-01"); // 2027 is not
  });
});

// ── addDaysISO: malformed input ─────────────────────────────────────────────

test("addDaysISO: empty or invalid date returns empty string", () => {
  assert.equal(addDaysISO("", 30), "");
  assert.equal(addDaysISO("not-a-date", 30), "");
});

test("addDaysISO: non-finite or out-of-range days returns empty string, never \"NaN-NaN-NaN\"", () => {
  assert.equal(addDaysISO("2026-03-12", NaN), "");
  assert.equal(addDaysISO("2026-03-12", Infinity), "");
  assert.equal(addDaysISO("2026-03-12", 100_000_000), "");
});

// ── diffDaysISO: the reverse gap (editing the due date directly) ───────────

test("diffDaysISO: whole-day gap for a Net 30 pair under IST", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(diffDaysISO("2026-03-12", "2026-04-11"), 30);
  });
});

test("diffDaysISO: whole-day gap under UTC matches IST (the fixed UTC offset cancels in the subtraction)", () => {
  withTZ("UTC", () => {
    assert.equal(diffDaysISO("2026-03-12", "2026-04-11"), 30);
  });
});

test("diffDaysISO: same-day gap (Due on Receipt) is 0", () => {
  withTZ("Asia/Kolkata", () => {
    assert.equal(diffDaysISO("2026-03-12", "2026-03-12"), 0);
  });
});

test("diffDaysISO: round-trips with addDaysISO for every payment-term preset, under IST", () => {
  withTZ("Asia/Kolkata", () => {
    for (const days of [0, 15, 30, 45, 60]) {
      const due = addDaysISO("2026-03-12", days);
      assert.equal(diffDaysISO("2026-03-12", due), days);
    }
  });
});

test("diffDaysISO: null on empty/malformed input", () => {
  assert.equal(diffDaysISO("", "2026-04-11"), null);
  assert.equal(diffDaysISO("2026-03-12", ""), null);
  assert.equal(diffDaysISO("nonsense", "2026-04-11"), null);
});
