// One palette, and a value outside a Tailwind class still comes from it.
// Run with:
//   node --experimental-strip-types --test scripts/one-palette-and-the-browser-reads-it.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT
// ─────────────────────────────────────────────────────────────────────────────
// `a-colour-and-a-type-size-come-from-the-token-file.test.ts` holds two
// budgets, and the second one — raw hex OUTSIDE a Tailwind class — was stuck at
// 46 with its reason written into the file: a chart colour, an SVG attribute
// and an inline style "are not classes and have no token to use".
//
// That was true. `tailwind.config.ts` is a Tailwind config: what it declares
// reaches a class and nothing else. So three screens threaded the palette
// through `style={{}}`, prop defaults and SVG `stroke=` as raw hex, and one of
// them was still writing **#94A3B8** — the value the config records moving
// `ps.hint` OFF at 2.56:1 on white — on an icon, where 1.4.11 wants 3:1.
//
// `lib/design/tokens.ts` is the token to use. This guard is what stops it
// becoming a SECOND palette, which is the failure mode of every copy this
// codebase has found: `account_group_mappings` outranking its own derivation,
// the Schedule III caption list drifting from the classifier, the supplier
// master nothing read.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE RULE, IN BOTH DIRECTIONS
// ─────────────────────────────────────────────────────────────────────────────
// Asserting only that the module's values appear in the config is half a
// guard. The Schedule III list drifted in BOTH directions at once — it offered
// five captions the engine had never heard of AND spelled five others
// differently — so this checks both:
//
//   1. every value in the module equals what the config holds at its named path
//   2. every export has a path in TOKEN_SOURCE, so nothing can be added to the
//      module without declaring where it came from
//
// and the config stays the authority: when the two disagree, the config wins
// and this fails.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const CONFIG = readFileSync("tailwind.config.ts", "utf8");
const MODULE = readFileSync("lib/design/tokens.ts", "utf8");

/**
 * The value the CONFIG holds at a dotted path like `state.ready-surface`.
 *
 * Deliberately a text scan rather than an import: the config is a TypeScript
 * module with a `satisfies Config` shape and importing it from a bare node
 * test drags in Tailwind's types. What matters is that the value is read from
 * the config FILE and never from a copy — a guard that reads its own table
 * passes exactly when both sides have drifted together.
 */
function configValue(path: string): string | null {
  const [group, key] = path.split(".");
  // The group's own block: `group: {` up to the matching close at the same
  // indent. Scoping first matters — `DEFAULT` appears in five groups, and a
  // flat search for it would answer with whichever came first in the file.
  const start = new RegExp(`\\n\\s+${group}:\\s*\\{`).exec(CONFIG);
  if (!start) return null;
  const open = CONFIG.indexOf("{", start.index);
  let depth = 0, end = -1;
  for (let i = open; i < CONFIG.length; i++) {
    if (CONFIG[i] === "{") depth++;
    else if (CONFIG[i] === "}") { depth--; if (depth === 0) { end = i; break; } }
  }
  if (end === -1) return null;
  const block = CONFIG.slice(open, end);
  // A key may be bare (`ink:`) or quoted (`"border-strong":`).
  const m = new RegExp(`(?:^|\\s)"?${key.replace(/[-]/g, "\\-")}"?:\\s*"(#[0-9A-Fa-f]{3,8})"`).exec(block);
  return m ? m[1].toUpperCase() : null;
}

/** The module's own two tables, read out of its source. */
function moduleTable(name: string): Record<string, string> {
  const start = MODULE.indexOf(`export const ${name}`);
  assert.ok(start !== -1, `${name} is not exported from lib/design/tokens.ts`);
  const open = MODULE.indexOf("{", start);
  let depth = 0, end = -1;
  for (let i = open; i < MODULE.length; i++) {
    if (MODULE[i] === "{") depth++;
    else if (MODULE[i] === "}") { depth--; if (depth === 0) { end = i; break; } }
  }
  const body = MODULE.slice(open, end);
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/(\w+):\s*"([^"]+)"/g)) out[m[1]] = m[2];
  return out;
}

/** `export const NAME = "#RRGGBB";` — the values themselves. */
function exportedConstants(): Record<string, string> {
  const out: Record<string, string> = {};
  for (const m of MODULE.matchAll(/^export const (\w+) = "(#[0-9A-Fa-f]{3,8})";/gm)) {
    out[m[1]] = m[2].toUpperCase();
  }
  return out;
}

