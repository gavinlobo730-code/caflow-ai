// ACC-23, the frontend half. Banks email statements locked with a password;
// the server now answers such an upload with a 422 carrying a CODE, and the
// import dialog has to ASK for the password on that code, send it in the body
// of the retry, and keep it nowhere else.
//
// What must not change: the dialog classifies the refusal by CODE (never by
// the wording of a sentence), the password travels in the multipart BODY (a
// query string is written to access logs), it is a password-type input that
// the browser is told not to save, it is dropped when the file changes and
// when the import lands, and it never reaches storage or a URL.
//
// The two code strings are the backend's vocabulary; the Python side pins them
// to this file (tests/test_a_password_protected_statement_can_be_opened.py).
//
// Run with: node --experimental-strip-types --test scripts/a-locked-pdf-statement-asks-for-its-password.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";
import {
  pdfPasswordAsk, PDF_PASSWORD_INCORRECT, PDF_PASSWORD_REQUIRED,
} from "../lib/banking/pdfPassword.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PANEL = path.join(__dirname, "..", "components", "banking", "AccountsPanel.tsx");
const API = path.join(__dirname, "..", "lib", "api", "index.ts");
const panel = stripComments(fs.readFileSync(PANEL, "utf8"));
const api = stripComments(fs.readFileSync(API, "utf8"));

test("the two refusals are told apart by code", () => {
  assert.equal(pdfPasswordAsk({ code: PDF_PASSWORD_REQUIRED }), "required");
  assert.equal(pdfPasswordAsk({ code: PDF_PASSWORD_INCORRECT }), "incorrect");
});

test("anything else is not a password question", () => {
  assert.equal(pdfPasswordAsk({ code: "totals_mismatch" }), null);
  assert.equal(pdfPasswordAsk({ code: null }), null);
  assert.equal(pdfPasswordAsk(new Error("This PDF is password-protected.")), null,
    "the wording must never be what decides it");
  assert.equal(pdfPasswordAsk(null), null);
  assert.equal(pdfPasswordAsk("pdf_password_required"), null);
  assert.equal(pdfPasswordAsk(undefined), null);
});

test("the dialog asks on the code, before it would open the column mapper", () => {
  assert.match(panel, /pdfPasswordAsk\(err\)/);
  // A locked file cannot be mapped either: the password check has to come
  // BEFORE the format-problem fallback or the CA is sent to a second dead end.
  const ask = panel.indexOf("if (askForPassword(err)) return;");
  const map = panel.indexOf("looksLikeAFormatProblem(message)) void startMapping()");
  assert.ok(ask > 0 && map > ask, "the password check must precede the mapper fallback");
});

test("all three requests that open the file carry the password in the body", () => {
  // baseForm() serves inspect and preview; the import builds its own form.
  const base = panel.slice(panel.indexOf("function baseForm()"), panel.indexOf("function askForPassword"));
  assert.match(base, /form\.append\("pdf_password", pdfPassword\)/);
  const imp = panel.slice(panel.indexOf("async function handleImport()"));
  assert.match(imp, /form\.append\("pdf_password", pdfPassword\)/);
});

test("the password is not in a URL, a storage call or a log", () => {
  for (const [name, src] of [["AccountsPanel", panel], ["lib/api", api]] as const) {
    const lines = src.split("\n").filter((l) => /pdf_?password/i.test(l));
    for (const l of lines) {
      assert.doesNotMatch(l, /localStorage|sessionStorage|indexedDB|document\.cookie/,
        `${name}: the password reaches browser storage: ${l.trim()}`);
      assert.doesNotMatch(l, /console\.|URLSearchParams|\?pdf_password|&pdf_password/,
        `${name}: the password reaches a log or a URL: ${l.trim()}`);
    }
  }
  // ...and the API client never learns the field at all: it forwards a FormData.
  assert.doesNotMatch(api, /pdf_password/);
});

test("the box is a password input the browser is told not to save", () => {
  const input = panel.slice(panel.indexOf('id="stmt-pdf-password"'));
  const tag = input.slice(0, input.indexOf("/>"));
  assert.match(tag, /type="password"/);
  assert.match(tag, /autoComplete="new-password"/);
  assert.match(tag, /spellCheck=\{false\}/);
  assert.match(panel, /htmlFor="stmt-pdf-password"/, "the field needs a programmatic label");
});

test("it is revealed by the server's refusal, never offered up front", () => {
  assert.match(panel, /\{passwordAsk && \(/);
});

test("it does not outlive the request that needed it", () => {
  const change = panel.slice(panel.indexOf("function handleFile"), panel.indexOf("function baseForm"));
  assert.match(change, /setPdfPassword\(""\)/, "a new file must clear the old password");
  assert.match(change, /setPasswordAsk\(null\)/);
  const landed = panel.slice(panel.indexOf("setResult(res.data)") - 200,
                             panel.indexOf("setResult(res.data)"));
  assert.match(landed, /setPdfPassword\(""\)/, "a landed import must clear it");
});

test("inspect and preview keep the server's code when they refuse", () => {
  // postStatementForm used to throw a bare Error, so a locked file seen by the
  // column mapper could not be told from a corrupt one.
  const post = api.slice(api.indexOf("postStatementForm: async"), api.indexOf("inspectStatement:"));
  assert.match(post, /new ApiRefusal\(message,/);
});
