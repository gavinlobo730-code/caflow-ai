/**
 * A workbook sheet turned into the CSV text the import pipeline reads, with the
 * cells Excel holds as DATES written as ISO dates (PRE-A-001, 08-10-2026).
 *
 * ── THE DEFECT ──────────────────────────────────────────────────────────────
 * `CsvImportModal` read a workbook with `XLSX.read` and turned the first sheet
 * into text with `sheet_to_csv`. A date cell in Excel is a NUMBER (a serial day)
 * with a number format, and `sheet_to_csv` prints the cell's DISPLAY text:
 *
 *     Excel's default short date (built-in format 14)  ->  3/15/25
 *     d-mmm-yy                                         ->  12-Mar-25
 *
 * — month-first, and with a two-digit year, whatever the CA's sheet shows. The
 * server refuses both ("a two-digit year is not read, because 4/1/26 could be 4
 * January or 1 April") and so does every browser importer in `lib/imports/mappers`
 * (they require yyyy-mm-dd). So a real Excel workbook, with dates exactly as
 * Excel writes them, was refused row by row on all five migration-day doors,
 * while the same dates saved as CSV from the same sheet were accepted. Driven in
 * a browser on 08-10-2026, with a workbook openpyxl wrote in Excel's own formats.
 *
 * ── THE RULE ────────────────────────────────────────────────────────────────
 * **A cell Excel itself holds as a date is read as the date it holds**, from the
 * stored serial number and never from its display text. The serial is the one
 * thing that does not depend on the format, the locale of the machine that wrote
 * the file or the one that reads it, and it is written out as `yyyy-mm-dd`,
 * which every importer in this product reads the same way.
 *
 * **Nothing else is touched.** A cell is converted only when ALL of these hold:
 *   - it is a number (a date TYPED as text, `15/03/2025`, stays text and is read
 *     by the server's own day-first rule);
 *   - its number format is one SheetJS recognises as a date or time;
 *   - that format shows a DAY OF THE MONTH and a YEAR. A time of day (`h:mm`), an
 *     elapsed time (`[h]:mm`), a weekday alone (`ddd`), a month name (`mmm`) and a
 *     month with a year (`mmm-yy`) do not name a date: converting the last would
 *     write the 1st of a month the CA never typed, and "nothing is guessed" is
 *     this module's whole reason to exist. Those cells keep the text Excel shows,
 *     and the server refuses it with a sentence;
 *   - the value is at least 1 (serial 0 is no date in either calendar).
 * A percentage, a currency, a General number and every text cell are printed
 * exactly as `sheet_to_csv` prints them, which a test asserts byte for byte.
 *
 * **The date is the calendar date and the time of day is dropped**: a document
 * date is a day, and a cell showing `15-03-2025 18:30` holds 15 March.
 *
 * **THE 1904 DATE SYSTEM IS READ OFF THE WORKBOOK.** Excel for Mac once defaulted
 * to a calendar whose day 0 is 1 January 1904, and the workbook says so in its
 * properties; the same serial is a different date in the two systems (1,462 days
 * apart), so a reader that ignored the flag would date every row four years late.
 *
 * ── HOW IT IS CALLED ────────────────────────────────────────────────────────
 * The sheet must have been read with `cellNF: true`, or no cell carries its
 * number format and this function converts nothing (a test pins the modal's call).
 * The library is taken as a PARAMETER, the way `lib/export/xlsx.ts` does, so this
 * file imports only TYPES and `xlsx` stays out of the first load of the ten
 * screens that import the modal (scripts/the-spreadsheet-library-is-not-in-the-
 * first-load.test.ts). No locale date API is used: `Date` objects carry the
 * machine's zone, and a serial number has none.
 *
 * The sheet is MUTATED (each converted cell's display text, `w`, is replaced): it
 * is the in-memory copy the caller has just read and is about to discard.
 */
import type { WorkBook, WorkSheet } from "xlsx";

/**
 * Does this number format SHOW a day of the month and a year?
 *
 * Quoted text (`"Due on" d`), escaped characters, `[...]` sections (colours,
 * conditions, the locale `[$-409]`, and the elapsed-time `[h]` `[mm]` `[ss]`),
 * padding and fill characters and the 12-hour marker (`AM/PM` has an M in it)
 * are removed first; only the first section is read, because it is the one a
 * positive number is shown with.
 */
export function isCalendarDateFormat(format: string): boolean {
  const first = format
    .replace(/"[^"]*"/g, "")
    .replace(/\\./g, "")
    .replace(/\[[^\]]*\]/g, "")
    .replace(/[_*]./g, "")
    .replace(/AM\/PM|A\/P/gi, "")
    .split(";")[0];
  // `d` or `dd` is the day of the month; `ddd` and `dddd` are the weekday name.
  const dayOfMonth = (first.match(/d+/gi) ?? []).some((run) => run.length <= 2);
  const year = /y/i.test(first);
  return dayOfMonth && year;
}

/** `yyyy-mm-dd` for a stored day number, or null where it is no calendar date. */
function isoFromSerial(X: typeof import("xlsx"), serial: number, date1904: boolean): string | null {
  const parts = X.SSF.parse_date_code(serial, { date1904 }) as
    { y: number; m: number; d: number } | null;
  if (!parts || !Number.isInteger(parts.y) || parts.y < 1 || parts.y > 9999) return null;
  const pad = (n: number, width: number) => String(n).padStart(width, "0");
  return `${pad(parts.y, 4)}-${pad(parts.m, 2)}-${pad(parts.d, 2)}`;
}

/**
 * The first sheet's CSV text, with each date cell written as yyyy-mm-dd.
 *
 * `X` is the `xlsx` namespace object (`await import("xlsx")`, never `.default`);
 * `wb` and `ws` are what `X.read(data, { type: "array", cellNF: true })` returned.
 */
export function sheetToCsvWithIsoDates(
  X: typeof import("xlsx"),
  wb: WorkBook,
  ws: WorkSheet,
): string {
  const date1904 = Boolean(wb.Workbook?.WBProps?.date1904);
  for (const address of Object.keys(ws)) {
    if (address.startsWith("!")) continue;         // !ref, !cols, !merges: sheet properties
    const cell = ws[address];
    if (!cell || cell.t !== "n" || typeof cell.v !== "number" || !Number.isFinite(cell.v)) continue;
    if (cell.v < 1 || typeof cell.z !== "string" || !X.SSF.is_date(cell.z)) continue;
    if (!isCalendarDateFormat(cell.z)) continue;
    const iso = isoFromSerial(X, cell.v, date1904);
    if (iso !== null) cell.w = iso;
  }
  return X.utils.sheet_to_csv(ws);
}
