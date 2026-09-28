// The "Mark as Filed" confirmation on /deadlines opens as a centred dialog
// next to wherever the CA clicked, instead of a static card pinned above the
// table.
//
// Run with:
//   node --experimental-strip-types --test scripts/mark-filed-opens-where-the-click-happened.test.ts
//
// WHAT WAS WRONG (sweep-home-and-global-nav-06)
//     app/deadlines/page.tsx rendered the "Mark as Filed" confirmation as a
//     plain <Card> above ExpiringEwayBills and the DataTable. The row button
//     only called setMarkFiled(...) — no scroll, no focus move, no dialog —
//     so on a table of 33+ rows the panel opened off-screen above whatever
//     row the CA had just clicked, which read as nothing happening.
//
// THE FIX
//     The same confirmation now renders inside the shared
//     components/ui/modal.tsx Modal, which centres itself over the viewport,
//     traps focus and closes on Escape regardless of where in the table the
//     row sits — so clicking "Mark Filed" on row 30 looks the same as
//     clicking it on row 1.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

const PAGE = "app/deadlines/page.tsx";

test("the deadlines page imports the shared Modal", () => {
  const src = read(PAGE);
  assert.match(src, /import\s*\{\s*Modal\s*\}\s*from\s*"@\/components\/ui\/modal"/);
});

test("Mark as Filed renders through the shared Modal, not a static Card", () => {
  const src = read(PAGE);
  assert.match(src, /<Modal\s+title="Mark as Filed"\s+onClose=\{\(\)\s*=>\s*setMarkFiled\(null\)\}/);
});

test("the old top-of-page Card confirmation is gone", () => {
  const src = read(PAGE);
  assert.doesNotMatch(src, /<Card className="border-blue-200 bg-blue-50">/);
});
