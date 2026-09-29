// Fixed Assets > Disposal preview showed a P&L computed WITHOUT the GST rate
// the CA had just picked. Run with:
//   node --experimental-strip-types --test scripts/the-disposal-preview-drops-a-stale-response.test.ts
//
// WHY THIS EXISTS
//     The preview effect debounces with setTimeout + clearTimeout, which
//     cancels a PENDING timer — but a timer that has already fired is an
//     in-flight fetch, and clearTimeout cannot cancel that. Typing the sale
//     proceeds, then answering "is this a supply?", then picking a GST rate
//     — each change more than 400ms apart, an entirely ordinary pace — fires
//     one request per change. Network timing is not FIFO: the FIRST request
//     (no GST rate yet) can resolve AFTER the LAST one (GST rate included)
//     and overwrite `preview` with the stale, GST-less answer — the panel
//     then shows a loss computed on the gross proceeds where the actual
//     disposal, netting the tax out, posts a materially larger one.
//     `knowledge-search-is-debounced-and-drops-stale-responses.test.ts`
//     fixed the identical shape (stale keystroke response overwriting a
//     newer one) in the client Knowledge Base search; this is the same
//     defect in a different screen.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const PAGE_FILE = "app/clients/[id]/fixed-assets/page.tsx";
const src = fs.readFileSync(path.join(ROOT, PAGE_FILE), "utf8");
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

function componentBody(name: string): string {
  const start = code.indexOf(`function ${name}(`);
  assert.ok(start >= 0, `could not find function ${name}`);
  let parenDepth = 0, i = start;
  for (; i < code.length; i++) {
    if (code[i] === "(") parenDepth++;
    else if (code[i] === ")" && --parenDepth === 0) { i++; break; }
  }
  const braceStart = code.indexOf("{", i);
  let depth = 0;
  for (i = braceStart; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") {
      depth--;
      if (depth === 0) return code.slice(braceStart, i + 1);
    }
  }
  throw new Error(`unterminated body for ${name}`);
}

const disposalTab = componentBody("DisposalTab");

test("DisposalTab holds a ref tracking the latest-fired preview request", () => {
  assert.match(disposalTab, /const latestPreviewRequest = useRef\(0\)/,
    "no request-generation ref found — without one, nothing can tell a " +
    "stale response for an earlier set of disposal terms apart from the " +
    "current one");
});

test("the request id is minted where the fetch actually fires, not once per keystroke", () => {
  // Inside the setTimeout callback, after the debounce has elapsed — a
  // cancelled (never-fired) timer must not consume an id, and more
  // importantly the id has to be assigned right where the fetch begins.
  assert.match(disposalTab,
    /window\.setTimeout\(async \(\) => \{\s*const requestId = \+\+latestPreviewRequest\.current;/,
    "the request id must be minted at the top of the debounced callback, " +
    "immediately before building the query — not outside the timeout, " +
    "where a cancelled timer would still consume an id for a fetch that " +
    "never went out");
});

test("setPreview is only called when the response's request is still the latest one", () => {
  const guardCount = (disposalTab.match(
    /if \(latestPreviewRequest\.current !== requestId\) return;/g) ?? []).length;
  assert.ok(guardCount >= 2,
    `found only ${guardCount} stale-response guard(s); both the success ` +
    "path (setPreview from j.data) and the failure path (setPreview(null)) " +
    "must each check this before writing, or a slow failure for an old " +
    "request can still clobber a fast success for a new one");
});

test("the success path's setPreview sits after its own guard, not before it", () => {
  const successIdx = disposalTab.search(/setPreview\(j\.success/);
  assert.ok(successIdx >= 0, "could not find the success-path setPreview call");
  const guardIdx = disposalTab.lastIndexOf(
    "if (latestPreviewRequest.current !== requestId) return;", successIdx);
  assert.ok(guardIdx >= 0 && guardIdx < successIdx,
    "the stale-response guard must run BEFORE setPreview(j.data...), or it " +
    "guards nothing");
});
