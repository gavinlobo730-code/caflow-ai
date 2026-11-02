// A SHARED FORM COMPONENT IS NAMED WHERE IT IS USED (POST-A-127, the call-site half). Run with:
//   node --experimental-strip-types --test scripts/a-shared-form-component-is-named-where-it-is-used.test.ts
//
// THE GAP THE FIRST HALF LEFT
//   `a-form-control-has-a-programmatic-name-or-is-on-the-frozen-list.test.ts` judges every native `<input>`, `<select>` and `<textarea>` where
//   it is WRITTEN. `Input`, `Select`, `Textarea`, `DateInput`, `Combobox` and the entity lookups render one from inside a component, so that
//   rule reads their file, finds the control forwarding its props, and passes: the name has to be supplied by whoever USES the component,
//   and nothing checked that anyone did. Four client pickers (trial-balance import, payroll declarations, cash-flow, TDS) sat beside a bare
//   `<label>Client *</label>` with no `htmlFor` and no `ariaLabel`, so a screen reader announced "edit text" at the field a CA picks the
//   client in. The first run of this rule over the tree found exactly those four among 290 uses; they are named and the list is empty.
//
// THE RULE (`scripts/formControlNames.ts`, `findSharedUses`, the TypeScript parser and not a regex)
//   A use of a shared component is named by the prop that component takes for it (`aria-label` / `aria-labelledby` on the four that render a
//   bare input, select or textarea; `ariaLabel` on `Combobox` and the lookups, which do not take the others), a `<label>` that wraps it, a
//   `Field` that ties its label to its children, or an `id` a `<label htmlFor>` in the same file points at. The component is the shared one only
//   when the file imports it from the module that defines it, under whatever local name.
//
// WHAT THIS HOLDS
//   * the walk reads the tree, and each component has uses in it (a floor per component, so a path change cannot empty the rule);
//   * no use outside `components/ui/` is unnamed, and there is NO frozen list: the first run left nothing to freeze;
//   * a use that spreads props is allowed only in `components/lookups/`, the adapters that forward a caller's `ariaLabel` (the same limit the
//     native rule puts on `components/ui/`);
//   * the rule itself, on synthetic sources: each naming route, the wrong prop for the component, an alias, a local component of the same name,
//     and the two components left out on purpose.
//
// WHAT IT DOES NOT SEE
//   A component imported by a path other than the one listed in `SHARED_CONTROLS`, a name computed away from the prop it was written as,
//   whether the name is a GOOD one (a lone "Name" on a row of a table says nothing about the row), and `YearPicker` and
//   `ServiceCataloguePicker`, which supply a name of their own when the caller gives none.
import test from "node:test";
import assert from "node:assert/strict";
import { findSharedUses, SHARED_CONTROLS } from "./formControlNames.ts";
import { SOURCES, sharedUsesByFile } from "./formControlSources.ts";

const uses = (src: string) => findSharedUses(src).map((u) => `${u.component}:${u.verdict}${u.via ? `(${u.via})` : ""}`);
const FIELD = `import { Input, Select, Textarea, Field } from "@/components/ui/field";\n`;
const wrap = (head: string, jsx: string) => `${head}export function X() { return (<div>${jsx}</div>); }`;

// ── The tree ──────────────────────────────────────────────────────────────────────────────────────────

const FLOOR: Record<string, number> = {
  Input: 10, Select: 3, Textarea: 1, DateInput: 100, Combobox: 4,
  ClientLookup: 30, CustomerLookup: 5, VendorLookup: 5, StateLookup: 2, AccountLookup: 5, HsnLookup: 5, EntityLookup: 5,
};

test("the walk finds the tree and every shared component has uses in it", () => {
  assert.ok(SOURCES.length > 400, `read only ${SOURCES.length} files`);
  assert.deepEqual(Object.keys(FLOOR).sort(), Object.keys(SHARED_CONTROLS).sort(), "a component was added to the rule without a floor, or the other way round");
  const counts: Record<string, number> = {};
  for (const list of Object.values(sharedUsesByFile())) for (const u of list) counts[u.component] = (counts[u.component] ?? 0) + 1;
  for (const [component, floor] of Object.entries(FLOOR)) assert.ok((counts[component] ?? 0) >= floor, `${component}: ${counts[component] ?? 0} uses found, expected at least ${floor}`);
});

test("no use of a shared form component is without a name, and there is no list to put one on", () => {
  const unnamed: string[] = [];
  for (const [file, list] of Object.entries(sharedUsesByFile())) for (const u of list) if (u.verdict === "unnamed") unnamed.push(`${file}:${u.line} <${u.component}>`);
  assert.deepEqual(unnamed, [],
    "a shared form component is used with no accessible name. Give it `aria-label` (Input, Select, Textarea, DateInput) or `ariaLabel` (Combobox and " +
    "the lookups), wrap it in its <label>, or put an `id` on it and a <label htmlFor> beside it. Do not freeze it: the list is empty on purpose.");
});

