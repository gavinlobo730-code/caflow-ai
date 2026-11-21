/**
 * A BROWSER SCENARIO'S PERMISSION MAP IS COMPLETED FROM THE ROLE'S OWN, IN ONE PLACE (POST-A-543).
 *
 * About eighty scenarios route `GET /api/identity/permissions` and say only what they are about (`{ gst: ["read"] }`). Since
 * one gate around every page asks the pair that opens the page's AREA, a "Partner" holding `gst` alone is told the page is not
 * part of their access, and the scenario never reaches its screen: thirteen of the sixteen scenarios in one nightly group
 * failed that way on the day the gate was built. The stand-in server completes the map: what a scenario NAMES is served as
 * written, and what it does not name is the role's own.
 *
 * These hold the rule on the function, and that the two ways out of it (`signInAs`, and a route that says `whole`) are in
 * the server's source.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ok, wholeMapFor } from "./drive/stub.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROLES = JSON.parse(readFileSync(resolve(HERE, "drive/role-permissions.json"), "utf8")) as Record<string, Record<string, string[]>>;
const stub = readFileSync(resolve(HERE, "drive/stub.mjs"), "utf8");

test("a resource the scenario names is served exactly as it wrote it, an empty list included", () => {
  const out = wholeMapFor(ok({ role: "Partner", permissions: { gst: ["read"], payroll: [] } }));
  assert.deepEqual(out.data.permissions.gst, ["read"], "the scenario's own `gst` was widened to the role's");
  assert.deepEqual(out.data.permissions.payroll, [], "an empty list the scenario wrote was filled in");
});

test("a resource the scenario does not name is the role's own, so the page's area opens", () => {
  for (const role of Object.keys(ROLES)) {
    const out = wholeMapFor(ok({ role, permissions: { gst: ["read"] } }));
    for (const [resource, actions] of Object.entries(ROLES[role])) {
      if (resource === "gst") continue;
      assert.deepEqual(out.data.permissions[resource], actions, `${role}: ${resource} is not the role's own`);
    }
  }
  assert.ok(ROLES.Partner.client.includes("read"), "the Partner's own map lost `client` `read`: the file is not the server's table");
});

test("nothing else about the answer moves, and an answer that is not a map is left alone", () => {
  const answer = ok({ role: "Manager", permissions: { tds: ["read"] }, has_overrides: true });
  const out = wholeMapFor(answer);
  assert.equal(out.data.role, "Manager");
  assert.equal(out.data.has_overrides, true);
  assert.deepEqual(answer.data.permissions, { tds: ["read"] }, "the scenario's own object was changed in place");
  const unknown = ok({ role: "Auditor", permissions: { tds: ["read"] } });
  assert.equal(wholeMapFor(unknown), unknown, "a role the file does not hold was given somebody's map");
  const refusal = { success: false, data: null, error: "no" };
  assert.equal(wholeMapFor(refusal), refusal);
  assert.deepEqual(wholeMapFor(ok([])), ok([]));
});

test("the server completes a routed answer only, and the two ways out are in its source", () => {
  assert.match(stub, /route && !route\.whole && req\.method === "GET" && IS_PERMISSIONS\.test\(pathname\) \? wholeMapFor\(answered\) : answered/,
    "the completion is not applied where a routed permissions answer is sent");
  const signIn = stub.slice(stub.indexOf("signInAs(role"), stub.indexOf("answerInserts(name"));
  assert.match(signIn, /whole: true,/, "signInAs serves a whole map of its own and must not be completed over (a blocked pair would come back)");
});
