/**
 * The OTHER half of `a-payload-field-is-not-a-list-until-it-is-checked.test.ts`
 * — and it is the half that actually crashed.
 *
 * That guard matches `useState<…>([])` and says, in its own comment, that an
 * object-typed `useState<X | null>(null)` "is a separate shape whose guard is
 * `objectOrNull` at the read". No guard for that shape existed. Meanwhile BOTH
 * components CLAUDE.md records as having crashed the 24-09-2026 smoke walk are
 * that shape:
 *
 *   * `ExpiringEwayBills` guarded `!report` and then read `report.bills.length`
 *     — `{}` is truthy, so the guard passes it straight through;
 *   * `FxRatesPanel` checked the ENVELOPE (`if (t.success && t.data)`) and then
 *     set state from `t.data.rate_types`, so `types` became undefined and the
 *     next line did `types.find(...)`.
 *
 * So the rule the array guard states is right and is stated about the wrong
 * half. This is the same rule for object state: a payload is not its FIELDS
 * until something has checked it.
 *
 * ⚠️ `objectOrNull` IS NECESSARY AND NOT SUFFICIENT, and that is the thing to
 * read before "fixing" anything with it. It answers whether `data` is the
 * right KIND of thing — it converts `[]`, `null` and a scalar to `null`, and
 * `{}` passes straight through. So a NESTED list still needs `arrayOrEmpty`
 * (or `?? []`) at the READ. `components/inventory/ReorderPanel.tsx` is the
 * worked example and does both.
 *
 * WHY A FROZEN LIST RATHER THAN A COUNT. 66 sites were live when this was
 * written — 62 by the first, narrower regex, and four more once `?.` was
 * taken (see the sweep). A budget is one number somebody raises, which CLAUDE.md records as
 * how a budget comes to mean nothing; a named list can only shrink, and a new
 * offender cannot join it without an edit a reviewer sees. The list is
 * asserted EXACTLY — fixing one fails until its entry is removed, which is
 * what makes the ratchet run in both directions instead of quietly tolerating
 * a fix nobody recorded.
 *
 * WHAT THIS DOES NOT CLAIM. It does not prove the fields a screen reads are
 * the fields the endpoint sends — a per-field schema in the browser would be a
 * second description of the backend's contract, which `lib/api/shape.ts`
 * refuses for stated reasons. It answers only: could this read throw.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", ".smoke"]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

/** Comments stripped first: a rule stated about SOURCE must not be satisfied —
 *  or broken — by prose describing it. */
function code(src: string): string {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split("\n")
    .map((l) => l.replace(/\/\/.*$/, ""))
    .join("\n");
}

/** Array-ish reads. A `.length` or a `.map` on a field that is not there is
 *  the crash; a scalar read (`report.total`) renders `undefined` and lives. */
const NESTED_ARRAY_READ = "(?:map|length|filter|forEach|slice|reduce|some|every|find|join)";

interface Site { file: string; state: string; fields: string[] }

function sweep(): Site[] {
  const found: Site[] = [];
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f).split("\\").join("/");
    if (rel.startsWith("scripts/")) continue;
    const src = code(readFileSync(f, "utf8"));

    // Object-typed state: `useState<X | null>(null)`. A `useState<X[]>([])` is
    // the sibling guard's business and a scalar cannot crash on a field read.
    const decl =
      /const\s*\[\s*(\w+)\s*,\s*(set\w+)\s*\]\s*=\s*useState\s*<[^>]*\|\s*null\s*>\s*\(\s*null\s*\)/g;
    for (const m of src.matchAll(decl)) {
      const [, state, setter] = m;

      // Only state actually fed from a payload. A screen that builds its own
      // object is not describing a contract it does not control.
      const sets = [...src.matchAll(new RegExp(`\\b${setter}\\s*\\(([^;]*?)\\)\\s*;`, "g"))]
        .map((c) => c[1])
        .filter((a) => /\.data\b/.test(a));
      if (!sets.length) continue;
      if (sets.every((a) => /objectOrNull|objectWithLists/.test(a))) continue;

      // ... and read with a nested array access somewhere in the file.
      // `\\??\\.` on BOTH hops, and that is not cosmetic: `x?.rows.map(...)`
      // is the DANGEROUS spelling — the `?.` guards `x` being null and says
      // nothing about `rows` being absent, so it throws on `{}` exactly as the
      // plain form does. A negative control adding one of these passed until
      // the regex took it, which is how this was found.
      const fields = [
        ...new Set(
          [...src.matchAll(
            new RegExp(`\\b${state}\\??\\.(\\w+)\\s*\\??\\.\\s*${NESTED_ARRAY_READ}\\b`, "g"),
          )].map((r) => r[1]),
        ),
      ].sort();
      if (fields.length) found.push({ file: rel, state, fields });
    }
  }
  return found;
}

const key = (s: Site) => `${s.file}::${s.state}`;

/**
 * Every site live on 24-09-2026, with the fields it reads. Measured, not
 * recalled. REMOVE an entry when you guard it — the assertion is an equality,
 * so a fix that leaves its entry here fails just as loudly as a new offender.
 */
