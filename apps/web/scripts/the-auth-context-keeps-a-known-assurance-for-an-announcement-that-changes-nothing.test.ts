// The auth context does not unresolve the sign-in assurance for an announcement that cannot have changed which session this is
// (POST-A-493), and reads everything else afresh exactly as before.
//
// Run with:
//   node --experimental-strip-types --test scripts/the-auth-context-keeps-a-known-assurance-for-an-announcement-that-changes-nothing.test.ts
//
// WHAT WAS WRONG. onAuthStateChange set the assurance to null on EVERY announcement and AuthGuard draws nothing for null, so a
// page was unmounted and mounted again when a tab regained focus, every hour at the token refresh and after a password was
// saved: what was typed was lost and a message set by a request already in flight was set on a page that had gone. Reproduced in a
// real browser with the sign-in service's account lookup held for a second (drive group auth-announcements).
//
// THE RULES (source guards; the decision itself is tested in lib/auth/assuranceCarry.test.ts and the behaviour in the drive):
//   1. the handler asks `mayKeepAssurance` and sets the assurance to null ONLY when it answers no;
//   2. there is no other place that sets the assurance to null except the initial read of the stored session;
//   3. every read goes through `readAssurance`, which remembers what it was read for and treats a failed read as "owed";
//   4. the guard still draws nothing for an unresolved assurance: the fail-closed rule is not touched.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const WEB = path.resolve(import.meta.dirname, "..");
const code = (rel: string) => fs.readFileSync(path.join(WEB, rel), "utf8")
  .replace(/\/\*[\s\S]*?\*\//g, " ").replace(/^\s*\/\/.*$/gm, " ");
const CONTEXT = code("lib/auth/AuthContext.tsx");

test("the handler keeps a known assurance only when the rule says the session cannot have changed", () => {
  assert.match(CONTEXT, /mayKeepAssurance\(\{ event: _event, known: assuranceKnown\.current, nextUserId, nextAccessToken \}\)/);
  assert.match(CONTEXT, /\} else \{\s*assuranceKnown\.current = \{ userId: nextUserId, accessToken: nextAccessToken, pending: null \};\s*setMfaPending\(null\);\s*\}/,
    "the 'not recognised as unchanged' branch no longer sets the assurance to unresolved");
});

test("the assurance is set to unresolved in exactly two places: the stored session at start, and an announcement the rule does not keep", () => {
  const nulls = CONTEXT.match(/setMfaPending\(null\)/g) ?? [];
  assert.equal(nulls.length, 2, `setMfaPending(null) appears ${nulls.length} times`);
});

test("every read goes through readAssurance, which remembers what it was read for and fails closed", () => {
  assert.equal((CONTEXT.match(/resolveMfaPending\(/g) ?? []).length, 2, "resolveMfaPending is called from somewhere other than its definition and readAssurance");
  assert.match(CONTEXT, /resolveMfaPending\(forSession\)\.then\(settle\)\.catch\(\(\) => settle\(true\)\)/);
  assert.match(CONTEXT, /assuranceKnown\.current = \{ userId, accessToken, pending \};\s*setMfaPending\(pending\);/);
});

test("the guard still draws nothing for an unresolved assurance", () => {
  const guard = code("lib/auth/guardDecision.ts");
  assert.match(guard, /if \(!onLogin && mfaPending !== false\) return false;/, "a protected page is drawn for something other than a resolved 'no challenge owed'");
  assert.match(code("lib/auth/AuthGuard.tsx"), /mayRenderProtected\(/);
});
