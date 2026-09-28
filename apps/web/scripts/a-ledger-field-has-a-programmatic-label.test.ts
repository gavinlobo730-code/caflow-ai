// Every input in the Add/Edit ledger modal is reachable by its visible label.
// Run with:
//   pnpm test scripts/a-ledger-field-has-a-programmatic-label.test.ts
//
// ─────────────────────────────────────────────────────────────────────────────
// THE DEFECT (sweep-accounting-hub-1-05)
// ─────────────────────────────────────────────────────────────────────────────
// LedgerDialog (app/accounting/account-groups/page.tsx) drew six fields —
// Ledger name, Code, Type, Parent group, Sub group, Nature — each as a bare
// `<label>` with no `htmlFor`, above an `<input>`/`<select>` with no `id`,
// `name` or `aria-label`. The visible label text was never programmatically
// tied to its control: a screen reader announced the field with no name, and
// `getByLabel` (Playwright, Testing Library) could not find any of them.
//
// ─────────────────────────────────────────────────────────────────────────────
// THE FIX, AND WHY THIS GUARD IS SHAPED THIS WAY
// ─────────────────────────────────────────────────────────────────────────────
// Each control now gets an `id` from `useId()` and a `name` matching its
// form-state key, and its `<label>` gets a matching `htmlFor`. The read-only
// "Type" paragraph shown while editing an existing account has no control to
// point at — `account_type` cannot be changed once anything may have posted —
// so its label's `htmlFor` is `undefined` in that branch; that is correct and
// this guard does not demand a `htmlFor` value there, only that the JSX
// attribute is present so a later edit does not quietly drop it back to a
// bare `<label>`.
//
// This is a regex guard, not a DOM render, because the rest of `scripts/*`
// checks this repository's own rules the same way (see
// `a-financial-year-choice-comes-from-the-clock.test.ts`). The tricky part is
// that `[^>]*` stops at the first `>`, and this file's own `onChange={e =>
// ...}` handlers contain one inside every arrow `=>` — so the `<select>`
// match below excludes a `>` immediately preceded by `=`, which is exactly
// what an arrow function's `>` is and a real tag's closing `>` never is.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const PATH = "app/accounting/account-groups/page.tsx";
const src = readFileSync(PATH, "utf8");

const dialogStart = src.indexOf("function LedgerDialog");
const dialogEnd = src.indexOf("\nexport default function AccountGroupsPage");
assert.ok(dialogStart >= 0 && dialogEnd > dialogStart,
  `LedgerDialog was not found in ${PATH}`);
const dialog = src.slice(dialogStart, dialogEnd);

// Self-closing `<input … />`. None of this file's attribute values contain a
// literal "/>", so the first one found is the tag's own close.
const INPUT_TAGS = () => [...dialog.matchAll(/<input\b([\s\S]*?)\/>/g)];
// `<select … >` is not self-closing (it wraps `<option>` children), so its
// close is the first `>` NOT immediately preceded by `=` — every arrow
// function's `>` is, and a real tag close never is.
const SELECT_TAGS = () => [...dialog.matchAll(/<select\b([\s\S]*?)(?<!=)>/g)];
const LABEL_TAGS = () => [...dialog.matchAll(/<label\b([^>]*)>/g)];

test("every input and select in the ledger dialog carries an id and a name", () => {
  const controls = [...INPUT_TAGS(), ...SELECT_TAGS()];
  assert.ok(controls.length >= 6,
    `expected at least six form controls in LedgerDialog, found ${controls.length}`);
  const unnamed = controls
    .filter(([, attrs]) => !/\bid=\{/.test(attrs) || !/\bname=/.test(attrs))
    .map(([full]) => full.slice(0, 60));
  assert.deepEqual(unnamed, [],
    "a form control in the ledger dialog has no id/name pair, so its visible "
    + "label cannot be linked to it and getByLabel cannot find it:\n  "
    + unnamed.join("\n  "));
});

test("every field label in the ledger dialog carries htmlFor", () => {
  const labels = LABEL_TAGS();
  assert.ok(labels.length >= 6,
    `expected at least six <label> elements in LedgerDialog, found ${labels.length}`);
  const unwired = labels
    .filter(([, attrs]) => !/\bhtmlFor=/.test(attrs))
    .map(([full]) => full.slice(0, 60));
  assert.deepEqual(unwired, [],
    "a <label> in the ledger dialog has no htmlFor, so its visible text is "
    + "not the accessible name of any control:\n  " + unwired.join("\n  "));
});

test("each declared id is used as both a label's htmlFor and a control's id", () => {
  for (const id of ["nameId", "codeId", "typeId", "parentGroupId", "subGroupId", "natureId"]) {
    assert.ok(new RegExp(`\\b${id}\\s*=\\s*useId\\(\\)`).test(dialog),
      `${id} is not declared with useId()`);
    assert.ok(new RegExp(`htmlFor=\\{[^}]*\\b${id}\\b[^}]*\\}`).test(dialog),
      `${id} is never used as a label's htmlFor`);
    assert.ok(new RegExp(`\\bid=\\{${id}\\}`).test(dialog),
      `${id} is never used as a control's id`);
  }
});
