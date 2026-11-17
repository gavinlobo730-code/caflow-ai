/**
 * A nested list read off a root that is only checked for being THERE defaults the field itself (POST-A-360).
 *
 * `x && x.rows.length`, `x?.rows.map(...)`, `!x || x.rows.length === 0` and `x ? x.rows.filter(...) : ...` check that `x` exists and say nothing
 * about `rows`: a payload of `{}` is truthy, the root guard passes it and the read throws (the 16-09-2026 smoke walk). POST-A-149 narrowed the
 * nine places the objects were LOADED, and `an-object-payload-is-not-its-fields-until-it-is-checked` follows state set straight from `.data`; a
 * value that passes through a helper's return or a prop is outside both, and following it needs a data-flow walk this repository does not have.
 *
 * THE RULE, STATED AT THE READ, so it needs no trace of where the value came from: a list read off a root that the same expression has just
 * tested for presence is written `(x.rows ?? []).length`. It costs nothing where the field is always there and is the whole guard where it is not.
 * Counted first (16-11-2026): 34 such reads in 28 files, 26 of the root-guarded form POST-A-149 named and 8 more spellings it did not (`!x ||`,
 * `x ? x.f.op`, `x !== null &&`), all rewritten here; one reads through an optional chain (`variance?.notes.length`), which is the dangerous
 * spelling because the `?.` guards `variance` and says nothing about `notes`.
 *
 * WHAT THIS CANNOT SEE. A read whose root is not tested in the same expression (`report.rows.map` after an early return somewhere above), which
 * is `an-object-payload-is-not-its-fields-until-it-is-checked`'s for state and nobody's for a prop; and an OBJECT field read off a presence-tested
 * root (`d?.revenue.total_paise`, `sheet?.session.status`, and a list on the third segment such as `d?.revenue.lines ?? []`, whose `?? []` covers
 * `lines` and not `revenue`), which throws on `{}` the same way: 53 such reads in 15 files on 17-11-2026, and POST-A-360 stays open for them. A
 * read of a string field's `.length` that happens to follow a root test would be flagged, and there is none today (the list of exceptions is
 * empty and a new one is named with its reason).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", ".smoke", "scripts"]);
const OPS = "(?:map|length|filter|forEach|slice|reduce|some|every|find|join|includes|flatMap|findIndex)";

/** `file::root.field` of a read that is allowed, each with its reason. Empty on purpose. */
const EXCEPTIONS: string[] = [];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (SKIP.has(name)) continue;
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.tsx?$/.test(name) && !/\.test\.tsx?$/.test(name)) out.push(p);
  }
  return out;
}

function code(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").split("\n").map((l) => l.replace(/(^|[^:])\/\/.*$/, "$1")).join("\n");
}

const R = "([A-Za-z_]\\w*)";
const UNSAFE: RegExp[] = [
  new RegExp(`\\b${R}\\s*&&\\s*\\1\\.(\\w+)\\.${OPS}\\b`, "g"),
  new RegExp(`\\b${R}\\?\\.(\\w+)\\.${OPS}\\b`, "g"),
  new RegExp(`!${R}\\s*\\|\\|\\s*\\1\\.(\\w+)\\.${OPS}\\b`, "g"),
  new RegExp(`\\b${R}\\s*\\?(?![.?])\\s*\\1\\.(\\w+)\\.${OPS}\\b`, "g"),
  new RegExp(`\\b${R}\\s*!==?\\s*(?:null|undefined)\\s*(?:&&|\\?)\\s*\\1\\.(\\w+)\\.${OPS}\\b`, "g"),
];
const GUARDED = new RegExp(`\\(${R}\\??\\.(\\w+)\\s*\\?\\?\\s*\\[\\]\\)\\.${OPS}\\b`, "g");

function reads(): { bad: string[]; guarded: number } {
  const bad: string[] = [];
  let guarded = 0;
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f).split("\\").join("/");
    const src = code(readFileSync(f, "utf8"));
    guarded += [...src.matchAll(GUARDED)].length;
    for (const re of UNSAFE) {
      for (const m of src.matchAll(re)) {
        const k = `${rel}::${m[1]}.${m[2]}`;
        if (!EXCEPTIONS.includes(k)) bad.push(`${k}  (line ${src.slice(0, m.index).split("\n").length})`);
      }
    }
  }
  return { bad, guarded };
}

test("no list is read off a root that is only tested for being there", () => {
  const { bad } = reads();
  assert.deepEqual(bad, [], "A root guard passes `{}` and the nested read then throws. Write `(x.rows ?? []).length` at the read.\n  " + bad.join("\n  "));
});

test("the walk still sees guarded reads at all", () => {
  assert.ok(reads().guarded >= 30, "the guarded form is no longer found: the walk or the regex has stopped matching");
});

test("the rule catches each spelling it names", () => {
  const spellings = ["a && a.rows.length", "a?.rows.map(x => x)", "!a || a.rows.length === 0", "a ? a.rows.filter(f) : []", "a !== null && a.rows.some(f)", "a\n    ? a.rows.filter(f)"];
  for (const s of spellings) assert.ok(UNSAFE.some((re) => new RegExp(re.source, "g").test(s)), `not caught: ${s}`);
  assert.ok(!UNSAFE.some((re) => new RegExp(re.source, "g").test("a && (a.rows ?? []).length")), "the guarded form is flagged");
});
