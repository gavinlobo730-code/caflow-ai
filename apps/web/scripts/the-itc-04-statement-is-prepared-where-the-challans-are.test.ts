// GST-30 — FORM GST ITC-04 reaches the CA, and decides nothing in the browser.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-itc-04-statement-is-prepared-where-the-challans-are.test.ts
//
// WHAT WAS WRONG
//     `itc_04_period` returned a refusal and two sentences, and the statement
//     Rule 45(3) requires was typed out again by hand from challans already
//     entered. A challan also held ONE date for all of its goods coming back, so
//     goods returned in lots could not be recorded. The endpoints exist now; a
//     screen that never calls them is the same defect one layer up.
//
// THE RULES, NOT SPELLINGS
//     * the screen the CA already keeps challans on renders the panel, and the
//       panel reads and writes through the server and no second data path;
//     * the cadence is NOT chosen here: every reading is rendered, none is
//       pre-selected, and the panel holds no turnover limit or due date;
//     * the panel does no arithmetic of its own — not on dates, not on a
//       quantity, not on a balance;
//     * a failed read is said in words, never rendered as an empty list (an empty
//       "still with the job worker" means every lot is back);
//     * quantities are keyed through the one quantity parser, and the form's
//       own caveats and the prepare-only sentence are rendered, not dropped;
//     * the panel is written once.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = path.join("components", "gst", "Itc04Panel.tsx");
const HELPER = path.join("lib", "gst", "itc04.ts");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the challans screen renders the panel and reloads when a lot is recorded", () => {
  const src = code(path.join("components", "sales", "SalesCycleTab.tsx"));
  assert.match(src, /<Itc04Panel\b[^>]*clientId=\{clientId\}/);
  assert.match(src, /onChanged=\{\(\) => void load\(\)\}/,
    "the last lot marks the challan received back, so the list must reload");
});

test("the panel reads and writes through the server and nothing else", () => {
  const src = code(PANEL);
  assert.match(src, /api\.salesCycle\.itc04\(/);
  assert.match(src, /api\.salesCycle\.recordChallanReturn\(/);
  assert.doesNotMatch(src, /supabase|\.from\(/, "no second data path");
  assert.doesNotMatch(src, /localStorage|sessionStorage/, "the CA's work is not kept in the browser");
});

test("both methods exist on the client and are typed", () => {
  const src = code(path.join("lib", "api", "index.ts"));
  assert.match(src, /itc04: \(clientId: string, financialYear: string, window\?: string \| null\)/);
  assert.match(src, /recordChallanReturn: \(challanId: string, body: ChallanReturnBody\)/);
  assert.match(src, /\/api\/sales-cycle\/itc-04\?client_id=/);
  assert.match(src, /\/api\/sales-cycle\/challans\/\$\{challanId\}\/returns/);
});

test("every reading is rendered and none is chosen for the CA", () => {
  const src = code(PANEL);
  assert.match(src, /readings\.map\(/);
  assert.match(src, /useState<string \| null>\(null\)/,
    "no window is open until the CA opens one — pre-selecting one would be choosing");
  assert.doesNotMatch(src, /\.chosen\b/);
  assert.doesNotMatch(src, /quarterly|half_yearly|annual/i,
    "naming a cadence here would be picking one");
});

test("the panel holds no limit, no due date and does no arithmetic", () => {
  const src = code(PANEL) + code(HELPER);
  assert.doesNotMatch(src, /new Date\(|Date\.now\(|getTime\(|86_?400/,
    "counting days here would be a second implementation of the clock");
  assert.doesNotMatch(src, /\b25\b|5_?00_?00_?000|10_?00_?00_?000/,
    "the 25th and the turnover limit are the server's, [S]-graded there");
  assert.doesNotMatch(src, /parseFloat|Number\(|\* 100|\/ 100/,
    "a quantity or a balance is never computed in the browser");
  assert.doesNotMatch(src, /outstanding\s*-|sent\s*-|returned\s*-/,
    "what is outstanding is the server's, never re-subtracted here");
});

test("a failed read is said in words, never rendered as an empty statement", () => {
  const src = code(PANEL);
  assert.match(src, /Couldn(&apos;|')t read the ITC-04 working/);
  assert.match(src, /role="alert"/);
  assert.match(src, /catch \{[\s\S]{0,80}setFailed\(true\)/);
  assert.match(src, /setFailed\(got === null\)/);
});

test("lists are read through the shape guards, not trusted", () => {
  const src = code(PANEL);
  assert.match(src, /objectWithLists<Itc04Statement>\([^)]*"readings"[^)]*"outstanding"[^)]*"gaps"/);
  assert.match(src, /objectOrNull<Itc04Statement\["period"\]>/);
  assert.match(src, /arrayOrEmpty<Itc04Window>\(reading\.windows\)/);
  assert.match(src, /arrayOrEmpty<Itc04Balance>\(st\?\.outstanding\)/);
});

test("a lot is keyed through the quantity parser", () => {
  const src = code(HELPER);
  assert.match(src, /parseQuantity\(/);
  assert.match(code(PANEL), /lotBody\(/);
});

test("the form's caveats and the prepare-only sentence are rendered", () => {
  const src = code(PANEL);
  assert.match(src, /arrayOrEmpty<string>\(st\.gaps\)/);
  assert.match(src, /period\?\.refusal/);
  assert.match(src, /t5b\?\.reason/);
  assert.match(src, /t5c\?\.reason/);
  assert.match(src, /furnished on the GST portal by the principal/);
});

test("the whole-challan control says what it does, and points at the lot-by-lot one", () => {
  const src = code(path.join("components", "sales", "SalesCycleTab.tsx"));
  assert.match(src, /Mark a whole challan back at once/);
  assert.match(src, /stops the s\.143 clock for every line/);
  assert.match(src, /lot by lot under ITC-04/);
});

test("the panel is written once", () => {
  const owners: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)
               && code(path.relative(WEB, p)).includes("FORM GST ITC-04 — goods sent for job work")) {
        owners.push(path.relative(WEB, p));
      }
    }
  };
  for (const d of ["app", "components"]) walk(path.join(WEB, d));
  assert.deepEqual(owners, [PANEL]);
});
