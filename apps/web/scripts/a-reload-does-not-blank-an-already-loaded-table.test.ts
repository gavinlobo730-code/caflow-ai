// The GSTR-1 and GSTR-3B returns tables keep their rows visible while a
// background reload (after Save Draft, Validate, CA Approve, …) is in
// flight, instead of swapping the whole table out for a skeleton.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-reload-does-not-blank-an-already-loaded-table.test.ts
//
// WHAT WAS WRONG (sweep-client-tax-compliance-10)
//     GSTR1Tab.load() and GSTR3BTab.load() both call setLoading(true) on
//     EVERY reload, not only the first, and the render was a plain
//     `loading ? <TableSkeleton …/> : <table>…` — so the existing header and
//     rows disappeared for the duration of every refetch, including the one
//     that follows Save Draft / Validate on a return the CA is already
//     looking at.
//
// THE FIX
//     The skeleton now shows only while there is nothing loaded yet
//     (`loading && returns.length === 0`); once a return exists, a later
//     reload keeps the table on screen and swaps its rows in place when the
//     refetch resolves.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the GSTR-1 tab only shows the skeleton on the first load", () => {
  const src = read("app/clients/[id]/compliance/gst/page.tsx");
  assert.match(src, /\{loading && returns\.length === 0 \? <TableSkeleton cols=\{5\} bare \/> : \(/);
});

test("the GSTR-3B tab only shows the skeleton on the first load", () => {
  const src = read("app/clients/[id]/compliance/gst/page.tsx");
  assert.match(src, /\{loading && returns\.length === 0 \? <TableSkeleton cols=\{6\} bare \/> : \(/);
});

test("neither tab swaps the whole table out on every reload any more", () => {
  const src = read("app/clients/[id]/compliance/gst/page.tsx");
  assert.doesNotMatch(src, /\{loading \? <TableSkeleton/);
});
