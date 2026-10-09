/**
 * The import template reads back as an empty template, and the done step counts
 * every row of the file (PRE-A-001). Run with:
 *   node --experimental-strip-types --test lib/spreadsheet/importTemplate.test.ts
 *
 * Driving the dialog in a browser found that uploading the Excel template exactly
 * as downloaded reported "2 valid rows": its hint row and a copy of it, read as
 * data. These tests do what the dialog does — write the template to .xlsx, read it
 * back, turn the sheet into text, parse it — so the round trip is the thing held.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { parseCsv } from "./parseCsv.ts";
import {
  heldBackHeading,
  heldBackRows,
  templateInstructions,
  templateNote,
  templateSheetRows,
  type TemplateColumn,
} from "./importTemplate.ts";
import { sheetToCsvWithIsoDates } from "./xlsxCsv.ts";

const loaded = await import("xlsx");
const X: typeof import("xlsx") =
  (loaded as unknown as { default?: typeof import("xlsx") }).default ?? loaded;

// The opening-documents columns, whose first hint carries a comma and whose
// amount hint carries Indian grouping — the two things that make a library quote
// a cell and hide a leading "#".
const COLUMNS: TemplateColumn[] = [
  { key: "party", label: "Customer", required: true, hint: "Customer name, as recorded for this client" },
  { key: "party_gstin", label: "Customer GSTIN", required: false, hint: "Optional — settles two parties with the same name" },
  { key: "document_no", label: "Invoice number", required: true, hint: "The number the old system issued" },
  { key: "document_date", label: "Document date", required: true, hint: "dd-mm-yyyy or yyyy-mm-dd (not a two-digit year)" },
  { key: "outstanding", label: "Still outstanding (₹)", required: true, hint: "What is STILL OPEN at the opening date, e.g. 1,25,000.00" },
];
const NO_HINTS: TemplateColumn[] = [
  { key: "name", label: "Name", required: true },
  { key: "city", label: "City", required: false },
];

/** What a CA gets: the template workbook, as the dialog writes it, read back as
 *  the dialog reads a chosen file. `below` are rows typed under the note. */
function csvOfTemplate(columns: TemplateColumn[], below: (string | number)[][] = []): string {
  const ws = X.utils.aoa_to_sheet([...templateSheetRows(columns), ...below]);
  const wb = { SheetNames: ["Template"], Sheets: { Template: ws } };
  const bytes = new Uint8Array(X.write(wb, { type: "array", bookType: "xlsx" }));
  const back = X.read(bytes, { type: "array", cellNF: true });
  return sheetToCsvWithIsoDates(X, back, back.Sheets[back.SheetNames[0]]);
}

test("the Excel template, uploaded exactly as downloaded, has no data rows", () => {
  for (const columns of [COLUMNS, NO_HINTS]) {
    const csv = csvOfTemplate(columns);
    assert.deepEqual(parseCsv(csv, columns), [], csv);
  }
});

test("the note survives being quoted: a hint with a comma is still a note", () => {
  const csv = csvOfTemplate(COLUMNS);
  const noteLine = csv.split("\n")[1];
  assert.ok(noteLine.startsWith('"#'), `the library quotes this note, which is the case that matters: ${noteLine}`);
  assert.deepEqual(parseCsv(csv, COLUMNS), []);
});

test("the CSV template, uploaded exactly as downloaded, has no data rows either", () => {
  for (const columns of [COLUMNS, NO_HINTS]) {
    const csv = `${columns.map((c) => c.key).join(",")}\n${templateNote(columns)}\n`;
    assert.deepEqual(parseCsv(csv, columns), []);
  }
});

test("the two templates carry the same note, as one cell that starts with '# '", () => {
  const rows = templateSheetRows(COLUMNS);
  assert.equal(rows.length, 2, "the headers and ONE note row, no example row");
  assert.deepEqual(rows[0], COLUMNS.map((c) => c.key));
  assert.equal(rows[1].length, 1, "the note is a single cell, a note to the reader");
  assert.equal(rows[1][0], templateNote(COLUMNS));
  assert.ok(rows[1][0].startsWith("# "));
  // A column with no hint says whether it is needed.
  assert.equal(templateNote(NO_HINTS), "# REQUIRED | optional");
});

