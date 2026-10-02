/**
 * DateInput, rendered (frontend_ux-19). Run with:
 *   node --experimental-strip-types --test components/ui/date-input.test.ts
 *
 * The same harness as page-header.test.ts: `pnpm test` strips types but does not
 * parse JSX, so the REAL date-input.tsx is transpiled with the TypeScript
 * compiler already in node_modules and rendered with react-dom/server. `cn` and
 * the reading rule (lib/dates/typedDate.ts) are the product's own code.
 *
 * WHAT THIS CAN AND CANNOT SEE. A server render has no focus, no keystroke and no
 * state change, so it reads the MARKUP: what a value is shown as, which
 * attributes the box carries and how a message is wired to it. How the field
 * behaves while somebody types is held by the pure rule's tests
 * (lib/dates/typedDate.test.ts) and by the browser run recorded in the commit,
 * and it says which of those it is — nothing here pretends to have clicked.
 */
import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import { renderToStaticMarkup } from "react-dom/server";
import React from "react";

const WEB = path.resolve(import.meta.dirname, "../..");
let dir = "";
type Props = Record<string, unknown>;
let DateInput: (props: Props) => React.ReactElement;
let DateFieldView: (props: Props) => React.ReactElement;

before(async () => {
  dir = fs.mkdtempSync(path.join(WEB, ".date-input-test-"));
  const source = fs.readFileSync(path.join(WEB, "components/ui/date-input.tsx"), "utf8");
  let js = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ESNext,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX,
    },
  }).outputText;
  js = js
    .replace('"@/lib/utils"', JSON.stringify(pathToFileURL(path.join(WEB, "lib/utils.ts")).href))
    .replace('"@/lib/dates/typedDate"', JSON.stringify(pathToFileURL(path.join(WEB, "lib/dates/typedDate.ts")).href));
  fs.writeFileSync(path.join(dir, "date-input.mjs"), js);
  const mod = await import(pathToFileURL(path.join(dir, "date-input.mjs")).href);
  DateInput = mod.DateInput;
  DateFieldView = mod.DateFieldView;
});

after(() => {
  if (dir) fs.rmSync(dir, { recursive: true, force: true });
});

const noop = () => {};
function html(props: Props): string {
  return renderToStaticMarkup(React.createElement(DateInput, { onChange: noop, ...props }));
}
function view(props: Props): string {
  return renderToStaticMarkup(React.createElement(DateFieldView, { inputId: "d1", text: "", problem: null, tone: "problem", ...props }));
}
/** The attributes of the one <input> in a piece of markup. */
function inputTag(out: string): string {
  const tags = out.match(/<input\b[^>]*>/g) ?? [];
  assert.equal(tags.length, 1, "exactly one input");
  return tags[0];
}

test("an ISO value is shown as dd/mm/yyyy, in a plain text box, never a native date input", () => {
  const tag = inputTag(html({ value: "2026-03-05" }));
  assert.match(tag, /value="05\/03\/2026"/);
  assert.match(tag, /type="text"/);
  assert.doesNotMatch(tag, /type="date"/);
});

test("the box asks for the numeric keypad, turns autocomplete off and shows its format as the placeholder", () => {
  const tag = inputTag(html({ value: "" }));
  assert.match(tag, /inputMode="numeric"/);
  assert.match(tag, /autoComplete="off"/);
  assert.match(tag, /placeholder="dd\/mm\/yyyy"/);
  assert.match(inputTag(html({ value: "", placeholder: "Date" })), /placeholder="Date"/, "a screen's own placeholder wins");
});

test("an empty value and one that is not a calendar date both show an empty box", () => {
  for (const value of ["", "2026-02-31", "garbage", "05/03/2026", "2026-03-05T00:00:00"]) {
    assert.match(inputTag(html({ value })), /value=""/, JSON.stringify(value));
  }
});

test("a leap day is shown, and the last day of a month is not rolled over", () => {
  assert.match(inputTag(html({ value: "2028-02-29" })), /value="29\/02\/2028"/);
  assert.match(inputTag(html({ value: "2026-03-31" })), /value="31\/03\/2026"/);
});

test("the box says nothing until there is something to say, and carries the focus ring", () => {
  const out = html({ value: "2026-03-05" });
  assert.doesNotMatch(out, /aria-invalid/);
  assert.doesNotMatch(out, /aria-describedby/);
  assert.doesNotMatch(out, /role="alert"/, "no message element is rendered for a date that is fine");
  assert.doesNotMatch(out, /<(?:div|p)\b/, "the markup is phrasing content, so it can sit inside a <label>");
  assert.match(inputTag(out), /focus:ring-2/);
  assert.match(inputTag(out), /focus:ring-brand/);
});

