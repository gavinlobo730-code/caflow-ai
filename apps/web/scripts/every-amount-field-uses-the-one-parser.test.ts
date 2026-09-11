// Every rupee amount a CA types goes through lib/money/rupeeInput.ts. Run with:
//   node --experimental-strip-types --test scripts/every-amount-field-uses-the-one-parser.test.ts
//
// WHY THIS EXISTS, AND WHY IT LOOKS LIKE THIS NOW
//     CLAUDE.md said "All 61 call sites across 28 files are converted... there
//     is no longer a second way", and nothing checked it. Nine live second ways
//     were found on 2026-09-08, so the prose was replaced by three regexes:
//
//         /rsToP\s*\(\s*parseFloat/
//         /Math\.round\s*\(\s*parseFloat/
//         /parseFloat\s*\([^)]*\)\s*\*\s*100\b/
//
//     …and the same claim was re-made on top of them. Running those three over
//     the tree the next day found SIXTEEN more files of the same defect class
//     that none of them matched, because none of them is the rule. They each
//     name one SPELLING:
//
//         parseInt(s.replace(/[^0-9]/g, ""), 10) * 100   // "1234.56" -> ₹1,23,456
//         Math.round(Number(cleaned) * 100)              // "1e3"     -> ₹1,000
//         Number(whole) * 100 + Number(frac)             // "1.2.3"   -> ₹1.02
//
//     So the check is now the RULE, in two directions:
//
//       1. POSITIVE — nothing that produces paise or basis points may contain a
//          numeric coercion or a multiplication by 100. Whatever the spelling,
//          the value has to arrive from somewhere else, and the only somewhere
//          else in this codebase is lib/money/rupeeInput.ts.
//       2. NAMED   — a function whose own name says it makes paise or bps out
//          of text must delegate to that module, by name.
//
//     The three original regexes are kept as a third test. They are subsumed by
//     the first, and they cost nothing, and each of them is a bug that shipped.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");

/** Source with comments stripped — the assertions are about CODE, and the
 *  notes left behind quote the very forms they replaced. */
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\/\/.*$/gm, "");
}

/** Every .ts/.tsx under apps/web, excluding node_modules, .next and the
 *  scripts/ directory (these tests quote the forms they forbid). */
