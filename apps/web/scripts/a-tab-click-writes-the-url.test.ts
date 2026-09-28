// Clicking a Sales sub-tab writes ?tab= into the URL, so a refresh keeps the
// CA's place instead of always landing back on the default tab.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-tab-click-writes-the-url.test.ts
//
// WHAT WAS WRONG (sweep-client-overview-sales-03)
//     app/clients/[id]/sales/page.tsx already reads ?tab= on mount (and on
//     every URL change, via useSearchParams — for the ACC-22 ledger
//     drill-through), but a manual tab click was `onClick={() => setTab(t.id)}`
//     — state only. A reload always landed back on the default tab.
//
// THE FIX
//     selectTab() writes ?tab=<id> into the URL with the same
//     window.history.replaceState pattern navigateTo() already uses for
//     ?cust= (this page is a static export, so a real navigation would be a
//     full reload rather than a state change), preserving other params, and
//     then sets the state as before. "invoices" is the page's own initial
//     state, so it is left off the URL rather than written as
//     ?tab=invoices — the mount effect already falls back to it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8");
}

const RAW = read("app/clients/[id]/sales/page.tsx");
const SRC = stripComments(RAW);

test("the tab bar's onClick calls selectTab, not a bare setTab", () => {
  assert.match(SRC, /onClick=\{\(\) => selectTab\(t\.id\)\}/);
});

test("selectTab writes ?tab= into the URL via history.replaceState, preserving other params", () => {
  const m = /function selectTab\(target: SalesTab\) \{([\s\S]*?)\n  \}/.exec(SRC);
  assert.ok(m, "selectTab not found");
  const body = m[1];
  assert.match(body, /new URLSearchParams\(window\.location\.search\)/);
  assert.match(body, /window\.history\.replaceState/);
  assert.match(body, /setTab\(target\)/);
});

test("the default tab (invoices) is left off the URL rather than written as ?tab=invoices", () => {
  const m = /function selectTab\(target: SalesTab\) \{([\s\S]*?)\n  \}/.exec(SRC);
  assert.ok(m);
  assert.match(m[1], /if \(target === "invoices"\) p\.delete\("tab"\)/);
});
