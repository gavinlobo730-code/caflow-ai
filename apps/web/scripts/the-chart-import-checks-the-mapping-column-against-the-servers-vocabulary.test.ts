/**
 * The chart-of-accounts import checks the Schedule III column before it writes (POST-A-164).
 *
 * Migration 520 makes the database refuse a `schedule_iii_mapping` the engine cannot read. The import screen writes the table
 * straight over PostgREST, so a made-up caption in a CSV would otherwise fail a whole batch of rows with a raw constraint
 * message and no row number. The screen asks the SERVER for the vocabulary (the menu plus the older spellings it still reads)
 * and names the offending row; it holds no caption list of its own.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/accounting/coa-import/page.tsx";
const HELPER = "lib/accounting/coaImportMapping.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the import screen takes the vocabulary from the server and checks each row's mapping with the shared helper", () => {
  const src = code(PAGE);
  assert.match(src, /scheduleIiiCaptions\(\)/, "the vocabulary must be the engine's");
  assert.match(src, /mappingProblem\(/, "each row's mapping must be checked before it is written");
  assert.match(src, /acceptedMappings\(/, "the accepted set must be built from the served payload");
});

test("a row with an unreadable mapping is left out of the import with its own message, not sent to fail a batch", () => {
  const src = code(PAGE);
  // The check sits in the per-row loop, before the row is pushed, and `continue`s like the other row validations do.
  assert.match(src, /const problem = mappingProblem\([^;]*;\s*if \(problem\) \{\s*errors\.push\(\{[^}]*\}\);\s*continue;\s*\}/,
    "a row that fails the mapping check must be recorded as an error and skipped");
});

test("neither the screen nor the helper carries a caption list", () => {
  const captionish = /"(?:Share Capital|Reserves & Surplus|Trade Payables|Trade Receivables|Inventories|Revenue from Operations|Other Income|Finance Costs|Other Expenses|Cash & Cash Equivalents)"/g;
  for (const rel of [PAGE, HELPER]) {
    const hits = code(rel).match(captionish) ?? [];
    assert.equal(hits.length, 0, `${rel} names Schedule III captions directly (${hits.join(", ")})`);
  }
});

test("the helper vouches for nothing when the server's payload could not be read", () => {
  const src = code(HELPER);
  assert.match(src, /accepted === null/, "an unread vocabulary must produce a message, never a silent pass");
});
