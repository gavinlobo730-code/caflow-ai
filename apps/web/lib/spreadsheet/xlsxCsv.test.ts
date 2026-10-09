/**
 * An Excel date cell is read as the date it holds (PRE-A-001). Run with:
 *   node --experimental-strip-types --test lib/spreadsheet/xlsxCsv.test.ts
 *
 * The workbooks here are REAL ones: cells are built, written to the .xlsx format
 * and read back through `read(..., { cellNF: true })` exactly as the import
 * modal reads a chosen file, so the number formats are the ones SheetJS takes off
 * the file and not ones this test invented for itself.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import path from "node:path";
import { isCalendarDateFormat, sheetToCsvWithIsoDates } from "./xlsxCsv.ts";

// Node resolves xlsx's CommonJS entry, whose namespace holds the library as
// `default`; the browser bundle resolves xlsx.mjs, whose namespace IS the
// library. Either way it is `typeof import("xlsx")`, which is all the helper asks.
const loaded = await import("xlsx");
const X: typeof import("xlsx") =
  (loaded as unknown as { default?: typeof import("xlsx") }).default ?? loaded;

// 15 March 2025 is serial 45731 in the 1900 date system and 44269 in the 1904 one.
const DAY_1900 = 45731;
const DAY_1904 = 44269;

type Spec = { v: number | string; z?: string };

/** One column of cells, written to xlsx bytes and read back. */
function workbookBytes(cells: Spec[], date1904 = false): Uint8Array {
  const ws: Record<string, unknown> = {
    "!ref": `A1:A${cells.length}`,
  };
  cells.forEach((c, i) => {
    ws[`A${i + 1}`] = typeof c.v === "number"
      ? { t: "n", v: c.v, ...(c.z ? { z: c.z } : {}) }
      : { t: "s", v: c.v };
  });
  const wb = {
    SheetNames: ["Sheet1"],
    Sheets: { Sheet1: ws },
    Workbook: { WBProps: { date1904 } },
  };
  return new Uint8Array(X.write(wb, { type: "array", bookType: "xlsx" }));
}

/** What the modal does: read with cellNF, then turn the first sheet into text. */
function csvOf(bytes: Uint8Array): string[] {
  const wb = X.read(bytes, { type: "array", cellNF: true });
  const ws = wb.Sheets[wb.SheetNames[0]];
  return sheetToCsvWithIsoDates(X, wb, ws).split("\n");
}

/** What the modal used to do, on the same bytes. */
function plainCsvOf(bytes: Uint8Array): string[] {
  const wb = X.read(bytes, { type: "array" });
  return X.utils.sheet_to_csv(wb.Sheets[wb.SheetNames[0]]).split("\n");
}

// ── the premise: the old output is what the server refuses ───────────────────

test("premise: sheet_to_csv prints Excel's own default short date month-first with a two-digit year", () => {
  // Built-in format 14 is what Excel writes for the regional short date; SheetJS
  // names it m/d/yy and prints it that way, whatever the CA's sheet displays.
  const [a, b] = plainCsvOf(workbookBytes([
    { v: DAY_1900, z: "m/d/yy" },
    { v: DAY_1900, z: "d-mmm-yy" },
  ]));
  assert.equal(a, "3/15/25");
  assert.equal(b, "15-Mar-25");
});

// ── the rule ─────────────────────────────────────────────────────────────────

test("a date cell is written as yyyy-mm-dd whatever its number format shows", () => {
  const out = csvOf(workbookBytes([
    { v: DAY_1900, z: "m/d/yy" },                  // built-in 14: 3/15/25
    { v: DAY_1900, z: "d-mmm-yy" },                // 15-Mar-25
    { v: DAY_1900, z: "dd-mm-yyyy" },              // 15-03-2025
    { v: DAY_1900, z: "dd/mm/yyyy" },
    { v: DAY_1900, z: "yyyy-mm-dd" },
    { v: DAY_1900, z: "[$-F800]dddd, mmmm dd, yyyy" }, // Excel's "Long Date"
    { v: DAY_1900, z: '"Due" dd/mm/yyyy' },        // quoted text beside a date
  ]));
  assert.deepEqual(out, Array(7).fill("2025-03-15"));
});

