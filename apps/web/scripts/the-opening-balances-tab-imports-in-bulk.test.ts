// accounting-05, the screen half. The Opening Balances tab took one document per
// drawer; a trading client with two hundred open invoices is a week of typing.
// The tab now offers the shared import dialog and hands every row to the server.
//
// What must not change, and what the dialog change must not break for the ten
// screens that already use it:
//   * the tab takes the ONE import door (the lazy wrapper) and never the modal
//     itself, so the spreadsheet library stays out of the first load;
//   * the rows are converted here and DECIDED on the server — no date is read in
//     the browser, no amount goes through parseFloat, no party is matched;
//   * a refused row keeps the number the person saw in the preview, so the
//     dialog hands its importer the row numbers beside the rows;
//   * the tab reloads after the write, because the reconciliation sentences it
//     already renders are the proof the parties foot.
//
// Run with: node --experimental-strip-types --test scripts/the-opening-balances-tab-imports-in-bulk.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...p: string[]) =>
  stripComments(fs.readFileSync(path.join(__dirname, "..", ...p), "utf8"));

const tab = read("components", "accounting", "OpeningBalancesTab.tsx");
const lib = read("lib", "accounting", "openingDocumentImport.ts");
const modal = read("components", "CsvImportModal.tsx");
const api = read("lib", "api", "index.ts");

test("the tab takes the one import door and nothing heavier", () => {
  assert.match(tab, /import CsvImportModal from "@\/components\/LazyCsvImportModal";/);
  // Types come from the modal's module with `import type`, which is erased.
  assert.match(tab, /import type \{[^}]*\} from "@\/components\/CsvImportModal";/);
  assert.doesNotMatch(tab, /import CsvImportModal from "@\/components\/CsvImportModal"/);
  assert.doesNotMatch(tab, /from "xlsx"|import\("xlsx"\)/);
});

test("the dialog is opened from the tab and titled for the side being imported", () => {
  assert.match(tab, /Import from CSV \/ Excel/);
  assert.match(tab, /\{showImport && \(\s*<CsvImportModal/);
  assert.match(tab, /columns=\{openingDocumentColumns\(kind\)\}/);
  assert.match(tab, /onImport=\{handleBulkImport\}/);
});

test("the rows are converted in the browser and decided on the server", () => {
  // Reading a date, matching a name and judging a duplicate are
  // domain/accounting/opening_document_import's rules; a browser copy of any
  // of them is a second implementation that agrees until it does not.
  assert.doesNotMatch(lib, /new Date\(|Date\.parse|toISOString|parseFloat|Number\(/);
  assert.doesNotMatch(lib, /toLowerCase|localeCompare|includes\(/,
    "matching a party is the server's rule");
  assert.match(lib, /paiseFromRupeeInput/);
  const handler = tab.slice(tab.indexOf("async function handleBulkImport"),
                            tab.indexOf("async function handleRemove"));
  assert.match(handler, /api\.openingDocuments\.bulkImport\(/);
  assert.match(handler, /buildOpeningDocumentRows\(rows, meta\?\.rowNumbers\)/);
  assert.doesNotMatch(handler, /dry_run/, "the screen imports; it does not silently preview");
});

test("a refused row keeps the number the preview showed", () => {
  assert.match(modal, /export interface ImportMeta/);
  assert.match(modal, /onImport\(validRows, \{ rowNumbers: valid\.map\(r => r\.index\) \}\)/);
  assert.match(modal, /onImport: \(rows: ImportRow\[\], meta\?: ImportMeta\)/,
    "the second argument must stay OPTIONAL — ten importers do not take it");
});

test("the tab reloads after the write and says how many parties still do not foot", () => {
  const handler = tab.slice(tab.indexOf("async function handleBulkImport"),
                            tab.indexOf("async function handleRemove"));
  assert.match(handler, /await load\(\)/);
  assert.match(handler, /importSummarySentence\(data, rupees\)/);
});

test("a payload from the server is not trusted to carry its lists", () => {
  // lib/api/shape: `{}` passes objectOrNull, so the two lists are named.
  assert.match(tab, /objectWithLists<OpeningDocumentBulkResult>\(res\.data, "rows", "reconciliation"\)/);
});

test("the client method posts to the bulk door with the client and the side", () => {
  const m = api.slice(api.indexOf("bulkImport: (body: {"), api.indexOf("reconciliation: (clientId: string)"));
  assert.match(m, /client_id: string;/);
  assert.match(m, /kind: "receivable" \| "payable";/);
  assert.match(m, /method: "POST"/);
  assert.match(m, /\/api\/opening-documents\/bulk/);
});

test("the done step names what was skipped for THIS import, not a customer list", () => {
  assert.match(modal, /skippedHeading\?: string/);
  assert.match(tab, /skippedHeading="Already recorded/);
});

test("every rupee figure on the tab goes through the one formatter", () => {
  // The tab wrote its own two-decimal Intl call, which prints the difference
  // between the ledger and the documents — negative whenever the documents are
  // short — as "₹-25,000.00"; formatPaise prints "-₹25,000.00", as every other
  // screen does (PRE-A-001).
  assert.match(tab, /import \{ formatPaise \} from "@\/lib\/money\/format";/);
  assert.doesNotMatch(tab, /toLocaleString|Intl\.NumberFormat/,
    "a figure formatted here is a second formatter that disagrees on a negative");
  assert.match(tab, /importSummarySentence\(data, rupees\)/,
    "the summary sentence must be given the same formatter as the table");
});
