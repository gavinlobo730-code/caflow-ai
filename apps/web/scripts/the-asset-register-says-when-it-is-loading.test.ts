// Fixed Assets > Asset Register showed "0 assets, Gross Block ₹0" on every
// navigation to the tab, indistinguishable from a client that genuinely has
// none, for however long the fetch took. Run with:
//   node --experimental-strip-types --test scripts/the-asset-register-says-when-it-is-loading.test.ts
//
// WHY THIS EXISTS
//     `assets` starts at `[]` (its useState default) before the load effect's
//     fetch resolves. The table itself already had a loading branch
//     (`loading ? <TableSkeleton .../> : ...`), but the three summary tiles
//     above it (Gross Block, Accumulated Depreciation, Net Block) and the "N
//     assets" count line computed straight off `assets` with no `loading`
//     check at all — only `loadFailed`, which is false while a load is still
//     in flight. So a client with real assets flashed a confidently wrong
//     "0 assets / ₹0" on every mount, with nothing distinguishing it from a
//     register that is actually empty. The convention already used
//     elsewhere in this same file (DisposalTab's own tiles, line ~2048) and
//     across the app (tds/page.tsx, mca/page.tsx, accounting/loans/page.tsx)
//     is `loading ? "…" : value` — checked BEFORE the value is computed, not
//     folded into (or displaced by) the failure check.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE_FILE = "app/clients/[id]/fixed-assets/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE_FILE), "utf8");
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

function componentBody(name: string): string {
  const start = code.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `could not find function ${name}`);
  let parenDepth = 0, i = start;
  for (; i < code.length; i++) {
    if (code[i] === "(") parenDepth++;
    else if (code[i] === ")" && --parenDepth === 0) { i++; break; }
  }
  const braceStart = code.indexOf("{", i);
  let depth = 0;
  for (i = braceStart; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") {
      depth--;
      if (depth === 0) return code.slice(braceStart, i + 1);
    }
  }
  throw new Error(`unterminated body for ${name}`);
}

const registerTab = componentBody("RegisterTab");

test("RegisterTab's summary tiles check `loading` before computing a value", () => {
  const labels = ["Gross Block", "Accumulated Depreciation", "Net Block \\(WDV\\)"];
  for (const label of labels) {
    const re = new RegExp(
      `label:\\s*"${label}"\\s*,\\s*value:\\s*loading\\s*\\?`);
    assert.match(registerTab, re,
      `the "${label.replace(/\\/g, "")}" tile must read \`loading\` first — ` +
      "reading only loadFailed leaves an in-flight load rendering its " +
      "not-yet-arrived data as if the register were empty");
  }
});

test("the asset count line distinguishes loading from a genuinely empty register", () => {
  assert.match(registerTab, /loading\s*\?\s*"Loading…"\s*:\s*`\$\{assets\.length\}/,
    "the \"N assets\" line must say it is loading, not read `assets.length` " +
    "(0, before the fetch resolves) as the real count");
});
