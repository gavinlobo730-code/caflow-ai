// Every rupee amount a CA types goes through lib/money/rupeeInput.ts. Run with:
//   node --experimental-strip-types --test scripts/every-amount-field-uses-the-one-parser.test.ts
//
// WHY THIS EXISTS
//     CLAUDE.md said "All 61 call sites across 28 files are converted... there
//     is no longer a second way", and nothing checked it. On 2026-09-08 there
//     were nine live second ways, every one of them the exact form CLAUDE.md
//     forbids:
//
//         rsToP(parseFloat(amounts[id] || "0") || 0)   // bank settlement
//         Math.round(parseFloat(form.amount_rupees) * 100)  // recurring entry
//
//     parseFloat("1,25,000") is 1. A CA settling an invoice, or setting up a
//     recurring journal, the way Indian amounts are grouped posted ONE RUPEE —
//     silently, with the balance left outstanding and no error anywhere. The
//     recurring one then repeated itself every month, unattended. parseFloat
//     also reads "12abc" as 12 and "1e3" as 1000, and returns NaN for a blank
//     field, which `|| 0` turned into a zero allocation and JSON.stringify
//     sends as null.
//
//     The prose was not the guard. This is.
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
    .replace(/^\s*\/\/.*$/gm, "");
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
  return out.map((p) => p.replace(/^\.\//, ""));
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
  "lib/purchases/billEditor.ts",
  "lib/purchases/debitNoteEditor.ts",
  "lib/purchases/purchaseCreditNoteEditor.ts",
]);

test("no file turns a typed amount into paise with parseFloat", () => {
  // The two forbidden shapes, named rather than approximated: parseFloat fed
  // straight into a paise converter, and parseFloat multiplied by 100.
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
  assert.deepEqual(offenders, [],
    "use paiseFromRupeeInput from lib/money/rupeeInput.ts — it refuses text that is not an amount instead of reading \"1,25,000\" as 1");
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

test("the GST reconciliation import reports an unreadable amount", () => {
  // A zero in an ITC reconciliation is not a missing figure — it is a claim
  // that no tax was charged (CGST s.16). Dropping the row is no better: that
  // reads as "the supplier never filed it".
  const src = code("app/gst/reconciliation/page.tsx");
  assert.match(src, /is not an amount/,
    "parseCsv must name the row it could not read rather than zeroing it");
});
