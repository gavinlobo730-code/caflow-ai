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

/** Every object-state-from-a-payload site, narrowed or not. What the walk can
 *  SEE, which is the only honest thing to put a vacuity floor on. */
function population(): number {
  let n = 0;
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f).split("\\").join("/");
    if (rel.startsWith("scripts/")) continue;
    const src = code(readFileSync(f, "utf8"));
    const decl =
      /const\s*\[\s*(\w+)\s*,\s*(set\w+)\s*\]\s*=\s*useState\s*<[^>]*\|\s*null\s*>\s*\(\s*null\s*\)/g;
    for (const m of src.matchAll(decl)) {
      const [, state, setter] = m;
      const sets = [...src.matchAll(new RegExp(`\\b${setter}\\s*\\(([^;]*?)\\)\\s*;`, "g"))]
        .map((c) => c[1])
        .filter((a) => /\.data\b/.test(a));
      if (!sets.length) continue;
      if ([...src.matchAll(new RegExp(`\\b${state}\\??\\.(\\w+)\\s*\\??\\.\\s*${NESTED_ARRAY_READ}\\b`, "g"))].length) n++;
    }
  }
  return n;
}

const key = (s: Site) => `${s.file}::${s.state}`;

/**
 * Every site live on 24-09-2026, with the fields it reads. Measured, not
 * recalled. REMOVE an entry when you guard it — the assertion is an equality,
 * so a fix that leaves its entry here fails just as loudly as a new offender.
 */
const KNOWN_UNGUARDED: string[] = [
  "app/clients/[id]/payroll/page.tsx::data",
  "app/clients/[id]/payroll/page.tsx::ecrSeq",
  "app/platform/page.tsx::detail",
  "components/payroll/EmployeeDrawer.tsx::result",
  "components/payroll/StatutoryHandoff.tsx::handoff",
  "components/payroll/StatutoryHandoff.tsx::result",
];

test("the sweep still finds object state at all", () => {
  // Vacuity floor, measured on the POPULATION and not on the offenders.
  //
  // ⚠️ It was written against `sweep()`, which excludes anything already
  // narrowed — so it failed the moment the backlog was worked down, which is
  // a floor that breaks when the work SUCCEEDS. A vacuity check has to count
  // what the walk can SEE, not what is still wrong with it, or the guard
  // cannot survive its own purpose being served.
  assert.ok(
    population() >= 40,
    `only ${population()} object-state payload sites found at all — the walk ` +
      "or the regex has probably stopped matching.",
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
