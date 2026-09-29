// The client GST tab's GSTR-3B list and its QRMP PMT-06 card, checked
// against the source of app/clients/[id]/compliance/gst/page.tsx.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-gstr3b-list-and-pmt06-card-tell-the-truth.test.ts
//
// THREE THINGS FIXED TOGETHER, because they are all defects of the same
// screen and none needed its own file:
//
// (1) THE GSTR-3B LIST HAD NO GSTIN COLUMN, unlike the GSTR-1 list right
//     above it — so once GST-20 let a client hold several registrations, the
//     GSTR-3B table gave no way to tell which return belonged to which
//     GSTIN. It reads the same `gstin` field `gstr3b_returns` already
//     carries (migration 234).
//
// (2) `Period {data.currentPeriod}` rendered the raw MMYYYY string
//     ("092026") instead of a formatted period, on a dashboard everywhere
//     else format dates for a human — `gstPeriodLabel` already existed
//     ("September 2026") and was reused rather than a second formatter
//     invented.
//
// (3) THE PMT-06 CARD WAS ALARM-RED WHATEVER IT SAID. "Not due — this
//     month's tax is paid with the quarterly return" — an entirely routine
//     QRMP month — rendered on `bg-state-problem-surface`, the same tint a
//     genuinely overdue challan gets. The tint is now conditional on
//     `data.pmt06Due` actually being set.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/compliance/gst/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the GSTR-3B table has its own GSTIN column", () => {
  const src = code(PAGE);
  // NEGATIVE CONTROL: before the fix there was exactly one `<th ...>GSTIN` in
  // this file (the GSTR-1 tab's), so this count must be at least two.
  const gstinHeaders = (src.match(/<th className="px-3 py-2 border-b">GSTIN<\/th>/g) ?? []).length;
  assert.ok(gstinHeaders >= 2,
    `expected the GSTR-1 AND GSTR-3B tables to both header a GSTIN column, found ${gstinHeaders}`);
  assert.match(src, /<td className="px-3 py-2 text-xs">\{r\.gstin as string\}<\/td>/,
    "and a row must actually render the return's own gstin, not just the header");
});

test("the QRMP dashboard's current period is a formatted month, not raw MMYYYY", () => {
  const src = code(PAGE);
  assert.match(src, /gstPeriodLabel\(data\.currentPeriod\)/,
    "the existing MMYYYY -> 'Month YYYY' formatter must be reused, not a raw string rendered");
});

test("the PMT-06 card is only alarm-red when a PMT-06 is genuinely due", () => {
  const src = code(PAGE);
  // NEGATIVE CONTROL: the old code was the literal class string with no
  // conditional at all — `className="rounded border p-4 bg-state-problem-surface"`
  // unconditionally. That literal must be gone from this card.
  assert.doesNotMatch(src,
    /<div className="rounded border p-4 bg-state-problem-surface">\s*<p className="text-xs text-ps-label">PMT-06/,
    "the alarm tint must not be hardcoded on the PMT-06 card any more");
  assert.match(src, /\$\{data\.pmt06Due \? "bg-state-problem-surface" : ""\}/,
    "the tint must be conditional on data.pmt06Due");
});
