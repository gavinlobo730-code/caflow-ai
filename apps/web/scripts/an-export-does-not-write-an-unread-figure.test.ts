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
//   C. a component that holds a read-error state (a `useState` named `error`, `loadError`, `loadFailed`, `pageError`,
//      `rowsError`, or `…LoadError` / `…LoadFailed`) never exports what a failed read left on screen: either the state gates
//      the export (it is in a `disabled={...}`, handed to the shared table as `error={...}`, which then withholds both its
//      exports, or ends the render early with `if (S) return`), or every place that sets it clears what was read in the same
//      function (`setX(null)` / `setX([])`), or it is named in ALLOWED below with the reason and the text that keeps it true.
//      A setter inside the function that writes the file (its own read, or the spreadsheet writer) is skipped: that failure
//      writes nothing.
//
// The review of 18-11-2026 found what an earlier version of this header got wrong: it said the screens it could not see
// cleared their list on a failed read, and the fee receivables ageing and the trend sheet did not, so Export wrote the
// previous client's or window's rows after a failed read. Rule C is what replaced that sentence.
//
// What it still does NOT see: a read-error state with another name, and a read in flight (a filter changed, the new read
// not back yet), where a screen's Export may still write the previous read's rows; the shared table and the screens fixed
// here also withhold it while loading where they have a loading state.
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
    if (!/downloadCsv\(|XLSX\.writeFile\(|exportFilename=/.test(src)) continue;
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

// ── C. a failed read leaves nothing on screen to export ───────────────────────────────────────────────────────────────

const READ_ERROR = /^(error|loadError|loadFailed|pageError|rowsError|\w+LoadError|\w+LoadFailed)$/;
const WRITES = /downloadCsv\(|XLSX\.writeFile\(|exportFilename=/;

/** Components whose read-error state is ALSO set by a write that leaves the read's rows true; each with text that must stay. */
const ALLOWED: Record<string, { why: string; holds: RegExp }> = {
  "app/accounting/budget/page.tsx::BudgetPage::error": {
    why: "a failed SAVE of one budget figure leaves the read true; the load clears the read on failure",
    holds: /catch \(e\) \{\s*setData\(null\);\s*setError/ },
  "app/accounting/recurring/page.tsx::RecurringPage::error": {
    why: "a failed update, delete, generate or run leaves the list as read; the load clears it on failure",
    holds: /setTemplates\(\[\]\);\s*setError\(e instanceof Error \? e\.message : "Failed to load"\)/ },
  "app/income-tax/ais/page.tsx::AISPage::error": {
    why: "an upload, a typed amount or a save refused leaves the statement as read; the load clears it on failure",
    holds: /setStatement\(null\)/ },
  "app/payroll/attendance/page.tsx::AttendancePage::loadError": {
    why: "it is the wording of a failed load, set beside loadFailed, which ends the render before any export is drawn",
    holds: /setLoadFailed\(true\);\s*setLoadError\([\s\S]*\n  if \(loadFailed\) \{\s*return / },
  "app/tds/page.tsx::TDSPage::matchLoadError": {
    why: "it is the challan-match lookup's failure, not the deduction list's; the list's own failure is handed to its table",
    holds: /error=\{listErrors\.deductions\}/ },
};

function ownFunctionSlice(body: string, at: number): string {
  const head = body.slice(0, at);
  const starts = [...head.matchAll(/useCallback\(|useEffect\(|(?:async )?function \w+\(|const \w+ = (?:async )?\(/g)];
  const from = starts.length ? starts[starts.length - 1].index! : 0;
  return body.slice(from, at + 200);
}

function violations(c: Component): string[] {
  const out: string[] = [];
  const states = [...c.body.matchAll(/const \[(\w+), set\w+\] = useState/g)].map((m) => m[1]).filter((n) => READ_ERROR.test(n));
  for (const s of states) {
    const key = `${c.file}::${c.name}::${s}`;
    const word = new RegExp(`\\b${s}\\b`);
    // Handing S to the shared table as `error=` gates the TABLE's exports only; a screen that also writes a file itself must
    // gate that button too (the risks page's CSV beside its register table was the case).
    const direct = /downloadCsv\(|XLSX\.writeFile\(/.test(c.body);
    const gated = [...c.body.matchAll(/disabled=\{([^}]*)\}/g)].some((m) => word.test(m[1]))
      || (!direct && [...c.body.matchAll(/\berror=\{([^}]*)\}/g)].some((m) => word.test(m[1])))
      || new RegExp(`\\bif \\(${s}\\)\\s*(?:\\{\\s*)?return\\b`).test(c.body);
    if (gated) continue;
    const setter = `set${s[0].toUpperCase()}${s.slice(1)}`;
    const unsafe = [...c.body.matchAll(new RegExp(`\\b${setter}\\((?!\\s*(?:null|false)\\s*\\))`, "g"))].filter((m) => {
      const slice = ownFunctionSlice(c.body, m.index!);
      // Set inside the function that writes the file: the export's own step failed (its read, or the spreadsheet writer would not
      // load), so nothing was written and nothing on screen is passed off as this read.
      if (/downloadCsv\(|XLSX\.writeFile\(|await import\("xlsx"\)/.test(slice)) return false;
      // What was READ is cleared: a setter of some other state than an error flag (clearing the error itself clears nothing).
      return ![...slice.matchAll(/\bset(\w+)\((?:null|\[\])\)/g)]
        .some((x) => !READ_ERROR.test(x[1][0].toLowerCase() + x[1].slice(1)) && !/(?:Error|Failed)$/.test(x[1]));
    });
    if (!unsafe.length) continue;
    const allowed = ALLOWED[key];
    if (allowed && allowed.holds.test(c.body)) continue;
    out.push(`${key}: the export is not gated on ${s}, and ${unsafe.length} place(s) set it without clearing what was read`);
  }
  return out;
}

test("C: a screen whose read failed does not export what that read left on screen", () => {
  const all = components().filter((c) => WRITES.test(c.body));
  assert.ok(all.length >= 40, `vacuity floor: expected the forty-odd screens that write a file, found ${all.length}`);
  assert.deepEqual(all.flatMap(violations), []);
  // an allowance names a component that still exists and still needs it
  for (const key of Object.keys(ALLOWED)) {
    const [file, name] = key.split("::");
    assert.ok(all.some((c) => c.file === file && c.name === name), `ALLOWED names ${key}, which no longer writes a file`);
  }
});

test("C: the shared table withholds both its exports while it shows a read error", () => {
  const src = stripComments(readFileSync(join(WEB, "components", "ui", "data-table.tsx"), "utf8"));
  assert.match(src, /onClick=\{\(\) => downloadCsv\(exportFilename, [^}]*\}\s*disabled=\{page\.total === 0 \|\| !!error\}/);
  assert.match(src, /\.filter\(\(a\) => !\(error && a\.id === "export-selected"\)\)/);
});

// The screens the review of 18-11-2026 led to, each named so a regression names its screen.
const FIXED: [string, string][] = [
  ["app/accounting/receivables/page.tsx", "ReceivablesAgingPage"],
  ["app/clients/[id]/reports/trend/page.tsx", "ClientTrendPage"],
  ["app/settings/audit-log/page.tsx", "AuditLogContent"],
  ["app/settings/firm-hsn-library/page.tsx", "FirmHsnLibraryPage"],
  ["app/risks/page.tsx", "RisksPage"],
  ["app/clients/[id]/compliance/page.tsx", "CompliancePage"],
  ["app/clients/[id]/compliance/gst/page.tsx", "GSTR3BDetailDrawer"],
  ["app/accounting/recurring/page.tsx", "RecurringPage"],
  ["app/accounting/schedule-iii/page.tsx", "ScheduleIIIPage"],
];
for (const [file, name] of FIXED) {
  test(`C: ${name} does not export what a failed read left on screen`, () => {
    const c = components().find((x) => x.file === file && x.name === name);
    assert.ok(c, `${file}::${name} not found`);
    assert.deepEqual(violations(c), []);
  });
}

test("C: the receivables ageing and the trend sheet clear their result when a read starts", () => {
  const rec = readFileSync(join(WEB, "app", "accounting", "receivables", "page.tsx"), "utf8");
  assert.match(rec, /async function generateAging\(\) \{[\s\S]{0,400}setRows\(\[\]\);\s*setGenerated\(false\);/);
  const trend = readFileSync(join(WEB, "app", "clients", "[id]", "reports", "trend", "page.tsx"), "utf8");
  assert.match(trend, /const load = useCallback\(async \(\) => \{[\s\S]{0,300}setTrend\(null\);/);
  const gst = readFileSync(join(WEB, "app", "clients", "[id]", "compliance", "gst", "page.tsx"), "utf8");
  assert.match(gst, /let cancelled = false;\s*\/\/[^\n]*\n\s*setRows\(null\);/);
});
