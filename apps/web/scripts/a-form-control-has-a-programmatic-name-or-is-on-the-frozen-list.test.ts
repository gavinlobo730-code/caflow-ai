// A NATIVE FORM CONTROL HAS A PROGRAMMATIC NAME, OR ITS FILE IS ON THE FROZEN LIST. Run with:
//   node --experimental-strip-types --test scripts/a-form-control-has-a-programmatic-name-or-is-on-the-frozen-list.test.ts
//
// THE DEFECT (frontend_ux-11, POST-A-127)
//   About 1,200 native `<input>`, `<select>` and `<textarea>` in the tree, and 591 of them, in 127 files, had no accessible name: a visible `<label>` sat
//   beside the control with no `htmlFor` and the control with no `id`, or there was only a placeholder. A screen reader announces such a field
//   as "edit text" and nothing more, and `getByLabel` (Playwright, Testing Library) cannot find it. The screens a CA types into all day were
//   among them.
//
// THE RULE (`scripts/formControlNames.ts`, found with the TypeScript parser and not a regex)
//   A control is named by `aria-label` / `aria-labelledby`, a wrapping `<label>`, an `id` that a `<label htmlFor>` in the same file points at,
//   a parent `Field` that ties its label to its children (the one from components/ui/field, or one declared in the same file that wraps
//   `{children}` in a `<label>`), or by being a hidden / button-like input. A placeholder or a `title` is NOT a name. A control that
//   spreads props is a wrapper's and is counted apart.
//
// WHAT THIS HOLDS
//   Every file holds exactly the unnamed controls `form-control-names-baseline.json` lists for it, each recorded as its tag and what it is bound
//   to (`input:form.asset_name`, or a hash of its text when it is bound to nothing). It is an EQUALITY in both directions: a new unnamed control
//   fails, a fix that leaves its entry behind fails, and, because the entries are the controls themselves and not a count, a fix and a new
//   control in the same file cannot net out. The list can only shrink. A control that spreads props is allowed only in `components/ui/`, the
//   shared primitives, whose callers name it; anywhere else a spread is a wrapper nobody has checked.
//   346 controls were named in the commit that introduced the rule, by giving each the text of the bare `<label>` written just before it as an
//   `aria-label` (visually identical; a wrapping label or an id and htmlFor is better where a screen can take it, and the rule accepts both).
//
// WHAT IT DOES NOT SEE
//   A control inside a component that is not a JSX element of the file, a label in another file, a name computed away from the expression it
//   was written as, and whether the NAME IS GOOD (an aria-label of "Name" on a row of a table says nothing about the row). It proves a name
//   exists, not that it is right.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { WEB, SOURCES, unnamedByFile, spreadByFile } from "./formControlSources.ts";

const BASELINE = JSON.parse(fs.readFileSync(path.join(WEB, "scripts", "form-control-names-baseline.json"), "utf8")) as { files: Record<string, string[]> };

test("the walk finds the tree", () => {
  assert.ok(SOURCES.length > 400, `read only ${SOURCES.length} files`);
  assert.ok(SOURCES.includes("components/ui/field.tsx"));
});

test("the baseline is sorted, names only files that exist, and lists distinct controls", () => {
  const files = Object.keys(BASELINE.files);
  assert.deepEqual(files, [...files].sort(), "the baseline is not in path order");
  for (const f of files) {
    assert.ok(fs.existsSync(path.join(WEB, f)), `${f} is on the baseline and no longer exists`);
    const keys = BASELINE.files[f];
    assert.ok(Array.isArray(keys) && keys.length > 0, `${f} holds no controls on the baseline`);
    assert.equal(new Set(keys).size, keys.length, `${f} lists a control twice`);
  }
});

test("no file holds an unnamed control that is not on its baseline entry, and no entry is left behind by a fix", () => {
  const now = unnamedByFile();
  const added: string[] = [];
  const stale: string[] = [];
  for (const f of new Set([...Object.keys(now), ...Object.keys(BASELINE.files)])) {
    const have = now[f] ?? [];
    const allowed = BASELINE.files[f] ?? [];
    for (const k of have) if (!allowed.includes(k)) added.push(`${f}: ${k}`);
    for (const k of allowed) if (!have.includes(k)) stale.push(`${f}: ${k}`);
  }
  assert.deepEqual(added, [],
    "a native <input>, <select> or <textarea> has no programmatic name. Give it an id and a <label htmlFor>, wrap it in its <label>, or " +
    "give it an aria-label (scripts/formControlNames.ts says what counts). Do not add it to the baseline.");
  assert.deepEqual(stale, [],
    "these controls are on the baseline and are not unnamed now: run `node --experimental-strip-types scripts/refresh-form-control-names-baseline.ts` " +
    "so the entry goes (the baseline may only shrink).");
});

test("a control that spreads its props is a shared primitive's, and only those are allowed to", () => {
  const outside = Object.entries(spreadByFile()).filter(([f]) => !f.startsWith("components/ui/")).map(([f, n]) => `${f}: ${n}`);
  assert.deepEqual(outside, [],
    "a control outside components/ui/ spreads props: it is named by whoever calls it, and nothing checks the callers. Name it where it is written.");
});
