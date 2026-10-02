/**
 * The one rule for a date a person types (frontend_ux-19). Run with:
 *   node --experimental-strip-types --test lib/dates/typedDate.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import path from "node:path";
import {
  MAX_YEAR,
  MIN_YEAR,
  addDaysISO,
  dateFieldState,
  isoFromRead,
  parseTypedDate,
  startingDay,
  stepTypedDate,
  typedDateText,
  type TypedDateContext,
} from "./typedDate.ts";
import { reportDateState } from "./useDateProblems.ts";

/** FY 2026-27, a document dated in July, "today" in October. */
const JULY: TypedDateContext = { financialYear: "2026-27", anchor: "2026-07", today: "2026-10-02" };

/** What a string must read as: an ISO date, or an error. */
function read(text: string, ctx: TypedDateContext = JULY): string {
  const r = parseTypedDate(text, ctx);
  if (r.kind === "date") return r.iso;
  if (r.kind === "empty") return "empty";
  return `error:${r.problem}`;
}

// ── The acceptance cases, as the brief states them ─────────────────────────

test("a bare day lands in the anchor's month, in the financial year's own year", () => {
  assert.equal(read("15"), "2026-07-15");
  assert.equal(read("1"), "2026-07-01");
  assert.equal(read("31"), "2026-07-31");
});

test("a day and month take the financial year: April-December its first calendar year, January-March its second", () => {
  assert.equal(read("15/7"), "2026-07-15");
  assert.equal(read("15/1"), "2027-01-15", "15/1 in FY 2026-27 is January 2027");
  assert.equal(read("15/3"), "2027-03-15");
  assert.equal(read("15/4"), "2026-04-15");
  assert.equal(read("15/12"), "2026-12-15");
  // and in the next year the same keystrokes mean the next calendar years
  const next = { ...JULY, financialYear: "2027-28", anchor: "2027-07" };
  assert.equal(read("15/1", next), "2028-01-15");
  assert.equal(read("15/7", next), "2027-07-15");
});

test("every month of a financial year resolves to the calendar year it falls in", () => {
  const years: Record<number, number> = { 4: 2026, 5: 2026, 6: 2026, 7: 2026, 8: 2026, 9: 2026, 10: 2026, 11: 2026, 12: 2026, 1: 2027, 2: 2027, 3: 2027 };
  for (const [m, y] of Object.entries(years)) {
    assert.equal(read(`1/${m}`), `${y}-${m.padStart(2, "0")}-01`, `month ${m}`);
  }
});

test("31/02/2026 is an error and NEVER another date", () => {
  assert.equal(read("31/02/2026"), "error:no_such_day");
  const r = parseTypedDate("31/02/2026", JULY);
  assert.equal(r.kind, "error");
  assert.ok(!("iso" in r), "an error carries no date to be mistaken for one");
  assert.match((r as { message: string }).message, /Feb 2026 has only 28 days/);
  // the rollover that a Date constructor would have chosen
  assert.notEqual(read("31/02/2026"), "2026-03-03");
});

test("29/02 is a date only in a leap year, and without a year it is judged in the financial year's own February", () => {
  assert.equal(read("29/02/2028"), "2028-02-29");
  assert.equal(read("29/02/2024"), "2024-02-29");
  assert.equal(read("29/02/2026"), "error:no_such_day");
  assert.equal(read("29/02/2100"), "error:no_such_day", "2100 is divisible by 100 and not by 400");
  assert.equal(read("29/02/2000"), "2000-02-29");
  assert.equal(read("29/02"), "error:no_such_day", "FY 2026-27's February is 2027");
  assert.equal(read("29/02", { ...JULY, financialYear: "2027-28", anchor: "2027-07" }), "2028-02-29", "FY 2027-28's February is 2028");
  assert.match((parseTypedDate("29/02/2026", JULY) as { message: string }).message, /not a leap year/);
});

test("ddmmyy resolves to 20yy and the result carries the full date to show at once", () => {
  const r = parseTypedDate("150326", JULY);
  assert.equal(r.kind, "date");
  if (r.kind === "date") {
    assert.equal(r.iso, "2026-03-15");
    assert.equal(r.display, "15/03/2026", "the box shows what was understood, in full");
  }
  assert.equal(read("15/03/26"), "2026-03-15");
  assert.equal(read("15/03/99"), "2099-03-15", "two digits are always 20yy, never 19yy");
  assert.equal(read("15/03/00"), "2000-03-15");
});

