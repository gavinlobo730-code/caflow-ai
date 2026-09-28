// The Migration Center's "N items" card and its own Import Preview
// breakdown must agree with what the job will actually import, and the
// card must not go stale after parsing.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-migration-preview-reflects-what-will-be-imported.test.ts
//
// WHAT WAS WRONG (sweep-clients-admin-06)
//     Two separate causes, neither about seed data.
//
//     (1) The preview grid rendered `parseResult.parsed_counts`, which is
//     parse_tally_xml's count of EVERY category the export happened to
//     contain. validate_migration_data only builds items for the job's own
//     `import_types` (default ["ledgers", "journals"]), so a Sundry Debtors
//     ledger and a Sundry Creditors ledger were shown in the preview as
//     "1 Customer" and "1 Vendor" although neither was ever queued or saved
//     — the job card's own "N items" figure (from `total_items`, built from
//     the saved items) correctly excluded them. The preview overstated what
//     would be imported.
//
//     (2) handleParse never reloaded the job list after save_migration_items
//     updated the job's `total_items` on the server, so the card kept
//     showing the 0 the job was created with until some later action
//     (handleImport) happened to reload it.
//
// THE FIX
//     The breakdown grid now reads `preview.by_type` — the saved, validated
//     items — instead of the parser's raw count. A parsed-but-unselected
//     category is named explicitly ("N <type> found — not selected for
//     import") via the pure `notSelectedForImport` helper, rather than
//     silently vanishing or being shown as though it will be imported.
//     handleParse calls `await load()` once parsing succeeds, so the list
//     reflects the real total_items straight away.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

const PAGE = "app/migration/page.tsx";

test("the preview breakdown grid is driven by preview.by_type, not the parser's raw per-category count", () => {
  const src = read(PAGE);
  // The old, overstating pattern must be gone.
  assert.doesNotMatch(src, /Object\.entries\(parseResult\.parsed_counts/);
  // The grid now maps the saved/validated counts.
  assert.match(src, /const previewByType = objectOrNull<Record<string, MigrationPreviewCount>>\(preview\?\.by_type\)/);
  assert.match(src, /Object\.entries\(previewByType\)\.map/);
});

test("a category the export carried but the job did not select is named, not shown as imported", () => {
  const src = read(PAGE);
  assert.match(src, /notImportedCategories\.map\(\(\{ type, count \}\)/);
  assert.match(src, /found — not selected for import/);
});

test("handleParse reloads the job list once parsing succeeds, so the card's total_items is never stale", () => {
  const src = read(PAGE);
  const m = /async function handleParse\(\) \{([\s\S]*?)\n  \}\n/.exec(src);
  assert.ok(m, "handleParse not found");
  const body = m[1];
  assert.match(body, /setStep\("preview"\);/);
  assert.match(body, /await load\(\);/);
  // The reload must come after the step is set, not before parsing/preview
  // have actually landed.
  assert.ok(body.indexOf('setStep("preview")') < body.indexOf("await load();"));
});

test("notSelectedForImport names every parsed category the job's Import Types excluded, and nothing else", () => {
  const src = read(PAGE);
  const m = /\): Array<\{ type: string; count: number \}> \{\n([\s\S]*?)\n\}\n/.exec(src);
  assert.ok(m, "notSelectedForImport body not found");
  const body = m[1];
  assert.doesNotMatch(body, /:/); // plain JS body, no leftover type annotation

  // eslint-disable-next-line no-new-func
  const notSelectedForImport = new Function("parsedCounts", "selectedTypes", body) as (
    parsedCounts: Record<string, number> | undefined,
    selectedTypes: string[],
  ) => Array<{ type: string; count: number }>;

  // The finding's own scenario: a default job selecting only ledgers and
  // journals, an export that also carries a Sundry Debtors and a Sundry
  // Creditors ledger.
  assert.deepEqual(
    notSelectedForImport(
      { ledgers: 3, journals: 2, customers: 1, vendors: 1, opening_balances: 0, masters: 0 },
      ["ledgers", "journals"],
    ),
    [
      { type: "customers", count: 1 },
      { type: "vendors", count: 1 },
    ],
  );

  // Every parsed category selected: nothing to name.
  assert.deepEqual(
    notSelectedForImport({ ledgers: 3, journals: 2 }, ["ledgers", "journals"]),
    [],
  );

  // A category with nothing parsed is not reported even though it is
  // unselected — there is nothing for the CA to act on.
  assert.deepEqual(
    notSelectedForImport({ customers: 0, vendors: 2 }, []),
    [{ type: "vendors", count: 2 }],
  );

  // parseResult may not exist yet (a resumed job with no fresh parse this
  // session) — must not throw.
  assert.deepEqual(notSelectedForImport(undefined, ["ledgers"]), []);
});
