// sweep-tds-mca-10: the "Add MCA Filing" client picker listed every client in
// the firm — Proprietorship, Partnership, LLP included — although every form
// in FORM_TYPES (AOC-4, MGT-7/7A, ADT-1, INC-20A, DIR-3 KYC, CHG-1, MSME-1) is
// a Companies Act 2013 form that only binds a company. It also defaulted the
// "Period" field to the string literal "FY 2025-26" rather than the current
// financial year.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-add-mca-filing-picker-is-companies-act-scoped.test.ts
//
// This is a guard on the SOURCE, matching the style of
// a-financial-year-choice-comes-from-the-clock.test.ts: the picker must derive
// its list from lib/entityObligations.isCompaniesActCompany (the one place
// this product decides which entities are on the Companies Act 2013 MCA
// regime — see that module's own docstring) rather than from a second,
// inline classification, and the default period must come off the clock.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const PAGE = "app/mca/page.tsx";

test("AddFilingModal filters its client picker to Companies Act entities", () => {
  const src = readFileSync(PAGE, "utf8");

  assert.match(
    src,
    /import\s*\{[^}]*isCompaniesActCompany[^}]*\}\s*from\s*["']@\/lib\/entityObligations["']/,
    `${PAGE} no longer imports isCompaniesActCompany from lib/entityObligations — ` +
      "the one place the product decides which entities are on the Companies Act " +
      "2013 MCA regime.",
  );

  const modalStart = src.indexOf("function AddFilingModal");
  assert.ok(modalStart >= 0, "AddFilingModal was not found");
  const modalEnd = src.indexOf("\n// ─", modalStart + 1);
  const modal = src.slice(modalStart, modalEnd > 0 ? modalEnd : undefined);

  assert.match(
    modal,
    /companyClients\s*=\s*useMemo\(\(\)\s*=>\s*clients\.filter\(c\s*=>\s*isCompaniesActCompany\(c\.entity_type\)\)/,
    "AddFilingModal no longer derives a companies-only list with isCompaniesActCompany",
  );

  assert.match(
    modal,
    /<ClientLookup[\s\S]*?clients=\{companyClients\}/,
    "The Client picker's <ClientLookup> is no longer handed the companies-only " +
      "list — it must not receive the firm's unfiltered client list, since every " +
      "MCA form here (AOC-4, MGT-7/7A, ADT-1, INC-20A, DIR-3 KYC, CHG-1, MSME-1) " +
      "binds a company and not an LLP or a proprietorship.",
  );
});

test("the Add MCA Filing period defaults from the clock, not a hardcoded FY", () => {
  const src = readFileSync(PAGE, "utf8");
  const modalStart = src.indexOf("function AddFilingModal");
  const modalEnd = src.indexOf("\n// ─", modalStart + 1);
  const modal = src.slice(modalStart, modalEnd > 0 ? modalEnd : undefined);

  assert.doesNotMatch(
    modal,
    /useState\(\s*["']FY \d{4}-\d{2}["']\s*\)/,
    "the Period field's default is a hardcoded financial-year literal again",
  );
  assert.match(
    modal,
    /useState\(\(\)\s*=>\s*`FY \$\{currentFinancialYearLabel\(\)\}`\)/,
    "the Period field no longer derives its default from currentFinancialYearLabel()",
  );
});
