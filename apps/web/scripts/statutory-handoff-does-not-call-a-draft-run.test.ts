// StatutoryHandoff.tsx only calls api.payroll.runHandoff(runId) for a
// finalised or paid run — the same predicate its own render-gating message
// already used (apex-payroll-yearend-08).
//
// Run with:
//   node --experimental-strip-types --test \
//     scripts/statutory-handoff-does-not-call-a-draft-run.test.ts
//
// WHAT WAS WRONG
//     load() called api.payroll.runHandoff(runId) unconditionally on mount
//     and on every run change — the render-gating check just below it
//     ("This month is still a draft…") only decided what to SHOW, never
//     whether to make the call at all. So opening a draft or review month
//     always fired the request, got back a bare FastAPI {"detail": ...} body
//     (before the backend fix), and logged a console error for a state this
//     component could already see without asking.
//
// THE FIX
//     `isReleased` is computed once, from `run`, and reused both to gate the
//     call inside load() and to decide the render-time message — one
//     predicate rather than two copies of it.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const FILE = "components/payroll/StatutoryHandoff.tsx";

function read(): string {
  return stripComments(fs.readFileSync(path.join(WEB, FILE), "utf8"));
}

test("isReleased is computed once from run.status", () => {
  const src = read();
  assert.match(
    src,
    /const isReleased = !!run && \(run\.status === "finalized" \|\| run\.status === "paid"\)/,
  );
});

test("load() refuses to call runHandoff unless the run is released", () => {
  const src = read();
  const m = /const load = useCallback\(async \(\) => \{([\s\S]*?)\}, \[runId, isReleased\]\);/.exec(src);
  assert.ok(m, "load() (with isReleased as a dependency) not found");
  const body = m[1];
  assert.match(body, /if \(!runId \|\| !isReleased\) \{ setHandoff\(null\); return; \}/);
  // runHandoff must be called only after that guard, not before it.
  const guardIdx = body.indexOf("if (!runId || !isReleased)");
  const callIdx = body.indexOf("api.payroll.runHandoff(runId)");
  assert.ok(guardIdx !== -1 && callIdx !== -1 && guardIdx < callIdx);
});

test("the render-gating message reuses isReleased rather than re-deriving it", () => {
  const src = read();
  assert.match(src, /\{run && !isReleased\s*\n?\s*\?\s*"This month is still a draft\./);
  // The old, duplicated predicate must be gone.
  assert.doesNotMatch(
    src,
    /run && run\.status !== "finalized" && run\.status !== "paid"/,
  );
});