const KNOWN_UNGUARDED: string[] = [
  "app/accounting/budget/page.tsx::data",
  "app/accounting/msme-tracker/page.tsx::working",
  "app/clients/[id]/accounting/page.tsx::ledger",
  "app/clients/[id]/compliance/gst/page.tsx::result",
  "app/clients/[id]/fixed-assets/page.tsx::movement",
  "app/clients/[id]/fixed-assets/page.tsx::preview",
  "app/clients/[id]/payroll/page.tsx::data",
  "app/clients/[id]/payroll/page.tsx::ecrSeq",
  "app/clients/[id]/sales/page.tsx::hist",
  "app/clients/[id]/sales/page.tsx::stmt",
  "app/clients/[id]/tax/26as/page.tsx::recon",
  "app/clients/[id]/tax/computation/page.tsx::computeResult",
  "app/clients/[id]/tax/computation/page.tsx::presResult",
  "app/clients/[id]/tax/filing/page.tsx::sheet",
  "app/clients/[id]/year-end/xbrl/page.tsx::selected",
  "app/income-tax/ais/page.tsx::statement",
  "app/income-tax/book-to-tax/page.tsx::bridge",
  "app/income-tax/section-32/page.tsx::answer",
  "app/income-tax/tax-audit/page.tsx::applicability",
  "app/onboarding/checklist/page.tsx::selected",
  "app/platform/page.tsx::detail",
  "app/risks/page.tsx::register",
  "app/workflows/page.tsx::analytics",
  "components/accounting/FxRevaluationPanel.tsx::plan",
  "components/accounting/OpeningBalancesTab.tsx::kinds",
  "components/accounting/OpeningBalancesTab.tsx::listing",
  "components/banking/AccountsPanel.tsx::preview",
  "components/banking/CashBook.tsx::book",
  "components/banking/ReconcileTab.tsx::history",
  "components/banking/ReconcileTab.tsx::projection",
  "components/banking/WorthALookTab.tsx::data",
  "components/fixed-assets/CwipTab.tsx::register",
  "components/gst/AmendmentsTab.tsx::amendments",
  "components/gst/ItcRegisterTab.tsx::advances",
  "components/gst/ItcRegisterTab.tsx::register",
  "components/gst/RegistrationsTab.tsx::kinds",
  "components/gst/RegistrationsTab.tsx::turnover",
  "components/inventory/CostFormulaPanel.tsx::policy",
  "components/inventory/LocationsAndBatches.tsx::expiry",
  "components/inventory/StockCountSheet.tsx::result",
  "components/inventory/StockCountSheet.tsx::sheet",
  "components/payroll/ApplyStructureModal.tsx::result",
  "components/payroll/BonusRegister.tsx::data",
  "components/payroll/EmployeeDrawer.tsx::result",
  "components/payroll/MonthlyReview.tsx::advice",
  "components/payroll/MonthlyReview.tsx::departments",
  "components/payroll/MonthlyReview.tsx::variance",
  "components/payroll/StatutoryHandoff.tsx::handoff",
  "components/payroll/StatutoryHandoff.tsx::result",
  "components/portal/TdsProjectionTab.tsx::data",
  "components/purchases/BillsOfEntryTab.tsx::authorities",
  "components/purchases/PurchaseCycleTab.tsx::matched",
  "components/purchases/PurchaseCycleTab.tsx::position",
  "components/purchases/RcmDocumentPanel.tsx::preview",
  "components/sales/SalesCycleTab.tsx::detail",
  "components/sales/SalesCycleTab.tsx::position",
  "components/sales/SalesCycleTab.tsx::vocab",
  "components/tax/RegimeElectionPanel.tsx::data",
];

test("the sweep still finds object state at all", () => {
  // Vacuity floor. This pattern is everywhere in this codebase; a sweep that
  // finds a handful has stopped parsing, and a guard that finds nothing passes
  // for the wrong reason.
  const all = sweep();
  assert.ok(
    all.length >= 40,
    `only ${all.length} object-state payload sites found — the walk or the ` +
      "regex has probably stopped matching.",
  );
});

test("no NEW screen reads an object payload's fields unchecked", () => {
  const live = sweep().map(key).sort();
  const known = new Set(KNOWN_UNGUARDED);
  const added = live.filter((k) => !known.has(k));
  assert.deepEqual(
    added,
    [],
    "These set object state from `.data` and then read a nested list off it. " +
      "`{}` is truthy, so an `if (!x)` guard passes it and the read throws.\n" +
      "Fix: `objectOrNull<T>(r.data)` at the setter AND `arrayOrEmpty(x.field)` " +
      "at the read — the first alone is not enough, because `{}` survives it.\n" +
      "See components/inventory/ReorderPanel.tsx.\n  " +
      added.join("\n  "),
  );
});

test("the known list has no entry that is already fixed", () => {
  // The other direction. Without this, guarding a screen leaves a stale entry
  // behind and the list stops describing anything — the shape CLAUDE.md
  // records as "an allowlist nobody re-reads is how an exemption outlives its
  // reason".
  const live = new Set(sweep().map(key));
  const stale = KNOWN_UNGUARDED.filter((k) => !live.has(k));
  assert.deepEqual(
    stale,
    [],
    "These are listed as unguarded and are not (any more). Delete each line — " +
      "the list is a ratchet and may only shrink.\n  " + stale.join("\n  "),
  );
});

test("the worked example is guarded both ways", () => {
  // ReorderPanel is the one this rule was written against, and it needs BOTH
  // halves: `objectOrNull` cannot make `groups` an array.
  const src = code(
    readFileSync(join(WEB, "components/inventory/ReorderPanel.tsx"), "utf8"),
  );
  assert.match(src, /objectOrNull<ReorderReport>\(\s*r\.data\s*\)/,
    "the setter must narrow the payload's KIND");
  assert.match(src, /arrayOrEmpty<[^>]*>\(\s*report\.groups\s*\)/,
    "the nested list must be narrowed at the READ — objectOrNull passes `{}`");
  assert.ok(!/\breport\.groups\.map\b/.test(src),
    "report.groups.map is the throw this guard exists to stop");
});