test("every colour the module exports is the value the config holds", () => {
  const sources = moduleTable("TOKEN_SOURCE");
  const constants = exportedConstants();
  const wrong: string[] = [];
  for (const [name, value] of Object.entries(constants)) {
    const path = sources[name];
    if (!path) continue; // caught by its own test below
    const live = configValue(path);
    if (live === null) wrong.push(`${name} names ${path}, which the config does not declare`);
    else if (live !== value.toUpperCase()) {
      wrong.push(`${name} is ${value.toUpperCase()} but ${path} is ${live}`);
    }
  }
  assert.deepEqual(
    wrong, [],
    "lib/design/tokens.ts has drifted from tailwind.config.ts. The CONFIG is " +
      "the authority — a screen reading a class and a screen reading this " +
      "module must get the same colour, or tokenising made the drift worse " +
      "rather than better.\n  " + wrong.join("\n  "),
  );
});

test("every exported colour declares where it came from", () => {
  const sources = moduleTable("TOKEN_SOURCE");
  const missing = Object.keys(exportedConstants()).filter((n) => !sources[n]);
  assert.deepEqual(
    missing, [],
    "A colour exported with no TOKEN_SOURCE entry is a value this module " +
      "invented, and nothing can check it. Add the token to " +
      "tailwind.config.ts first, then name its path here.\n  " + missing.join(", "),
  );
});

test("TOKEN_VALUES lists every exported colour", () => {
  // The walkable table and the individual exports are two spellings of one
  // thing, and a consumer importing TOKEN_VALUES would silently miss a colour
  // that was added only as a constant.
  //
  // TOKEN_VALUES is written in SHORTHAND (`{ BRAND, BRAND_DARK, … }`), so
  // `moduleTable`'s `key: "value"` scan finds nothing in it — which is how
  // this assertion failed on its first run. Shorthand is the right form there:
  // spelling each value a second time would make the table a third copy of the
  // palette, and the copy is what this whole file exists to prevent.
  const start = MODULE.indexOf("export const TOKEN_VALUES");
  assert.ok(start !== -1, "TOKEN_VALUES is not exported from lib/design/tokens.ts");
  const open = MODULE.indexOf("{", start);
  let depth = 0, end = -1;
  for (let i = open; i < MODULE.length; i++) {
    if (MODULE[i] === "{") depth++;
    else if (MODULE[i] === "}") { depth--; if (depth === 0) { end = i; break; } }
  }
  const listed = new Set(
    [...MODULE.slice(open + 1, end).matchAll(/\b([A-Z][A-Z0-9_]*)\b/g)].map((m) => m[1]),
  );
  const constants = exportedConstants();
  const missing = Object.keys(constants).filter((n) => !listed.has(n));
  assert.deepEqual(missing, [],
    `TOKEN_VALUES is missing ${missing.join(", ")} — it is meant to be every ` +
    `exported colour, so a walker sees all of them.`);
});

test("the probe can still find the config's values at all", () => {
  // A negative control on the parser rather than on the data. Every assertion
  // above passes vacuously if `configValue` starts returning null for
  // everything — a rename of the `colors` block, a reformat, a move to JSON —
  // and a guard that has stopped reading its authority is worse than none,
  // because it reports success.
  const resolved = Object.values(moduleTable("TOKEN_SOURCE"))
    .map(configValue).filter((v) => v !== null);
  assert.ok(
    resolved.length >= 25,
    `the config parser resolved only ${resolved.length} of ` +
      `${Object.keys(moduleTable("TOKEN_SOURCE")).length} token paths. It has ` +
      `stopped reading tailwind.config.ts and every assertion above is vacuous.`,
  );
});

test("a screen prefers a class and reaches the module only where it cannot", () => {
  // The module is a FALLBACK. If a file imports it, it should be because it
  // threads colour through something a class cannot reach — a style object, an
  // SVG attribute, a prop. What it must never become is a way to write
  // `className={...}` with a value instead of a token name, because Tailwind
  // scans source text and a class built from a variable never reaches the
  // stylesheet at all.
  const offenders: string[] = [];
  for (const file of ["app/executive-dashboard/page.tsx", "app/copilot/page.tsx", "app/workflows/page.tsx"]) {
    const body = readFileSync(file, "utf8");
    if (!body.includes("@/lib/design/tokens")) continue;
    // `className={`text-[${BRAND}]`}` and friends: a token value interpolated
    // into a class is the one use this module must not have.
    if (/className=\{[^}]*\$\{[A-Z_]{3,}\}/.test(body)) offenders.push(file);
  }
  assert.deepEqual(offenders, [], 
    "A token value interpolated into a className produces a class Tailwind " +
    "never emitted, so the element renders unstyled. Use the token NAME as a " +
    "class (bg-brand), or the value in a style object — never the value in a " +
    "class.\n  " + offenders.join("\n  "));
});
