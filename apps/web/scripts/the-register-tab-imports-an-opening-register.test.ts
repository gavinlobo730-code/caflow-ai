// accounting-18, the screen half. An asset could be added one way — the Add Asset
// drawer, which starts accumulated depreciation at nil and posts a fresh
// acquisition — so a migrated client's hundred part-depreciated assets were
// either typed one at a time with the wrong position or charged from their
// purchase date on top of the balance the opening trial balance already carries.
//
// What must hold, stated as the rule rather than a spelling of it:
//   * the screen takes the ONE import door (the lazy wrapper), never the modal
//     itself and never the spreadsheet library;
//   * it DECIDES NOTHING: no date is read, no category matched, no figure
//     compared in the browser, and the vocabulary (the categories) is the
//     server's, fetched and not copied;
//   * the date the figures are stated as at is CHOSEN and never defaulted, and
//     its choices come from the clock, because it decides which month the next
//     depreciation run starts at;
//   * the result says what was NOT done — the server's own sentence that nothing
//     was posted, shown beside the totals, and held nowhere in the browser;
//   * the button is on the register tab.
//
// No DOM harness exists in this repository, so this holds the wiring from the
// source; the behaviour it wires is in lib/fixedAssets/openingRegister.test.ts and
// apps/api/tests/test_opening_register_import.py.
//
// Run with: node --experimental-strip-types --test scripts/the-register-tab-imports-an-opening-register.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (...p: string[]) =>
  stripComments(fs.readFileSync(path.join(__dirname, "..", ...p), "utf8"));

const screen = read("components", "fixed-assets", "OpeningRegisterImport.tsx");
const lib = read("lib", "fixedAssets", "openingRegister.ts");
const page = read("app", "clients", "[id]", "fixed-assets", "page.tsx");

test("the screen takes the one import door and nothing heavier", () => {
  assert.match(screen, /import CsvImportModal from "@\/components\/LazyCsvImportModal";/);
  assert.match(screen, /import type \{[^}]*\} from "@\/components\/CsvImportModal";/);
  assert.doesNotMatch(screen, /import CsvImportModal from "@\/components\/CsvImportModal"/);
  assert.doesNotMatch(screen, /from "xlsx"|import\("xlsx"\)/);
});

test("the browser converts and the server decides", () => {
  // A date, a category, a basis and a position are the server's rules; a browser
  // copy of any of them agrees with it until it does not.
  // `new Date()` with NO argument is the clock the picker is derived from; a Date
  // built FROM a cell, or any parse or coercion, is the server's job.
  assert.doesNotMatch(lib, /new Date\([^)]|Date\.parse|toISOString|parseFloat|Number\(/,
    "no date is read and no cell coerced in the browser");
  assert.doesNotMatch(lib, /toLowerCase|localeCompare|\.includes\(/,
    "matching a category is the server's rule");
  assert.match(lib, /paiseFromRupeeInput/);
  assert.doesNotMatch(lib, /accumulated\w*\s*(?:>|<|>=|<=)\s*\w*cost|cost\w*\s*-\s*\w*accum/i,
    "whether a position is possible is the server's rule");
});

test("the categories are the server's, fetched, and the browser holds no list of them", () => {
  assert.match(screen, /\/api\/fixed-assets\/categories\?client_id=/);
  assert.match(screen, /arrayOrEmpty</);
  for (const name of ["Plant & Machinery", "Furniture & Fixtures", "Office Equipment",
                      "Computer & IT Equipment", "Vehicles", "Intangibles"]) {
    assert.ok(!lib.includes(name) && !screen.includes(name), `${name} must not be copied here`);
  }
});

test("the position date is chosen, never defaulted", () => {
  assert.match(screen, /useState\(""\)/);
  // Opening again starts from no answer, not from last time's.
  assert.match(screen, /setAsAt\(""\);[\s\S]*?setStep\("choose"\)/);
  assert.match(screen, /<option value="">Choose the date…<\/option>/);
  assert.match(screen, /disabled=\{!asAt\}/);
  // The import step cannot be reached, nor a request built, without one.
  assert.match(screen, /step === "import" && asAt && \(/);
  assert.match(screen, /if \(!asAt\) throw new Error\(/);
});

test("the choices come from the clock and are never a listed year", () => {
  assert.match(screen, /setChoices\(positionChoices\(\)\)/);
  assert.match(lib, /financialYearChoices\(/);
  assert.doesNotMatch(lib + screen, /"20\d\d-\d\d"|'20\d\d-\d\d'|20\d\d-03-31/,
    "no year is written into the source");
});

test("the import posts the client, the position and the rows to the register door", () => {
  const handler = screen.slice(screen.indexOf("async function handleImport"),
                               screen.indexOf("const warnings"));
  assert.match(handler, /\/api\/fixed-assets\/opening-register/);
  assert.match(handler, /method: "POST"/);
  assert.match(handler, /client_id: clientId,/);
  assert.match(handler, /as_at: asAt,/);
  assert.match(handler, /buildOpeningRegisterRows\(rows, meta\?\.rowNumbers\)/);
  assert.doesNotMatch(handler, /dry_run/, "the screen imports; it does not silently preview");
  // The register reloads, because the figures on the tab just changed.
  assert.match(handler, /onImported\(\)/);
});

test("a payload from the server is not trusted to carry its lists", () => {
  // lib/api/shape: `{}` passes objectOrNull and `.map` on it throws.
  assert.match(screen, /objectWithLists<OpeningRegisterResult>\(res\.data, "rows", "by_category", "gaps"\)/);
});

test("what was NOT done is the server's sentence, shown beside the totals, and held nowhere here", () => {
  assert.match(screen, /result\.ledger_note/);
  assert.match(screen, /<Callout tone="attention" title="Compare these totals with the ledger">/);
  assert.doesNotMatch(lib + screen, /Nothing was posted to the ledger/,
    "the sentence is served — a browser copy is a second authority on what the import did");
  // Gaps and per-asset warnings are rendered, not dropped.
  assert.match(screen, /<GapList gaps=\{result\.gaps\}/);
  assert.match(screen, /<GapList gaps=\{warnings\}/);
});

test("a re-upload reads as skipped, not as an error, in the done step", () => {
  assert.match(screen, /skippedHeading="Already on the register/);
});

test("the button is on the register tab beside Add Asset", () => {
  assert.match(page, /import \{ OpeningRegisterImportButton \} from "@\/components\/fixed-assets\/OpeningRegisterImport";/);
  const uses = page.match(/<OpeningRegisterImportButton\b/g) ?? [];
  assert.equal(uses.length, 1, "one entry point");
  assert.match(page, /<OpeningRegisterImportButton clientId=\{clientId\} onImported=\{load\} \/>/);
  const tab = page.slice(page.indexOf("function RegisterTab"), page.indexOf("function CorrectAssetDrawer"));
  assert.ok(tab.includes("<OpeningRegisterImportButton"), "it sits in RegisterTab");
});
