// Two sibling screens on the client Accounting tab treated the same kind of
// row inconsistently.
//
// (1) Chart of Accounts rows were not clickable at all, while the identical
//     account rows on Trial Balance / P&L / Balance Sheet open the ledger
//     drill-down. Fixed by wiring the same onDrillDown into ChartOfAccounts'
//     DataTable via onRowClick, which is also what gives the row its cursor
//     and hover affordance (DataTable derives both from onRowClick itself).
//
// (2) The journal tab's "Reverse posted" bulk action had no appliesTo, so it
//     stayed enabled and clickable for a selection made entirely of Draft
//     entries — which reverse-posted can never do anything to (its own run()
//     filters to e.is_posted and reports every draft as skipped). Every other
//     bulk action in this codebase that only applies to some states hides
//     itself via BulkAction.appliesTo (see lib/table/types.ts and
//     components/banking/EntriesTab.tsx) rather than offering a button that
//     completes and reports "0 applied".
//
// Run with: node --experimental-strip-types --test scripts/the-accounting-tabs-behave-alike.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PAGE = path.join(__dirname, "..", "app", "clients", "[id]", "accounting", "page.tsx");
const src = stripComments(fs.readFileSync(PAGE, "utf8"));

test("the Chart of Accounts tab is handed the same drill-down as Trial Balance", () => {
  assert.match(src, /<ChartOfAccounts accounts=\{accounts\} loading=\{accsLoading\} error=\{accountsError\} onRefresh=\{loadAccounts\} onDrillDown=\{openDrillDown\} \/>/,
    "the coa tab must receive onDrillDown, the same prop Trial Balance/P&L/Balance Sheet already take");
});

test("ChartOfAccounts declares onDrillDown and wires it to a row click", () => {
  const at = src.indexOf("function ChartOfAccounts(");
  assert.ok(at > 0, "ChartOfAccounts was not found — has it moved?");
  const end = src.indexOf("function journalEditorHref(", at);
  assert.ok(end > at, "could not find the end of ChartOfAccounts — has the next section moved?");
  const body = src.slice(at, end);

  assert.match(body, /onDrillDown \}: \{ accounts: Account\[\]; loading: boolean; error\?: string \| null; onRefresh: \(\) => void; onDrillDown: \(accountId: string\) => void \}/,
    "the component must accept onDrillDown as a required prop, not an optional one silently skipped");
  assert.match(body, /onRowClick=\{\(a\) => onDrillDown\(a\.id\)\}/,
    "the DataTable must open the ledger drill-down on a row click, the same call TrialBalance makes");
});

test("reverse-posted hides itself for an all-draft selection", () => {
  const at = src.indexOf('id: "reverse-posted"');
  assert.ok(at > 0, "the reverse-posted bulk action was not found — has it moved?");
  const end = src.indexOf("exportSelectedAction(", at);
  assert.ok(end > at, "could not find the end of the reverse-posted action");
  const action = src.slice(at, end);

  // Must run over the SELECTION, not the page — the same discipline
  // BulkAction.appliesTo documents for every other action in the app.
  assert.match(action, /appliesTo: \(rows\) => rows\.some\(\(e\) => e\.is_posted\)/,
    "reverse-posted must hide itself unless at least one selected row is posted — " +
    "without this, ticking only Draft entries still shows an enabled button that " +
    "completes and reports every row skipped");

  // And it must be declared BEFORE run(), so a selection of all drafts never
  // reaches the confirm dialog at all.
  const appliesAt = action.indexOf("appliesTo:");
  const runAt = action.indexOf("run: (rows) => runBulk(");
  assert.ok(appliesAt > 0 && runAt > appliesAt,
    "appliesTo must gate the action before its run()");
});
