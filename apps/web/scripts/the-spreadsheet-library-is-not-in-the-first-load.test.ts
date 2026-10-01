// THE SPREADSHEET LIBRARY IS FETCHED WHEN SOMEBODY USES IT, NEVER WITH THE PAGE.
//   node --experimental-strip-types --test scripts/the-spreadsheet-library-is-not-in-the-first-load.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (frontend_ux-04)
// ─────────────────────────────────────────────────────────────────────────────
// `components/CsvImportModal.tsx` opened with `import * as XLSX from "xlsx"`,
// and ten screens import that modal — the client list, client Sales, Purchases
// and Payroll, onboarding, /tds, payroll people and attendance, the firm HSN
// library and the catalogue panel. SheetJS is 404 KB raw / ~135 KB gzip, so
// measured on the built export (`next build`, first-load scripts of each
// page's own HTML, the noModule polyfill excluded):
//
//     /clients                     434 KB gzip  (SheetJS chunk in the list)
//     /clients/_placeholder/sales  460 KB
//     /clients/_placeholder/purchases 455 KB
//     /login                       278 KB       (the same app, without it)
//
// — for a file picker most visits never open. Five more pages (the MSME
// tracker, the budget, Schedule III, the trend report, the AIS review) imported
// it at the top for an export button, which is the same cost on each of them.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE
// ─────────────────────────────────────────────────────────────────────────────
// 1. NOTHING under app/, components/ or lib/ imports `xlsx` STATICALLY. A type
//    import (`import type { WorkBook } from "xlsx"`) is erased at build time and
//    is fine; every runtime use is `await import("xlsx")` inside the handler
//    that needs it. `lib/export/xlsx.ts` already takes the module as a
//    PARAMETER for exactly this reason.
// 2. NO SCREEN IMPORTS THE IMPORT MODAL'S COMPONENT DIRECTLY. They take
//    `@/components/LazyCsvImportModal` — a `next/dynamic` door — and import the
//    TYPES (`ImportRow`, `ResolvedReference`, …) from the real module with
//    `import type`. One door, so a screen cannot opt back in by accident.
// 3. THE MODAL'S TWO HANDLERS FETCH THE LIBRARY THEMSELVES, before they touch
//    it, and a failed fetch is reported as a failed fetch — "could not read the
//    file" would send a CA to re-save a good workbook when the reader never
//    arrived.
//
// This is the RULE, not a spelling of the one import that was found: rule 1 is
// asked of every file in three trees with NO allowlist, so a sixth page that
// writes `import * as XLSX from "xlsx"` — or `import { read } from 'xlsx'`, or
// `import XLSX from "xlsx"`, or a bare `require("xlsx")` — fails here.
//
// This file does not build the site. Its measurement is recorded in the commit
// that introduced it; the thing that can be asserted cheaply and cannot flake
// is that the IMPORT GRAPH has no static edge, which is what put the chunk in
// the first load in the first place.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dirname, "..");
const ROOTS = ["app", "components", "lib"];

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(join(WEB, dir))) {
    if (entry === "node_modules" || entry === ".next") continue;
    const rel = join(dir, entry).replace(/\\/g, "/");
    if (statSync(join(WEB, rel)).isDirectory()) walk(rel, out);
    else if (rel.endsWith(".ts") || rel.endsWith(".tsx")) out.push(rel);
  }
  return out;
}
const FILES = ROOTS.flatMap((r) => walk(r));

function stripComments(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}
function code(rel: string): string {
  return stripComments(readFileSync(join(WEB, rel), "utf8"));
}

/** A specifier clause that is wholly type-only: `type X`, or `{ type A, type B }`.
 *  Both are erased, so neither puts a byte in the bundle. */
function isTypeOnlyClause(clause: string): boolean {
  const c = clause.trim();
  if (/^type\s/.test(c)) return true;
  const braces = /^\{([^}]*)\}$/.exec(c);
  if (!braces) return false;
  const items = braces[1].split(",").map((s) => s.trim()).filter(Boolean);
  return items.length > 0 && items.every((s) => /^type\s/.test(s));
}

/** Every STATIC runtime import of `module` in `src` — the clause text for each
 *  `import <clause> from "module"`, a bare `import "module"` (clause `""`), a
 *  `export … from "module"` and a `require("module")` (clause `"require"`).
 *  The clause alphabet excludes quotes and semicolons, so one match can never
 *  run on across two statements. */
