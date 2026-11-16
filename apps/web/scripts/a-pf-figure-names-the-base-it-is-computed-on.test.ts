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

/** The PF deduction or PF choice a screen LABELS in its text (JSX text, not a column key or a CSV header), and whether it names the base. */
function pfLabels(text: string): { line: string; named: boolean }[] {
  return text.split("\n")
    .filter((line) => /(^|>)\s*PF (Deduction|Applicable)\b/.test(line))
    .map((line) => ({ line: line.trim(), named: /12% of PF wages/.test(line) }));
}

test("the screen that had it still says what the base is, and so does every PF deduction or choice a screen labels", () => {
  // Not a bare absence check: deleting the parenthetical would also pass the
  // test above, and a PF figure with no base named is worse than one with the
  // wrong base named — the CA cannot tell there is a question.
  //
  // The second screen that had it, the payslip panel on the payroll page, was
  // deleted on 16-11-2026 with its Print button (POST-A-217): nothing opened
  // it. So the rule is now said of every label, not of a list of files: a
  // screen that labels the PF deduction or the PF choice names the base.
  assert.match(rendered(path.join(ROOT, "components/payroll/AddEmployeeModal.tsx")), /12% of PF wages/,
    "components/payroll/AddEmployeeModal.tsx must name the base the figure is actually computed on");
  const unnamed: string[] = [];
  let labels = 0;
  for (const f of sources(ROOT)) {
    for (const l of pfLabels(rendered(f))) {
      labels += 1;
      if (!l.named) unnamed.push(`${path.relative(ROOT, f)}: ${l.line.slice(0, 110)}`);
    }
  }
  assert.ok(labels >= 1, "found no PF deduction or PF choice label at all: the rule reads nothing");
  assert.deepEqual(unnamed, [], "a PF deduction or PF choice label must name the base it is computed on (12% of PF wages)");
});

test("self-test: a label with no base is named, a label with the base and a column key are not", () => {
  const sample = [
    "<td>PF Deduction</td>",
    "                PF Deduction (12% of PF wages)",
    '<label htmlFor="pf">PF Applicable (12% of PF wages)</label>',
    '{ key: "pf_applicable", header: "PF Applicable", accessor: (e) => e.pf_applicable }',
  ].join("\n");
  assert.deepEqual(pfLabels(sample).map((l) => [l.line.slice(0, 20), l.named]),
    [["<td>PF Deduction</td", false], ["PF Deduction (12% of", true], ["<label htmlFor=\"pf\">", true]]);
});