test("anything that is not a date is an error, never a guess", () => {
  for (const text of ["abc", "15/", "/3", "15//3", "15/3/", "--", "1/2/3/4", "15 03", "1e3", "15-03-2026x", "3rd", "15/03/2026 10:00",
    "２０２６０３１５", "१५/०३/२०२६"]) {
    assert.equal(parseTypedDate(text, JULY).kind, "error", JSON.stringify(text));
  }
});

test("a one-, three- or five-digit year is refused with its own sentence", () => {
  for (const text of ["15/03/6", "15/03/026", "15/03/20266"]) {
    assert.equal(read(text), text === "15/03/20266" ? "error:unreadable" : "error:year_digits", text);
  }
});

test("an odd count of digits is ambiguous and refused", () => {
  for (const text of ["153", "15032", "1503202"]) assert.equal(read(text), "error:unreadable", text);
  assert.equal(read("1503"), "2027-03-15", "four digits are ddmm");
  assert.equal(read("15032026"), "2026-03-15");
  assert.equal(read("20260315"), "error:no_such_month", "yyyymmdd is not guessed: it is ddmmyyyy with month 26");
});

test("month 13, day 0 and day 32 each get their own sentence", () => {
  assert.equal(read("15/13"), "error:no_such_month");
  assert.equal(read("15/0"), "error:no_such_month");
  assert.equal(read("0"), "error:no_such_day");
  assert.equal(read("32"), "error:no_such_day");
  assert.equal(read("0/7"), "error:no_such_day");
  assert.equal(read("45/7/2026"), "error:no_such_day");
  assert.equal(read("31/04/2026"), "error:no_such_day", "April has 30 days");
  assert.equal(read("30/04/2026"), "2026-04-30");
  assert.equal(read("15/03/1899"), "error:bad_year");
  assert.equal(read("15/03/3000"), "error:bad_year");
  assert.equal(read(`15/03/${MIN_YEAR}`), "1900-03-15");
  assert.equal(read(`15/03/${MAX_YEAR}`), "2999-03-15");
});

// ── Every accepted format, one date ────────────────────────────────────────

test("every accepted spelling of one date reads as that date", () => {
  for (const text of [
    "15/03/2026", "15-03-2026", "15.03.2026", "15032026", "150326", "15/03/26", "15-03-26", "15.03.26",
    "15/3/2026", "15/3/26", "2026-03-15", "2026/03/15", "2026.03.15", "2026-3-15",
    "  15/03/2026  ", "15 / 03 / 2026", "15 - 03 - 2026", "15 .03. 2026",
  ]) {
    assert.equal(read(text), "2026-03-15", JSON.stringify(text));
  }
  for (const text of ["5/3/2026", "05/03/2026", "05032026", "5.3.26", "050326", "05-03-26"]) {
    assert.equal(read(text), "2026-03-05", JSON.stringify(text));
  }
});

test("one separator throughout, or it is not a date", () => {
  for (const text of ["15/03-2026", "15-03/2026", "15.03/2026", "15/03.26", "2026-03/15"]) {
    assert.equal(read(text), "error:unreadable", text);
  }
});

test("a year and month alone is not a date", () => {
  assert.equal(read("2026-03"), "error:unreadable");
  assert.equal(read("03/2026"), "error:unreadable");
});

// ── Empty ──────────────────────────────────────────────────────────────────

test("blank text is empty, which an optional date may be, and is not an error", () => {
  for (const text of ["", " ", "   ", "\t", "\n"]) assert.equal(read(text), "empty", JSON.stringify(text));
  assert.equal(parseTypedDate(null).kind, "empty");
  assert.equal(parseTypedDate(undefined).kind, "empty");
});

// ── The anchor and the financial year ──────────────────────────────────────

test("the anchor is a day, a month, or today in India", () => {
  assert.equal(read("20", { financialYear: "2026-27", anchor: "2026-11-05" }), "2026-11-20");
  assert.equal(read("20", { financialYear: "2026-27", anchor: "2026-11" }), "2026-11-20");
  assert.equal(read("20", { financialYear: "2026-27", today: "2027-02-10" }), "2027-02-20", "no anchor: today");
  assert.equal(read("20", { today: "2027-02-10" }), "2027-02-20", "no FY either: today's own financial year");
});

test("with no financial year the anchor's own is used, so a January anchor stays in the year it is in", () => {
  assert.equal(read("15/1", { anchor: "2027-01-10" }), "2027-01-15");
  assert.equal(read("15/7", { anchor: "2027-01-10" }), "2026-07-15", "FY 2026-27 began in the previous calendar year");
  assert.equal(read("15/4", { anchor: "2027-04-10" }), "2027-04-15", "April 2027 starts FY 2027-28");
});

