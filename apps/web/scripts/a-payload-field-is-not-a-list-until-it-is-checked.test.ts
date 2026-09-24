/**
 * A list on screen came from a payload, and a payload is not a list until
 * something has checked.
 *
 * THE DEFECT, TWICE IN ONE MORNING
 *
 *   The smoke walk of 24-09-2026 — the first run after the harness was
 *   rebuilt — crashed two screens outright:
 *
 *     /deadlines               TypeError: reading 'length' of undefined
 *     /settings/multi-currency TypeError: reading 'find' of undefined
 *
 *   `components/gst/ExpiringEwayBills` guarded `!report` and then read
 *   `report.bills.length`; `[]` is truthy and `{}` is truthy, so the guard
 *   passed both and the read threw. `components/currency/FxRatesPanel` did
 *   `if (t.success && t.data) setTypes(t.data.rate_types)` — the ENVELOPE was
 *   checked and the FIELD inside it was not, so `types` became undefined and
 *   the very next line did `types.find(...)`.
 *
 *   THE STATE TYPE HIDES IT COMPLETELY. `useState<T[]>([])` satisfies
 *   TypeScript on `setTypes(t.data.rate_types)` however absent that key is at
 *   runtime, because the payload type says it is there. Nothing in the
 *   compiler can see the difference.
 *
 * WHY A GUARD AND NOT JUST TWO FIXES
 *
 *   `lib/api/shape.ts` was written for exactly this on 16-09-2026 and its own
 *   docstring counts THIRTEEN screens that failed this way. Both components
 *   above were written AFTER that sweep and reintroduced it, and a sweep over
 *   the tree on 24-09-2026 found 28 more live sites. A fix without a rule is
 *   a fix that gets re-broken by the next component, which is what happened.
 *
 *   And it is NOT a test-harness artefact. `shape.ts` names three production
 *   paths that deliver a body without the expected fields: the GST workspace
 *   router answers a refusal as HTTP 200, `lib/api` aborts at 45 seconds, and
 *   Render's free tier cold-starts. A rolling deploy is a fourth — the
 *   frontend is live before the backend that serves the new field.
 *
 * THE RULE
 *
 *   Array-typed state (`useState<T[]>([])`) may not be REPLACED from an API
 *   payload unless the payload passes through `arrayOrEmpty`/`objectOrNull`,
 *   or through a function that takes `unknown` and returns a typed array —
 *   which is itself a narrowing boundary, and the allowlist below names the
 *   two that exist.
 *
 *   A `?? []` fallback also passes, and that is deliberate rather than
 *   generous: it defends the common null case, which is most of the 312
 *   setters in the tree. It does NOT defend a truthy non-array, so it is
 *   weaker than the helper — but holding 312 files to the stronger rule is
 *   the kind of budget this repository has watched get raised until it means
 *   nothing. The rule here is narrow, true and enforceable.
 *
 * WHAT THIS DELIBERATELY DOES NOT COVER, and it is a DIFFERENT bug
 *
 *   `setRows(prev => [json.data, ...prev])` — a functional update that INSERTS
 *   one item. That does not make the state undefined; it puts `undefined` in
 *   as an ELEMENT, and the row renders blank instead of the screen crashing.
 *   15 of those exist. Folding them in here would make the count bigger and
 *   the claim weaker, because a blank row and a dead screen are not the same
 *   defect and do not have the same fix.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", ".smoke"]);

/** Functions that take `unknown` and return a typed array. Calling one IS the
 *  check — it is a narrowing boundary of the same kind as `arrayOrEmpty`, just
 *  with domain knowledge inside it. Each is listed with where it lives so the
 *  claim can be re-read rather than trusted. */
const NARROWING_HELPERS: Record<string, string> = {
  registerNotesFrom: "lib/purchases/registerNotes.ts — (data: unknown) => RegisterNote[]",
  topLevelNotesFrom: "lib/purchases/registerNotes.ts — (data: unknown) => RegisterNote[]",
};

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

interface Hit { file: string; setter: string; arg: string; functional: boolean }

