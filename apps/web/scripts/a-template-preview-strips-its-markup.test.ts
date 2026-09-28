// The Templates tab's card preview shows plain text, not raw HTML tags.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-template-preview-strips-its-markup.test.ts
//
// WHAT WAS WRONG (sweep-clients-admin-09)
//     app/engagements/page.tsx rendered `{t.content.slice(0, 120)}…` directly.
//     t.content is stored HTML (the seeded templates start with `<h2>…`), so
//     the card showed the literal tags instead of a clean snippet.
//
// THE FIX
//     stripHtmlPreview() strips tags with a plain regex — not DOMParser, since
//     this "use client" page still pre-renders at build time under
//     `output: "export"` (no DOM in that Node process) — and collapses
//     whitespace, before the same slice(0, 120) as before.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the template card preview runs t.content through stripHtmlPreview before slicing", () => {
  const src = read("app/engagements/page.tsx");
  assert.match(src, /stripHtmlPreview\(t\.content\)\.slice\(0, 120\)/);
  // Not the raw content directly.
  assert.doesNotMatch(src, /\{t\.content\.slice\(0, 120\)\}/);
});

test("stripHtmlPreview removes tags and collapses whitespace, without a DOM", () => {
  const src = read("app/engagements/page.tsx");
  const m = /function stripHtmlPreview\(html: string\): string \{([\s\S]*?)\n\}/.exec(src);
  assert.ok(m, "stripHtmlPreview not found");
  const body = m[1];
  assert.doesNotMatch(body, /DOMParser/);

  // Run the function's OWN extracted body (not a re-typed copy of it), the
  // way the browser will: strip tags, collapse whitespace, trim.
  // eslint-disable-next-line no-new-func
  const strip = new Function("html", body) as (html: string) => string;
  assert.equal(strip("<h2>Engagement Letter</h2>\n<p>Dear {{client_name}},</p>"), "Engagement Letter Dear {{client_name}},");
});
