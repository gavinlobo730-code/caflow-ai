// The rule that decides whether a native form control has a programmatic name (POST-A-127). Run with:
//   node --experimental-strip-types --test scripts/formControlNames.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import { findControls } from "./formControlNames.ts";

const verdicts = (src: string) => findControls(src).map((c) => `${c.tag}:${c.verdict}${c.via ? `(${c.via})` : ""}`);
const wrap = (jsx: string) => `export function X() { return (<div>${jsx}</div>); }`;

test("a bare control has no name, and a placeholder or a title is not one", () => {
  assert.deepEqual(verdicts(wrap(`<input />`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<input placeholder="Search" title="Search" />`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<textarea rows={3} />`)), ["textarea:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<select><option>a</option></select>`)), ["select:unnamed"]);
});

test("aria-label and aria-labelledby name a control, whatever the value", () => {
  assert.deepEqual(verdicts(wrap(`<input aria-label="Amount" />`)), ["input:named(aria)"]);
  assert.deepEqual(verdicts(wrap(`<select aria-labelledby={headingId}></select>`)), ["select:named(aria)"]);
  assert.deepEqual(verdicts(wrap(`<input aria-label={label} />`)), ["input:named(aria)"]);
});

test("a label that wraps the control names it", () => {
  assert.deepEqual(verdicts(wrap(`<label>Amount <input /></label>`)), ["input:named(inside label)"]);
  assert.deepEqual(verdicts(wrap(`<label><span>Amount</span><div><input /></div></label>`)), ["input:named(inside label)"]);
});

test("an id and a label's htmlFor with the same text name it, as a literal or as the same expression", () => {
  assert.deepEqual(verdicts(wrap(`<label htmlFor="amt">Amount</label><input id="amt" />`)), ["input:named(id+htmlFor)"]);
  assert.deepEqual(verdicts(wrap(`<label htmlFor={id}>Amount</label><input id={id} />`)), ["input:named(id+htmlFor)"]);
  assert.deepEqual(verdicts(wrap(`<label htmlFor={`+"`x-${n}`"+`}>Amount</label><input id={`+"`x-${n}`"+`} />`)), ["input:named(id+htmlFor)"]);
});

test("an id with no label pointing at it, a label pointing at another id, and a label with no htmlFor do not name it", () => {
  assert.deepEqual(verdicts(wrap(`<input id="amt" />`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<label htmlFor="other">Amount</label><input id="amt" />`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<label>Amount</label><input />`)), ["input:unnamed"], "a bare sibling label names nothing");
});

test("a Field names its control only when it is the shared one or ties its own label to its children", () => {
  const imported = (jsx: string) => `import { Field } from "@/components/ui/field";\n${wrap(jsx)}`;
  assert.deepEqual(verdicts(imported(`<Field label="Amount"><input /></Field>`)), ["input:named(inside Field)"]);
  // a Field declared in the file whose body wraps {children} in a <label>
  const wrapping = `function Field({ label, children }) { return <label><span>{label}</span>{children}</label>; }\n${wrap(`<Field label="Amount"><input /></Field>`)}`;
  assert.deepEqual(verdicts(wrapping), ["input:named(inside Field)"]);
  const arrow = `const Field = ({ label, children }) => <label>{label}{children}</label>;\n${wrap(`<Field label="Amount"><input /></Field>`)}`;
  assert.deepEqual(verdicts(arrow), ["input:named(inside Field)"]);
  // a Field declared in the file that draws its label BESIDE the children names nothing (the fixed-assets screen's was this)
  const sibling = `function Field({ label, children }) { return <div><label>{label}</label>{children}</div>; }\n${wrap(`<Field label="Amount"><input /></Field>`)}`;
  assert.deepEqual(verdicts(sibling), ["input:unnamed"]);
  // a Field the file neither imports from ui/field nor declares, or imports from somewhere else, is nobody's promise
  assert.deepEqual(verdicts(wrap(`<Field label="Amount"><input /></Field>`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(`import { Field } from "@/components/other";\n${wrap(`<Field label="Amount"><input /></Field>`)}`), ["input:unnamed"]);
  // a primitive imported under another name is not the one this reads
  assert.deepEqual(verdicts(`import { Field as F } from "@/components/ui/field";\n${wrap(`<Field label="Amount"><input /></Field>`)}`), ["input:unnamed"]);
});

test("a control's key is its tag and what it is bound to, so it survives a restyle and tells two controls apart", () => {
  const key = (jsx: string) => findControls(wrap(jsx)).map((c) => c.key);
  assert.deepEqual(key(`<input className="a" value={form.name} onChange={f} />`), ["input:form.name"]);
  assert.deepEqual(key(`<input className="b px-3" value={ form.name } />`), ["input:form.name"], "a restyle or reformat changed the key");
  assert.deepEqual(key(`<select value={form.kind}></select><input value={form.name} />`), ["select:form.kind", "input:form.name"]);
  assert.deepEqual(key(`<input type="checkbox" checked={on} />`), ["input:on"]);
  const unbound = key(`<input type="file" />`)[0];
  assert.match(unbound, /^input#[0-9a-f]{8}$/);
  assert.notEqual(unbound, key(`<input type="date" />`)[0], "two different unbound controls share a key");
});


test("a button-like or hidden input needs no label of its own", () => {
  for (const t of ["hidden", "submit", "button", "reset", "image"]) assert.deepEqual(verdicts(wrap(`<input type="${t}" />`)), [`input:named(type=${t})`]);
  assert.deepEqual(verdicts(wrap(`<input type="text" />`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<input type="checkbox" />`)), ["input:unnamed"]);
  assert.deepEqual(verdicts(wrap(`<select type="hidden"></select>`)), ["select:unnamed"], "only an input is exempt by its type");
});

test("a control that spreads props is counted apart, never as named and never as unnamed", () => {
  assert.deepEqual(verdicts(wrap(`<input {...props} />`)), ["input:spread"]);
  assert.deepEqual(verdicts(wrap(`<input {...props} aria-label="x" />`)), ["input:named(aria)"]);
});

test("a capitalised component is not a native control, and a control nested in another element's attribute is still found", () => {
  assert.deepEqual(verdicts(wrap(`<Input /><DateInput /><Combobox />`)), []);
  assert.deepEqual(verdicts(wrap(`<Wrapper render={() => <input />} />`)), ["input:unnamed"]);
});

test("each control is reported on its own line", () => {
  const src = `export function X() {\n  return (\n    <div>\n      <input aria-label="a" />\n      <input />\n    </div>\n  );\n}\n`;
  assert.deepEqual(findControls(src).map((c) => [c.line, c.verdict]), [[4, "named"], [5, "unnamed"]]);
});
