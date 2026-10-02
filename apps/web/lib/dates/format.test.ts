/**
 * The one date format (frontend_ux-20). Run with:
 *   node --experimental-strip-types --test lib/dates/format.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";
import {
  DATE_ABSENT,
  MONTH_ABBREVIATIONS,
  formatDate,
  formatDateTime,
  formatMonthYear,
  formatTime,
  formatWeekdayDate,
  todayIstISO,
} from "./format.ts";

test("a bare calendar date is printed as dd MMM yyyy, zero-padded", () => {
  assert.equal(formatDate("2026-09-05"), "05 Sep 2026");
  assert.equal(formatDate("2026-12-31"), "31 Dec 2026");
  assert.equal(formatDate("2026-01-01"), "01 Jan 2026");
  assert.equal(formatDate("2024-02-29"), "29 Feb 2024");
});

test("the month comes from the fixed table, so September is Sep and never Sept", () => {
  const spelled = Array.from({ length: 12 }, (_, i) =>
    formatDate(`2026-${String(i + 1).padStart(2, "0")}-15`).split(" ")[1]);
  assert.deepEqual(spelled, [...MONTH_ABBREVIATIONS]);
  assert.equal(MONTH_ABBREVIATIONS[8], "Sep");
  assert.ok(!formatDate("2026-09-05").includes("Sept"));
});

test("a bare date is the same date in every timezone, because it is never parsed as an instant", () => {
  // `new Date("2026-03-31")` is UTC midnight and `toLocaleDateString` reads it
  // in the BROWSER's zone, so the old formatter printed 30 March for anybody
  // west of Greenwich. Each zone below is a separate process: TZ is read once,
  // when the engine starts.
  const here = pathToFileURL(path.join(import.meta.dirname, "format.ts")).href;
  const script =
    `import { formatDate, formatDateTime } from ${JSON.stringify(here)};` +
    `process.stdout.write(JSON.stringify([` +
    `formatDate("2026-03-31"), formatDate("2026-04-01"),` +
    // 19:00 UTC on 31 March is 00:30 IST on 1 April, whatever the machine says.
    `formatDateTime("2026-03-31T19:00:00Z"), formatDate("2026-03-31T19:00:00Z")]))`;
  for (const tz of ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Pacific/Honolulu", "Pacific/Kiritimati", "Europe/London"]) {
    const out = execFileSync(
      process.execPath,
      ["--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
      { env: { ...process.env, TZ: tz }, encoding: "utf8" },
    );
    assert.deepEqual(JSON.parse(out), [
      "31 Mar 2026", "01 Apr 2026", "01 Apr 2026, 12:30 am", "01 Apr 2026",
    ], `TZ=${tz} moved a date`);
  }
});

test("a timestamp is converted to its Indian date, and the boundary is 18:30 UTC", () => {
  assert.equal(formatDate("2026-03-31T18:29:59Z"), "31 Mar 2026");
  assert.equal(formatDate("2026-03-31T18:30:00Z"), "01 Apr 2026");
  assert.equal(formatDateTime("2026-03-31T18:29:59Z"), "31 Mar 2026, 11:59 pm");
  assert.equal(formatDateTime("2026-03-31T18:30:00Z"), "01 Apr 2026, 12:00 am");
  assert.equal(formatDateTime("2026-06-15T10:00:00Z"), "15 Jun 2026, 3:30 pm");
  assert.equal(formatDateTime("2026-06-15T06:30:00Z"), "15 Jun 2026, 12:00 pm");
});

test("the forms the API and Postgres actually send are all read", () => {
  const instant = "15 Jun 2026, 3:30 pm";
  assert.equal(formatDateTime("2026-06-15T10:00:00+00:00"), instant);
  assert.equal(formatDateTime("2026-06-15 10:00:00+00"), instant);
  assert.equal(formatDateTime("2026-06-15T10:00:00.123456+00:00"), instant);
  assert.equal(formatDateTime("2026-06-15T15:30:00+05:30"), instant);
  assert.equal(formatDateTime("2026-06-15T15:30:00+0530"), instant);
  // No zone: read as UTC, the server's own convention for a naive stamp.
  assert.equal(formatDateTime("2026-06-15T10:00:00"), instant);
  assert.equal(formatDateTime("2026-06-15T10:00"), instant);
});

test("a bare date has no time of day, so the date-time form does not invent one", () => {
  assert.equal(formatDateTime("2026-06-15"), "15 Jun 2026");
  assert.equal(formatTime("2026-06-15"), DATE_ABSENT);
});

test("an absent or unreadable value is the fallback, never a date", () => {
  for (const bad of [null, undefined, "", "   ", "not a date", "2026-02-31", "2026-13-01", "2026-00-10",
    "05/09/2026", "2026-09-05T25:00:00Z", "2026-09-05T10:61:00Z", 42, {}, []] as unknown[]) {
    assert.equal(formatDate(bad as string), DATE_ABSENT, `formatDate(${JSON.stringify(bad)})`);
    assert.equal(formatDateTime(bad as string), DATE_ABSENT, `formatDateTime(${JSON.stringify(bad)})`);
    assert.equal(formatMonthYear(bad as string), DATE_ABSENT, `formatMonthYear(${JSON.stringify(bad)})`);
    assert.equal(formatWeekdayDate(bad as string), DATE_ABSENT, `formatWeekdayDate(${JSON.stringify(bad)})`);
  }
  assert.equal(formatDate(null, "not recorded"), "not recorded");
  assert.equal(formatDate("2026-02-31", ""), "");
  assert.equal(formatDateTime(undefined, "never"), "never");
});

test("a leap day is a real day and a rolled-over one is not", () => {
  assert.equal(formatDate("2024-02-29"), "29 Feb 2024");
  assert.equal(formatDate("2026-02-29"), DATE_ABSENT);
});

test("a month label is Mon yyyy from a period, a date or a timestamp", () => {
  assert.equal(formatMonthYear("2026-09"), "Sep 2026");
  assert.equal(formatMonthYear("2026-09-30"), "Sep 2026");
  assert.equal(formatMonthYear("2026-09-30T20:00:00Z"), "Oct 2026");
  assert.equal(formatMonthYear("2026-13"), DATE_ABSENT);
});

test("the weekday is arithmetic on the day, so no zone can move it", () => {
  assert.equal(formatWeekdayDate("2026-10-01"), "Thursday, 01 Oct 2026");
  assert.equal(formatWeekdayDate("2026-03-31"), "Tuesday, 31 Mar 2026");
  assert.equal(formatWeekdayDate("2024-02-29"), "Thursday, 29 Feb 2024");
});

test("today in India is the Indian calendar day, however late it is in UTC", () => {
  // 19:00 UTC on 31 March is already 1 April in India.
  assert.equal(todayIstISO(Date.parse("2026-03-31T19:00:00Z")), "2026-04-01");
  assert.equal(todayIstISO(Date.parse("2026-03-31T18:29:59Z")), "2026-03-31");
  assert.equal(todayIstISO(Date.parse("2026-12-31T23:59:59Z")), "2027-01-01");
  assert.match(todayIstISO(), /^\d{4}-\d{2}-\d{2}$/);
});

test("the time of day is IST with a 12-hour clock", () => {
  assert.equal(formatTime("2026-06-15T10:00:00Z"), "3:30 pm");
  assert.equal(formatTime("2026-06-15T18:30:00Z"), "12:00 am");
  assert.equal(formatTime("2026-06-15T06:30:00Z"), "12:00 pm");
});
