// The client portal's Statements tab showed BOTH a friendly empty-state
// message ("No statement is available for this client yet.") AND, stacked
// above it in a red banner, the raw backend text of statementPdf's own 404
// ("API error 404: {"detail":"No statement available for this client."}").
//
// The two calls answer the SAME question — services/portal_data_service.py's
// resolve_fee_scope returning nothing — through two different endpoints:
// `statement()` (the JSON path `loadSection("statements", …)` calls, which
// answers cleanly with `{available: false}`) and `statement_pdf()` (which
// 404s with that exact sentence, because it has no "available: false" shape
// to answer with). The Download PDF button called the second regardless of
// what the first had already said, so a click while the empty state was
// showing put the raw error banner ON TOP of it.
//
// The fix is the button, not the wording: it must be disabled — and
// downloadStatement() must refuse to run even if it were somehow called
// another way — whenever there is nothing to download. Regex over the
// source, in this repo's established style for a .tsx a plain type-stripper
// cannot import (JSX elsewhere in the file).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const FILE = path.resolve(import.meta.dirname, "..", "app", "portal", "dashboard", "page.tsx");

function read(): string {
  return fs.readFileSync(FILE, "utf8");
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

function downloadStatementBody(rawSrc: string): string {
  const start = rawSrc.indexOf("const downloadStatement = async () => {");
  assert.ok(start > -1, "could not find downloadStatement");
  const end = rawSrc.indexOf("\n  };", start) + 5;
  assert.ok(end > start, "could not find the end of downloadStatement");
  return rawSrc.slice(start, end);
}

function downloadButtonMarkup(rawSrc: string): string {
  const anchor = rawSrc.indexOf("onClick={downloadStatement}");
  assert.ok(anchor > -1, "could not find the Download PDF button's onClick");
  // The button opens with `<button` somewhere before its onClick.
  const start = rawSrc.lastIndexOf("<button", anchor);
  assert.ok(start > -1, "could not find the Download PDF button's opening tag");
  const end = rawSrc.indexOf(">", anchor) + 1;
  return rawSrc.slice(start, end);
}

test("the Download PDF button is disabled when there is no statement to download", () => {
  const markup = stripComments(downloadButtonMarkup(read()));
  assert.match(
    markup,
    /disabled=\{[^}]*statement\s*===\s*null[^}]*\|\|[^}]*statement\.available\s*===\s*false[^}]*\}/,
    "the button must be disabled while `statement` is null or available:false " +
    "— the same condition the friendly empty-state below it renders on"
  );
});

test("downloadStatement() itself refuses to run under the same condition", () => {
  const body = stripComments(downloadStatementBody(read()));
  assert.match(
    body,
    /if\s*\(\s*statement\s*===\s*null\s*\|\|\s*statement\.available\s*===\s*false\s*\)\s*return;/,
    "belt-and-suspenders: even if the disabled button were bypassed, the " +
    "handler must not call statementPdf when there is nothing to download"
  );
});

test("downloadStatement still runs its real request when a statement IS available", () => {
  // Negative-control companion: the guard above must narrow the function,
  // not gut it.
  const body = stripComments(downloadStatementBody(read()));
  assert.match(body, /api\.portalSelf\.statementPdf\(/);
});
