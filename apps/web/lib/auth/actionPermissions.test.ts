// Action-level permission tests — run with:
//   node --experimental-strip-types --test lib/auth/actionPermissions.test.ts
//
// These cover the half of permissions.ts that does NOT hold a role list: can() /
// canAll() / parsePermissionMap() read the map served by the backend. The role
// helpers are covered in permissions.test.ts; the concern here is that the
// consumer of a fetched map fails closed on every way that fetch can go wrong.
import test from "node:test";
import assert from "node:assert/strict";
import { can, canAll, parsePermissionMap, type PermissionMap } from "./permissions.ts";

// Shape as served by GET /api/identity/permissions for an Executive — the role
// at the centre of the drift this work fixes: reads accounting, cannot write it.
const EXECUTIVE: PermissionMap = {
  accounting: ["read"],
  gst: ["read", "compute"],
  task: ["read", "write"],
  client: ["read"],
};

test("can() reports an action the map grants", () => {
  assert.equal(can(EXECUTIVE, "accounting", "read"), true);
  assert.equal(can(EXECUTIVE, "gst", "compute"), true);
});

test("can() refuses an action the map withholds", () => {
  // The concrete bug: accounting:read admits Executive, accounting:write does
  // not, so a screen gated on "can I see this page?" was offering write actions.
  assert.equal(can(EXECUTIVE, "accounting", "write"), false);
  assert.equal(can(EXECUTIVE, "accounting", "approve"), false);
});

test("can() refuses a resource absent from the map entirely", () => {
  assert.equal(can(EXECUTIVE, "billing", "read"), false);
  assert.equal(can(EXECUTIVE, "practice", "write"), false);
});

test("can() fails CLOSED on an unresolved map", () => {
  // null is the state while the fetch is in flight AND after it fails. Both
  // must hide controls: the alternative is offering actions the API will 403.
  assert.equal(can(null, "accounting", "read"), false);
  assert.equal(can(null, "anything", "at-all"), false);
});

test("can() fails CLOSED on an empty map", () => {
  // What the backend returns for a role string it does not recognise.
  assert.equal(can({}, "accounting", "read"), false);
});

test("an action name is matched exactly, not by prefix", () => {
  // "read" must not satisfy a check for "readwrite", and vice versa — a
  // substring match here would quietly grant the strongest action on the list.
  assert.equal(can({ accounting: ["readwrite"] }, "accounting", "read"), false);
  assert.equal(can({ accounting: ["read"] }, "accounting", "rea"), false);
});

test("canAll() requires every pair", () => {
  assert.equal(canAll(EXECUTIVE, [["accounting", "read"], ["gst", "read"]]), true);
  assert.equal(canAll(EXECUTIVE, [["accounting", "read"], ["accounting", "write"]]), false);
});

test("canAll() on an empty list is true, and on a null map is false", () => {
  // Vacuous truth is right for "no requirements", but a null map must still
  // fail closed the moment there IS a requirement.
  assert.equal(canAll(EXECUTIVE, []), true);
  assert.equal(canAll(null, []), true);
  assert.equal(canAll(null, [["accounting", "read"]]), false);
});

test("parsePermissionMap accepts the backend's shape", () => {
  const parsed = parsePermissionMap({ accounting: ["read", "write"], gst: [] });
  assert.deepEqual(parsed, { accounting: ["read", "write"], gst: [] });
});

test("parsePermissionMap rejects anything that is not that shape", () => {
  // Each of these is a real failure mode: an HTML error page from a proxy, an
  // older backend without the endpoint, a truncated body. All must land on
  // null, because a truthy non-map would answer can() with undefined — which
  // is falsy, so the button hides, but silently and for the wrong reason.
  assert.equal(parsePermissionMap(null), null);
  assert.equal(parsePermissionMap(undefined), null);
  assert.equal(parsePermissionMap("<!doctype html>"), null);
  assert.equal(parsePermissionMap(42), null);
  assert.equal(parsePermissionMap([["accounting", "read"]]), null);
  assert.equal(parsePermissionMap({ accounting: "read" }), null);      // not an array
  assert.equal(parsePermissionMap({ accounting: [1, 2] }), null);       // not strings
  assert.equal(parsePermissionMap({ ok: ["read"], bad: 3 }), null);     // one bad key poisons it
});

test("parsePermissionMap accepts an empty object", () => {
  // Distinct from the rejections above: {} is what the backend legitimately
  // returns for an unrecognised role, and must survive as an empty map rather
  // than collapse to null. Both deny everything, but only one is a parse error.
  assert.deepEqual(parsePermissionMap({}), {});
});

test("a parsed map is a copy, not the parsed body", () => {
  // Guards against handing callers a reference into the fetch response that
  // some other code could mutate.
  const body = { accounting: ["read"] };
  const parsed = parsePermissionMap(body)!;
  assert.notEqual(parsed, body);
  assert.equal(can(parsed, "accounting", "read"), true);
});
