/**
 * apex-bank-assets-inventory-08.
 *
 * WHAT WAS WRONG
 *     Three independent effects fired on mount: one called `loadRows()`, one
 *     called `loadCounts()`, and a third invoked `settle()` — which ITSELF
 *     called `loadCounts()` again at its own top, and unconditionally called
 *     `reload()` (= `Promise.all([loadCounts(), loadRows({quiet:true})])`) in
 *     its `finally` block, even when settle found nothing undrafted and no
 *     trusted rule had anything pending. Net result on a single page load:
 *     counts fetched up to THREE times and rows up to TWO times.
 *
 * THE FIX
 *     Two changes, neither touching how or when either mount effect fires
 *     (an existing test — "settle runs on open, not on every filter/search/
 *     page change" — polices that wiring exactly, because settle must stay
 *     pinned to `[clientId]` alone and never to its own reactive identity):
 *
 *       1. `loadCounts` shares ONE in-flight request: a second call arriving
 *          before the first has resolved gets back the SAME promise instead
 *          of firing a second one. The counts effect and settle's own first
 *          `loadCounts()` call happen within the same tick on mount, so this
 *          collapses them into a single network request without changing
 *          settle's signature or either effect's dependency array.
 *       2. settle's trailing `reload()` is now conditional on something
 *          having actually changed (the undraft loop having run, or a
 *          trusted rule having passed something), rather than firing
 *          unconditionally on every call.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/entries-tab-settles-once-per-mount.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const TAB = path.join(WEB, "components", "banking", "EntriesTab.tsx");

function src(): string {
  return stripComments(fs.readFileSync(TAB, "utf8"));
}

/** A named function's body, isolated so a check phrased against it cannot
 *  accidentally match some other function on the page. */
function body(s: string, startMarker: string, endMarker: string): string {
  const at = s.indexOf(startMarker);
  assert.ok(at >= 0, `"${startMarker}" was not found`);
  const decl = s.slice(at);
  const end = decl.indexOf(endMarker);
  assert.ok(end > 0, `"${endMarker}" was not found after "${startMarker}"`);
  const b = decl.slice(0, end);
  assert.ok(b.length > 100, `the extracted body for "${startMarker}" looks too short`);
  return b;
}

test("loadCounts shares one in-flight request instead of firing a second while the first is pending", () => {
  const b = body(src(), "const loadCounts = useCallback(async () => {", "}, [clientId, bankAccountId]);");
  assert.match(b, /if \(inflightCountsRef\.current\) return inflightCountsRef\.current;/,
    "a call arriving while one is already in flight must reuse it, not start a second request");
  assert.match(b, /inflightCountsRef\.current = promise;/,
    "the in-flight promise must be recorded before anything awaits it");
  assert.match(b, /finally \{\s*inflightCountsRef\.current = null;\s*\}/,
    "the slot must be cleared once the real request settles, so the NEXT genuine refresh is not deduped forever");
});

test("settle's trailing reload() is conditional on something having changed, not unconditional", () => {
  const b = body(src(), "const settle = useCallback(async () => {", "}, [clientId, loadCounts, reload]);");
  assert.match(b, /if \(changedSomething\) await reload\(\);/,
    "the finally block must only reload when something was actually proposed or passed");
  assert.match(b, /changedSomething = true;/,
    "something must actually flip the flag when the undraft loop or a trusted pass runs");
  // The bug's exact shape, scoped to settle alone: passAllReady legitimately
  // reloads unconditionally after a bulk pass, and a check that was not
  // scoped to settle's own body would wrongly match that instead.
  assert.doesNotMatch(b,
    /finally \{\s*setProgress\(null\);\s*busyRef\.current = false;\s*await reload\(\);\s*\}/,
    "settle must not unconditionally reload every time it runs");
});

test("settle keeps its original no-argument signature and mount wiring untouched", () => {
  // This is the invariant scripts/bank-entries-is-a-table.test.ts already
  // polices: settle must be triggered by an effect pinned to [clientId]
  // alone, via a ref, never by an effect that depends on settle's own
  // identity (which carries every filter it closes over). Re-asserted here,
  // scoped to this finding, so a regression on THIS fix is caught by name.
  const s = src();
  const at = s.indexOf("const settle = useCallback(");
  assert.ok(at > 0, "settle is not declared");
  assert.match(s.slice(at),
    /useEffect\(\(\) => \{[\s\S]{0,200}settleRef\.current\(\);[\s\S]{0,40}\}, \[clientId\]\);/,
    "the effect that runs settle on open must still depend on [clientId] alone");
  assert.match(s, /onClick=\{settle\}/,
    "the Propose button must still call settle directly — its signature did not change");
});
