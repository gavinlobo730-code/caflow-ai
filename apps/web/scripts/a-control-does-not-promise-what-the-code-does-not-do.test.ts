// A label on a control says what pressing it does — and three did not.
//
// TDS-INCOME-TAX-33: (1) the approved TDS return offered "Download JSON (for
// e-filing upload)" but the file is an internal payload that no government
// utility accepts; (2) the marketing home page said the ITR JSON was "ready to
// file" while the generator always refuses (pinned from the Python side in
// apps/api/tests/test_the_marketing_site_does_not_claim_what_the_code_does_not_do.py,
// because the marketing app has no test runner of its own); (3) "Generate
// certificate" inserted a pending register row and produced no document — Form
// 16 / 16A come only from TRACES.
//
// The rule is stated over every file under app/, components/ and lib/ rather than
// over the three spellings that shipped: no label may offer an "e-filing upload"
// of a file this product prepares, and no certificate control may say "generate"
// or "draft" while the server only records a register entry.
//
// Run with: node --experimental-strip-types --test scripts/a-control-does-not-promise-what-the-code-does-not-do.test.ts
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stripComments } from "./stripComments.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WEB = path.join(__dirname, "..");

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (["node_modules", ".next", "out"].includes(entry.name)) continue;
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) out.push(full);
  }
  return out;
}

const FILES = ["app", "components", "lib"]
  .flatMap((d) => sources(path.join(WEB, d)))
  .map((f) => ({ file: path.relative(WEB, f), code: stripComments(fs.readFileSync(f, "utf8")) }));

// A label that offers a government upload of a file this product prepares.
const OFFERS_AN_EFILING_UPLOAD = /for e-?filing upload|e-?filing upload\)|upload (this|the) (file|json) (to|on) (the )?(income[- ]tax|tds|traces|gst)/i;
// A certificate control that says it produces something.
// "Generate draft" alone is NOT matched: the recurring-invoice and billing screens
// really do generate drafts. On the certificate screen the word is checked by file.
const CERTIFICATE_SAYS_GENERATE = /Generate Certificate|certificate draft|Certificates are draft only/i;
const GENERATE_DRAFT = /Generate Draft\b/i;

test("the sweep reads the files it is about", () => {
  assert.ok(FILES.length > 500, `only ${FILES.length} source files read; bad roots?`);
  const register = FILES.find((f) => f.file.endsWith(path.join("compliance", "tds", "page.tsx")));
  assert.ok(register, "the certificate register screen was not found");
});

test("no control offers an e-filing upload of a file the product only prepares", () => {
  const hits = FILES.filter((f) => OFFERS_AN_EFILING_UPLOAD.test(f.code)).map((f) => f.file);
  assert.deepEqual(hits, [], "label it for what it is — the prepared figures — not an upload file");
});

test("no certificate control says generate or draft while the server only records a row", () => {
  const hits = FILES.filter((f) => CERTIFICATE_SAYS_GENERATE.test(f.code)).map((f) => f.file);
  assert.deepEqual(hits, [], "the route records a register entry; the certificate comes from TRACES");
});

test("the certificate screen never says 'Generate Draft'", () => {
  const tab = FILES.find((f) => f.file.endsWith(path.join("compliance", "tds", "page.tsx")))!;
  assert.doesNotMatch(tab.code, GENERATE_DRAFT);
});

test("the certificate screen says where the certificate comes from", () => {
  const tab = FILES.find((f) => f.file.endsWith(path.join("compliance", "tds", "page.tsx")))!;
  assert.match(tab.code, /TRACES/);
  assert.match(tab.code, /Record certificate/);
});

test("the patterns detect what they claim to", () => {
  assert.ok(OFFERS_AN_EFILING_UPLOAD.test("Download JSON (for e-filing upload)"));
  assert.ok(!OFFERS_AN_EFILING_UPLOAD.test("Download the prepared figures (JSON)"));
  assert.ok(CERTIFICATE_SAYS_GENERATE.test("Generate Certificate Draft"));
  assert.ok(GENERATE_DRAFT.test("+ Generate Draft"));
  assert.ok(!CERTIFICATE_SAYS_GENERATE.test("+ Record certificate"));
  assert.ok(!CERTIFICATE_SAYS_GENERATE.test("Generate draft invoice"), "a real draft generator must not be flagged");
});