test("a use that spreads props is a lookup adapter's, and only those are allowed to", () => {
  const outside: string[] = [];
  for (const [file, list] of Object.entries(sharedUsesByFile())) {
    if (file.startsWith("components/lookups/")) continue;
    for (const u of list) if (u.verdict === "spread") outside.push(`${file}:${u.line} <${u.component}>`);
  }
  assert.deepEqual(outside, [], "a shared form component outside components/lookups/ spreads props: whoever calls it names it, and nothing checks the callers. Name it where it is written.");
});

// ── The rule, on synthetic sources ───────────────────────────────────────────────────────────────────

test("a bare use has no name, and a placeholder or a sibling label is not one", () => {
  assert.deepEqual(uses(wrap(FIELD, `<Input />`)), ["Input:unnamed"]);
  assert.deepEqual(uses(wrap(FIELD, `<Input placeholder="Search" title="Search" />`)), ["Input:unnamed"]);
  assert.deepEqual(uses(wrap(FIELD, `<label>Client *</label><Select><option>a</option></Select>`)), ["Select:unnamed"], "a bare sibling label names nothing");
  const lookups = `import { ClientLookup } from "@/components/lookups/ClientLookup";\n`;
  assert.deepEqual(uses(wrap(lookups, `<label className="x">Client *</label><ClientLookup clients={c} value={v} onChange={f} />`)), ["ClientLookup:unnamed"]);
});

test("each component takes its own prop for a name, and the other component's prop names nothing", () => {
  assert.deepEqual(uses(wrap(FIELD, `<Input aria-label="Amount" /><Textarea aria-labelledby={h} />`)), ["Input:named(aria)", "Textarea:named(aria)"]);
  const date = `import { DateInput } from "@/components/ui/date-input";\n`;
  assert.deepEqual(uses(wrap(date, `<DateInput aria-label="Due date" value={v} onChange={f} />`)), ["DateInput:named(aria)"]);
  const combo = `import { Combobox } from "@/components/ui/combobox";\nimport { VendorLookup } from "@/components/lookups/VendorLookup";\n`;
  assert.deepEqual(uses(wrap(combo, `<Combobox ariaLabel="Account" /><VendorLookup ariaLabel="Supplier" />`)), ["Combobox:named(aria)", "VendorLookup:named(aria)"]);
  // `ariaLabel` is not a prop of Input and `aria-label` is not a prop of the lookups: each is a name the component does not receive
  assert.deepEqual(uses(wrap(FIELD, `<Input ariaLabel="Amount" />`)), ["Input:unnamed"]);
  assert.deepEqual(uses(wrap(combo, `<VendorLookup aria-label="Supplier" />`)), ["VendorLookup:unnamed"]);
  assert.deepEqual(uses(wrap(combo, `<Combobox aria-label="Account" />`)), ["Combobox:unnamed"]);
});

test("a wrapping label, a Field that ties its label to its children, and an id with a label pointing at it name a use", () => {
  assert.deepEqual(uses(wrap(FIELD, `<label>Amount <Input /></label>`)), ["Input:named(inside label)"]);
  assert.deepEqual(uses(wrap(FIELD, `<Field label="Amount"><Input /></Field>`)), ["Input:named(inside Field)"]);
  assert.deepEqual(uses(wrap(FIELD, `<label htmlFor="amt">Amount</label><Input id="amt" />`)), ["Input:named(id+htmlFor)"]);
  assert.deepEqual(uses(wrap(FIELD, `<Input id="amt" />`)), ["Input:unnamed"], "an id nothing points at names nothing");
  // a Field the file declares itself that draws its label BESIDE the children is nobody's promise
  const sibling = `import { Input } from "@/components/ui/field";\nfunction Field({ label, children }) { return <div><label>{label}</label>{children}</div>; }\n`;
  assert.deepEqual(uses(wrap(sibling, `<Field label="Amount"><Input /></Field>`)), ["Input:unnamed"]);
});

test("a use that spreads props is counted apart, and a component the file does not import from the shared module is nobody's", () => {
  assert.deepEqual(uses(wrap(FIELD, `<Input {...props} />`)), ["Input:spread"]);
  assert.deepEqual(uses(wrap(`import { Input } from "@/components/other";\n`, `<Input />`)), [], "an Input from somewhere else");
  assert.deepEqual(uses(wrap(``, `<Input />`)), [], "a local Input, or none");
  assert.deepEqual(uses(wrap(`import { Select as Dropdown } from "@/components/ui/field";\n`, `<Dropdown /><Select />`)), ["Select:unnamed"], "an alias is resolved back, and the bare name is not the import");
});

test("the two components that supply a name of their own are not in the rule", () => {
  assert.ok(!("YearPicker" in SHARED_CONTROLS) && !("ServiceCataloguePicker" in SHARED_CONTROLS));
  assert.deepEqual(uses(wrap(`import { YearPicker } from "@/components/ui/year-picker";\n`, `<YearPicker value={y} onChange={f} />`)), []);
});
