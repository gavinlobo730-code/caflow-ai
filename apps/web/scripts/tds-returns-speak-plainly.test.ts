// The client TDS tab's Returns and Challans lists, checked against the
// source of app/clients/[id]/compliance/tds/page.tsx.
//
// Run with:
//   node --experimental-strip-types --test scripts/tds-returns-speak-plainly.test.ts
//
// TWO THINGS FIXED, both readability of a raw stored value rather than any
// figure changing:
//
// (1) THE RETURNS TABLE RENDERED THE STORED ROUTING KEY (`return_type`,
//     e.g. "26Q") RATHER THAN THE ACT'S OWN FORM NUMBER FOR THE PERIOD.
//     tds_workspace.py's `list_returns` already computes `statement_form`
//     via `domain/tds/vocabulary.statement_form` (so a FY2026-27+ 26Q reads
//     "Form 140 (26Q)" under the Income-tax Act 2025 renumbering, per
//     TDS-17) but the response never carried it and the screen never asked
//     — a CA filing a post-01-04-2026 quarter saw the pre-fork label. The
//     screen now prefers `statement_form` and falls back to the raw key
//     only for a row saved before this field existed on the response.
//
// (2) BOTH TABLES BADGED THE RAW STATUS STRING ("ca_approved", "prepared")
//     rather than a readable label, unlike every other status badge on this
//     product's compliance screens.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/compliance/tds/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the Returns table prefers the Act-translated statement_form over the raw routing key", () => {
  const src = code(PAGE);
  assert.match(src, /\(r\.statement_form as string\) \?\? \(r\.return_type as string\)/,
    "statement_form must be read first, with return_type only as the fallback " +
    "for a row saved before the field existed");
  // NEGATIVE CONTROL: the old code rendered return_type alone, unconditionally.
  assert.doesNotMatch(src,
    /<td className="px-3 py-2 font-medium">\{r\.return_type as string\}<\/td>/,
    "the raw routing key must no longer be rendered on its own");
});

test("both the Returns and Challans tables badge a readable status label", () => {
  const src = code(PAGE);
  assert.match(src, /const STATUS_LABEL: Record<string, string> = \{/,
    "a label map must exist");
  assert.match(src, /ca_approved: "CA Approved"/, "and it must translate the raw enum values");
  const usages = (src.match(/STATUS_LABEL\[r\.status as string\] \?\? \(r\.status as string\)/g) ?? []).length;
  assert.equal(usages, 2,
    "both the challans tab and the returns tab must render through the label map " +
    `(found ${usages} — the old code rendered {r.status as string} bare in both places)`);
});
