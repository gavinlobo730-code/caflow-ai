// apex-overview-practice-07(c): `AuthContext.applyContext` (a users-table
// query + resolvePermissions()) is invoked from BOTH `getSession().then(...)`
// and `onAuthStateChange`'s own INITIAL_SESSION case on every page load —
// each a full identity + permissions fetch for the SAME user — and again on
// every hourly TOKEN_REFRESHED. This pins the dedup guard: a call for a
// user identity that is ALREADY being resolved is skipped outright, while a
// later call once that resolution has settled (the genuine TOKEN_REFRESHED
// case) still runs.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const FILE = path.resolve(import.meta.dirname, "..", "lib", "auth", "AuthContext.tsx");

function read(): string {
  return fs.readFileSync(FILE, "utf8");
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

function applyContextBody(rawSrc: string): string {
  // Boundaries are found in the RAW source (comments intact) — the "Perf:"
  // marker below is itself a comment, so searching a comment-STRIPPED copy
  // for it would never find it. Callers strip comments themselves on the
  // returned slice if they need to.
  const start = rawSrc.indexOf("function applyContext(u: User | null) {");
  assert.ok(start > -1, "could not find applyContext");
  // applyContext is followed by the mount useEffect, which itself starts
  // "useEffect(() => {\n    // Perf:" — a distinctive enough marker to bound
  // the function body without a full brace-matcher.
  const end = rawSrc.indexOf("useEffect(() => {\n    // Perf:", start);
  assert.ok(end > -1, "could not find the end of applyContext (the mount effect after it)");
  return rawSrc.slice(start, end);
}

test("a ref tracks which identity a context resolution is currently in flight for", () => {
  const code = stripComments(read());
  assert.match(code, /const contextInFlightFor = useRef</,
    "no in-flight tracking ref was found — nothing can tell a duplicate " +
    "concurrent call apart from a genuine later one");
});

test("applyContext returns early, BEFORE any state is touched, when the same identity is already in flight", () => {
  const body = stripComments(applyContextBody(read()));
  const guardAt = body.search(/if\s*\(\s*owner\s*===\s*contextInFlightFor\.current\s*\)\s*return;/);
  assert.ok(guardAt > -1, "the dedup guard (early return) was not found");
  const firstStateWrite = body.search(/setHasFirm\(null\)|setRoleLoading\(true\)|contextRequest\.current/);
  assert.ok(firstStateWrite > -1, "could not find where applyContext starts doing work");
  assert.ok(guardAt < firstStateWrite,
    "the dedup guard runs AFTER state has already been touched — a duplicate " +
    "call would still cause a visible effect (e.g. resetting hasFirm) even if " +
    "the fetch itself were later skipped");
});

test("the in-flight slot is claimed for this owner right after the guard, before the async fetch starts", () => {
  const body = stripComments(applyContextBody(read()));
  assert.match(body, /if\s*\(\s*owner\s*===\s*contextInFlightFor\.current\s*\)\s*return;\s*\n\s*contextInFlightFor\.current\s*=\s*owner;/,
    "contextInFlightFor is not claimed immediately after the guard — a second " +
    "call arriving before the claim would race past the check too");
});

test("the in-flight slot is released in a finally, so a thrown/failed resolution cannot wedge future calls for this owner", () => {
  const body = stripComments(applyContextBody(read()));
  assert.match(body, /finally\s*\{[^}]*contextInFlightFor\.current\s*=\s*undefined;?[^}]*\}/s,
    "no finally block clears contextInFlightFor — a failed resolution would " +
    "permanently block every later call for this user, including a genuine " +
    "TOKEN_REFRESHED");
});

test("resolvePermissions() is still called for a genuinely new (or newly signed-in) user", () => {
  // Negative-of-the-negative: the fix must not have accidentally deleted the
  // permissions fetch entirely while adding the guard.
  const body = stripComments(applyContextBody(read()));
  assert.match(body, /resolvePermissions\(\)\.then\(setPermissions\)/);
});
