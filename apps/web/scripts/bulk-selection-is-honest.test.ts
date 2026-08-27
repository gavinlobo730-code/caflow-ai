// The selection bar must not claim to have selected rows it is not holding.
// Run with:
//   node --experimental-strip-types --test scripts/bulk-selection-is-honest.test.ts
//
// WHY THIS EXISTS
//     DataTable's bulk bar said "All N matching rows selected" whenever every
//     row it held was ticked. For a client-paged table that is true — `data` is
//     every match. For a SERVER-paged one it is not: `data` is one page, and
//     because serverPaged passes pageSize 0 (show the page whole), processRows
//     reports that page as the entire result. So on a 300-line bank statement
//     at 50 a page, ticking select-all produced:
//
//         "All 50 matching rows selected"
//
//     and a bulk Record or Exclude then ran on a sixth of what that sentence
//     promised. Nothing errored. The count was even accurate — it was the word
//     "matching" that was false.
//
//     A cross-page selection cannot simply be added instead: bulk actions
//     receive `selectedRows`, which filters `data`, so an id from a page that
//     is not loaded reaches no action at all. The fix is therefore to say what
//     is true and offer to bring the rest onto one page.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TABLE = path.join(__dirname, "..", "components", "ui", "data-table.tsx");

/** The bulk bar's source, sliced — every phrase below also appears in prose
 *  elsewhere in this file, and a whole-file scan would be satisfied by the
 *  comments explaining the bug while the bug itself was back. */
function bulkBarSource(): string {
  const s = fs.readFileSync(TABLE, "utf8");
  const start = s.indexOf("{hasBulk && t.selected.size > 0 && (");
  assert.ok(start > 0, "the bulk action bar was not found — has it moved?");
  // Ends where the action buttons begin. Matched on "{bulkActions!" alone, not
  // on "{bulkActions!.map(" — an appliesTo filter was later chained in front of
  // the .map and every test in this file went red with "could not find the end
  // of the bulk bar", which is at least a loud failure rather than a silent
  // empty slice, but the marker should not be that brittle.
  const end = s.indexOf("{bulkActions!", start);
  assert.ok(end > start, "could not find the end of the bulk bar");
  const bar = s.slice(start, end);
  assert.ok(bar.length > 800, `the bulk bar came back at ${bar.length} chars`);
  return bar;
}

test("the count is only called \"matching\" when the table holds every match", () => {
  const bar = bulkBarSource();

  // The claim has to be conditional on the server's total, not on
  // allFilteredSelected alone — which is what made it false.
  assert.match(bar, /serverPaged && serverPaged\.total > t\.selected\.size/,
    "the label must compare the SERVER's total against what is selected; " +
    "allFilteredSelected only ever describes the rows this table is holding");
  assert.match(bar, /All \$\{t\.selected\.size\} on this page selected/,
    "when more rows match than are held, the bar must say \"on this page\"");

  // And the honest wording must not be reachable only through dead code: the
  // unqualified sentence has to sit on the far side of that comparison.
  const onPageAt = bar.indexOf("on this page selected");
  const allAt = bar.indexOf("matching rows selected");
  assert.ok(onPageAt > 0 && allAt > 0, "both wordings must exist");
  assert.ok(onPageAt < allAt,
    "the page-scoped wording must be the branch taken when the totals differ, " +
    "with the unqualified one as the fallback — the other order restores the lie");
});

test("no cross-page select-all is offered where it could not work", () => {
  const bar = bulkBarSource();

  // selectAllFiltered selects ids out of `data`. Under serverPaged `data` is
  // one page, so the button would select exactly what is already selected and
  // label it as all N — the same false claim with an extra click.
  const at = bar.indexOf("t.selectAllFiltered");
  assert.ok(at > 0, "the client-paged select-all must still exist");
  const guard = bar.lastIndexOf("{!serverPaged &&", at);
  assert.ok(guard > 0 && guard < at,
    "the cross-page \"Select all N matching rows\" button must be guarded on " +
    "!serverPaged — it cannot reach rows the table has not loaded");
});

test("the way to reach the other pages is to load them, not to pretend", () => {
  const bar = bulkBarSource();
  assert.match(bar, /serverPaged\.onChange\(\{/,
    "the bar must offer to bring the remaining matches onto one page");
  assert.match(bar, /Math\.min\(PAGE_SIZES\[PAGE_SIZES\.length - 1\], serverPaged\.total\)/,
    "and cap that at the largest page size offered, which is the largest page " +
    "one fetch corresponds to — an uncapped pageSize would ask the server for " +
    "an unbounded result set");
});

test("the bar renders only the actions the current selection can take", () => {
  // Deliberately NOT bulkBarSource(): that slice ends where the buttons begin,
  // and the filter is chained on the far side of it. Sliced from the array to
  // its .map instead, so this cannot be satisfied by a filter somewhere else.
  const s = fs.readFileSync(TABLE, "utf8");
  const from = s.indexOf("{bulkActions!");
  assert.ok(from > 0, "the bulk action list was not found");
  const bar = s.slice(from, s.indexOf(".map((a) => (", from));
  assert.ok(bar.length > 40 && bar.length < 600,
    `the action-list slice came back at ${bar.length} chars`);
  // The filter has to run over the SELECTED rows, not the page: a guard fed the
  // whole page would offer Undo on a For-review tab that happens to hold one
  // recorded line the user did not tick.
  assert.match(bar, /\.filter\(\(a\) => !a\.appliesTo \|\| a\.appliesTo\(t\.selectedRows\)\)/,
    "bulk actions must be filtered by their own appliesTo against the selected " +
    "rows — without it every action shows on every tab and the inapplicable " +
    "ones report \"0 applied\" rather than being absent");
});

test("the search box takes the toolbar's free space", () => {
  const s = fs.readFileSync(TABLE, "utf8");
  const at = s.indexOf('aria-label="Search"');
  assert.ok(at > 0, "the search input was not found");
  const wrapperAt = s.lastIndexOf('<div className="relative', at);
  const wrapper = s.slice(wrapperAt, at);
  assert.match(wrapper, /flex-1/,
    "the search box must grow into the toolbar rather than sit at a fixed " +
    "width beside a lane of empty space — with no picker on the row, " +
    "narrowing to a run of similar lines is how a statement gets worked");
  assert.match(wrapper, /min-w-\[/,
    "and keep a floor, or it collapses to nothing when filters crowd the row");

  // Two elements both claiming the slack fight over it. Scanned on the
  // CLASSNAME of the div that wraps the right-hand group and nothing else: a
  // 200-character window before it also caught the comment explaining why
  // ml-auto was removed, so the test failed on the prose describing the fix.
  const teAt = s.indexOf("{toolbarExtra}");
  assert.ok(teAt > 0, "the right-hand toolbar group was not found");
  const divAt = s.lastIndexOf("<div className=\"", teAt);
  const cls = s.slice(divAt + '<div className="'.length, s.indexOf('"', divAt + 17));
  assert.ok(cls.includes("flex"), `the wrapper class came back as "${cls}"`);
  assert.ok(!cls.includes("ml-auto"),
    `the right-hand group still claims the free space (class "${cls}") now ` +
    "that the search takes it");
});
