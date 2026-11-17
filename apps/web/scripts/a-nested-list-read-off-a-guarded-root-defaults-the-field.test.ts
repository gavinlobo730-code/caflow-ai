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
 * is `an-object-payload-is-not-its-fields-until-it-is-checked`'s for state and nobody's for a prop.
 *
 * AND AN OBJECT FIELD, SINCE 17-11-2026 (POST-A-360's second slice). The read is now any field after the field, not only a list
 * operation: `d?.revenue.total_paise`, `sheet?.session.status` and `d?.revenue.lines ?? []` (whose `?? []` covers `lines` and not
 * `revenue`) throw on `{}` the same way. Counted with this walk: 53 reads in 15 files. Each was either written with the field tested
 * (`x?.a?.b`), or its root is now narrowed where it is LOADED (the section checked with `objectOrNull`, and the screen says the answer
 * came back in a shape it cannot read), and the read is named below with the file and the text that narrows it; the test fails an
 * exception whose narrowing text is gone or that no longer matches a read, so the list cannot go stale. A narrowing in another file (the
 * TDS preview's `explain`, narrowed in `lib/data/tds.ts`) is named by that file.
 *
 * STILL NOT SEEN: a read whose root is tested by an early return above it (`if (!x) return; ... x.a.b`).
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const WEB = join(import.meta.dirname, "..");
const SKIP = new Set(["node_modules", ".next", "out", ".vercel", ".git", ".smoke", "scripts"]);
const OPS = "(?:map|length|filter|forEach|slice|reduce|some|every|find|join|includes|flatMap|findIndex)";
/** What may follow the field: any field at all (POST-A-360's second slice), so an object read is held as a list read is. */
const ANY = "\\w+";

/** `file::root.field` of a read that is allowed, each with the file and the text that narrows the root where it is loaded. */
const EXCEPTIONS: Record<string, { reason: string; narrowedIn: string; text: string }> = {
  "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx::activeData.balance_sheet":
    { reason: "every statement the page keeps passed drawableStatement", narrowedIn: "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx", text: "!objectOrNull(d.balance_sheet)" },
  "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx::comp.balance_sheet":
    { reason: "comparatives are null or carry both statements", narrowedIn: "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx", text: "!objectOrNull(d.comparatives.balance_sheet)" },
  "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx::comparative.balance_sheet":
    { reason: "a rounded comparative is null or carries its balance sheet", narrowedIn: "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx", text: "!objectOrNull(r.comparative.balance_sheet)" },
  "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx::rounding.current":
    { reason: "a rounding block carries its current period", narrowedIn: "app/clients/[id]/year-end/[engagementId]/financial-statements/_page.tsx", text: "!objectOrNull(r.current.balance_sheet)" },
  "app/tds/page.tsx::shown.explain":
    { reason: "the preview is refused without its explanation", narrowedIn: "lib/data/tds.ts", text: "!objectOrNull(shaped.explain)" },
  "components/banking/AccountsPanel.tsx::preview.balance_check":
    { reason: "the statement preview is refused without its balance check", narrowedIn: "components/banking/AccountsPanel.tsx", text: "!objectOrNull(shaped.balance_check)" },
  "components/banking/ReconcileTab.tsx::report.reconciliation":
    { reason: "the report is refused without its session, summary and counts", narrowedIn: "components/banking/ReconcileTab.tsx", text: "!objectOrNull(shaped.reconciliation)" },
  "components/inventory/StockCountSheet.tsx::sheet.session":
    { reason: "a sheet without its session is not kept", narrowedIn: "components/inventory/StockCountSheet.tsx", text: "objectOrNull(sh.session)" },
  "components/CsvImportModal.tsx::resolveTarget.resolver":
    { reason: "built by the modal from its own column config, never from a payload", narrowedIn: "components/CsvImportModal.tsx", text: "setResolveTarget({ resolver, name })" },
};

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
  new RegExp(`\\b${R}\\s*&&\\s*\\1\\.(\\w+)\\.${ANY}\\b`, "g"),
  new RegExp(`\\b${R}\\?\\.(\\w+)\\.${ANY}\\b`, "g"),
  new RegExp(`!${R}\\s*\\|\\|\\s*\\1\\.(\\w+)\\.${ANY}\\b`, "g"),
  new RegExp(`\\b${R}\\s*\\?(?![.?])\\s*\\1\\.(\\w+)\\.${ANY}\\b`, "g"),
  new RegExp(`\\b${R}\\s*!==?\\s*(?:null|undefined)\\s*(?:&&|\\?)\\s*\\1\\.(\\w+)\\.${ANY}\\b`, "g"),
];
const GUARDED = new RegExp(`\\(${R}\\??\\.(\\w+)\\s*\\?\\?\\s*\\[\\]\\)\\.${OPS}\\b`, "g");

function reads(): { bad: string[]; guarded: number; excepted: Map<string, number> } {
  const bad: string[] = [];
  const excepted = new Map<string, number>();
  let guarded = 0;
  for (const f of walk(WEB)) {
    const rel = relative(WEB, f).split("\\").join("/");
    const src = code(readFileSync(f, "utf8"));
    guarded += [...src.matchAll(GUARDED)].length;
    for (const re of UNSAFE) {
      for (const m of src.matchAll(re)) {
        const k = `${rel}::${m[1]}.${m[2]}`;
        if (k in EXCEPTIONS) excepted.set(k, (excepted.get(k) ?? 0) + 1);
        else bad.push(`${k}  (line ${src.slice(0, m.index).split("\n").length})`);
      }
    }
  }
  return { bad, guarded, excepted };
}

test("no field is read off a root that is only tested for being there", () => {
  const { bad } = reads();
  assert.deepEqual(bad, [], "A root guard passes `{}` and the nested read then throws. Write `(x.rows ?? []).length` for a list, `x?.a?.b` for "
    + "an object field, or narrow the field where the payload is loaded and name it in EXCEPTIONS.\n  " + bad.join("\n  "));
});

test("every exception still matches a read and its narrowing is still there", () => {
  const { excepted } = reads();
  for (const [k, e] of Object.entries(EXCEPTIONS)) {
    assert.ok((excepted.get(k) ?? 0) > 0, `${k} is excepted and no longer read that way: delete the exception`);
    const narrowing = readFileSync(join(WEB, e.narrowedIn), "utf8");
    assert.ok(narrowing.includes(e.text), `${k} is excepted because ${e.reason}, and ${e.narrowedIn} no longer holds \`${e.text}\``);
  }
});

test("the walk still sees narrowed object reads at all", () => {
  const n = [...reads().excepted.values()].reduce((a, b) => a + b, 0);
  assert.ok(n >= 20, `only ${n} narrowed object reads were seen: the walk or the regex has stopped matching`);
});

test("the walk still sees guarded reads at all", () => {
  assert.ok(reads().guarded >= 30, "the guarded form is no longer found: the walk or the regex has stopped matching");
});

test("the rule catches each spelling it names", () => {
  const spellings = ["a && a.rows.length", "a?.rows.map(x => x)", "!a || a.rows.length === 0", "a ? a.rows.filter(f) : []", "a !== null && a.rows.some(f)", "a\n    ? a.rows.filter(f)",
    "d?.revenue.total_paise", "d?.revenue.lines ?? []", "sheet && sheet.session.status", "x ? x.status.replace(a, b) : y"];
  for (const s of spellings) assert.ok(UNSAFE.some((re) => new RegExp(re.source, "g").test(s)), `not caught: ${s}`);
  for (const safe of ["a && (a.rows ?? []).length", "d?.revenue?.total_paise", "x?.status ? x.status.replace(a, b) : y"]) {
    assert.ok(!UNSAFE.some((re) => new RegExp(re.source, "g").test(safe)), `the guarded form is flagged: ${safe}`);
  }
});
