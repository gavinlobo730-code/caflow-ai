// GST-07 — the GSTR-3B screens show how the build compares with the GSTR-1 that
// was filed.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-gstr3b-is-tied-out-against-the-filed-gstr1.test.ts
//
// WHAT WAS WRONG
//     From the July 2025 tax period the portal fills GSTR-3B Table 3.1 from the
//     period's GSTR-1 and locks it. `POST /api/gst/gstr3b/from-books` now
//     returns `gstr1_tie_out` — the filed GSTR-1's outward figures against the
//     build's, in exact paise, with the cause and the route. If a screen drops
//     it, the CA is back to finding out while filing.
//
// THREE RULES, ALL DURABLE
//     * every screen that computes a GSTR-3B hands the block to the findings
//       component, and the data layer carries it through;
//     * the component says NOT FILED in its own words and never renders a
//       figure for it (a period with nothing filed has nothing to be equal to);
//     * the component DECIDES NOTHING — the difference is the server's. A
//       subtraction in the browser would be a second implementation of the
//       comparison, which is the defect this codebase keeps recording.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const COMPONENT = path.join("components", "gst", "Gstr3bFindings.tsx");

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

const SCREENS = [
  path.join("app", "gst", "gstr3b", "page.tsx"),
  path.join("app", "clients", "[id]", "compliance", "gst", "page.tsx"),
];

test("both GSTR-3B screens hand the tie-out to the findings component", () => {
  for (const rel of SCREENS) {
    const body = code(rel);
    assert.match(body, /<Gstr3bFindings\b[\s\S]*?gstr1TieOut=\{[^}]*gstr1_tie_out[^}]*\}[\s\S]*?\/>/,
      `${rel} computes a GSTR-3B and does not pass \`gstr1_tie_out\` to <Gstr3bFindings />`);
  }
});

test("the data layer carries the block through", () => {
  const gst = code(path.join("lib", "data", "gst.ts"));
  const shaper = gst.slice(gst.indexOf("const shaped: GSTR3BComputeResult"));
  assert.match(shaper.slice(0, 1600), /\bgstr1_tie_out:/,
    "computeGSTR3B drops `gstr1_tie_out`, so no screen can show it");
  assert.match(gst, /export interface Gstr1TieOutBlock/);
});

test("NOT FILED is its own state and carries no figure", () => {
  const src = code(COMPONENT);
  const notFiled = src.slice(src.indexOf('tieOut.status === "not_filed"'));
  const branch = notFiled.slice(0, notFiled.indexOf("if (tieOut.status !== \"ok\")"));
  assert.match(branch, /not filed/i);
  assert.doesNotMatch(branch, /rupees\(|signedRupees\(|figures/,
    "a period with nothing filed must not render a figure — a zero there reads as 'they agree'");
});

test("an unreadable or absent block renders as itself, never as a clean tie", () => {
  const src = code(COMPONENT);
  assert.match(src, /Not checked against the filed GSTR-1/);
  // `tied` is the only road to the green panel.
  const green = src.slice(src.indexOf("if (tieOut.tied)"));
  assert.match(green.slice(0, 200), /tieOut\.tied/);
  assert.match(src, /if \(!tieOut \|\| typeof tieOut !== "object"\) return null;/,
    "an older backend sends no block; that is nothing, not a tie");
});

test("the component decides nothing: no arithmetic on the two sides", () => {
  const src = code(COMPONENT);
  const panel = src.slice(src.indexOf("export function Gstr3bGstr1TieOut"),
                          src.indexOf("export function Gstr3bFindings"));
  assert.doesNotMatch(panel, /gstr1_filed\s*[-+*/]|[-+*/]\s*[a-z.?]*books_3b/,
    "the difference is the server's — subtracting here is a second implementation");
  assert.match(panel, /f\.difference/);
  // The lists are read through arrayOrEmpty: a payload is not a list until
  // something has checked.
  for (const field of ["rows", "causes", "route", "gaps"]) {
    assert.match(panel, new RegExp(`arrayOrEmpty[^;]*tieOut\\.${field}`),
      `tieOut.${field} is read without arrayOrEmpty`);
  }
});

test("the panel is written once", () => {
  const owners: string[] = [];
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === "node_modules" || e.name === ".next" || e.name.startsWith(".")) continue;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (/\.tsx?$/.test(e.name)
               && code(path.relative(WEB, p)).includes("This return differs from the filed GSTR-1")) {
        owners.push(path.relative(WEB, p));
      }
    }
  };
  for (const d of ["app", "components"]) walk(path.join(WEB, d));
  assert.deepEqual(owners, [COMPONENT]);
});
