// POST-A-464. A read that failed is not a file of zeros.
//
// POST-A-360 made the client's trial balance, P&L and balance sheet workbooks refuse a failed read. The other export builders
// were not looked for, and two shapes still wrote a failed read into a file as figures:
//
//   * A MULTI-PERIOD REPORT keeps a period whose read failed as a column tagged `error: true` with no figures (the client P&L,
//     balance sheet and cash flow). Its CSV wrote that column as 0.00 under the period's own heading.
//   * A READ HOOK hands back `{ ..., error }` and an empty list when it fails (the payroll reports' payslips). The year-to-date
//     export built twelve months from that empty list and wrote twelve months of nil pay.
//
// The rule, over every screen that writes a file (`downloadCsv(` or `XLSX.writeFile(`):
//
//   A. a component that tags an unread value `error: true` asks `unreadColumnsSentence(` once for every file it writes;
//   B. a component that takes `error: X` from a read hook gates its export on X: X is in a `disabled={...}` and in an `if`.
//
// What it does NOT see, said rather than implied: a read whose failure is held in a plain `useState` and which clears the
// list it renders (the statutory summary, the year-end payroll summary, the budget, Schedule III, the MSME and trend sheets),
// where the export is disabled by the empty list; each was read by hand on 17-11-2026 and writes nothing on a failure.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { unreadColumnsSentence, unreadSentence } from "../lib/export/unread.ts";

const WEB = join(import.meta.dirname, "..");
const EXPORT = /downloadCsv\(|XLSX\.writeFile\(/g;

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (p.endsWith(".tsx") && !p.includes(".test.")) out.push(p);
  }
  return out;
}

const stripComments = (s: string) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:"'`])\/\/[^\n]*/g, "$1");

type Component = { file: string; name: string; body: string };

function components(): Component[] {
  const out: Component[] = [];
  for (const file of [...walk(join(WEB, "app")), ...walk(join(WEB, "components"))]) {
    const src = stripComments(readFileSync(file, "utf8"));
    if (!EXPORT.test(src)) continue;
    EXPORT.lastIndex = 0;
    const starts = [...src.matchAll(/^(?:export default |export )?(?:async )?(?:function (\w+)|const ([A-Z]\w*) = )/gm)];
    starts.forEach((m, i) => {
      const body = src.slice(m.index, i + 1 < starts.length ? starts[i + 1].index : src.length);
      out.push({ file: relative(WEB, file), name: m[1] ?? m[2], body });
    });
  }
  return out;
}

const writes = (c: Component) => (c.body.match(EXPORT) ?? []).length;

test("the refusal names every unread period, and says nothing when all were read", () => {
  assert.equal(unreadColumnsSentence([{ label: "Apr" }, { label: "May" }], "profit and loss"), null);
  const one = unreadColumnsSentence([{ label: "Apr" }, { label: "May", error: true }], "profit and loss");
  assert.match(one ?? "", /profit and loss for May could not be read, so nothing was exported\. Retry that period/);
  const two = unreadColumnsSentence([{ label: "Q1", error: true }, { label: "Q2" }, { label: "Q3", error: true }], "cash flow");
  assert.match(two ?? "", /for Q1 and Q3 could not be read.*Retry those periods/);
  assert.equal(unreadSentence("payslips", null), null);
  assert.match(unreadSentence("payslips", "timed out") ?? "", /payslips could not be read \(timed out\), so nothing was exported/);
});

test("A: a screen that tags an unread period asks the refusal for every file it writes", () => {
  const tagged = components().filter((c) => writes(c) > 0 && /\berror: true\b/.test(c.body));
  assert.ok(tagged.length >= 3, `vacuity floor: expected the client P&L, balance sheet and cash flow, found ${tagged.map((c) => c.name)}`);
  const bad = tagged
    .filter((c) => (c.body.match(/unreadColumnsSentence\(/g) ?? []).length < writes(c))
    .map((c) => `${c.file}::${c.name} writes ${writes(c)} file(s) and asks unreadColumnsSentence fewer times`);
  assert.deepEqual(bad, []);
});

test("B: a screen whose figures come from a read hook gates its export on the hook's error", () => {
  const hooked: { c: Component; names: string[] }[] = [];
  for (const c of components()) {
    if (!writes(c)) continue;
    const names = [...c.body.matchAll(/const \{([^}]*)\}\s*=\s*use[A-Z]\w*\(/g)]
      .flatMap((m) => [...m[1].matchAll(/\berror:\s*(\w+)/g)].map((n) => n[1]));
    if (names.length) hooked.push({ c, names });
  }
  assert.ok(hooked.length >= 2, `vacuity floor: expected the payroll year-to-date and CTC tabs, found ${hooked.map((h) => h.c.name)}`);
  const gates = (c: Component) => [...c.body.matchAll(/disabled=\{([^}]*)\}/g)].map((m) => m[1]).join(" ");
  const ifs = (c: Component) => [...c.body.matchAll(/\bif \(([^)]*)\)/g)].map((m) => m[1]).join(" ")
    + " " + [...c.body.matchAll(/unreadSentence\([^)]*?,\s*(\w+)\)/g)].map((m) => m[1]).join(" ");
  const bad: string[] = [];
  for (const { c, names } of hooked) {
    for (const n of names) {
      const word = new RegExp(`\\b${n}\\b`);
      if (!word.test(gates(c))) bad.push(`${c.file}::${c.name}: the export is not disabled on ${n}`);
      if (!word.test(ifs(c))) bad.push(`${c.file}::${c.name}: the export does not refuse on ${n}`);
    }
  }
  assert.deepEqual(bad, []);
});
