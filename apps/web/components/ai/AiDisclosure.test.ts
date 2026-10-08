// The AI disclosure, rendered (PRE-A-006). Run with:
//   node --experimental-strip-types --test components/ai/AiDisclosure.test.ts
//
// Same method as components/ui/page-header.test.ts: the REAL component is
// transpiled by the TypeScript compiler already in node_modules and rendered with
// react-dom/server through scripts/tsxHarness.ts. No browser, no layout, no pixels,
// and it says so. What it pins is what a person would be shown: the sentence for the
// surface that was asked for, in a span a checkbox's label can hold, and the
// caller's colour winning where the box it sits in is tinted.
import test from "node:test";
import assert from "node:assert/strict";
import type React from "react";
import { loadModule, requireFromWeb } from "../../scripts/tsxHarness.ts";
import { AI_DISCLOSURES, type AiDisclosureSurface } from "../../lib/ai/disclosure.ts";

const { renderToStaticMarkup } = requireFromWeb("react-dom/server") as typeof import("react-dom/server");
const React_ = requireFromWeb("react") as typeof import("react");

type Cmp = (p: { surface: AiDisclosureSurface; className?: string }) => React.ReactElement;
const { AiDisclosure } = loadModule<{ AiDisclosure: Cmp }>("components/ai/AiDisclosure");

const SURFACES = Object.keys(AI_DISCLOSURES) as AiDisclosureSurface[];

function render(surface: AiDisclosureSurface, className?: string): string {
  return renderToStaticMarkup(React_.createElement(AiDisclosure as never, { surface, className }));
}
/** The text a person reads: tags off, the entities React writes turned back. */
function text(html: string): string {
  return html.replace(/<[^>]*>/g, "")
    .replace(/&#x27;/g, "'").replace(/&quot;/g, "\"").replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">");
}

test("each surface renders its own sentence, once, and says which surface it is", () => {
  for (const s of SURFACES) {
    const html = render(s);
    assert.equal(text(html), AI_DISCLOSURES[s].sentence, s);
    assert.match(html, new RegExp(`data-ai-surface="${s}"`));
  }
});

test("it is a block span, not a paragraph: it has to fit inside the scan checkbox's label", () => {
  const html = render("statement_scan");
  assert.match(html, /^<span /);
  assert.doesNotMatch(html, /<p[ >]/);
  assert.match(html, /\bblock\b/);
});

test("by default it is readable text on white, at the size of the notes beside it", () => {
  const html = render("assistant");
  assert.match(html, /\btext-3xs\b/);
  assert.match(html, /\btext-ps-label\b/);
});

test("a caller's colour replaces the default, so the Extract box can use its own notes' ink", () => {
  const html = render("invoice_extraction", "text-state-attention");
  assert.match(html, /\btext-state-attention\b/);
  assert.doesNotMatch(html, /\btext-ps-label\b/);
  // …and the size is not lost to the colour (a merge that read the size as a colour would drop it).
  assert.match(html, /\btext-3xs\b/);
});

test("an id is passed through, so the control it is about can describe itself by it", () => {
  const html = renderToStaticMarkup(React_.createElement(AiDisclosure as never, { surface: "invoice_extraction", id: "note-1" }));
  assert.match(html, /^<span id="note-1" /);
  assert.doesNotMatch(render("invoice_extraction"), /\sid=/);
});

test("no surface renders an empty notice", () => {
  for (const s of SURFACES) assert.ok(text(render(s)).trim().length > 40, s);
});
