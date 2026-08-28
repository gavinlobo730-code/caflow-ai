// The financial year is chosen on the page that uses it, never above it.
// Run with:
//   node --experimental-strip-types --test scripts/financial-year-is-a-page-control.test.ts
//
// WHY THIS EXISTS
//     There used to be one financial-year selector, in the client header,
//     backed by `financialYear` on ClientNavContext and persisted to
//     localStorage. Eleven of the twenty-odd client pages read it; the rest
//     ignored it. So it sat above screens the year had no bearing on — and,
//     worse, above screens with their own period filter, where the two could
//     disagree in a way that looked like a bug in the data.
//
//     The reported case: the Sales page showing "FY 2026-27" in the header,
//     "Last Financial Year (FY 2025-26)" in the filter directly beneath it,
//     and rows dated 2026-03-31. All three statements were true. Nothing on
//     screen said which one the table belonged to.
//
// WHAT IS ASSERTED, AND WHY IT IS SHAPED THIS WAY
//     Not "the header renders no dropdown" — that is one line of JSX away from
//     coming back, and a page could still reach for a shared year without the
//     header showing one. The load-bearing assertion is that the CONTEXT does
//     not carry a financial year at all. While the value is reachable, the next
//     page that wants a year takes the global one and the whole shape returns.
//
//     A guard on absence needs its detector proved, or it holds vacuously. So
//     the first tests check the analysis can see a financial year where one
//     really is, using this repo's own files rather than invented strings.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

const read = (...p: string[]) => fs.readFileSync(path.join(WEB, ...p), "utf8");

const CONTEXT = ["lib", "workspace", "ClientNavContext.tsx"];
const HEADER = ["components", "ClientHeader.tsx"];

/** Files under app/ and components/, so a new page is covered without listing it. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (e.name !== "node_modules") walk(full); }
      else if (/\.tsx?$/.test(e.name)) out.push(full);
    }
  };
  walk(path.join(WEB, "app"));
  walk(path.join(WEB, "components"));
  return out;
}

/**
 * What a file destructures out of useClientNav(), e.g. "clientId, financialYear".
 * Returns null when the file does not call the hook.
 */
export function clientNavDestructuring(src: string): string | null {
  const m = /const\s*\{([^}]*)\}\s*=\s*useClientNav\(\)/.exec(src);
  return m ? m[1].replace(/\s+/g, " ").trim() : null;
}

// ── The detector works ──────────────────────────────────────────────────────

test("the destructuring of useClientNav is actually read", () => {
  assert.equal(clientNavDestructuring("const { clientId } = useClientNav();"), "clientId");
  assert.equal(clientNavDestructuring("const { clientId, financialYear } = useClientNav();"),
               "clientId, financialYear");
  assert.equal(clientNavDestructuring("nothing here"), null);
});

test("at least a dozen real files call useClientNav, so the sweep is not empty", () => {
  const callers = sourceFiles().filter((f) => clientNavDestructuring(fs.readFileSync(f, "utf8")));
  assert.ok(callers.length >= 12,
    `only ${callers.length} files call useClientNav — the sweep below would pass vacuously`);
});

// ── The rule ────────────────────────────────────────────────────────────────

test("the client nav context exposes no financial year", () => {
  const src = read(...CONTEXT);
  const value = /export interface ClientNavContextValue\s*\{([^}]*)\}/.exec(src);
  assert.ok(value, "ClientNavContextValue is no longer declared where this test looks");
  assert.equal(/financialYear/.test(value[1]), false,
    "ClientNavContextValue carries a financial year again. A period belongs to "
    + "the control that scopes the query, on the page that runs it — while a "
    + "shared one is reachable here, the next page takes it and the header "
    + "selector's failure mode comes back with it.");
});

test("no page destructures a financial year out of the shared context", () => {
  const offenders = sourceFiles().filter((f) => {
    const d = clientNavDestructuring(fs.readFileSync(f, "utf8"));
    return d !== null && /financialYear/.test(d);
  }).map((f) => path.relative(WEB, f));
  assert.deepEqual(offenders, [],
    "these read a financial year from the shared context. Hold it as page state "
    + "seeded from getCurrentFinancialYear(), and render a FinancialYearPicker "
    + "or PeriodPicker where the user needs to change it.");
});

test("the client header holds no financial-year control", () => {
  const src = read(...HEADER);
  assert.equal(/financialYear|FinancialYearPicker|PeriodPicker|FY \{/.test(src), false,
    "a financial-year control is back in the client header. It sits above every "
    + "client page, including the ones a year does not apply to, and on the ones "
    + "it does it competes with the page's own filter.");
});

test("the year is not persisted globally either", () => {
  // localStorage made the disagreement durable: a year chosen on one client
  // followed the CA to the next one, across sessions, with no indication that
  // the figures on screen were not this year's.
  //
  // Matched on a real storage call rather than the old key's name, so the
  // comment in ClientNavContext that explains what was removed does not itself
  // trip the guard.
  const STORES_A_YEAR = /(localStorage|sessionStorage)\s*\.\s*(get|set)Item\s*\([^)]*[Ff]inancialYear/;
  const offenders = [...sourceFiles(), path.join(WEB, ...CONTEXT)]
    .filter((f) => STORES_A_YEAR.test(fs.readFileSync(f, "utf8")))
    .map((f) => path.relative(WEB, f));
  assert.deepEqual(offenders, []);
});

test("that storage detector can see a real persisted year", () => {
  // Without this, the test above would pass on any regex that matches nothing.
  const STORES_A_YEAR = /(localStorage|sessionStorage)\s*\.\s*(get|set)Item\s*\([^)]*[Ff]inancialYear/;
  assert.ok(STORES_A_YEAR.test(
    'window.localStorage.setItem(FY_STORAGE_KEY, fy);'.replace("FY_STORAGE_KEY", '"caflow.financialYear"')),
    "the detector cannot see the exact call migration removed from ClientNavContext");
  assert.equal(STORES_A_YEAR.test('window.localStorage.setItem("tablePrefs", v)'), false);
});

// ── What replaced it is really there ────────────────────────────────────────

test("a page control exists to replace the header one", () => {
  const picker = read("components", "FinancialYearPicker.tsx");
  assert.match(picker, /financialYearChoices/);
  const users = sourceFiles().filter((f) =>
    /FinancialYearPicker/.test(fs.readFileSync(f, "utf8"))
    && !f.endsWith("FinancialYearPicker.tsx"));
  assert.ok(users.length >= 5,
    `only ${users.length} pages render a FinancialYearPicker — the header control "
    + "was removed from more pages than that, so some now offer no way to change "
    + "the year at all`);
});

test("the period dropdown names financial years instead of relating them to another control", () => {
  const src = read("lib", "dates", "periods.ts");
  const choices = /export function periodChoices\([\s\S]*?\n\}/.exec(src);
  assert.ok(choices, "periodChoices is no longer declared where this test looks");
  assert.equal(/This Financial Year|Last Financial Year/.test(choices[0]), false,
    "the dropdown offers a relative financial year again. Relative to what? "
    + "There is no second control to be relative to, which is the point.");
  assert.match(choices[0], /financialYearChoices/);
});