function staticImportsOf(src: string, module: string): string[] {
  const m = module.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const found: string[] = [];
  const from = new RegExp(
    `\\b(?:import|export)\\s+([\\w*{}\\s,$]+?)\\s+from\\s*["']${m}["']`, "g");
  for (const hit of src.matchAll(from)) {
    if (!isTypeOnlyClause(hit[1])) found.push(hit[1].trim());
  }
  if (new RegExp(`\\bimport\\s*["']${m}["']`).test(src)) found.push("");
  if (new RegExp(`\\brequire\\(\\s*["']${m}["']\\s*\\)`).test(src)) found.push("require");
  return found;
}

// ── the detector has to detect, or every test below passes for ever ──────────

test("the detector catches each spelling of a static import", () => {
  for (const sample of [
    'import * as XLSX from "xlsx";',
    "import * as XLSX from 'xlsx';",
    'import XLSX from "xlsx";',
    'import { read, utils } from "xlsx";',
    'import XLSX, { read } from "xlsx";',
    'import "xlsx";',
    'const XLSX = require("xlsx");',
    'export * from "xlsx";',
    'import {\n  read,\n  utils,\n} from "xlsx";',
  ]) {
    assert.ok(staticImportsOf(sample, "xlsx").length > 0, `missed: ${sample}`);
  }
});

test("the detector leaves erased and lazy forms alone", () => {
  for (const sample of [
    'import type { WorkBook, WorkSheet } from "xlsx";',
    'import { type WorkBook } from "xlsx";',
    'import { type WorkBook, type WorkSheet } from "xlsx";',
    'const XLSX = await import("xlsx");',
    'let XLSX: typeof import("xlsx");',
    'import { foo } from "./xlsx";',
    'import { buildWorkbook } from "@/lib/export/xlsx";',
  ]) {
    assert.deepEqual(staticImportsOf(sample, "xlsx"), [], `flagged: ${sample}`);
  }
});

test("the detector does not run across two statements", () => {
  const two = 'import a from "a";\nimport b from "b";\nconst x = "xlsx";';
  assert.deepEqual(staticImportsOf(two, "xlsx"), []);
});

// ── rule 1 ───────────────────────────────────────────────────────────────────

test("nothing under app, components or lib imports xlsx statically", () => {
  const offenders = FILES.flatMap((f) =>
    staticImportsOf(code(f), "xlsx").map((c) => `${f}  (import ${c || "…"})`));
  assert.deepEqual(offenders, [],
    "a static import of xlsx puts SheetJS — 404 KB raw, ~135 KB gzip — in the " +
    "FIRST LOAD of the page that imports it, and of every page that imports a " +
    "component that does. Fetch it inside the handler that needs it: " +
    'const XLSX = await import("xlsx");  (the namespace object, never .default)\n  ' +
    offenders.join("\n  "));
});

