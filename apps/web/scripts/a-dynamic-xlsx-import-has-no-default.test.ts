// xlsx 0.18.5 resolves through its "module" entry (xlsx.mjs), which has no
// default export — so `(await import("xlsx")).default` is `undefined`.
//   node --experimental-strip-types --test scripts/a-dynamic-xlsx-import-has-no-default.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// `app/clients/[id]/accounting/page.tsx`'s `exportXLSX` and `shareToPortal`
// both wrote:
//
//     const XLSX = (await import("xlsx")).default;
//
// Webpack resolves the `xlsx` package through its `package.json` "module"
// field to `xlsx.mjs`, a real ES module with no `export default` — so
// `XLSX` was `undefined`. `buildWorkbook(XLSX, ...)` (lib/export/xlsx.ts)
// then read `XLSX.utils` and threw, and both call sites caught that into
// `alert(e.message)`, so every XLSX export button and the Share (P&L) button
// on that screen failed with "Cannot read properties of undefined (reading
// 'utils')" — no file downloaded, no request sent.
//
// `esModuleInterop` is exactly why neither `tsc` nor the Next.js build caught
// it: TypeScript SYNTHESISES a `.default` on any type-only `import("xlsx")`
// whether or not the runtime module actually has one, so the code type-checks
// and builds cleanly while being dead at the one moment it runs.
// `app/clients/[id]/reports/trend/page.tsx` never hit this because it uses a
// static `import * as XLSX from "xlsx"`, which resolves the SAME `xlsx.mjs`
// but as a namespace object — the shape `buildWorkbook` actually declares
// its parameter as (`typeof import("xlsx")`).
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE
// ─────────────────────────────────────────────────────────────────────────────
// A dynamic import of `xlsx` is the namespace object, never `.default`:
//
//     const XLSX = await import("xlsx");
//
// never
//
//     const XLSX = (await import("xlsx")).default;
//
// This is the RULE, not a spelling of the one call site that broke — the
// pattern is checked wherever it could recur (`app`, `components`, `lib`),
// not just at the two lines that were wrong, so a third call site cannot
// silently reintroduce this exact defect class.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const ROOTS = ["app", "components", "lib"];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(join(WEB, dir))) {
    if (entry === "node_modules" || entry === ".next") continue;
    const rel = join(dir, entry);
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".ts") || rel.endsWith(".tsx")) out.push(rel);
  }
  return out;
}
const FILES = ROOTS.flatMap((r) => walk(r));

function code(rel: string): string {
  return readFileSync(join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

// Matches `(await import("xlsx")).default` and `(await import('xlsx')).default`
// with any whitespace, so reformatting cannot slip it past the guard.
const DOT_DEFAULTED_XLSX_IMPORT =
  /\(\s*await\s+import\(\s*["']xlsx["']\s*\)\s*\)\s*\.\s*default/;

test("no dynamic import of xlsx reads .default", () => {
  const offenders = FILES.filter((f) => DOT_DEFAULTED_XLSX_IMPORT.test(code(f)));
  assert.deepEqual(offenders, [],
    "xlsx resolves through its \"module\" entry (xlsx.mjs), which has no " +
    "default export, so `(await import(\"xlsx\")).default` is `undefined` " +
    "and every call into it throws at runtime with esModuleInterop hiding " +
    "the mistake from tsc. Use `const XLSX = await import(\"xlsx\");` " +
    "(the namespace object, matching buildWorkbook's `typeof import(\"xlsx\")` " +
    "parameter) instead:\n  " + offenders.join("\n  "));
});

test("the accounting screen's two xlsx exports use the namespace import", () => {
  // THE BEHAVIOUR, not just the absence of the bad pattern: assert the actual
  // fixed call sites are present, so a future edit that removes the import
  // entirely (rather than fixing it) still fails a test.
  const rel = join("app", "clients", "[id]", "accounting", "page.tsx");
  const src = readFileSync(join(WEB, rel), "utf8");
  const matches = src.match(/const XLSX = await import\(["']xlsx["']\);/g) ?? [];
  assert.equal(matches.length, 2,
    "expected exportXLSX and shareToPortal to each import xlsx as a namespace " +
    `object; found ${matches.length} such import(s) in ${rel}`);
});
