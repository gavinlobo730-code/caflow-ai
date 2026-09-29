// The Trial Balance's own TOTAL row filled in the Closing Dr/Cr columns and
// left Opening and This-period blank under one wide "Total" cell, on a screen
// that otherwise renders Opening, This-period and Closing side by side per
// account.
//
// Run with:
//   node --experimental-strip-types --test scripts/trial-balance-totals-every-column.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const src = fs.readFileSync(path.join(WEB, "app/clients/[id]/accounting/page.tsx"), "utf8");

// The Trial Balance's own <tfoot>, sliced out so these assertions cannot
// accidentally match a different table's Total row on this 3,900-line page.
const tbStart = src.indexOf("function TrialBalance(");
const tbEnd = src.indexOf("\nfunction ", tbStart + 1);
const tb = src.slice(tbStart, tbEnd);
const footStart = tb.indexOf("<tfoot>");
const foot = tb.slice(footStart, tb.indexOf("</tfoot>", footStart));

test("the Trial Balance total row no longer spans straight over Opening and This-period", () => {
  assert.ok(!/colSpan=\{periodic \? 7 : 3\}/.test(foot),
    "the wide colSpan that swallowed the Opening and Period columns is still there");
  assert.match(foot, /colSpan=\{3\}/,
    "the Total label should span only Code/Account/Type now that the other four cells carry figures");
});

test("Opening and This-period are each summed and rendered, not left blank", () => {
  assert.match(foot, /openingTotals\.debit/, "Opening Dr has no total");
  assert.match(foot, /openingTotals\.credit/, "Opening Cr has no total");
  assert.match(foot, /periodTotals\.debit/, "This-period Dr has no total");
  assert.match(foot, /periodTotals\.credit/, "This-period Cr has no total");
});

test("the sums are built from the rows already on screen, keyed on the right fields", () => {
  assert.match(tb, /opening_debit_paise \?\? 0/);
  assert.match(tb, /opening_credit_paise \?\? 0/);
  assert.match(tb, /period_debit_paise \?\? 0/);
  assert.match(tb, /period_credit_paise \?\? 0/);
});

test("the Closing pair still comes from the backend's own authoritative totals, unchanged", () => {
  // The single-source-of-truth note above `grandDebit`/`grandCredit` is about
  // NOT recomputing these two from the rows — this fix must not have quietly
  // done that instead of adding the two new sums beside them.
  assert.match(foot, /formatPaise\(grandDebit\)/);
  assert.match(foot, /formatPaise\(grandCredit\)/);
});
