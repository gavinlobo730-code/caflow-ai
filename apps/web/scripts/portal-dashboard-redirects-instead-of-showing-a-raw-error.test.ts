// Revisiting /portal/dashboard with no live session lands on /portal/login,
// never on a raw backend error string.
//
// Run with:
//   node --experimental-strip-types --test scripts/portal-dashboard-redirects-instead-of-showing-a-raw-error.test.ts
//
// WHAT WAS WRONG
//     app/portal/dashboard/page.tsx's mount effect polled
//     supabase.auth.getSession() up to 10 times, then called
//     api.portalSelf.memberships() UNCONDITIONALLY — even when the loop never
//     found a session at all (a stale tab left open after sign-out, a
//     bookmark, a refresh with nothing to restore). The 401 that call drew
//     back was caught and rendered with `setError(e.message)`, straight onto
//     the page: no header, no nav, no link to sign in — just
//     "Missing or invalid Authorization header".
//
// THE FIX
//     If the polling loop never finds a session, the page redirects to
//     /portal/login immediately and never calls the API at all. And if the
//     API call fails anyway (a session found a moment ago is stale or
//     revoked by the time the request lands), the handler re-checks the
//     session before deciding what to show: no session there either means
//     the same redirect, and only a genuine, session-holding failure falls
//     through to the existing error banner.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const raw = fs.readFileSync(path.join(WEB, "app/portal/dashboard/page.tsx"), "utf8");
const src = stripComments(raw);

/** The mount effect's own body — from its useEffect(() => { down to the
 *  effect array that closes it (`// eslint-disable-next-line react-hooks/exhaustive-deps\n  }, []);`
 *  is unique to this one effect in the file). */
function mountEffectBody(): string {
  const start = src.indexOf("useEffect(() => {\n    let cancelled = false;");
  assert.ok(start !== -1, "could not find the mount effect");
  const end = src.indexOf("}, []);", start);
  assert.ok(end !== -1, "could not find the mount effect's closing deps array");
  return src.slice(start, end);
}

test("no session after polling means a redirect, never a call to the API", () => {
  const body = mountEffectBody();
  // The redirect to /portal/login must appear BEFORE the memberships() call
  // in source order — i.e. the API call is inside a branch that is only
  // reached once a session has actually been found.
  const redirectAt = body.indexOf('router.replace("/portal/login")');
  const apiCallAt = body.indexOf("api.portalSelf.memberships()");
  assert.notEqual(redirectAt, -1, "no redirect to /portal/login in the mount effect");
  assert.notEqual(apiCallAt, -1, "memberships() call not found");
  assert.ok(redirectAt < apiCallAt,
    "the redirect must guard the API call, not merely exist somewhere after it");
});

test("a failed API call re-checks the session before rendering anything", () => {
  const body = mountEffectBody();
  const catchAt = body.indexOf("} catch (e) {");
  assert.notEqual(catchAt, -1, "no catch block in the mount effect");
  const catchBody = body.slice(catchAt, body.indexOf("} finally {", catchAt));
  assert.match(catchBody, /getSession\(\)/,
    "the catch block does not re-check the session before deciding what to render");
  assert.match(catchBody, /router\.replace\("\/portal\/login"\)/,
    "a stale/revoked session on the catch path does not redirect to login");
});

test("setError still exists for a genuine, session-holding failure", () => {
  // The fix narrows setError's callers; it must not disappear outright, or a
  // real backend failure with a live session would render nothing at all.
  assert.match(src, /setError\(e instanceof Error \? e\.message/,
    "setError(e.message) path removed entirely rather than narrowed");
});
