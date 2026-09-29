// components/gst/Gstr9cWorking.tsx's loadReconciliation() catches its own
// failures instead of leaving an uncaught promise rejection and a form that
// silently falls back to "not recorded".
//
// Run with:
//   node --experimental-strip-types --test scripts/gstr9c-working-reports-a-load-failure.test.ts
//
// WHAT WAS WRONG
//     loadReconciliation had no catch clause at all, so any of its several
//     awaited calls throwing (a network error, a malformed response) became
//     an uncaught promise rejection, and the effect that calls it
//     (`useEffect(() => { ...; loadReconciliation(); }, [...])`) never learns
//     the load failed — the form simply stayed on emptyForm(), which a CA
//     reads as "nothing recorded yet" rather than "the load failed".
//
// THE FIX
//     loadReconciliation now has its own try/catch/finally, setting
//     `loadError` on failure and clearing it at the start of each attempt;
//     the screen renders a Callout with a Retry button while loadError is
//     set, and the effect keeps a backstop .catch() for a rejection that
//     somehow occurs before the try block runs.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const FILE = "components/gst/Gstr9cWorking.tsx";

function code(rel: string): string {
  return fs.readFileSync(path.join(ROOT, rel), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
}

test("loadReconciliation has its own try/catch and records a loadError state", () => {
  const src = code(FILE);
  assert.match(src, /const \[loadError, setLoadError\] = useState<string \| null>\(null\)/,
    "a loadError state must exist to distinguish 'load failed' from 'nothing recorded'");
  assert.match(src, /const loadReconciliation = useCallback\(async \(\) => \{\s*setLoadingRecon\(true\);\s*setLoadError\(null\);/,
    "loadError must be cleared at the START of every attempt");
  assert.match(src, /\} catch \(e\) \{\s*setLoadError\(/,
    "and set on failure inside loadReconciliation's own try block");
});

test("the effect keeps a backstop catch so a rejection never reaches the console uncaught", () => {
  const src = code(FILE);
  assert.match(src, /loadReconciliation\(\)\.catch\(\(\) => setLoadError\(/,
    "the effect must not call loadReconciliation() bare");
  // NEGATIVE CONTROL: the old effect called it with no .catch at all.
  assert.doesNotMatch(src, /loadReconciliation\(\);\s*\n\s*\/\/ eslint-disable-next-line react-hooks\/exhaustive-deps/,
    "the bare, uncaught call must be gone");
});

test("a load failure renders as an error with a way to retry, not a silently empty form", () => {
  const src = code(FILE);
  assert.match(src, /if \(loadError && !loadingRecon\) \{/,
    "the error state must gate a dedicated render branch");
  assert.match(src, /onClick=\{loadReconciliation\}/,
    "and offer a retry rather than leaving the CA stuck");
});
