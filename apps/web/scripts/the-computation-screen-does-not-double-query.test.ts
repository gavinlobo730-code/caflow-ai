// app/clients/[id]/tax/computation/page.tsx's load() no longer fires with an
// empty or invalid FY filter before the real financial year has resolved.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-computation-screen-does-not-double-query.test.ts
//
// WHAT WAS WRONG
//     `fy` starts at "" and is only set once GET /api/income-tax/financial-
//     years resolves. `load` is a useCallback closing over `fy`, and the
//     effect that calls it depends on `[load]` — so on every mount the
//     screen ran `load()` once with `financial_year=eq.` (an empty, invalid
//     filter) and then ran it AGAIN the instant the real FY resolved and
//     `load`'s identity changed. Every page open cost two round trips to
//     Supabase for the first.
//
// THE FIX
//     load() now returns immediately, before touching Supabase at all, while
//     clientId is unset/the SSG placeholder or fy is still empty.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE = "app/clients/[id]/tax/computation/page.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("load() refuses to run before clientId and fy are both real", () => {
  const src = code(PAGE);
  assert.match(src,
    /const load = useCallback\(async \(\) => \{\s*if \(!clientId \|\| clientId === "_placeholder" \|\| !fy\) return;/,
    "the guard must be the FIRST thing load() does, before any Supabase call");
});
