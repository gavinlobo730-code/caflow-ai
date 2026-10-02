import { test } from "node:test";
import assert from "node:assert/strict";
import { emptyKind, FILTERED_EMPTY } from "./emptyKind.ts";

// frontend_ux-24. A table with no rows is "nothing recorded" (the screen's own
// first-run message and action) or "your search or filters hid every row" (clear
// them). The two must never be confused, in either direction.

test("a table given no rows is empty, whatever the reader typed or ticked", () => {
  assert.equal(emptyKind({ rowCount: 0, serverPaged: false, activeFilterCount: 0, search: "" }), "empty");
  // the case that matters: a screen's DEFAULT filter (initialFilters={{ status: "active" }})
  // is an active filter on the very first load of a practice with no records at all
  assert.equal(emptyKind({ rowCount: 0, serverPaged: false, activeFilterCount: 1, search: "" }), "empty");
  assert.equal(emptyKind({ rowCount: 0, serverPaged: false, activeFilterCount: 0, search: "acme" }), "empty");
});

test("a table that was given rows and shows none was emptied by the reader's own narrowing", () => {
  assert.equal(emptyKind({ rowCount: 40, serverPaged: false, activeFilterCount: 0, search: "zzz" }), "filtered");
  assert.equal(emptyKind({ rowCount: 1, serverPaged: false, activeFilterCount: 2, search: "" }), "filtered");
});

test("a server-paged table's rows are one page, so only the reader's narrowing can be known", () => {
  assert.equal(emptyKind({ rowCount: 0, serverPaged: true, activeFilterCount: 0, search: "" }), "empty");
  assert.equal(emptyKind({ rowCount: 0, serverPaged: true, activeFilterCount: 0, search: "acme" }), "filtered");
  assert.equal(emptyKind({ rowCount: 0, serverPaged: true, activeFilterCount: 1, search: "" }), "filtered");
  assert.equal(emptyKind({ rowCount: 0, serverPaged: true, activeFilterCount: 0, search: "   " }), "empty",
    "a search of spaces narrows nothing");
  assert.equal(emptyKind({ rowCount: 0, serverPaged: true, activeFilterCount: 0 }), "empty");
});

test("the filtered message tells the reader to clear what they set and never claims nothing is recorded", () => {
  assert.match(FILTERED_EMPTY.description, /search or filters you have set/);
  assert.match(FILTERED_EMPTY.clearLabel, /Clear/);
  assert.doesNotMatch(FILTERED_EMPTY.title + FILTERED_EMPTY.description, /No (invoices|records|rows) (yet|recorded)/i,
    "a filtered table must not claim there is nothing recorded");
});
