// A portal principal (client or employee) has no `users` row and no RBAC
// role, so GET /api/identity/permissions correctly 403s for one — but
// AuthContext's applyContext used to call resolvePermissions() for ANY
// signed-in identity unconditionally, so that 403 fired on every single
// portal page load. isPortalPrincipalPath() is the frontend-side equivalent
// of core/portal_auth's principal check (see its own docstring in
// AuthContext.tsx); this pins both its own boundary behaviour and that the
// one call site this exists for actually consults it.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const FILE = path.resolve(import.meta.dirname, "AuthContext.tsx");

function read(): string {
  return fs.readFileSync(FILE, "utf8");
}

function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/[^\n]*/g, "$1");
}

/** Extracts isPortalPrincipalPath's own body and re-builds it as a plain,
 * dependency-free function against an INJECTED `window` — the same
 * extract-and-execute technique the file's own tests use for pure logic
 * that lives inside a .tsx module `--experimental-strip-types` cannot import
 * directly (this file has JSX elsewhere, which a type-stripper cannot parse). */
function loadIsPortalPrincipalPath(pathname: string | undefined): boolean {
  const src = stripComments(read());
  const start = src.indexOf("function isPortalPrincipalPath(): boolean {");
  assert.ok(start > -1, "could not find isPortalPrincipalPath");
  const end = src.indexOf("\n}", start) + 2;
  assert.ok(end > start, "could not find the end of isPortalPrincipalPath");
  const body = src.slice(start, end).replace("function isPortalPrincipalPath(): boolean", "function isPortalPrincipalPath()");
  const factory = new Function(
    "windowOrUndefined",
    `const window = windowOrUndefined; ${body}; return isPortalPrincipalPath();`
  );
  return factory(pathname === undefined ? undefined : { location: { pathname } });
}

test("matches the bare /portal path", () => {
  assert.equal(loadIsPortalPrincipalPath("/portal"), true);
});

test("matches a client portal sub-route", () => {
  assert.equal(loadIsPortalPrincipalPath("/portal/dashboard"), true);
});

test("matches an employee portal sub-route", () => {
  assert.equal(loadIsPortalPrincipalPath("/portal/employee/activate"), true);
});

test("does not match a path that merely starts with the same letters", () => {
  assert.equal(loadIsPortalPrincipalPath("/portaldecoy"), false);
});

test("does not match an ordinary staff route", () => {
  assert.equal(loadIsPortalPrincipalPath("/settings"), false);
});

test("does not match a staff route that carries 'portal' inside a segment", () => {
  // apps/web/app/clients/[id]/portal/page.tsx is the CA-facing screen that
  // manages a client's portal contacts — staff, not a portal principal.
  assert.equal(loadIsPortalPrincipalPath("/clients/abc123/portal"), false);
});

test("answers false rather than throwing when there is no window at all", () => {
  assert.equal(loadIsPortalPrincipalPath(undefined), false);
});

// ── the call site actually consults it ──────────────────────────────────────

function applyContextBody(rawSrc: string): string {
  const start = rawSrc.indexOf("function applyContext(u: User | null) {");
  assert.ok(start > -1, "could not find applyContext");
  const end = rawSrc.indexOf("useEffect(() => {\n    // Perf:", start);
  assert.ok(end > -1, "could not find the end of applyContext (the mount effect after it)");
  return rawSrc.slice(start, end);
}

test("applyContext skips resolvePermissions() for a portal principal", () => {
  const body = stripComments(applyContextBody(read()));
  assert.match(
    body,
    /if\s*\(\s*u\s*&&\s*!\s*isPortalPrincipalPath\(\)\s*\)\s*\{\s*\n?\s*resolvePermissions\(\)/,
    "resolvePermissions() must be called only when the caller is signed in " +
    "AND is not a portal principal — a bare `if (u)` reintroduces the bug"
  );
});

test("resolvePermissions() is still reachable for a genuinely new staff user", () => {
  // Negative-control companion to the guard above: the fix must narrow the
  // condition, not delete the call. Same assertion the dedup-guard test file
  // already makes; kept here too so this file alone proves the property.
  const body = stripComments(applyContextBody(read()));
  assert.match(body, /resolvePermissions\(\)\.then\(setPermissions\)/);
});
