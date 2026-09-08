// Reverse-charge tax reaches the CA's eye, not just the response. Run with:
//   node --experimental-strip-types --test scripts/the-gst-challan-figure-is-on-the-screen.test.ts
//
// WHY THIS EXISTS
//     CGST Act s.49(4) lets the electronic credit ledger be used only for
//     "output tax", and s.2(82) defines output tax as EXCLUDING "tax payable
//     by him on reverse charge basis". So tax under s.9(3)/(4) is always cash,
//     always on top of whatever Table 6's set-off leaves.
//
//     Table 6 on this screen was headed "Net Tax Payable" and its fourth cell
//     was labelled "Total", in bold red. That is the number a CA reads off and
//     pays — and it was the set-off result only, short by the whole of Table
//     3.1(d). Underpaying GSTR-3B carries interest under s.50(1) at 18% and
//     the return does not count as filed.
//
//     The backend has carried rcm_cash_paise and cash_payable_paise since the
//     s.49(5) cross-utilisation was rebuilt. This test is about the last inch:
//     a correct figure nobody is shown is not a fixed bug.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const GSTR3B = "app/gst/gstr3b/page.tsx";
const REPORTS = "app/reports/page.tsx";

/** Source with comments stripped — the assertions are about what RENDERS, and
 *  the notes beside this code explain the very figures they replaced. */
function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("the GSTR-3B screen renders the challan total, not only the set-off", () => {
  const src = code(GSTR3B);
  assert.match(src, /net_payable\.challan_total_paise/,
    "Table 6 must show what is actually paid in cash");
  assert.match(src, /net_payable\.rcm_cash_paise/,
    "and how much of it is reverse charge, or the CA cannot reconcile it");
});

test("the bold total is no longer labelled as if it were the amount due", () => {
  // The label mattered as much as the number: "Total" in red beside three tax
  // heads reads as the challan figure whatever the code behind it does.
  const src = code(GSTR3B);
  assert.match(src, /After set-off/,
    "the set-off cell must say what it is");
  assert.match(src, /Total payable in cash/,
    "and the challan figure must be the one that says 'payable'");
});

test("the GST summary report adds reverse charge on top of the set-off", () => {
  const src = code(REPORTS);
  assert.match(src, /rcm_cash/,
    "the report's Total column is the same set-off result and had the same gap");
  assert.match(src, /totalNetLiability\)\s*\+\s*rcmCash/,
    "the cash total must be the set-off plus the reverse charge");
});

test("a zero-rated supply prints the IGST it actually carries", () => {
  // The IGST cell on the zero-rated row was a hardcoded em dash. That is right
  // for an export under an LUT or bond (s.16(3)(a)) and wrong for one made on
  // payment of tax (s.16(3)(b)), which owes real IGST and reclaims it under
  // s.54.
  const src = code(GSTR3B);
  assert.match(src, /outward\.zero_rated_igst_paise/,
    "the zero-rated row must print the tax on the supply, not always a dash");
});

test("Total Output Tax includes the zero-rated IGST the row above it prints", () => {
  // Fixing the row above made this line CONTRADICT it: the total summed
  // taxable_igst_paise alone, so a s.16(3)(b) exporter saw a zero-rated IGST
  // figure and a "total" that did not contain it — and that total is what the
  // Table 6 liability below is set off against. §16(3)(b) tax is owed in THIS
  // return and refunded later under §54; Table 6.1 on the portal includes it,
  // and services/filing_demo/gstr3b.py's head_liability already did.
  const src = code(GSTR3B);
  assert.match(
    src,
    /taxable_igst_paise\s*\+\s*w\.outward\.zero_rated_igst_paise/,
    "the IGST total must add the zero-rated IGST, not just the taxable IGST");
});

test("no GST screen states the withdrawn Rule 36(4) buffer", () => {
  // Rule 36(4)'s provisional buffer — 120%, then 110%, then 105% — was
  // WITHDRAWN by Notification 40/2021-Central Tax with effect from
  // 1 January 2022. Credit is now strictly matched to GSTR-2B.
  //
  // The reconciliation screen told the CA "restricted to 105%" in three
  // places, including the blue banner above the run button, while the engine
  // (domain/gst/gstr3b_computer._RULE_36_4_NUMERATOR = 100) had it right all
  // along. That is a wrong statement of law on the screen a CA reads BEFORE
  // deciding how much credit to claim — the cushion it promises does not
  // exist, and claiming into it is what draws the reversal notice the same
  // banner warns about.
  for (const rel of ["app/gst/reconciliation/page.tsx", "app/gst/gstr3b/page.tsx"]) {
    const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
    // Comments are NOT stripped here: the header comments are what a developer
    // reads to learn the rule, and both stated the superseded figure.
    const claims = src.split("\n").filter((line) =>
      /10[05]\s*%|1[12]0\s*%/.test(line) && /36\(4\)|restricted|cap(ped)?\b/i.test(line));
    for (const line of claims) {
      assert.doesNotMatch(line, /(105|110|120)\s*%/,
        `${rel} states a Rule 36(4) buffer that was withdrawn on 01-01-2022: ${line.trim()}`);
    }
  }
});
