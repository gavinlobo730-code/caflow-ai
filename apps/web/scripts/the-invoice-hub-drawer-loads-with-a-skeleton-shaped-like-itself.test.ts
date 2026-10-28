// The Invoice Hub drawer's loading state looked like neither the drawer nor anything else: a generic six-field form skeleton above a
// generic seven-column table (POST-A-150, the density audit's F2 residue). Create and Edit already used skeletons shaped like their
// own pages (InvoiceEditorSkeleton, SummaryPanelSkeleton); the Hub was the one left. Run with:
//   node --experimental-strip-types --test scripts/the-invoice-hub-drawer-loads-with-a-skeleton-shaped-like-itself.test.ts
//
// WHAT IS HELD
//     * the drawer's loading branch renders `InvoiceHubSkeleton` and nothing generic;
//     * the skeleton announces itself (role="status" with a label) so a screen reader hears that the invoice is loading;
//     * it carries the sections the loaded drawer has, in the order it has them: the header and total, the status chips, the detail
//       rows, the action bar, the line items and the accounting rows. The sections are counted from the loaded drawer's own markers,
//       so a section added to the drawer without a skeleton for it fails here and is not found by a reader a year later.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const read = (f: string) => fs.readFileSync(path.join(ROOT, f), "utf8");
const strip = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");

const DRAWER = strip(read("components/invoices/InvoiceViewDrawer.tsx"));
const SKELETON_SRC = read("components/invoices/InvoiceEditorSkeleton.tsx");
const SKELETON = strip(SKELETON_SRC);

test("the drawer's loading branch is the Hub skeleton, not a generic form and table", () => {
  assert.match(DRAWER, /loading\s*\?\s*\(\s*<InvoiceHubSkeleton\s*\/>/, "the loading branch no longer renders InvoiceHubSkeleton");
  assert.doesNotMatch(DRAWER, /\bFormSkeleton\b|\bTableSkeleton\b/, "a generic skeleton is back in the drawer");
});

test("the Hub skeleton announces itself to assistive technology", () => {
  const body = SKELETON.slice(SKELETON.indexOf("export function InvoiceHubSkeleton"));
  assert.match(body, /role="status"\s+aria-label="Loading invoice"/);
});

test("the skeleton has a stand-in for every section the loaded drawer opens with", () => {
  // The loaded drawer's sections, by the headings and groups it renders. Each pair is [what the drawer renders, what the skeleton must
  // have to stand in for it].
  const sections: Array<[RegExp, RegExp, string]> = [
    [/Grand total/, /items-start justify-between/, "customer and grand total"],
    [/Three independent status groups/, /rounded-full/, "status chips"],
    [/grid grid-cols-2 gap-x-4/, /grid grid-cols-2 gap-x-4/, "the detail rows"],
    [/Action bar/, /flex flex-wrap gap-2/, "the action bar"],
    [/Line items/, /LineRowSkeleton/, "the line items"],
    [/Accounting/, /h-3 w-24/, "the accounting rows"],
  ];
  const drawerRaw = read("components/invoices/InvoiceViewDrawer.tsx");
  const hub = SKELETON.slice(SKELETON.indexOf("export function InvoiceHubSkeleton"));
  for (const [drawerMark, skeletonMark, what] of sections) {
    assert.match(drawerRaw, drawerMark, `the drawer no longer has ${what}: this test's map of it is stale`);
    assert.match(hub, skeletonMark, `the Hub skeleton has no stand-in for ${what}`);
  }
});
