// The PF deduction a screen shows is 12% of the s.2(88) WAGE BASE, and no
// label may say "of basic". Run with:
//   node --experimental-strip-types --test scripts/a-pf-figure-names-the-base-it-is-computed-on.test.ts
//
// WHY THIS EXISTS
//     The Code on Social Security 2020 subsumed the EPF Act and brought its own
//     wage definition: the listed exclusions are capped at HALF of total
//     remuneration and the excess is deemed wages (migration 334,
//     domain/payroll/wage_base.py). On the ordinary low-basic Indian structure
//     — ₹10,000 basic with ₹18,000 HRA — exclusions are 64% of the total, the
//     base is ₹14,000, and the employee's PF is ₹1,680.
//
//     Two screens went on labelling that figure "12% of Basic": the payslip
//     panel a CA reads the deduction off, and the checkbox they decide
//     pf_applicable with. The numbers were right and the labels contradicted
//     them, on the two screens where the decision is made — so a CA
//     reconciling ₹1,680 against ₹10,000 × 12% would find a ₹480 difference
//     the software had told them to expect.
//
// THE RULE, NOT THE SPELLING
//     No rendered text may describe a PF amount as a percentage OF BASIC.
//     Comments are stripped first: the note explaining why the old label was
//     wrong necessarily quotes it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", ".git", "out", "dist", "coverage"]);

function sources(dir: string, out: string[] = []): string[] {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (SKIP.has(e.name)) continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) sources(p, out);
    else if (/\.tsx?$/.test(e.name) && !/\.test\.tsx?$/.test(e.name)) out.push(p);
  }
  return out;
}

/** Comments removed — a note about the wrong label quotes the wrong label. */
function rendered(file: string): string {
  return fs.readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("no screen labels a PF figure as a percentage of basic", () => {
  const offenders: string[] = [];
  for (const f of sources(ROOT)) {
    for (const line of rendered(f).split("\n")) {
      // "12% of basic", "12 % of Basic", "of basic pay" — beside anything PF.
      if (/\bPF\b|provident/i.test(line) && /%\s*of\s+basic/i.test(line)) {
        offenders.push(`${path.relative(ROOT, f)}: ${line.trim().slice(0, 110)}`);
      }
    }
  }
  assert.deepEqual(offenders, [],
    "PF is 12% of the Code on Social Security s.2(88) wage base, which exceeds " +
    "basic whenever the excluded allowances are more than half of pay");
});

test("the two screens that had it still say what the base is", () => {
  // Not a bare absence check: deleting the parenthetical would also pass the
  // test above, and a PF figure with no base named is worse than one with the
  // wrong base named — the CA cannot tell there is a question.
  for (const rel of ["app/payroll/page.tsx",
                     "components/payroll/AddEmployeeModal.tsx"]) {
    assert.match(rendered(path.join(ROOT, rel)), /12% of PF wages/,
      `${rel} must name the base the figure is actually computed on`);
  }
});
