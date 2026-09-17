// ACC-22 — the drill-through reaches the CA.
//
// The backend half is held in apps/api (builders.ledger, migration 400, the
// SQL/Python parity proof, and the guard that pins this vocabulary from the
// Python side). This file holds the part only the browser can be wrong about:
// that the ledger row is actually wired to the route map, and that every
// screen a source routes to can receive the deep link.
//
// RESOLVED BY WHAT THEY SAY, NOT BY A PATH. Three guards in this directory
// have already broken on a move that did not break their rule; panelSource
// finds the one file containing a phrase and asserts there is exactly one.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-ledger-row-opens-its-document.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";
import { panelSource } from "./panelSource.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const ledger = stripComments(panelSource('key: "source", header: "Source"'));
const table = stripComments(fs.readFileSync(path.join(WEB, "components", "ui", "data-table.tsx"), "utf8"));
const map = stripComments(fs.readFileSync(path.join(WEB, "lib", "accounting", "sourceDocument.ts"), "utf8"));

test("the ledger row opens the document, through the one route map", () => {
  assert.match(ledger, /documentTarget\(clientId, l\)/,
    "the ledger must ask lib/accounting/sourceDocument where the row goes");
  assert.match(ledger, /onRowClick=\{\(l\) => \{/);
  assert.match(ledger, /router\.push\(target\.href\)/);
});

test("a row with no document is not clickable and says why", () => {
  // A row that shows a pointer and then does nothing is worse than an inert
  // one: a real ledger is full of entries posted before their path stamped a
  // source, and the Source cell carries the reason on hover.
  assert.match(ledger, /rowClickable=\{\(l\) => documentTarget\(clientId, l\) !== null\}/);
  assert.match(ledger, /noRouteReason\(l\)/);
  assert.match(table, /const clickable = Boolean\(onRowClick\) && \(rowClickable\?\.\(row\) \?\? true\)/,
    "DataTable must decide the pointer per row, not per table");
});

test("the ledger does not compute the label or the route itself", () => {
  // The vocabulary is journal_source.ALL_SOURCES and the route map is one
  // file; a second copy in the page is out of step the first time a source is
  // added — which is what the Schedule III caption list did for months.
  assert.doesNotMatch(ledger, /"sales_invoice"|"purchase_bill"|"bank_transaction"/,
    "a source_type spelled in the page is a second route map");
});

test("one deep-link convention, not one param per document kind", () => {
  assert.match(map, /\?tab=\$\{encodeURIComponent\(tab\)\}&doc=\$\{encodeURIComponent\(docId\)\}/);
  // `?invoice=` predates this and still opens the Sales drawer; it must not
  // grow siblings.
  for (const stray of ["?bill=", "?run=", "?asset=", "?note=", "?payment="]) {
    assert.ok(!map.includes(stray), `${stray} is a second deep-link vocabulary`);
  }
});

test("every screen a source routes to reads the deep link", () => {
  // Derived from the map, not listed: a module added to ROUTES without a
  // screen that honours ?tab=&doc= would land the CA on the wrong tab with
  // nothing ringed, silently.
  const modules = [...map.matchAll(/module:\s*"([a-z-]+)"/g)].map((m) => m[1]);
  assert.ok(modules.length >= 15, `only ${modules.length} routes parsed — the regex has drifted`);
  for (const mod of new Set(modules)) {
    const page = fs.readFileSync(
      path.join(WEB, "app", "clients", "[id]", mod, "page.tsx"), "utf8");
    assert.match(page, /openedAt\(window\.location\.search\)/,
      `/clients/[id]/${mod} does not read the ?tab=&doc= deep link`);
    assert.match(page, /TABS\.some\(\(x\) => x\.id === t\)/,
      `/clients/[id]/${mod} trusts the tab in the URL instead of validating it ` +
      "against its own TABS");
  }
});

test("the highlight is one mechanism and never changes what the reader sees", () => {
  assert.match(table, /highlightRowId\?: string \| null;/);
  assert.match(table, /highlightRef\.current\?\.scrollIntoView/);
  // Keyed on the id, so sorting or paging does not yank the scroll back.
  assert.match(table, /\}, \[highlightRowId\]\);/);
  // No filter is cleared and no page is forced: a deep link must not silently
  // change what the reader is looking at.
  assert.doesNotMatch(table, /setPage\(0\)[\s\S]{0,80}highlightRowId/);
});
