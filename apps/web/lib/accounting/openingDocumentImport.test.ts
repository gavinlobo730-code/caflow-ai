// ACC-05 — the spreadsheet side of the opening-document import, as pure
// functions. What the SERVER decides (party, date, duplicate, reconciliation) is
// pinned in apps/api/tests/test_bulk_opening_documents.py; this is only the
// conversion the browser owns.
//
// Run with: node --experimental-strip-types --test lib/accounting/openingDocumentImport.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import {
  buildOpeningDocumentRows, importOutcomeFrom, importSummarySentence,
  openingDocumentColumns,
} from "./openingDocumentImport.ts";
import type { OpeningDocumentBulkResult } from "../api/index.ts";

const row = (over: Record<string, string> = {}) => ({
  party: "Acme Traders", party_gstin: "", document_no: "INV/1",
  document_date: "01-03-2026", due_date: "", outstanding: "1,25,000.50",
  notes: "", ...over,
});

test("the two sides share their keys and differ only in the words", () => {
  const rec = openingDocumentColumns("receivable");
  const pay = openingDocumentColumns("payable");
  assert.deepEqual(rec.map((c) => c.key), pay.map((c) => c.key));
  assert.equal(rec[0].label, "Customer");
  assert.equal(pay[0].label, "Vendor");
  assert.equal(rec.find((c) => c.key === "document_no")!.label, "Invoice number");
  assert.equal(pay.find((c) => c.key === "document_no")!.label, "Bill number");
});

test("the four columns a document cannot exist without are required", () => {
  const req = openingDocumentColumns("receivable").filter((c) => c.required).map((c) => c.key);
  assert.deepEqual(req, ["party", "document_no", "document_date", "outstanding"]);
});

test("an amount typed the Indian way is exact paise through the one parser", () => {
  const [r] = buildOpeningDocumentRows([row()]);
  assert.equal(r.outstanding_paise, 12_500_050);
  assert.equal(buildOpeningDocumentRows([row({ outstanding: "₹ 9,999" })])[0].outstanding_paise, 999_900);
  assert.equal(buildOpeningDocumentRows([row({ outstanding: "0.05" })])[0].outstanding_paise, 5);
});

test("a cell that is not an amount travels as null, never as a number", () => {
  // parseFloat would read each of these as something; the server refuses the
  // row BY NUMBER, so it must arrive.
  for (const bad of ["", "12abc", "1e3", "1.234", "abc", "--5", "Rs. ten"]) {
    const [r] = buildOpeningDocumentRows([row({ outstanding: bad })]);
    assert.equal(r.outstanding_paise, null, `"${bad}" should not be an amount`);
  }
});

test("a date goes up exactly as typed — reading it is the server's rule", () => {
  // 4/1/26 is the cell the server is about to refuse; a browser that tidied it
  // first would hide it.
  for (const d of ["4/1/26", "01-Mar-2026", "2026-03-01", "31-02-2026"]) {
    assert.equal(buildOpeningDocumentRows([row({ document_date: d })])[0].document_date, d);
  }
});

test("the preview's row numbers survive the rows the modal held back", () => {
  // The modal hands over only rows that cleared ITS checks, so rows 1, 2 and 4
  // arrive as three items: position is not number.
  const out = buildOpeningDocumentRows([row(), row(), row()], [1, 2, 4]);
  assert.deepEqual(out.map((r) => r.row), [1, 2, 4]);
  assert.deepEqual(buildOpeningDocumentRows([row(), row()]).map((r) => r.row), [1, 2]);
});

test("blank optional cells are null and text is trimmed", () => {
  const [r] = buildOpeningDocumentRows([row({ party: "  Acme  ", party_gstin: "", due_date: " ", notes: " " })]);
  assert.equal(r.party, "Acme");
  assert.equal(r.party_gstin, null);
  assert.equal(r.due_date, null);
  assert.equal(r.notes, null);
});

const result = (over: Partial<OpeningDocumentBulkResult> = {}): OpeningDocumentBulkResult => ({
  kind: "receivable", dry_run: false, received: 4, created: 2, would_create: 0,
  already_recorded: 1, rejected: 1, created_paise: 3_00_000, would_create_paise: 0,
  rows: [
    { row: 1, document_no: "A", status: "new", problems: [], party_name: "X", outstanding_paise: 1, id: "1" },
    { row: 2, document_no: "B", status: "already_recorded", problems: [], party_name: "X", outstanding_paise: 1, id: "2" },
    { row: 3, document_no: "C", status: "rejected", problems: ["No customer named \"Z\".", "The due date is not a date."], party_name: null, outstanding_paise: 0, id: null },
    { row: 4, document_no: "", status: "rejected", problems: ["The document's own number is required."], party_name: null, outstanding_paise: 0, id: null },
  ],
  reconciliation: [], unreconciled_parties: 2, ...over,
});

test("the verdicts become the modal's counters and lists, by row number", () => {
  const out = importOutcomeFrom(result());
  assert.equal(out.imported, 2);
  assert.equal(out.skipped, 1);
  assert.deepEqual(out.skippedDetail, ["Row 2 (B): already recorded — nothing added"]);
  assert.deepEqual(out.errors, [
    "Row 3 (C): No customer named \"Z\". The due date is not a date.",
    "Row 4: The document's own number is required.",
  ]);
});

test("a malformed answer cannot crash the report", () => {
  const out = importOutcomeFrom(result({ rows: undefined as unknown as [] }));
  assert.deepEqual(out.errors, []);
  assert.deepEqual(out.skippedDetail, []);
});

test("the summary says what landed and how many parties still do not foot", () => {
  const rupees = (p: number) => `₹${(p / 100).toFixed(2)}`;
  assert.equal(importSummarySentence(result(), rupees),
    "2 documents recorded (₹3000.00), 1 already there, 1 refused. "
    + "2 parties do not add up to the opening balance on the record — each is named below.");
  assert.match(importSummarySentence(result({ unreconciled_parties: 1 }), rupees), /1 party does not add up/);
  assert.match(importSummarySentence(result({ unreconciled_parties: 0, rejected: 0, already_recorded: 0, created: 1, created_paise: 100 }), rupees),
    /^1 document recorded \(₹1\.00\)\. Every party's documents add up to its opening balance\.$/);
});
