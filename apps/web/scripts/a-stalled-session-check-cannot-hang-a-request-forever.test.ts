// request()'s pre-fetch auth check is bounded. Run with:
//   node --experimental-strip-types --test scripts/a-stalled-session-check-cannot-hang-a-request-forever.test.ts
//
// WHY THIS EXISTS
//     Every call through lib/api's request() awaited `supabase.auth
//     .getSession()` before ever reaching fetchWithTimeout's own 45s budget —
//     and that await had no timeout of its own. Nothing bounds
//     `await this.initializePromise` inside auth-js, so a stalled auth client
//     (lock contention across many concurrent tabs sharing one session is the
//     observed case) left request() awaiting forever: no fetch issued, no
//     error thrown, nothing for a caller's try/catch/finally to react to,
//     because nothing had settled. Two screens that only call through
//     request() showed it directly — the Multi-currency page never issued its
//     first request and sat on its skeleton loaders forever, and the
//     Statutory Values "Record a notification" form sat on a disabled
//     "Saving…" button forever, with the backend never even receiving the
//     PUT.
//
//     The fix is a bounded race, not a retry: getSession() now runs against a
//     timeout that REJECTS with a readable message, so request() always
//     settles — either with a real session, or with an error the caller's
//     existing catch already knows how to show.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.join(import.meta.dirname, "..");
const API_FILE = "lib/api/index.ts";
const src = fs.readFileSync(path.join(ROOT, API_FILE), "utf8");

/** Comments stripped — this file's own note above quotes the bug it fixes. */
const code = src
  .replace(/\/\*[\s\S]*?\*\//g, "")
  .replace(/^\s*\/\/.*$/gm, "");

/** The body of request(), isolated so assertions about it cannot accidentally
 *  match sessionTokenWithTimeout's own body, refreshSession's 401 branch, or
 *  one of the other unrelated getSession() call sites further down this
 *  10,000-line file (file upload helpers each manage their own token). */
function functionBody(name: string): string {
  // `request<T>(...)` carries a generic between the name and the paren, so
  // this cannot require the paren immediately after the name.
  const start = code.indexOf(`function ${name}`);
  assert.ok(start >= 0, `could not find function ${name}`);
  const braceStart = code.indexOf("{", start);
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

const requestBody = functionBody("request");
const helperBody = functionBody("sessionTokenWithTimeout");

test("request() does not await getSession() directly", () => {
  // It must go through the bounded helper instead, or the timeout below
  // protects nothing.
  assert.doesNotMatch(requestBody, /supabase\.auth\.getSession/,
    "request() must resolve the token through the bounded helper, not a bare " +
    "getSession() call with no timeout");
  assert.match(requestBody, /await sessionTokenWithTimeout\(\)/);
});

test("the helper races getSession() against a bounded timeout", () => {
  assert.match(helperBody, /Promise\.race\(\s*\[\s*supabase\.auth\.getSession\(\)/,
    "a stalled getSession() must lose a race, not be awaited on its own");
});

test("the timeout rejects — a stall becomes a readable error, not a silent hang", () => {
  // A timeout that RESOLVES (e.g. with an empty session) would make request()
  // silently proceed as an anonymous call instead of telling the caller
  // anything failed. It must reject, and with a message a caller's existing
  // `e instanceof Error ? e.message : "..."` catch can show as-is.
  assert.match(helperBody, /reject\(new Error\(/);
  assert.doesNotMatch(helperBody, /resolve\(/);
});

test("the timeout is bounded and shorter than the fetch budget", () => {
  const m = code.match(/const SESSION_TIMEOUT_MS = ([\d_]+);/);
  assert.ok(m, "SESSION_TIMEOUT_MS constant not found");
  const ms = Number(m![1].replace(/_/g, ""));
  // Long enough not to fire on an ordinary slow network, short enough that a
  // stalled auth client fails well before fetchWithTimeout's own 45s budget
  // — the whole point is that this budget is spent BEFORE any request is
  // even issued, not on top of it.
  assert.ok(ms >= 3_000 && ms <= 20_000, `SESSION_TIMEOUT_MS is ${ms}, expected 3s-20s`);
});

test("the timer is cleared once the race settles, either way", () => {
  assert.match(helperBody, /finally\s*\{\s*clearTimeout\(timeoutId!?\);?\s*\}/);
});

// The bounded race above makes a STALL settle instead of hanging forever —
// but "settle" includes settling by REJECTING, and that can happen on the
// very first getSession() call of a page's lifetime for reasons that are
// gone a moment later (the auth client's own one-time startup racing a
// background token refresh; a cold storage read that a repeat read does
// not hit). Before this, request() propagated that rejection immediately:
// no fetch was ever attempted, the CA saw "Could not verify your session —
// please retry.", and clicking the SAME button again — unchanged — worked,
// because whatever caused the first rejection had already cleared. This is
// a DIFFERENT thing from "the fix is a bounded race, not a retry" above:
// that note is about not retrying a call that might ALSO hang forever;
// this retries a call that has already SETTLED (bounded or not) and failed,
// which is free of side effects because nothing has reached the network yet.
test("a session-token failure is retried once before request() gives up", () => {
  const calls = (requestBody.match(/sessionTokenWithTimeout\(\)/g) ?? []).length;
  assert.ok(calls >= 2,
    "request() must call sessionTokenWithTimeout() again after a first " +
    "failure — found only " + calls + " call(s), so a first rejection (not " +
    "just a stall) still fails the whole request with no retry");
});

test("the retry sits in a catch of the first attempt, not a duplicate first call", () => {
  assert.match(requestBody,
    /try\s*\{\s*token\s*=\s*await sessionTokenWithTimeout\(\);\s*\}\s*catch[\s\S]*?try\s*\{\s*token\s*=\s*await sessionTokenWithTimeout\(\);\s*\}\s*catch/,
    "the second call must be inside the first attempt's catch block, so it " +
    "only runs after a failure — never on the happy path");
});

test("a second failure in a row still fails the request, with the original error", () => {
  // No unbounded loop, and the CA sees the FIRST failure's message (the one
  // that actually happened first), not a second attempt's possibly different
  // wording for what is likely the same underlying cause.
  assert.match(requestBody, /catch\s*\{\s*throw firstError;\s*\}/);
});