test("data typed from row 3, as the Instructions say, is read, and only that", () => {
  const csv = csvOfTemplate(COLUMNS, [
    ["Nandini Retail", "", "INV/1", "15-03-2025", 100000],
    ["Gokhale Stores", "", "INV/2", "25-03-2025", 50000.5],
  ]);
  const rows = parseCsv(csv, COLUMNS);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r.data.document_no), ["INV/1", "INV/2"]);
  assert.deepEqual(rows.map((r) => r.errors), [[], []]);
  // A row is numbered by its line after the header, so the note row is number 1
  // and the first data row is 2: the number is the spreadsheet row MINUS ONE,
  // which is what the preview shows and what every importer's "Row N" quotes.
  assert.deepEqual(rows.map((r) => r.index), [2, 3]);
});

test("the Instructions sheet says what the reader does", () => {
  const text = templateInstructions(COLUMNS).map((r) => r.join(" ")).join("\n");
  assert.match(text, /Row 2 is a note[^\n]*begins with #[^\n]*skipped/);
  assert.match(text, /Enter your data from Row 3 onwards/);
  assert.doesNotMatch(text, /Delete Row 2/, "row 2 is skipped; deleting it is optional, not a step");
  assert.match(text, /read as that date, whatever format it shows/);
  // One guide row per column, in the template's order.
  const guide = templateInstructions(COLUMNS).filter((r) => r.length === 3);
  assert.deepEqual(guide.map((r) => r[0]), COLUMNS.map((c) => c.key));
  assert.deepEqual(guide.map((r) => r[1]), COLUMNS.map((c) => (c.required ? "REQUIRED" : "optional")));
});

// The byte-order mark, as its code unit: a literal U+FEFF in source is invisible in every editor
// (scripts/one-csv-writer-and-it-escapes.test.ts).
const BOM = String.fromCharCode(0xfeff);

// ── the reader itself ────────────────────────────────────────────────────────

test("parseCsv: a BOM, CRLF, a note in either spelling and a required blank", () => {
  const csv = BOM + "name,city\r\n# REQUIRED | optional\r\n\"# a quoted note, with a comma\"\r\nAsha,Pune\r\n,Mumbai\r\n";
  const rows = parseCsv(csv, NO_HINTS);
  assert.equal(rows.length, 2);
  // Numbered by the line after the header, the two notes included (3 and 4).
  assert.deepEqual(rows[0], { index: 3, data: { name: "Asha", city: "Pune" }, errors: [] });
  assert.deepEqual(rows[1].errors, ['"Name" is required']);
  assert.equal(rows[1].index, 4);
});

test("parseCsv: a quoted data cell that merely begins with a hash is a row, not a note", () => {
  // The library quotes a cell holding a comma. A customer called "#12, MG Road Traders" is data;
  // only the template's own `# ` note (hash, space) is skipped, quoted or not.
  const csv = 'name,city\n"#12, MG Road Traders",Pune\n"# a quoted note, with a comma"\nAcme,Delhi\n';
  const rows = parseCsv(csv, NO_HINTS);
  assert.deepEqual(rows.map((r) => r.data.name), ["#12, MG Road Traders", "Acme"]);
});

test("parseCsv: a header with no rows under it is no data", () => {
  assert.deepEqual(parseCsv("name,city\n", NO_HINTS), []);
  assert.deepEqual(parseCsv("", NO_HINTS), []);
});

// ── the done step ────────────────────────────────────────────────────────────

test("the rows the preview flagged are named in the done step, with their reasons", () => {
  const rows = [
    { index: 1, errors: [] },
    { index: 2, errors: ['"Purchase cost" is required'] },
    { index: 3, errors: [] },
    { index: 6, errors: ['"Accumulated depreciation" is required', '"Purchase date" is required'] },
  ];
  const held = heldBackRows(rows);
  assert.equal(held.count, 2);
  assert.deepEqual(held.lines, [
    'Row 2: "Purchase cost" is required',
    'Row 6: "Accumulated depreciation" is required; "Purchase date" is required',
  ]);
  assert.equal(held.more, 0);
  assert.equal(heldBackHeading(2), "2 rows in your file were not sent because the preview flagged them:");
  assert.equal(heldBackHeading(1), "1 row in your file was not sent because the preview flagged it:");
});

test("nothing held back says nothing, and a long list is cut with the rest counted", () => {
  assert.deepEqual(heldBackRows([{ index: 1, errors: [] }]), { count: 0, lines: [], more: 0 });
  assert.deepEqual(heldBackRows([]), { count: 0, lines: [], more: 0 });
  const many = Array.from({ length: 12 }, (_, i) => ({ index: i + 1, errors: ["x"] }));
  const held = heldBackRows(many, 8);
  assert.equal(held.count, 12);
  assert.equal(held.lines.length, 8);
  assert.equal(held.more, 4);
});