test("an anchor outside the financial year is clamped to its nearest end", () => {
  const fy = { financialYear: "2024-25" };
  assert.equal(read("15", { ...fy, anchor: "2026-10-02" }), "2025-03-15", "after the FY: its last month, March");
  assert.equal(read("15", { ...fy, anchor: "2023-01-01" }), "2024-04-15", "before the FY: its first month, April");
  assert.equal(read("15", { ...fy, anchor: "2024-09-09" }), "2024-09-15", "inside: untouched");
  assert.equal(read("15", { ...fy, today: "2026-10-02" }), "2025-03-15", "today clamps the same way");
});

test("an anchor on the boundary of a financial year is inside it", () => {
  assert.equal(read("15", { financialYear: "2026-27", anchor: "2026-04-01" }), "2026-04-15");
  assert.equal(read("15", { financialYear: "2026-27", anchor: "2027-03-31" }), "2027-03-15");
  assert.equal(read("15", { financialYear: "2026-27", anchor: "2027-04-01" }), "2027-03-15", "one day after: clamped");
  assert.equal(read("15", { financialYear: "2026-27", anchor: "2026-03-31" }), "2026-04-15", "one day before: clamped");
});

test("a financial year label that is not one is ignored, not trusted", () => {
  // 2026-28 passes a shape regex and then means 2026-27 in the loose parsers
  // (models/fy.py's reason): here it is not a year, and the anchor decides.
  assert.equal(read("15/1", { financialYear: "2026-28", anchor: "2027-07-01" }), "2028-01-15");
  for (const bad of ["", "2026", "26-27", "2026-2027", "abcd-ef", "2026-27x"]) {
    assert.equal(read("15/1", { financialYear: bad, anchor: "2026-07-01" }), "2027-01-15", `label ${JSON.stringify(bad)}`);
  }
});

test("an unreadable anchor falls back to today instead of failing", () => {
  for (const anchor of ["", "garbage", "2026-13", "2026-02-31", null, undefined]) {
    assert.equal(read("15", { financialYear: "2026-27", anchor, today: "2026-09-09" }), "2026-09-15", String(anchor));
  }
});

// ── The calendar, exhaustively ─────────────────────────────────────────────