test("the time of day is dropped: a date-time cell holds a calendar day", () => {
  assert.deepEqual(csvOf(workbookBytes([
    { v: DAY_1900 + 0.75, z: "dd-mm-yyyy hh:mm" },
    { v: DAY_1900 + 0.999, z: "dd-mm-yyyy hh:mm:ss" },
  ])), ["2025-03-15", "2025-03-15"]);
});

test("the 1904 date system is read off the workbook, not assumed", () => {
  // The same wording in two workbooks: serial 44269 is 15 March 2025 in the 1904
  // system and 14 March 2021 in the 1900 one.
  assert.deepEqual(csvOf(workbookBytes([{ v: DAY_1904, z: "m/d/yy" }], true)), ["2025-03-15"]);
  assert.deepEqual(csvOf(workbookBytes([{ v: DAY_1904, z: "m/d/yy" }], false)), ["2021-03-14"]);
});

test("a month-end and a leap day are the days they are", () => {
  // 29 February 2024 is serial 45351; 31 December 2025 is 46022.
  assert.deepEqual(csvOf(workbookBytes([
    { v: 45351, z: "d/m/yyyy" },
    { v: 46022, z: "d/m/yyyy" },
    { v: 45658, z: "d/m/yyyy" },
  ])), ["2024-02-29", "2025-12-31", "2025-01-01"]);
});

// ── nothing else is touched ──────────────────────────────────────────────────

const NOT_DATES: Spec[] = [
  { v: 0.5, z: "h:mm" },                        // a time of day
  { v: 36.5, z: "[h]:mm" },                     // an elapsed time of 36 h 30 min: value >= 1, still no date
  { v: 0.181, z: "0.0%" },                      // a percentage
  { v: 1234.5, z: '"Rs." #,##0.00' },           // a currency, with a quoted word
  { v: 100000, z: "##\\,##\\,##0.00" },         // Indian grouping
  { v: DAY_1900 },                              // a General number that is the right size for a date
  { v: DAY_1900, z: "General" },
  { v: "15/03/2025" },                          // a date typed as text
  { v: "INV/001" },
  { v: DAY_1900, z: "mmm-yy" },                 // shows no day: converting would write a 1st nobody typed
  { v: DAY_1900, z: "mmmm yyyy" },
  { v: DAY_1900, z: "d-mmm" },                  // shows no year
  { v: DAY_1900, z: "dddd" },                   // a weekday name
  { v: 0, z: "dd-mm-yyyy" },                    // serial 0 is no date
];

test("every cell that is not a date prints byte for byte as sheet_to_csv prints it", () => {
  const bytes = workbookBytes(NOT_DATES);
  assert.deepEqual(csvOf(bytes), plainCsvOf(bytes));
});

test("a mixed column converts the dates and leaves the neighbours alone", () => {
  const mixed: Spec[] = [
    { v: DAY_1900, z: "m/d/yy" }, ...NOT_DATES.slice(0, 3), { v: DAY_1900, z: "d-mmm-yy" }, { v: "x" },
  ];
  const bytes = workbookBytes(mixed);
  const plain = plainCsvOf(bytes);
  const out = csvOf(bytes);
  assert.equal(out.length, plain.length);
  mixed.forEach((cell, i) => {
    const isDate = typeof cell.v === "number" && cell.v >= 1 && cell.z && isCalendarDateFormat(cell.z);
    if (isDate) assert.equal(out[i], "2025-03-15");
    else assert.equal(out[i], plain[i], `row ${i + 1} changed`);
  });
});