function sweep(): Hit[] {
  const hits: Hit[] = [];
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f);
    if (rel.startsWith("scripts/")) continue;
    const src = code(readFileSync(f, "utf8"));

    // Array-typed state only: `useState<...>([])`. A scalar cannot crash on
    // `.length`, and an object-typed `useState<X | null>(null)` is a separate
    // shape whose guard is `objectOrNull` at the read.
    const setters = new Set<string>();
    for (const m of src.matchAll(
      /const\s*\[\s*\w+\s*,\s*(set\w+)\s*\]\s*=\s*useState\s*(?:<[^>]*>)?\s*\(\s*\[\]\s*\)/g,
    )) setters.add(m[1]);

    for (const setter of setters) {
      const re = new RegExp(`\\b${setter}\\s*\\(([^;]*?)\\)\\s*;`, "g");
      for (const c of src.matchAll(re)) {
        const arg = c[1].trim();
        if (!/\.data\b/.test(arg)) continue;
        if (/arrayOrEmpty|objectOrNull/.test(arg)) continue;
        if (/\?\?\s*\[\]|\|\|\s*\[\]/.test(arg)) continue;
        if (Object.keys(NARROWING_HELPERS).some((h) => arg.includes(`${h}(`))) continue;
        const functional = /^\(?\s*(prev|p)\b[^)]*\)?\s*(:[^=]*)?=>/.test(arg);
        hits.push({ file: rel, setter, arg: arg.replace(/\s+/g, " ").slice(0, 90), functional });
      }
    }
  }
  return hits;
}

test("no screen replaces a list from an unchecked payload", () => {
  const offenders = sweep().filter((h) => !h.functional);
  assert.deepEqual(
    offenders.map((h) => `${h.file}: ${h.setter}( ${h.arg} )`),
    [],
    "these set array state straight from an API payload. If the field is " +
      "absent — a rolling deploy, a 200 carrying a refusal, a cold start, an " +
      "aborted request — the state becomes undefined and the next render " +
      "throws, which is how /deadlines and /settings/multi-currency died on " +
      "the smoke walk of 24-09-2026. Wrap it in arrayOrEmpty() from " +
      "@/lib/api/shape.",
  );
});

test("the sweep is not vacuous — it finds the files it is meant to read", () => {
  // Without this, a broken walk() or a filter that excludes everything makes
  // the assertion above pass for ever. Counted rather than matched, because
  // the population is what the rule is about.
  const files = walk(WEB).filter((f) => !relative(WEB, f).startsWith("scripts/"));
  assert.ok(files.length > 300, `walk() found only ${files.length} sources`);
  const withArrayState = files.filter((f) =>
    /useState\s*(?:<[^>]*>)?\s*\(\s*\[\]\s*\)/.test(code(readFileSync(f, "utf8"))),
  );
  assert.ok(
    withArrayState.length > 80,
    `only ${withArrayState.length} files declare array state — the state ` +
      "pattern has changed and this guard is reading almost nothing",
  );
});

test("the functional-insert variant is counted apart, not swept in", () => {
  // A DIFFERENT defect: `setRows(prev => [json.data, ...prev])` inserts
  // undefined as an ELEMENT, so a row renders blank and the screen survives.
  // Recorded with a number so it cannot quietly grow into the crashing kind,
  // and NOT failed, because its fix is different and it is not urgent.
  const functional = sweep().filter((h) => h.functional);
  assert.ok(
    functional.length <= 15,
    `functional inserts from an unchecked payload rose to ${functional.length} ` +
      `(was 15 on 24-09-2026):\n  ` +
      functional.map((h) => `${h.file}: ${h.setter}`).join("\n  "),
  );
});

test("the narrowing-helper allowlist is real, not a hole", () => {
  // Every name here must be a function that actually takes `unknown`. An
  // allowlist nobody re-reads is how an exemption outlives its reason.
  const src = readFileSync(join(WEB, "lib/purchases/registerNotes.ts"), "utf8");
  for (const name of Object.keys(NARROWING_HELPERS)) {
    assert.match(
      src,
      new RegExp(`export function ${name}\\s*\\(\\s*\\w+\\s*:\\s*unknown`),
      `${name} is allowlisted as a narrowing boundary but does not take ` +
        "`unknown` — so it trusts its caller and is not one",
    );
  }
});
