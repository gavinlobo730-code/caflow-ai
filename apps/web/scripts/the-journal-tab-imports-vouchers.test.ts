// ACC-17, the screen half. Bulk import existed for invoices, receipts, bills and
// notes and not for the vouchers a bookkeeper most often has in a spreadsheet —
// journals, payments, receipts, contras — so a small client's Excel of payments
// was typed again, line by line.
//
// What must hold, stated as the rule rather than a spelling of it:
//   * the screen takes the ONE import door (the lazy wrapper), never the modal
//     itself and never the spreadsheet library;
//   * it DECIDES NOTHING: no date is read, no ledger matched, no balance summed
//     and no type normalised in the browser — those are
//     domain/accounting/voucher_import's answers and every posting goes through
//     the one kernel on the server;
//   * the CA says where the vouchers go and neither answer is pre-selected,
//     because the server refuses a request that does not say;
//   * a file is sent as small requests of WHOLE vouchers (the browser abandons a
//     request at 45 seconds and never retries), and the loop stops at the first
//     batch that does not answer;
//   * the button is on the Journal tab, not on the day book, which is a report.
//
// No DOM harness exists in this repository, so this holds the wiring from the
// source; the behaviour it wires is in lib/accounting/voucherImport.test.ts and
// apps/api/tests/test_voucher_import.py.
//
// Run with: node --experimental-strip-types --test scripts/the-journal-tab-imports-vouchers.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...p: string[]) =>
  stripComments(fs.readFileSync(path.join(__dirname, "..", ...p), "utf8"));

const screen = read("components", "accounting", "VoucherImport.tsx");
const lib = read("lib", "accounting", "voucherImport.ts");
const api = read("lib", "api", "index.ts");
const page = read("app", "clients", "[id]", "accounting", "page.tsx");

test("the screen takes the one import door and nothing heavier", () => {
  assert.match(screen, /import CsvImportModal from "@\/components\/LazyCsvImportModal";/);
  assert.match(screen, /import type \{[^}]*\} from "@\/components\/CsvImportModal";/);
  assert.doesNotMatch(screen, /import CsvImportModal from "@\/components\/CsvImportModal"/);
  assert.doesNotMatch(screen, /from "xlsx"|import\("xlsx"\)/);
});

test("the browser converts and the server decides", () => {
  // A date, a ledger match, a balance and a type are the server's rules; a
  // browser copy of any of them agrees with it until it does not.
  assert.doesNotMatch(lib, /new Date\(|Date\.parse|toISOString|parseFloat|Number\(/);
  assert.doesNotMatch(lib, /toLowerCase|localeCompare|\.includes\(/,
    "matching a ledger or a type is the server's rule");
  assert.doesNotMatch(lib, /debit_paise\s*[-+]=|credit_paise\s*[-+]=|reduce\(/,
    "whether a voucher balances is the server's rule");
  assert.match(lib, /paiseFromRupeeInput/);
  assert.doesNotMatch(screen, /\.posted\b|_create_journal|journal_entries/,
    "the screen never writes to the ledger itself");
});

test("the CA must say where the vouchers go, and neither answer is pre-selected", () => {
  assert.match(screen, /useState<VoucherStatus \| null>\(null\)/);
  // Re-opening the dialog starts from no answer again, not from last time's.
  assert.match(screen, /setStatus\(null\);\s*setStep\("choose"\)/);
  assert.match(screen, /disabled=\{status === null\}/);
  assert.match(screen, /Post to the ledger now/);
  assert.match(screen, /Save as drafts for review/);
  // The import step cannot be reached, nor a request built, without a status.
  assert.match(screen, /step === "import" && status && \(/);
  assert.match(screen, /if \(!status\) throw new Error\(/);
});

test("a file goes up as small requests of whole vouchers and stops at the first that fails", () => {
  const handler = screen.slice(screen.indexOf("async function handleImport"),
                               screen.indexOf("const radio"));
  assert.match(handler, /chunkVouchers\(buildVoucherLegs\(rows, layout, meta\?\.rowNumbers\)\)/);
  assert.match(handler, /for \(let i = 0; i < batches\.length; i\+\+\)/);
  assert.match(handler, /api\.accounting\.importVouchers\(\{/);
  // The first batch that does not answer ends the loop, so nothing more is
  // posted on top of a state the CA cannot see.
  assert.match(handler, /catch \(e\)[\s\S]*?break;/);
  assert.match(handler, /Upload the same file again/);
  assert.doesNotMatch(handler, /dry_run/, "the screen imports; it does not silently preview");
  // The ledger list reloads whatever happened, because earlier batches are real.
  assert.match(handler, /onImported\(\)/);
});

test("a payload from the server is not trusted to carry its list", () => {
  // lib/api/shape: `{}` passes objectOrNull, so the list is named.
  assert.match(screen, /objectWithLists<VoucherImportResult>\(res\.data, "results"\)/);
});

test("the request size is a number that cannot quietly grow past the browser's patience", () => {
  const m = lib.match(/export const VOUCHERS_PER_REQUEST = (\d+);/);
  assert.ok(m, "the batch size is a named constant");
  assert.ok(Number(m[1]) <= 25, `${m[1]} vouchers a request is too many for a 45 second abort`);
});

test("the api method posts the client, the status and the legs to the import door", () => {
  const m = api.slice(api.indexOf("importVouchers: (body: {"),
                      api.indexOf("importVouchers: (body: {") + 400);
  assert.match(m, /client_id: string;/);
  assert.match(m, /status: "draft" \| "posted";/);
  assert.match(m, /legs: VoucherImportLeg\[\];/);
  assert.match(m, /method: "POST"/);
  assert.match(m, /\/api\/accounting\/vouchers\/import/);
});

test("the button is on the Journal tab and not on the day book", () => {
  assert.match(page, /import \{ VoucherImportButton \} from "@\/components\/accounting\/VoucherImport";/);
  const uses = page.match(/<VoucherImportButton\b/g) ?? [];
  assert.equal(uses.length, 1, "one entry point, in JournalList");
  // It sits inside the `!dayBook` branch, which is where New Journal Entry is.
  const start = page.indexOf("{!dayBook && (");
  const at = page.indexOf("<VoucherImportButton");
  const end = page.indexOf("<DataTable", start);
  assert.ok(start >= 0 && at > start && at < end,
    "the import button must sit in the branch the day book does not render");
  assert.match(page, /<VoucherImportButton clientId=\{clientId\} onImported=\{loadEntries\}/);
});