test("the scan reads the tree it claims to, and the lazy imports are there", () => {
  // A floor, so a moved directory cannot turn the test above into a no-op, and
  // a check that the fix is what it says — the library IS still used, lazily,
  // in every place that used it.
  assert.ok(FILES.length > 400, `only ${FILES.length} source files scanned`);
  const lazy = FILES.filter((f) => /await\s+import\(\s*["']xlsx["']\s*\)/.test(code(f)));
  for (const expected of [
    "components/CsvImportModal.tsx",
    "app/accounting/msme-tracker/page.tsx",
    "app/accounting/budget/page.tsx",
    "app/accounting/schedule-iii/page.tsx",
    "app/clients/[id]/reports/trend/page.tsx",
    "app/income-tax/ais/page.tsx",
    "app/clients/[id]/accounting/page.tsx",
  ]) {
    assert.ok(lazy.includes(expected),
      `${expected} no longer fetches xlsx lazily (lazy importers: ${lazy.join(", ")})`);
  }
});

// ── rule 2 ───────────────────────────────────────────────────────────────────

const MODAL = "components/CsvImportModal.tsx";
const LAZY_DOOR = "components/LazyCsvImportModal.tsx";

test("no screen imports the import modal's component directly", () => {
  const offenders = FILES
    .filter((f) => f !== MODAL && f !== LAZY_DOOR)
    .flatMap((f) =>
      staticImportsOf(code(f), "@/components/CsvImportModal")
        .map((c) => `${f}  (import ${c})`));
  assert.deepEqual(offenders, [],
    "import the COMPONENT from @/components/LazyCsvImportModal (a next/dynamic " +
    "door) and only TYPES from @/components/CsvImportModal, with `import type`:\n  " +
    offenders.join("\n  "));
});

test("the ten importing screens all take the lazy door", () => {
  const users = FILES.filter((f) => f !== MODAL && f !== LAZY_DOOR
    && /<CsvImportModal[\s>]/.test(code(f)));
  assert.ok(users.length >= 10, `expected at least ten screens, found ${users.length}`);
  const missing = users.filter((f) =>
    !/import\s+CsvImportModal\s+from\s*["']@\/components\/LazyCsvImportModal["']/.test(code(f)));
  assert.deepEqual(missing, [],
    "a screen renders <CsvImportModal> without taking it from LazyCsvImportModal:\n  " +
    missing.join("\n  "));
});

test("the lazy door is next/dynamic, client-only", () => {
  const src = code(LAZY_DOOR);
  assert.match(src, /import\s+dynamic\s+from\s*["']next\/dynamic["']/);
  assert.match(src, /dynamic\(\s*\(\)\s*=>\s*import\(\s*["']@\/components\/CsvImportModal["']\s*\)/,
    "the door must import the modal lazily, by import()");
  assert.match(src, /ssr:\s*false/,
    "the modal reads window and FileReader; a static export has no server render to skip");
  assert.match(src, /loading:\s*\(\)\s*=>/,
    "the click that opens the modal has to visibly do something before its chunk arrives");
  assert.match(src, /export\s+default\s+LazyCsvImportModal/);
});

// ── rule 3 ───────────────────────────────────────────────────────────────────

function between(src: string, start: RegExp, end: RegExp): string {
  const a = src.search(start);
  assert.ok(a >= 0, `anchor not found: ${start}`);
  const rest = src.slice(a);
  const b = rest.slice(1).search(end);
  return b < 0 ? rest : rest.slice(0, b + 1);
}

test("the modal fetches xlsx in the template handler before it touches it", () => {
  const body = between(code(MODAL), /async\s+function\s+downloadTemplate\s*\(/, /\n\s*function\s+processText\s*\(/);
  const fetched = body.search(/await\s+import\(\s*["']xlsx["']\s*\)/);
  const used = body.search(/XLSX\.utils\./);
  assert.ok(fetched >= 0, "downloadTemplate does not fetch xlsx");
  assert.ok(used > fetched, "downloadTemplate uses XLSX before it has fetched it");
  assert.match(body, /setFileError\(XLSX_UNAVAILABLE\)/,
    "a failed fetch of the library must be reported, not swallowed");
});

test("the modal fetches xlsx once a workbook is CHOSEN, before it reads it", () => {
  const body = between(code(MODAL), /function\s+handleFile\s*\(/, /\n\s*async\s+function\s+handleImport\s*\(/);
  assert.match(body, /reader\.onload\s*=\s*async\s*\(/,
    "onload must be async to await the library");
  const fetched = body.search(/await\s+import\(\s*["']xlsx["']\s*\)/);
  const used = body.search(/XLSX\.read\(/);
  assert.ok(fetched >= 0, "handleFile does not fetch xlsx");
  assert.ok(used > fetched, "handleFile reads the workbook before it has fetched the reader");
  // The library must be asked for ONLY on the workbook branch: a CSV has to
  // parse without it, offline included.
  const branchStart = body.search(/if\s*\(\s*isXlsx\s*\)\s*\{/);
  assert.ok(branchStart >= 0 && fetched > branchStart,
    "xlsx is fetched outside the `if (isXlsx)` branch, so a CSV would wait for it too");
  assert.match(body, /setFileError\(XLSX_UNAVAILABLE\)/);
});

test("a failed fetch is worded as itself and points at the CSV", () => {
  const src = readFileSync(join(WEB, MODAL), "utf8");
  const m = /const\s+XLSX_UNAVAILABLE\s*=\s*\n?\s*"([^"]+)"/.exec(src);
  assert.ok(m, "XLSX_UNAVAILABLE is not declared");
  assert.match(m![1], /Could not load the Excel reader/);
  assert.match(m![1], /CSV/, "the CSV path works offline and the message must say so");
  assert.doesNotMatch(m![1], /Could not read the file/,
    "that is the message for a bad FILE, which this is not");
});
