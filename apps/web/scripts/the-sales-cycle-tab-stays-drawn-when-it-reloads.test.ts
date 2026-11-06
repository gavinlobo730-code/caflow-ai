// THE SALES CYCLE TAB STAYS DRAWN WHEN IT RELOADS, AND THE PANEL INSIDE IT IS TOLD TO READ AGAIN (POST-A-385). Run with:
//   node --experimental-strip-types --test scripts/the-sales-cycle-tab-stays-drawn-when-it-reloads.test.ts
//
// THE DEFECT. `SalesCycleTab.load()` set `loading` on every read and the component returned "Loading…" in place of itself while it was set. The FORM GST ITC-04 panel is inside the tab and calls
// `onChanged` (the tab's reload) after it records a lot, so the reload unmounted the panel it was called from: the line it had just said ("Recorded. That was the last lot — the challan is now
// marked received back and its s.143 clock has stopped."), the year and window the person had chosen and any other open lot form were lost, and the person saw the list change without being
// told that it had worked.
//
// THE FIRST FIX WAS HALF OF IT, and a review found the other half: the unmount and remount was also, by accident, the only thing that made the panel READ ITS STATEMENT AGAIN after the tab's
// own writes ("Record goods back" on a whole challan, a new job-work challan), so a tab that stayed drawn showed a statement that was no longer the books'. The panel now takes a
// `refreshToken` prop that the tab bumps when a reload has landed, and reads again when it changes: a PROP and not a React `key`, because a key would unmount it again.
//
// THE RULE.
//  1. The tab blocks with "Loading…" for the first read of a CLIENT's lists and for no read after it: the block is conditional on a ref that records which client the lists belong to, and the
//     ref is set only when a read CAME BACK. A failed read, first or later, resets it, so "Try again" blocks again and never shows lists that were not read as empty ones or the last, stale ones.
//     A tab reused for another client blocks again, because it must not show the last client's lists while the new ones load.
//  2. The panel is told a reload landed (`refreshToken`) and reads again on a change, and is never keyed on a reload.
//  3. A reload can be asked for while an earlier one is in flight (the panel does not wait for it): the answer to the LAST question is the one applied, and only the last read releases "Loading…".
//
// WHAT THIS CANNOT SEE. That the panel keeps its line and re-reads in a browser: that is the date drive's `itc04-the-last-lot-recorded-keeps-the-panel-drawn-and-its-success-line-is-seen` and
// `itc04-marking-a-whole-challan-back-reads-the-panel-again`.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = fs.readFileSync(path.join(WEB, "components/sales/SalesCycleTab.tsx"), "utf8");
const PANEL = fs.readFileSync(path.join(WEB, "components/gst/Itc04Panel.tsx"), "utf8");

/** The text of the `load` callback: from `const load = useCallback(` to its dependency list. */
function loadBody(src: string): string {
  const start = src.indexOf("const load = useCallback(");
  assert.ok(start > 0, "the tab has no load callback");
  const end = src.indexOf("}, [clientId]);", start);
  assert.ok(end > start, "the load callback no longer ends with its dependency on the client");
  return src.slice(start, end);
}

test("the tab blocks with Loading… only for the first read of a client's lists", () => {
  const body = loadBody(TAB);
  assert.match(body, /if \(loadedFor\.current !== clientId\) setLoading\(true\);/, "the block is not conditional on whether this client's lists were read");
  assert.equal((body.match(/setLoading\(true\)/g) ?? []).length, 1, "something else still blocks the tab on a reload");
  assert.match(TAB, /const loadedFor = useRef<string \| null>\(null\);/, "the ref that records which client the lists belong to is gone");
});

test("a read counts as the first only when it came back, and a failed one makes the next a first read again", () => {
  const body = loadBody(TAB);
  const tryPart = body.slice(body.indexOf("try {"), body.indexOf("} catch"));
  assert.match(tryPart, /loadedFor\.current = clientId;/, "a read that came back does not record the client");
  const rest = body.slice(body.indexOf("} catch"));
  assert.doesNotMatch(rest, /loadedFor\.current = clientId/, "a failed read records the client: Try again would show lists that were never read as empty ones");
  assert.match(rest, /loadedFor\.current = null;/, "a failed read does not reset the record: Try again would redraw the last, stale lists with no sign a read is in flight");
  assert.match(rest, /setLoadFailed\(true\)/, "a failed read is no longer answered");
});

test("the early return still blocks the first read, and nothing else keys the tab's mounting on a reload", () => {
  assert.match(TAB, /if \(loading\) \{\s*return <div className="p-6 text-sm text-ps-hint">Loading…<\/div>;\s*\}/, "the first read no longer shows Loading…");
  assert.match(TAB, /<Itc04Panel clientId=\{clientId\} onChanged=\{\(\) => void load\(\)\} refreshToken=\{itc04Refresh\} \/>/, "the panel is not told a reload landed, or no longer asks the tab to reload after a lot");
  assert.doesNotMatch(TAB, /key=\{[^}]*(loading|reload|nonce|itc04Refresh)[^}]*\}/, "the tab or the panel is keyed on a reload: that remounts the panel as the early return did");
});

test("the panel is told when a reload has landed, and reads its statement again on a change (not a key)", () => {
  const body = loadBody(TAB);
  assert.match(TAB, /const \[itc04Refresh, setItc04Refresh\] = useState\(0\);/, "the tab holds no refresh token");
  const tryPart = body.slice(body.indexOf("try {"), body.indexOf("} catch"));
  assert.match(tryPart, /setItc04Refresh\(\(n\) => n \+ 1\);/, "a reload that landed does not bump the token");
  assert.match(PANEL, /refreshToken\?: number;/, "the panel takes no refresh token");
  assert.match(PANEL, /const seenToken = useRef\(refreshToken\);/, "the panel does not remember the token it has seen: its first value would count as a change");
  assert.match(PANEL, /useEffect\(\(\) => \{\s*if \(seenToken\.current === refreshToken\) return;\s*seenToken\.current = refreshToken;\s*void load\(\);\s*\}, \[refreshToken, load\]\);/,
    "the panel does not read its statement again when the token changes");
});

test("an answer to an earlier question is not applied over the last one", () => {
  const body = loadBody(TAB);
  assert.match(TAB, /const latestRead = useRef\(0\);/, "the tab keeps no count of its reads");
  assert.match(body, /const mine = \+\+latestRead\.current;/, "a read does not take its place in the count");
  assert.match(body, /if \(mine !== latestRead\.current\) return;\s*\/\/[^\n]*\n\s*if \(v\.success/, "a stale answer is applied before the lists are read out of it");
  assert.match(body, /finally \{\s*if \(mine === latestRead\.current\) setLoading\(false\);/, "a stale read releases Loading… for a later one that is still in flight");
});
