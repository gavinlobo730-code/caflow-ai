// The Year End workspace's header status chip (Draft / In Review / Approved /
// Locked) refreshes after an action that changes it, instead of only on the
// next full page load.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-year-end-status-badge-refreshes-after-a-review-action.test.ts
//
// WHAT WAS WRONG (sweep-client-inventory-docs-reports-05)
//     _workspace.tsx fetched the engagement for the header badge exactly once,
//     when engagementId changed, with no way for anything else to ask it to
//     fetch again. The Review tab's doAction() (Submit for Review, Approve,
//     Request Revision, Final Approve & Lock, Reopen) and the Checklist tab's
//     handleSubmitForReview() both really do flip the engagement's status on
//     the backend and log it in Review History — the tab's own view of the
//     data updates correctly — but the header chip next to the FY label kept
//     showing the old status for the rest of that session. A full reload (or
//     re-navigation) showed the right value, because that re-ran the one-time
//     fetch.
//
// THE FIX
//     The workspace exposes its own engagement fetch through a small context
//     (_engagementRefresh.tsx) that any stage rendered inside it can call.
//     Both tabs now call it after a mutation succeeds.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const DIR = "app/clients/[id]/year-end/[engagementId]";

function read(rel: string): string {
  return stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
}

test("the workspace fetch is exposed through a context, not re-implemented per stage", () => {
  const src = read(`${DIR}/_engagementRefresh.tsx`);
  assert.match(src, /export function useRefreshEngagement\(/);
  assert.match(src, /export const EngagementRefreshProvider/);
});

test("the workspace wraps the active stage in the refresh provider, fed by its own fetch", () => {
  const src = read(`${DIR}/_workspace.tsx`);
  assert.match(src, /const loadEngagement = useCallback\(/, "the fetch must be re-callable, not a one-shot effect body");
  assert.match(src, /<EngagementRefreshProvider value=\{loadEngagement\}>/);
  // The header's own one-time fetch on mount must still exist — this is an
  // addition, not a replacement.
  assert.match(src, /useEffect\(\(\) => \{ loadEngagement\(\); \}, \[loadEngagement\]\);/);
});

test("the Review tab refreshes the header after every successful action", () => {
  const src = read(`${DIR}/review/_page.tsx`);
  assert.match(src, /import \{ useRefreshEngagement \} from "\.\.\/_engagementRefresh"/);
  assert.match(src, /const refreshEngagement = useRefreshEngagement\(\);/);
  // doAction() has exactly one success path (shared by submit / approve /
  // requestRevision / finalApprove / reopen) — the call belongs right after
  // it, before the catch.
  assert.match(
    src,
    /setActionMsg\(\{ msg: "Action completed successfully\.", ok: true \}\);\s*\n\s*await load\(\);\s*\n\s*refreshEngagement\(\);/,
  );
});

test("the Checklist tab refreshes the header after a successful Submit for Review", () => {
  const src = read(`${DIR}/checklist/_page.tsx`);
  assert.match(src, /import \{ useRefreshEngagement \} from "\.\.\/_engagementRefresh"/);
  assert.match(src, /const refreshEngagement = useRefreshEngagement\(\);/);
  assert.match(
    src,
    /setSubmitMsg\("Submitted for review successfully\."\);\s*\n\s*refreshEngagement\(\);/,
  );
});

test("the guard is looking at real files", () => {
  for (const rel of [
    `${DIR}/_engagementRefresh.tsx`,
    `${DIR}/_workspace.tsx`,
    `${DIR}/review/_page.tsx`,
    `${DIR}/checklist/_page.tsx`,
  ]) {
    assert.ok(fs.existsSync(path.join(WEB, rel)), `expected ${rel} to exist`);
  }
});
