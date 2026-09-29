// Fixed Assets > Add Asset (and its sibling, Correct Asset) posted twice from
// one click. Run with:
//   node --experimental-strip-types --test scripts/a-single-click-cannot-create-two-assets.test.ts
//
// WHY THIS EXISTS
//     Both drawers' Save button had exactly one guard against a repeat
//     submission: `disabled={saving}`, driven by React state. State updates
//     are not synchronous — the DOM's `disabled` attribute does not flip
//     until React re-renders and commits, which happens AFTER the click
//     handler returns (or suspends at its first `await`), not before. Two
//     click events queued back to back — a stray duplicate dispatch, not a
//     deliberate double-click — are each processed to completion (JS is
//     single-threaded; the browser dispatches one event's listeners at a
//     time) before that commit ever lands, so BOTH invocations read `saving`
//     as it was before either one ran, both pass validation identically
//     (the form hasn't changed), and both reach the network — which is
//     exactly how one click on Add Asset produced two identical fixed
//     assets, each carrying the full entered cost, and how one click on
//     Correct Asset would reverse and re-post the same journal twice.
//
//     The fix is a ref, not more state: a ref is read and written on the
//     same synchronous tick as the call itself, with no render in between,
//     so the second of two back-to-back invocations sees it already set and
//     returns immediately — before it can validate, before it can touch
//     `saving`, before it can reach the network.
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

/** The body of a top-level `function NAME(...) { ... }` component.
 *
 *  These components take a destructured props object — `function Foo({ a, b
 *  }: {...})` — so the FIRST `{` after the name is the parameter list's own
 *  braces, not the function body's. The parens have to be balanced past
 *  first, or this reads the parameter object as the whole component and
 *  finds nothing of what is actually inside it. */
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
  for (let i = braceStart; i < code.length; i++) {
    if (code[i] === "{") depth++;
    else if (code[i] === "}") {
      depth--;
      if (depth === 0) return code.slice(braceStart, i + 1);
    }
  }
  throw new Error(`unterminated body for ${name}`);
}

/** The body of the first `async function save() { ... }` inside `body`. */
function saveBody(body: string): string {
  const start = body.indexOf("async function save()");
  assert.ok(start >= 0, "could not find async function save()");
  const braceStart = body.indexOf("{", start);
  let depth = 0;
  for (let i = braceStart; i < body.length; i++) {
    if (body[i] === "{") depth++;
    else if (body[i] === "}") {
      depth--;
      if (depth === 0) return body.slice(braceStart, i + 1);
    }
  }
  throw new Error("unterminated body for save()");
}

for (const component of ["AddAssetDrawer", "CorrectAssetDrawer"]) {
  const body = componentBody(component);
  const save = saveBody(body);

  test(`${component} declares a submission-in-progress ref`, () => {
    assert.match(body, /const submittingRef = useRef\(false\)/,
      `${component} must hold a ref, not only the \`saving\` STATE, to guard ` +
      "against a second call landing before React's own re-render commits " +
      "the disabled attribute");
  });

  test(`${component}'s save() checks the ref before anything else`, () => {
    const guardIdx = save.search(/if\s*\(\s*submittingRef\.current\s*\)\s*return;?/);
    assert.ok(guardIdx >= 0,
      `${component}.save() must return immediately when submittingRef is ` +
      "already set");
    // Nothing that could itself be a second write (setSaving, setError, the
    // request() call) may run before this check — the whole point is that a
    // second invocation is stopped before it does anything.
    const before = save.slice(0, guardIdx);
    assert.doesNotMatch(before, /setSaving\(true\)|await request(?:<[^>]*>)?\(/,
      "the ref check must come before setSaving/request, not after — a " +
      "guard placed after the point it is meant to guard protects nothing");
  });

  test(`${component}'s save() sets the ref before the request, and clears it in finally`, () => {
    assert.match(save, /submittingRef\.current\s*=\s*true;?[\s\S]*?await request(?:<[^>]*>)?\(/,
      "the ref must be set before the mutating request, not after");
    assert.match(save, /finally\s*\{\s*submittingRef\.current\s*=\s*false;/,
      "the ref must be cleared in finally so a legitimate later save is not " +
      "permanently blocked by an earlier attempt");
  });
}