test("the label association is the screen's: id and name pass straight through", () => {
  const out = renderToStaticMarkup(
    React.createElement("div", null,
      React.createElement("label", { htmlFor: "inv-date" }, "Invoice Date"),
      React.createElement(DateInput, { id: "inv-date", value: "2026-03-05", onChange: noop, name: "invoice_date", "aria-label": "Invoice date", required: true })),
  );
  const tag = inputTag(out);
  assert.match(tag, /id="inv-date"/);
  assert.match(tag, /name="invoice_date"/);
  assert.match(tag, /aria-label="Invoice date"/);
  assert.match(tag, /required=""/);
  assert.match(out, /<label for="inv-date">/);
});

test("with no id of its own it still has one, so a message can be tied to it", () => {
  const tag = inputTag(html({ value: "" }));
  assert.match(tag, /id="date-[^"]+"/);
});

test("disabled and read-only pass through, and a disabled field still shows its date", () => {
  const tag = inputTag(html({ value: "2026-03-05", disabled: true, readOnly: true }));
  assert.match(tag, /disabled=""/);
  assert.match(tag, /readonly=""/i);
  assert.match(tag, /value="05\/03\/2026"/);
});

test("an unreadable date is announced: aria-invalid, a message tied to the box by aria-describedby, role alert", () => {
  const out = view({ text: "31/02/2026", problem: "Feb 2026 has only 28 days.", tone: "problem" });
  const tag = inputTag(out);
  assert.match(tag, /aria-invalid="true"/);
  assert.match(tag, /aria-describedby="d1-msg"/);
  assert.match(out, /<span id="d1-msg" role="alert"[^>]*>Feb 2026 has only 28 days\.<\/span>/);
  assert.match(tag, /border-state-problem/, "colour is not the only signal, but it is one");
  assert.match(tag, /focus:ring-state-problem/);
  assert.doesNotMatch(tag, /(?<![\w-])border-ps-border/, "the problem border replaces the neutral one");
  assert.match(out, /text-state-problem/);
});

test("a range hint is shown but does not mark the box invalid", () => {
  const out = view({ text: "31/03/2026", problem: "31 Mar 2026 is before 01 Apr 2026.", tone: "hint" });
  const tag = inputTag(out);
  assert.doesNotMatch(tag, /aria-invalid/);
  assert.match(tag, /aria-describedby="d1-msg"/, "still described by the sentence");
  assert.match(out, /text-state-attention/);
  assert.doesNotMatch(out, /text-state-problem/);
});

test("a parent's own invalid flag marks the box even with no message of ours", () => {
  const tag = inputTag(view({ text: "", problem: null, invalid: true }));
  assert.match(tag, /aria-invalid="true"/);
  assert.doesNotMatch(tag, /aria-describedby/, "there is no message to describe it with");
});

test("a describedby the screen already had is kept and the message is added after it", () => {
  const tag = inputTag(view({ text: "x", problem: "No.", "aria-describedby": "inv-help" }));
  assert.match(tag, /aria-describedby="inv-help d1-msg"/);
  assert.match(inputTag(view({ text: "x", problem: null, "aria-describedby": "inv-help" })), /aria-describedby="inv-help"/);
});

test("a screen's own classes are merged over the default look, and the ring survives them", () => {
  const tag = inputTag(html({
    value: "",
    className: "w-full px-2 py-1 text-xs border border-ps-border rounded-lg disabled:bg-ps-bg",
  }));
  assert.match(tag, /(?<![\w-])w-full(?![\w-])/);
  assert.match(tag, /text-xs/);
  assert.doesNotMatch(tag, /text-sm/, "the screen's size replaces the default size");
  assert.match(tag, /px-2/);
  assert.doesNotMatch(tag, /px-3/);
  assert.match(tag, /disabled:bg-ps-bg/);
  assert.match(tag, /focus:ring-brand/, "an outline is never removed with nothing drawn in its place");
});

test("the wrapper class is the screen's, and the wrapper can shrink inside a grid", () => {
  const out = html({ value: "", wrapperClassName: "col-span-2" });
  assert.match(out, /^<span class="block min-w-0 col-span-2">/);
});
