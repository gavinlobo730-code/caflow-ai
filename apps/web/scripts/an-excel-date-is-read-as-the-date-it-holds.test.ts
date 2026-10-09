// A WORKBOOK BECOMES TEXT IN ONE PLACE, AND THAT PLACE READS A DATE CELL AS A DATE.
//   node --experimental-strip-types --test scripts/an-excel-date-is-read-as-the-date-it-holds.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (PRE-A-001, found by driving the import modal in a browser)
// ─────────────────────────────────────────────────────────────────────────────
// `CsvImportModal` turned a chosen workbook into text with `sheet_to_csv`, which
// prints each cell's DISPLAY text. Excel stores a date as a number and shows it
// in a format, and SheetJS names Excel's own default short date `m/d/yy`, so a
// date the CA's sheet showed as 15-03-2025 reached the importers as `3/15/25` —
// month-first with a two-digit year, the one shape the server refuses by design
// ("4/1/26 could be 4 January or 1 April"). A real Excel workbook was refused row
// by row on all five migration-day doors and by every importer in
// `lib/imports/mappers`, while the same dates saved as CSV were accepted.
//
// The unit tests (`lib/spreadsheet/xlsxCsv.test.ts`) pin what the converter does.
// This file pins that nothing goes AROUND it.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE
// ─────────────────────────────────────────────────────────────────────────────
// 1. NOTHING BUT `lib/spreadsheet/xlsxCsv.ts` TURNS A SHEET INTO TEXT. Not
//    `sheet_to_csv`, and not its siblings (`sheet_to_json`, `sheet_to_txt`,
//    `sheet_to_html`, `sheet_to_formulae`), which all print the same display
//    text or the same cell values. A new importer that needs a sheet as rows
//    adds a function BESIDE the converter, where the date rule already is.
//    Test files are exempt: they compare against what the library prints.
// 2. A FILE THAT READS A WORKBOOK ASKS FOR THE NUMBER FORMATS AND USES THE
//    CONVERTER. Without `cellNF: true` no cell carries its format, so the
//    converter silently converts nothing; without the converter the first rule
//    would have nothing to be the exception to.
//
// This is the rule over `app/`, `components/` and `lib/`, not a spelling of the
// one call that was found, and the detector is tested on each spelling.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const ROOTS = ["app", "components", "lib"];
const CONVERTER = "lib/spreadsheet/xlsxCsv.ts";
const MODAL = "components/CsvImportModal.tsx";

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(join(WEB, dir))) {
    if (entry === "node_modules" || entry === ".next") continue;
    const rel = join(dir, entry).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if ((rel.endsWith(".ts") || rel.endsWith(".tsx")) && !rel.endsWith(".test.ts")) out.push(rel);
  }
  return out;
}
const FILES = ROOTS.flatMap((r) => walk(r));

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}
function code(rel: string): string {
  return stripComments(readFileSync(join(WEB, rel), "utf8"));
}

/** Every `<anything>.sheet_to_<kind>` mention in code: a call, a reference passed
 *  on, or a destructured name, because each reaches the same display text. */
const SHEET_TO_TEXT = /\bsheet_to_(?:csv|json|txt|html|formulae)\b/g;
function sheetToTextMentions(src: string): string[] {
  return [...src.matchAll(SHEET_TO_TEXT)].map((m) => m[0]);
}