function sources(): string[] {
  const out: string[] = [];
  const skip = new Set(["node_modules", ".next", "out", "scripts", ".turbo"]);
  (function walk(dir: string) {
    for (const e of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = path.join(dir, e.name);
      if (e.isDirectory()) { if (!skip.has(e.name)) walk(rel); continue; }
      if (e.name.endsWith(".ts") || e.name.endsWith(".tsx")) out.push(rel);
    }
  })(".");
  return out.map((p) => p.replace(/^\.\//, "")).filter((p) => !p.endsWith(".test.ts") && !p.endsWith(".test.tsx"));
}

// The three deliberate exceptions CLAUDE.md records, all in one place: the
// purchase-note previews pass the RATE string to gstLine.ratePaiseFromRupees,
// which shared/gst-parity-vectors.json pins to the Python backend on exactly
// those strings — including "1.005", which the backend truncates to 100 paise
// and which the exact parser refuses. Converting to paise and dividing back
// would put a float round-trip inside the one calculation that is pinned.
// What protects them is upstream: parseLineAmounts has already refused
// anything but a plain decimal by the time parseFloat sees it.
const PINNED_TO_THE_BACKEND = new Set([
  "lib/money/gstLine.ts",
  "lib/purchases/billEditor.ts",
  "lib/purchases/debitNoteEditor.ts",
  "lib/purchases/purchaseCreditNoteEditor.ts",
]);

// A literal times a literal is exact and is not a conversion: these are the
// statutory ceilings written the way the Act states them (₹1,50,000) next to
// the paise the app holds them in. Nothing is parsed.
const LITERAL_LIMIT = /^\s*[\d_]+\s*\*\s*100\s*$/;

/**
 * The value expression a `…_paise`/`…Paise`/`…_bps`/`…Bps` name is given —
 * from the `:` or `=` to the comma or semicolon that ends it, tracking bracket
 * depth so a nested call's own commas do not cut it short.
 */
function valueRegion(src: string, from: number): string {
  let depth = 0;
  for (let i = from; i < src.length && i - from < 600; i++) {
    const c = src[i];
    if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") { if (depth === 0) return src.slice(from, i); depth--; }
    else if (depth === 0 && (c === "," || c === ";")) return src.slice(from, i);
  }
  return src.slice(from, Math.min(src.length, from + 600));
}

const NAMES_PAISE = /\b([A-Za-z_$][\w$]*(?:_paise|Paise|_bps|Bps))\s*\??\s*[:=](?![=>])/g;
const COERCIONS: [RegExp, string][] = [
  [/\bparseFloat\s*\(/, "parseFloat"],
  [/\bparseInt\s*\(/, "parseInt"],
  [/\bNumber\s*\(/, "Number()"],
  [/\*\s*100\b/, "* 100"],
];

/**
 * `Number(row.tds_paise ?? 0)` is a CAST, not a conversion: the value is
 * already in the unit the name says, and PostgREST hands a bigint back as a
 * string. What makes it safe is that the SOURCE carries the unit in its own
 * name — so this allows exactly that and nothing else. A conversion has a
 * rupee or a percent on the right-hand side, and that never reads as _paise.
 */
const ALREADY_IN_THE_UNIT = /(?:_paise|Paise|_bps|Bps)\b/;
function isCastOfSameUnit(region: string): boolean {
  const args = region.match(/(?:parseFloat|parseInt|Number)\s*\(([^()]*)\)/g) ?? [];
  return args.length > 0 && args.every((a) => ALREADY_IN_THE_UNIT.test(a));
}

test("nothing that produces paise or basis points coerces or multiplies by 100", () => {
  // THE RULE, not a spelling of it. Every one of the sixteen files found on
  // 2026-09-08 is caught here and none of them was caught by the three regexes
  // this replaced.
  const offenders: string[] = [];
  for (const f of sources()) {
    if (PINNED_TO_THE_BACKEND.has(f)) continue;
    const src = code(f);
    NAMES_PAISE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = NAMES_PAISE.exec(src)) !== null) {
      const region = valueRegion(src, m.index + m[0].length);
      if (LITERAL_LIMIT.test(region)) continue;
      if (!/\*\s*100\b/.test(region) && isCastOfSameUnit(region)) continue;
      for (const [re, what] of COERCIONS) {
        if (re.test(region)) {
          const line = src.slice(0, m.index).split("\n").length;
          offenders.push(`${f}:${line} — ${m[1]} is built with ${what}:${region.replace(/\s+/g, " ").trim().slice(0, 90)}`);
          break;
        }
      }
    }
  }
  assert.deepEqual(offenders, [],
    "build paise with paiseFromRupeeInput (or bpsFromPercentInput / parseQuantity) from lib/money/rupeeInput.ts — they refuse text that is not an amount instead of reading \"1,25,000\" as 1 and \"1234.56\" as ₹1,23,456");
});

test("a function whose name says it makes paise from text delegates to the one parser", () => {
  // The second direction. rupeesToPaise, rsToPaise, parsePaise, toPaise,
  // fieldPaise — five names for one job, in five files, each with its own
  // arithmetic. They may keep their names; they may not keep their arithmetic.
  const MAKER = /\bfunction\s+([A-Za-z_$][\w$]*(?:[Pp]aise|[Bb]ps))\s*\(([^)]*)\)/g;
  const offenders: string[] = [];
  for (const f of sources()) {
    if (PINNED_TO_THE_BACKEND.has(f)) continue;
    const src = code(f);
    MAKER.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = MAKER.exec(src)) !== null) {
      // Only the ones that take text. paiseToRupees(n: number) is the other way.
      if (!/:\s*string/.test(m[2]) && !/string\s*\|/.test(m[2])) continue;
      const body = valueRegion(src, src.indexOf("{", m.index + m[0].length));
      // Only the ones that PARSE. calculateFDMaturityPaise(principalPaise:
      // number, …, startDate: string) takes a string and reads no amount out
      // of it, so there is nothing for it to delegate.
      if (!COERCIONS.some(([re]) => re.test(body))) continue;
      if (!/paiseFromRupeeInput|bpsFromPercentInput|parseQuantity|rsToP\b/.test(body)) {
        const line = src.slice(0, m.index).split("\n").length;
        offenders.push(`${f}:${line} — ${m[1]}() reads text into paise without the one parser`);
      }
    }
  }
  assert.deepEqual(offenders, [],
    "delegate to lib/money/rupeeInput.ts rather than writing a fifth rupee parser");
});

