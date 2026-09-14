/**
 * GST-10 — the browser must not consolidate the year.
 *
 * Which figure belongs on which row of GSTR-9, which rows cannot be derived and
 * why, are `domain/gst/gstr9_builder.py`'s answers. A row the server could not
 * derive must never render as a zero: on an annual return a nil is a positive
 * declaration that nothing was owed.
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const PANEL = "components/gst/GSTR9Working.tsx";
const PAGE = "app/clients/[id]/compliance/gst/page.tsx";
const API = "lib/api/index.ts";

function code(rel: string): string {
  return fs.readFileSync(path.join(WEB, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, " ")
    .replace(/^\s*\/\/.*$/gm, " ");
}

test("the panel adds nothing up of its own", () => {
  const src = code(PANEL);
  // No arithmetic on the figures: every total, sub-total and difference is a
  // row the server sent.
  assert.doesNotMatch(src, /_paise\s*[-+]\s*\w+_paise/,
    "sub-totals and differences are the server's rows");
  assert.doesNotMatch(src, /reduce\(/,
    "a reduce over the rows is a total the server already computed");
  // And no table numbering of its own beyond the titles.
  assert.doesNotMatch(src, /"4A"|"6B"|"7E"|"8C"/,
    "row codes come off the wire");
});

test("a row the server could not derive shows its note beside its own figure", () => {
  /* A note collected into a list at the bottom is read as being about some
     other row, and the zero next to the label reads as a declaration. */
  const src = code(PANEL);
  assert.match(src, /r\.note && \(/);
  assert.match(src, /r\.note && v === 0 \? "—"/,
    "an underivable row shows a dash, not a nil");
});

test("an incomplete year says so before any figure", () => {
  /* CGST Act s.44 with Rule 80(1): the portal opens FORM GSTR-9 once every
     monthly return is furnished. A consolidation of eleven months presented as
     twelve is a wrong return. */
  const src = code(PANEL);
  assert.match(src, /working\.is_complete \?/);
  assert.match(src, /part<\/strong> of the year/);
});

test("every gap the server named is rendered verbatim", () => {
  const src = code(PANEL);
  assert.match(src, /working\.gaps\.map/);
  // RENDERED, not merely mentioned: a mention survives a panel gated off.
  assert.match(src, /Object\.entries\(working\.not_built\)\.map/,
    "and what is left to do on the portal, so the working never reads as the whole return");
  assert.match(src, /\{working\.not_built && Object\.keys\(working\.not_built\)\.length > 0 && \(/,
    "gated on there being something to say, not on a constant");
});

test("the panel holds no statute of its own", () => {
  const src = code(PANEL);
  // The reasons are the server's sentences.
  assert.doesNotMatch(src, /Rule 42|Rule 43|s\.17\(5\)|section 17\(5\)/);
  assert.doesNotMatch(src, /TRAN-I|TRAN-II/);
});

test("it computes on demand and never on mount", () => {
  /* Consolidating a year is a real read. A screen that fires it on every tab
     switch turns opening the GSTR-9 tab into twenty-four round trips to
     Mumbai. */
  const src = code(PANEL);
  assert.doesNotMatch(src, /useEffect\([\s\S]{0,120}compute/,
    "the consolidation is a button, not a mount effect");
  assert.match(src, /onClick=\{compute\}/);
});

test("the panel is reachable from the GSTR-9 tab", () => {
  const src = code(PAGE);
  assert.match(src, /<GSTR9Working clientId=\{clientId\} financialYear=\{fy\} \/>/);
});

test("the api layer carries shapes and no statute", () => {
  const src = code(API);
  const start = src.indexOf("gstr9: {");
  assert.ok(start > 0, "the namespace exists");
  const ns = src.slice(start, start + 700);
  assert.match(ns, /\/api\/gst-workspace\/gstr9\/compute/);
  // A read. Consolidating a year must not write one.
  assert.doesNotMatch(ns, /method: "POST"|method: "PUT"|method: "DELETE"/);
});
