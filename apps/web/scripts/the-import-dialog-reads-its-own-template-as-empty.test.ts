// THE IMPORT DIALOG'S TEMPLATE READS BACK AS EMPTY, AND ITS LAST STEP COUNTS EVERY ROW.
//   node --experimental-strip-types --test scripts/the-import-dialog-reads-its-own-template-as-empty.test.ts
//
// Found by driving the dialog in a browser (PRE-A-001):
//
//   * The Excel template was a header row, a row of hints and a copy of the hints
//     as an "example". Only a line starting with `#` is skipped on upload, so
//     uploading the template exactly as downloaded reported TWO VALID ROWS.
//   * The done step reported New / Already existed / Failed for the rows that
//     were SENT. A row the preview had flagged (a blank required cell) is held
//     back in the browser, so a file of six rows reported "3 new, 2 failed" and
//     the sixth was in neither number.
//
// The behaviour is held by lib/spreadsheet/importTemplate.test.ts, which writes
// the template to .xlsx, reads it back as the dialog reads a chosen file and
// parses it. This file holds that the DIALOG USES those functions, so a copy of
// the old template cannot grow back inside the component, where a node test
// cannot see it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, " ")
  .replace(/^\s*\/\/.*$/gm, " ");

const MODAL = read("components/CsvImportModal.tsx");

test("the dialog parses with the shared reader and keeps no copy of it", () => {
  assert.match(MODAL, /import\s+\{\s*parseCsv\s*\}\s+from\s*["']@\/lib\/spreadsheet\/parseCsv["']/);
  assert.doesNotMatch(MODAL, /function\s+parseCsv(?:Line)?\s*\(/,
    "a second reader is a second idea of what a note line is");
  // Nothing in the dialog decides what a note line looks like.
  assert.doesNotMatch(MODAL, /startsWith\(\s*["']#["']\s*\)/);
});

test("both templates are built from the shared note, and there is no example row", () => {
  assert.match(MODAL, /templateNote\(columns\)/, "the CSV template's second line");
  assert.match(MODAL, /aoa_to_sheet\(templateSheetRows\(columns\)\)/, "the workbook template's sheet");
  assert.match(MODAL, /templateInstructions\(columns\)/, "the Instructions sheet");
  assert.doesNotMatch(MODAL, /\bexampleRow\b/,
    "an example row made of the hints is read as data");
  assert.doesNotMatch(MODAL, /Delete Row 2/,
    "row 2 is a skipped note, not a step the CA must perform");
});

test("the done step names the rows the preview held back", () => {
  const done = MODAL.slice(MODAL.indexOf('step === "done" && result'));
  assert.ok(done.length > 100, "the done step is no longer found");
  assert.match(done, /heldBackRows\(rows\)/);
  assert.match(done, /heldBackHeading\(held\.count\)/);
  // It reads the rows the PREVIEW parsed, which is where the flagged ones are.
  assert.match(MODAL, /const\s+\[rows,\s*setRows\]\s*=\s*useState<ParsedRow\[\]>/);
});

test("the two reader modules import no spreadsheet library", () => {
  // They are imported by the modal at the top of the file; the first-load rule is
  // that nothing but a dynamic import reaches xlsx.
  for (const rel of ["lib/spreadsheet/parseCsv.ts", "lib/spreadsheet/importTemplate.ts"]) {
    assert.doesNotMatch(read(rel), /from\s*["']xlsx["']|import\(\s*["']xlsx["']\s*\)|require\(\s*["']xlsx["']\s*\)/, rel);
  }
});