test("the three shapes that actually shipped stay named", () => {
  // Subsumed by the rule above, kept because each of these is a bug that was in
  // production and a regex is cheaper to read than a scanner.
  const FORBIDDEN = [
    /rsToP\s*\(\s*parseFloat/,
    /Math\.round\s*\(\s*parseFloat/,
    /parseFloat\s*\([^)]*\)\s*\*\s*100\b/,
  ];
  const offenders: string[] = [];
  for (const f of sources()) {
    if (PINNED_TO_THE_BACKEND.has(f)) continue;
    const src = code(f);
    for (const re of FORBIDDEN) {
      if (re.test(src)) { offenders.push(`${f} matches ${re}`); break; }
    }
  }
  assert.deepEqual(offenders, []);
});

test("the banking rsToP is the exact parser, not a float multiply", () => {
  // It took a `number` and did Math.round(rs * 100), which is what forced
  // every call site to parseFloat first. The signature is the fix: a string
  // in, and null out for anything that is not an amount.
  const src = code("components/banking/shared.ts");
  assert.match(src, /export function rsToP\(rs: string\): number \| null/,
    "rsToP must take the text as typed and be allowed to refuse it");
  assert.match(src, /paiseFromRupeeInput/,
    "rsToP must delegate to the one parser");
  assert.doesNotMatch(src, /Math\.round\s*\(\s*rs\s*\*\s*100\s*\)/,
    "the float multiply must be gone, not just wrapped");
});

test("the bank settlement refuses an allocation it cannot read", () => {
  // The severe one: these amounts are posted to the general ledger through
  // bank_posting_service, and a coerced zero settles nothing while telling the
  // CA the document is done.
  const src = code("components/banking/SettleDocumentsModal.tsx");
  assert.match(src, /badAllocIds/,
    "an unreadable allocation must block the save, not become zero");
  assert.match(src, /isn't a number/,
    "and it must say which document it could not read");
});

test("a split leg that is not an amount is refused by its own name", () => {
  // `Math.round(Number(cleaned) * 100)` read "1e3" as ₹1,000 and posted it
  // through the split-replace RPC, and read "abc" as 0 — which splitBlock then
  // reported as a NON-POSITIVE leg, advice about a fault that was not the one
  // the reader had.
  const src = code("lib/banking/splitLegs.ts");
  assert.match(src, /code: "unreadable"/,
    "an unreadable leg needs its own block code, not the non-positive one");
  const modal = code("components/banking/SplitAcrossLedgersModal.tsx");
  assert.match(modal, /case "unreadable":/,
    "and the modal must have words for it");
});

test("a trial-balance cell that will not read blocks the import instead of posting zero", () => {
  // The import posts ONE balanced opening journal from these rows, so a
  // silently-zeroed cell either unbalances the entry — refused by the backend,
  // with nothing on screen saying which row — or balances it at the wrong
  // opening position.
  const parser = code("lib/accounting/trialBalanceParser.ts");
  assert.match(parser, /dr_unreadable/,
    "0 and \"could not read it\" must not be the same fact on the row");
  const page = code("app/accounting/trial-balance-import/page.tsx");
  assert.match(page, /unreadable\.length > 0/,
    "and the import button must be blocked while any row is unreadable");
});