test("for every day of every month of five years: valid exactly when the day exists, and then exactly that day", () => {
  const isLeap = (y: number) => (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0;
  const length = (y: number, m: number) => [31, isLeap(y) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1];
  let checked = 0;
  for (const y of [2024, 2025, 2026, 2027, 2028, 2100]) {
    for (let m = 1; m <= 12; m++) {
      for (let d = 1; d <= 33; d++) {
        const r = parseTypedDate(`${d}/${m}/${y}`, JULY);
        checked++;
        if (d <= length(y, m)) {
          assert.equal(r.kind, "date", `${d}/${m}/${y}`);
          if (r.kind === "date") {
            assert.equal(r.iso, `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`);
          }
        } else {
          assert.equal(r.kind, "error", `${d}/${m}/${y} must be refused, not rolled over`);
        }
      }
    }
  }
  assert.ok(checked > 2000);
});

test("a leap day with no year follows the financial year's own February, in every year the table tries", () => {
  for (const [fy, start] of [["2023-24", 2023], ["2024-25", 2024], ["2027-28", 2027]] as const) {
    const ctx = { financialYear: fy, anchor: `${start}-07` };
    const feb29 = parseTypedDate("29/02", ctx);
    const leap = (start + 1) % 4 === 0;
    assert.equal(feb29.kind, leap ? "date" : "error", `29/02 in FY ${fy}`);
  }
});

// ── Range hints ────────────────────────────────────────────────────────────

test("min and max are a hint: the date is still returned, and says it is outside", () => {
  const ctx = { ...JULY, min: "2026-04-01", max: "2027-03-31" };
  const before = parseTypedDate("31/03/2026", ctx);
  assert.equal(before.kind, "date");
  if (before.kind === "date") {
    assert.equal(before.iso, "2026-03-31", "still the date — the server decides");
    assert.equal(before.outOfRange, "min");
    assert.equal(before.message, "31 Mar 2026 is before 01 Apr 2026.");
  }
  const after = parseTypedDate("01/04/2027", ctx);
  assert.equal(after.kind === "date" && after.outOfRange, "max");
  const inside = parseTypedDate("01/04/2026", ctx);
  assert.equal(inside.kind === "date" && inside.outOfRange, null);
  assert.equal(inside.kind === "date" && inside.message, null);
  const edge = parseTypedDate("31/03/2027", ctx);
  assert.equal(edge.kind === "date" && edge.outOfRange, null, "the bounds themselves are inside");
});

test("a bound that is not a date is ignored", () => {
  const r = parseTypedDate("15/07/2026", { ...JULY, min: "not a date", max: "2026-02-31" });
  assert.equal(r.kind === "date" && r.outOfRange, null);
});

// ── The pieces the field is built from ─────────────────────────────────────

test("typedDateText writes a bare date as dd/mm/yyyy and anything else as nothing", () => {
  assert.equal(typedDateText("2026-03-05"), "05/03/2026");
  assert.equal(typedDateText("2024-02-29"), "29/02/2024");
  assert.equal(typedDateText(""), "");
  assert.equal(typedDateText(null), "");
  assert.equal(typedDateText("2026-02-31"), "");
  assert.equal(typedDateText("2026-03-05T00:00:00"), "", "an instant is not a calendar day");
  assert.equal(typedDateText("05/03/2026"), "");
});

test("what typedDateText writes reads back as the same date", () => {
  for (const iso of ["2026-03-05", "2024-02-29", "1900-01-01", "2999-12-31", "2027-01-31"]) {
    assert.equal(read(typedDateText(iso)), iso);
  }
});

test("addDaysISO crosses month ends, year ends and leap days in the UTC frame", () => {
  assert.equal(addDaysISO("2026-03-31", 1), "2026-04-01");
  assert.equal(addDaysISO("2026-04-01", -1), "2026-03-31");
  assert.equal(addDaysISO("2026-12-31", 1), "2027-01-01");
  assert.equal(addDaysISO("2027-01-01", -1), "2026-12-31");
  assert.equal(addDaysISO("2028-02-28", 1), "2028-02-29");
  assert.equal(addDaysISO("2028-02-29", 1), "2028-03-01");
  assert.equal(addDaysISO("2026-02-28", 1), "2026-03-01");
  assert.equal(addDaysISO("2026-03-15", 0), "2026-03-15");
  assert.equal(addDaysISO("2026-03-15", 365), "2027-03-15");
  assert.equal(addDaysISO("1900-01-01", -1), null, "off the bottom of the span");
  assert.equal(addDaysISO("2999-12-31", 1), null, "off the top of it");
  assert.equal(addDaysISO("", 1), null);
  assert.equal(addDaysISO("2026-02-31", 1), null);
  assert.equal(addDaysISO("2026-03-15", 1.5), null);
});

test("ArrowUp/ArrowDown move a readable date, and start an empty or unreadable box at the anchor", () => {
  assert.equal(stepTypedDate("15/07/2026", 1, JULY), "2026-07-16");
  assert.equal(stepTypedDate("15/07/2026", -1, JULY), "2026-07-14");
  assert.equal(stepTypedDate("01/08/2026", -1, JULY), "2026-07-31");
  assert.equal(stepTypedDate("15", 1, JULY), "2026-07-16", "a bare day is read first, then moved");
  assert.equal(stepTypedDate("", 1, JULY), "2026-07-01", "empty: the anchor's day, whichever arrow");
  assert.equal(stepTypedDate("", -1, JULY), "2026-07-01");
  assert.equal(stepTypedDate("31/02/2026", 1, JULY), "2026-07-01", "unreadable text is not moved from");
  assert.equal(stepTypedDate("01/01/1900", -1, JULY), null);
  assert.equal(startingDay({ financialYear: "2026-27", anchor: "2026-11-05" }), "2026-11-05");
  assert.equal(startingDay({ financialYear: "2024-25", today: "2026-10-02" }), "2025-03-31", "clamped into the year");
});

test("the state a field reports tells empty, valid and invalid apart", () => {
  const empty = parseTypedDate("", JULY);
  assert.deepEqual(dateFieldState("", empty), { status: "empty", text: "", message: null, outOfRange: null });
  assert.equal(isoFromRead(empty), "");

  const ok = parseTypedDate("15/7", JULY);
  assert.deepEqual(dateFieldState("15/7", ok), { status: "valid", text: "15/7", message: null, outOfRange: null });
  assert.equal(isoFromRead(ok), "2026-07-15");

  const bad = parseTypedDate("31/02/2026", JULY);
  const state = dateFieldState("31/02/2026", bad);
  assert.equal(state.status, "invalid");
  assert.match(state.message ?? "", /28 days/);
  // The two things "" can mean are told apart by status, and BOTH hand up "".
  assert.equal(isoFromRead(bad), "", "an invalid field must not hand up a stale or guessed date");
  assert.notEqual(state.status, dateFieldState("", empty).status);

  const outside = parseTypedDate("31/03/2026", { ...JULY, min: "2026-04-01" });
  const o = dateFieldState("31/03/2026", outside);
  assert.equal(o.status, "valid", "outside a hint is still a date");
  assert.equal(o.outOfRange, "min");
});

test("a form's problems map holds one sentence per unreadable date and drops it when the field is fine again", () => {
  const bad = dateFieldState("31/02/2026", parseTypedDate("31/02/2026", JULY));
  const good = dateFieldState("15/07/2026", parseTypedDate("15/07/2026", JULY));
  const blank = dateFieldState("", parseTypedDate("", JULY));
  let p: Record<string, string> = {};
  p = reportDateState(p, "billDate", "Bill date", bad);
  assert.deepEqual(Object.keys(p), ["billDate"]);
  assert.match(p.billDate, /^Bill date: Feb 2026 has only 28 days\./);
  p = reportDateState(p, "dueDate", "Due date", bad);
  assert.equal(Object.keys(p).length, 2);
  const same = reportDateState(p, "dueDate", "Due date", bad);
  assert.equal(same, p, "an unchanged report returns the same object, so nothing re-renders");
  p = reportDateState(p, "billDate", "Bill date", good);
  assert.deepEqual(Object.keys(p), ["dueDate"]);
  p = reportDateState(p, "dueDate", "Due date", blank);
  assert.deepEqual(p, {}, "blank is not a problem: an optional date may be empty");
  // out of range is a hint and never blocks
  const hint = dateFieldState("31/03/2026", parseTypedDate("31/03/2026", { ...JULY, min: "2026-04-01" }));
  assert.deepEqual(reportDateState({}, "x", "X", hint), {});
});

// ── No zone can move a date, and no string goes through Date ───────────────

test("the typed text never goes through the Date parser", () => {
  const src = readFileSync(path.join(import.meta.dirname, "typedDate.ts"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  const constructions = [...src.matchAll(/new Date\(([^)]*)/g)].map((m) => m[1].trim());
  assert.ok(constructions.length > 0, "the scan found nothing to judge");
  for (const arg of constructions) {
    assert.match(arg, /^Date\.UTC\(/, `new Date(${arg}…) reads a string or a local midnight; only Date.UTC(...) is allowed`);
  }
  assert.doesNotMatch(src, /Date\.parse\(|\.toLocale|Intl\./, "no locale or parser API");
});

test("the same table reads the same under every timezone, because a calendar day has no zone", () => {
  const here = pathToFileURL(path.join(import.meta.dirname, "typedDate.ts")).href;
  const script =
    `import { parseTypedDate, addDaysISO, stepTypedDate } from ${JSON.stringify(here)};` +
    `const ctx = { financialYear: "2026-27", anchor: "2026-07", today: "2026-10-02" };` +
    `const iso = (t) => { const r = parseTypedDate(t, ctx); return r.kind === "date" ? r.iso : r.kind; };` +
    `process.stdout.write(JSON.stringify([` +
    `iso("15"), iso("15/7"), iso("15/1"), iso("31/02/2026"), iso("29/02"), iso("29/02/2028"), iso("150326"),` +
    `iso("31/03/2027"), iso("01/04/2026"), addDaysISO("2026-03-31", 1), addDaysISO("2026-04-01", -1),` +
    `stepTypedDate("31/03/2026", 1, ctx), stepTypedDate("", 1, ctx)]))`;
  const expected = [
    "2026-07-15", "2026-07-15", "2027-01-15", "error", "error", "2028-02-29", "2026-03-15",
    "2027-03-31", "2026-04-01", "2026-04-01", "2026-03-31", "2026-04-01", "2026-07-01",
  ];
  for (const tz of ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Pacific/Honolulu", "Pacific/Kiritimati", "Europe/London", "Australia/Lord_Howe"]) {
    const out = execFileSync(
      process.execPath,
      ["--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
      { env: { ...process.env, TZ: tz }, encoding: "utf8" },
    );
    assert.deepEqual(JSON.parse(out), expected, `TZ=${tz} moved a date`);
  }
});
