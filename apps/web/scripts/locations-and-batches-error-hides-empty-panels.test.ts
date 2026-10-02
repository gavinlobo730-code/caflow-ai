/**
 * apex-bank-assets-inventory-10.
 *
 * WHAT WAS WRONG
 *     `error` was set in the catch block and rendered as a banner, but the
 *     component only early-returned on `loading` — not on `error` — so when
 *     the fetch genuinely failed, execution fell through and rendered the
 *     Godowns / Stock-by-godown-and-lot / Lots sub-panels from their
 *     untouched EMPTY initial state, indistinguishable on screen from a
 *     client that genuinely has no data recorded.
 *
 * THE FIX
 *     An early return, right after the `loading` one, that renders the error
 *     banner ALONE when there is no cached prior data for any of the three
 *     lists — `error && !godowns.length && !detail.length && !batches.length`
 *     — so a failed reload after a SUCCESSFUL one still shows what was last
 *     loaded (with the banner on top), and only a failure with truly nothing
 *     to fall back on hides the misleading empty-state panels.
 *
 * Run with:
 *   node --experimental-strip-types --test scripts/locations-and-batches-error-hides-empty-panels.test.ts
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = path.join(WEB, "components", "inventory", "LocationsAndBatches.tsx");

function src(): string {
  return stripComments(fs.readFileSync(FILE, "utf8"));
}

test("an early return renders the error banner alone when there is nothing cached", () => {
  const s = src();
  assert.match(s,
    /if \(error && !godowns\.length && !detail\.length && !batches\.length\) \{/,
    "the guard must check all three lists, not just one");
});

test("the error-only return sits between the loading guard and the main render", () => {
  const s = src();
  const loadingAt = s.indexOf("if (loading) return <TableSkeleton />;");
  const errorGuardAt = s.indexOf("if (error && !godowns.length && !detail.length && !batches.length) {");
  // The panel's own empty-state text. It was a bare paragraph ending in a full
  // stop and is now the title of the shared EmptyState (frontend_ux-24), so the
  // rule is asked of the WORDS, not of how the sentence happened to be punctuated.
  const godownsEmptyAt = s.indexOf("No godowns recorded");
  assert.ok(loadingAt >= 0, "the loading guard must still exist");
  assert.ok(errorGuardAt > loadingAt,
    "the error guard must come after the loading guard, not before it");
  assert.ok(godownsEmptyAt > errorGuardAt,
    "the error guard must come before the Godowns panel's own empty-state text, " +
    "so a genuine failure is caught before it falls through to a false empty state");
});

test("the error-only branch actually returns and does not merely set a flag", () => {
  const s = src();
  const at = s.indexOf("if (error && !godowns.length && !detail.length && !batches.length) {");
  const body = s.slice(at, at + 400);
  assert.match(body, /return \(/, "the guard must short-circuit the render, not just annotate it");
  assert.match(body, /role="alert"/, "the standalone error state must still be announced to assistive tech");
  assert.doesNotMatch(body.slice(0, body.indexOf("return (")), /No godowns recorded/,
    "the guard must not itself render any of the misleading empty-state copy");
});