test("a sheet read without cellNF converts nothing, which is why the modal asks for it", () => {
  const bytes = workbookBytes([{ v: DAY_1900, z: "m/d/yy" }]);
  const wb = X.read(bytes, { type: "array" });                 // no cellNF
  const ws = wb.Sheets[wb.SheetNames[0]];
  assert.equal(sheetToCsvWithIsoDates(X, wb, ws), "3/15/25");
});

test("a date cell sitting beside text in a header-and-rows sheet keeps the sheet's shape", () => {
  const ws = X.utils.aoa_to_sheet([["document_no", "document_date", "outstanding"], ["INV/1", "x", 100]]);
  ws["B2"] = { t: "n", v: DAY_1900, z: "m/d/yy" };
  const wb = { SheetNames: ["S"], Sheets: { S: ws } };
  const bytes = new Uint8Array(X.write(wb, { type: "array", bookType: "xlsx" }));
  assert.deepEqual(csvOf(bytes), [
    "document_no,document_date,outstanding",
    "INV/1,2025-03-15,100",
  ]);
});

// ── which formats show a date ────────────────────────────────────────────────

test("isCalendarDateFormat: a day of the month and a year, and nothing less", () => {
  for (const f of [
    "m/d/yy", "d-mmm-yy", "dd-mm-yyyy", "yyyy-mm-dd", "dd/mm/yyyy hh:mm",
    "d/m/yy h:mm AM/PM", "[$-F800]dddd, mmmm dd, yyyy", '"Due" dd/mm/yyyy',
    "[>=45000]dd-mm-yyyy;dd/mm/yy", "dddd, mmmm d, yyyy",
  ]) assert.equal(isCalendarDateFormat(f), true, f);
  for (const f of [
    "h:mm", "[h]:mm", "[mm]:ss", "h:mm:ss AM/PM", "mmm-yy", "mmmm yyyy", "d-mmm",
    "ddd", "dddd", "dddd mmm", "mmm", '"day year" h:mm', "\\d\\y h:mm", "General", "0.0%",
  ]) assert.equal(isCalendarDateFormat(f), false, f);
});

// ── no time zone moves a date ────────────────────────────────────────────────

test("the same workbook reads as the same dates in every time zone", () => {
  // A serial number has no zone; a `Date` object does. Each zone is a separate
  // process because TZ is read once, when the engine starts (lib/dates/format.test.ts).
  const here = pathToFileURL(path.join(import.meta.dirname, "xlsxCsv.ts")).href;
  const bytes = Array.from(workbookBytes([
    { v: DAY_1900, z: "m/d/yy" }, { v: 45351, z: "d-mmm-yy" }, { v: 45658, z: "dd/mm/yyyy" },
    { v: 0.5, z: "h:mm" }, { v: "15/03/2025" },
  ]));
  const script =
    `import { sheetToCsvWithIsoDates } from ${JSON.stringify(here)};` +
    `const loaded = await import("xlsx");` +
    `const X = loaded.default ?? loaded;` +
    `const wb = X.read(new Uint8Array(${JSON.stringify(bytes)}), { type: "array", cellNF: true });` +
    `process.stdout.write(JSON.stringify(sheetToCsvWithIsoDates(X, wb, wb.Sheets[wb.SheetNames[0]])));`;
  const expected = ["2025-03-15", "2024-02-29", "2025-01-01", "12:00", "15/03/2025"].join("\n");
  for (const tz of ["UTC", "Asia/Kolkata", "America/Los_Angeles", "Pacific/Honolulu", "Pacific/Kiritimati", "Europe/London"]) {
    const out = execFileSync(
      process.execPath,
      ["--experimental-strip-types", "--no-warnings", "--input-type=module", "-e", script],
      { cwd: path.join(import.meta.dirname, "..", ".."), env: { ...process.env, TZ: tz }, encoding: "utf8" },
    );
    assert.equal(JSON.parse(out), expected, `TZ=${tz} moved a date`);
  }
});