/** The argument text of every `<ident>.read(` call on a workbook in `src`. */
function readCalls(src: string): string[] {
  const calls: string[] = [];
  for (const m of src.matchAll(/\b[A-Za-z_$][\w$]*\.read\(/g)) {
    let depth = 1;
    let i = m.index! + m[0].length;
    const start = i;
    while (i < src.length && depth > 0) {
      const ch = src[i];
      if (ch === "(") depth++;
      else if (ch === ")") depth--;
      i++;
    }
    calls.push(src.slice(start, i - 1));
  }
  return calls;
}

// ── the detectors have to detect, or every test below passes for ever ───────

test("the detector sees each spelling of turning a sheet into text", () => {
  for (const sample of [
    "const t = XLSX.utils.sheet_to_csv(ws);",
    "const t = X.utils.sheet_to_csv(ws, { FS: ';' });",
    "const rows = XLSX.utils.sheet_to_json(ws, { raw: false });",
    "const h = XLSX.utils.sheet_to_html(ws);",
    "const t = XLSX.utils.sheet_to_txt(ws);",
    "const { sheet_to_csv } = XLSX.utils;",
    "const f = XLSX.utils.sheet_to_csv; f(ws);",
    "XLSX.utils['sheet_to_csv'](ws);",
  ]) assert.ok(sheetToTextMentions(sample).length > 0, `missed: ${sample}`);
});

test("the detector leaves the other XLSX.utils calls alone", () => {
  for (const sample of [
    "const ws = XLSX.utils.aoa_to_sheet(rows);",
    "const ws = XLSX.utils.json_to_sheet(rows);",
    "XLSX.utils.book_append_sheet(wb, ws, 'S');",
    "const a = XLSX.utils.encode_cell({ r: 0, c: 1 });",
    "const csv = sheetToCsvWithIsoDates(XLSX, wb, ws);",
  ]) assert.deepEqual(sheetToTextMentions(sample), [], `flagged: ${sample}`);
});

test("the read-call reader returns the whole argument list, nested braces included", () => {
  const calls = readCalls(
    'const wb = XLSX.read(data, { type: "array", cellNF: true });\nconst z = foo(bar(1));',
  );
  assert.deepEqual(calls, ['data, { type: "array", cellNF: true }']);
  assert.deepEqual(readCalls("const a = f(x(1), y);"), []);
});

// ── rule 1 ───────────────────────────────────────────────────────────────────

test("nothing but the converter turns a sheet into text", () => {
  const offenders = FILES
    .filter((f) => f !== CONVERTER)
    .flatMap((f) => sheetToTextMentions(code(f)).map((m) => `${f}  (${m})`));
  assert.deepEqual(offenders, [],
    "a sheet printed with the library's own sheet_to_* functions writes an Excel " +
    "date as its display text — `3/15/25` for Excel's default short date — which " +
    "every importer refuses. Add the function beside sheetToCsvWithIsoDates in " +
    CONVERTER + ", where the date rule is:\n  " + offenders.join("\n  "));
});

test("the converter is the one place the library prints a sheet", () => {
  const src = code(CONVERTER);
  assert.ok(sheetToTextMentions(src).length > 0, "the converter no longer prints a sheet");
  // It takes the library as a parameter and imports only types, so the spreadsheet
  // reader stays out of the first load of the screens that import the modal.
  assert.match(src, /import\s+type\s+\{[^}]*\}\s+from\s*["']xlsx["']/);
  assert.doesNotMatch(src, /(?:^|\n)\s*import\s+(?!type\b)[^;]*from\s*["']xlsx["']/,
    "the converter must not import xlsx at runtime");
  assert.match(src, /export\s+function\s+sheetToCsvWithIsoDates\s*\(/);
});

// ── rule 2 ───────────────────────────────────────────────────────────────────

test("every file that reads a workbook asks for the number formats and uses the converter", () => {
  const readers = FILES.filter((f) => f !== CONVERTER
    && /import\(\s*["']xlsx["']\s*\)/.test(code(f))
    && readCalls(code(f)).some((args) => /\btype\s*:\s*["']array["']/.test(args)));
  assert.ok(readers.includes(MODAL), `the modal is no longer found reading a workbook (found: ${readers.join(", ")})`);
  for (const f of readers) {
    const src = code(f);
    const reads = readCalls(src).filter((args) => /\btype\s*:\s*["']array["']/.test(args));
    for (const args of reads) {
      assert.match(args, /\bcellNF\s*:\s*true\b/,
        `${f} reads a workbook without cellNF: true, so no date cell carries its format and the ` +
        "converter converts nothing");
    }
    assert.match(src, /\bsheetToCsvWithIsoDates\s*\(\s*XLSX\s*,/,
      `${f} reads a workbook and does not turn it into text with sheetToCsvWithIsoDates`);
    assert.match(src, /from\s*["']@\/lib\/spreadsheet\/xlsxCsv["']/);
  }
});

test("the modal hands the converter the workbook it read and the sheet it chose", () => {
  const src = code(MODAL);
  assert.match(src,
    /const\s+wb\s*=\s*XLSX\.read\([^)]*cellNF\s*:\s*true[^)]*\);[\s\S]*?const\s+text\s*=\s*sheetToCsvWithIsoDates\(\s*XLSX\s*,\s*wb\s*,\s*firstSheet\s*\)/);
});
