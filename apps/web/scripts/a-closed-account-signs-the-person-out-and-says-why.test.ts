// A closed account is signed out at once and told why; a destructive platform action asks for a fresh code.
//
// Run with:
//   node --experimental-strip-types --test scripts/a-closed-account-signs-the-person-out-and-says-why.test.ts
//
// WHAT WAS WRONG (POST-A-482, POST-A-484; read in the code on 19-11-2026 after the owner's live testing)
//     A platform administrator's suspend, soft delete or purge only flipped the firm's flags, so its people stayed
//     signed in on screens the API now refused, and the browser had no handler for the refusal (403 "Firm suspended",
//     "Firm unavailable", "Account disabled", 401 "Session revoked"). The platform page's destructive actions ran on a
//     session that had passed the second factor once, however long ago.
//
// THE RULES (the decisions are unit-tested in lib/auth; the server half is apps/api/tests/test_closing_a_firm_ends_…)
//     1. the request helper decides by closedAccountReason() on every refusal and ends the session through ONE
//        function that signs out, goes to the closed-account page, and never does it twice or from that page;
//     2. the closed-account page is reachable signed out (a public path) and speaks only closedAccountWords();
//     3. the platform page's suspend and soft delete go through withFreshCode, and the permanent delete proves a
//        code (stepUpWithCode) right before it asks.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { isPublicPath } from "../lib/auth/public-paths.ts";

const WEB = path.resolve(import.meta.dirname, "..");
function code(rel: string): string {
  const src = fs.readFileSync(path.join(WEB, rel), "utf8");
  return src.replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ").replace(/\{\s*\/\*[\s\S]*?\*\/\s*\}/g, " ");
}

test("the request helper signs a closed account out on the refusal, through one guarded function", () => {
  const src = code("lib/api/index.ts");
  assert.match(src, /const closed = closedAccountReason\(res\.status, message\);\s*if \(closed\) void endSessionBecause\(closed\);/);
  const fn = /async function endSessionBecause\(reason: ClosedAccountReason\): Promise<void> \{([\s\S]*?)\n\}/.exec(src);
  assert.ok(fn, "endSessionBecause was not found");
  assert.match(fn[1], /if \(endingSession \|\| typeof window === "undefined"\) return;/);
  assert.match(fn[1], /if \(isAlreadyOutside\(window\.location\.pathname\)\) return;/);
  assert.match(fn[1], /supabase\.auth\.signOut\(\)/);
  assert.match(fn[1], /window\.location\.assign\(closedAccountPath\(reason\)\)/);
});

test("the closed-account page is reachable signed out and says only what closedAccountWords says", () => {
  assert.equal(isPublicPath("/auth/account-closed/"), true);
  const src = code("app/auth/account-closed/page.tsx");
  assert.match(src, /closedAccountWords\(why\)/);
  assert.match(src, /new URLSearchParams\(window\.location\.search\)\.get\("why"\)/);
});

test("the platform page asks for a fresh code on suspend and soft delete, and proves one before a permanent delete", () => {
  const src = code("app/platform/page.tsx");
  assert.match(src, /act\(\(\) => withFreshCode\(\(\) => api\.platform\.suspend\(/);
  assert.match(src, /act\(\(\) => withFreshCode\(\(\) => api\.platform\.softDelete\(/);
  assert.match(src, /isFreshCodeRefusal\(e\.message\)/);
  const purge = /async function confirmPurge\(\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(purge, "confirmPurge was not found");
  assert.match(purge[1], /await stepUpWithCode\(code\);[\s\S]*?api\.platform\.purge\(/);
});
