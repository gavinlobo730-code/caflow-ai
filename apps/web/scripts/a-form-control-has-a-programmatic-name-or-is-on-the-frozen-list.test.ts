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
//   a `Field` parent, or by being a hidden / button-like input. A placeholder or a `title` is NOT a name. A control that spreads props is a
//   wrapper's and is counted apart.
//
// WHAT THIS HOLDS
//   Every file holds at most the number of unnamed controls `form-control-names-baseline.json` allows it, and the file is asserted as an
//   EQUALITY in both directions: a new unnamed control fails, and so does a fix that leaves its line behind, so the list can only shrink.
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
import { WEB, SOURCES, unnamedByFile } from "./formControlSources.ts";

const BASELINE = JSON.parse(fs.readFileSync(path.join(WEB, "scripts", "form-control-names-baseline.json"), "utf8")) as { files: Record<string, number> };

test("the walk finds the tree", () => {
  assert.ok(SOURCES.length > 400, `read only ${SOURCES.length} files`);
  assert.ok(SOURCES.includes("components/ui/field.tsx"));
});

test("the baseline is sorted, names only files that exist, and holds positive counts", () => {
  const files = Object.keys(BASELINE.files);
  assert.deepEqual(files, [...files].sort(), "the baseline is not in path order");
  for (const f of files) {
    assert.ok(fs.existsSync(path.join(WEB, f)), `${f} is on the baseline and no longer exists`);
    assert.ok(Number.isInteger(BASELINE.files[f]) && BASELINE.files[f] > 0, `${f} holds ${BASELINE.files[f]} on the baseline`);
  }
});

test("no file holds more unnamed controls than its baseline line, and no line is left behind by a fix", () => {
  const now = unnamedByFile();
  const grew = Object.entries(now).filter(([f, n]) => n > (BASELINE.files[f] ?? 0)).map(([f, n]) => `${f}: ${n} unnamed, baseline ${BASELINE.files[f] ?? 0}`);
  assert.deepEqual(grew, [],
    "a native <input>, <select> or <textarea> has no programmatic name. Give it an id and a <label htmlFor>, wrap it in its <label>, or " +
    "give it an aria-label (scripts/formControlNames.ts says what counts). Do not raise the baseline.");
  const stale = Object.entries(BASELINE.files).filter(([f, n]) => (now[f] ?? 0) < n).map(([f, n]) => `${f}: baseline ${n}, now ${now[f] ?? 0}`);
  assert.deepEqual(stale, [],
    "these files hold fewer unnamed controls than the baseline allows: run `node --experimental-strip-types scripts/refresh-form-control-names-baseline.ts` " +
    "so the line shrinks (the baseline may only shrink).");
});
