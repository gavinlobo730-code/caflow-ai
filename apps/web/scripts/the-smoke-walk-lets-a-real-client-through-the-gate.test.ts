// THE SMOKE WALK CAN RENDER A REAL CLIENT WORKSPACE (POST-A-036).
//   node --experimental-strip-types --test scripts/the-smoke-walk-lets-a-real-client-through-the-gate.test.ts
//
// Since `ClientResolutionGate` (D28) a screen under /clients/<uuid>/… renders only once `clients?id=eq.<uuid>` answers a
// row; an absent row renders "no such client". The walk's stub answered every read it did not know with `[]`, so
// `--real-client` photographed 40 refusals and the axe scan of "a client's sales" scanned one. `scripts/walkStub.mjs`
// answers ONE lookup, the one the gate makes, and leaves every list empty. This file holds that behaviour (the stub is
// a pure module, so it is exercised, not read), what the gate selects (so the row cannot lose a column the gate needs)
// and the workflow's second pass.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
// @ts-expect-error — a plain .mjs module with no declaration file
import { CLIENT_ROW, CLIENT_UUID, knownRead, project, selectItems } from "./walkStub.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (rel: string) => fs.readFileSync(path.join(here, rel), "utf8");
const REST = "/__supabase/rest/v1/clients";

test("the gate's own lookup answers the client, as one object for maybeSingle", () => {
  const select = "id, client_name, entity_type, gstin, status";
  const row = knownRead(REST, `select=${encodeURIComponent(select)}&id=eq.${CLIENT_UUID}`, true);
  assert.deepEqual(Object.keys(row).sort(), ["client_name", "entity_type", "gstin", "id", "status"]);
  assert.equal(row.id, CLIENT_UUID);
  assert.ok(row.client_name && row.status);
});

test("the same lookup as a list is a one-row list", () => {
  const rows = knownRead(REST, `select=id&id=eq.${CLIENT_UUID}`, false);
  assert.deepEqual(rows, [{ id: CLIENT_UUID }]);
});

test("an alias is applied, because PostgREST answers the aliased name", () => {
  assert.deepEqual(knownRead(REST, `select=${encodeURIComponent("id,name:client_name")}&id=eq.${CLIENT_UUID}`, true),
    { id: CLIENT_UUID, name: CLIENT_ROW.client_name });
});

test("negative control: a client the walk does not name, and every list read, stay unanswered (empty)", () => {
  assert.equal(knownRead(REST, "select=id&id=eq.00000000-0000-4000-8000-0000000000aa", true), undefined);
  assert.equal(knownRead(REST, "select=id&firm_id=eq.x&is_internal=eq.false", false), undefined);
  assert.equal(knownRead("/__supabase/rest/v1/invoices", `client_id=eq.${CLIENT_UUID}`, false), undefined);
  assert.equal(knownRead("/__supabase/rest/v1/clients_view", `id=eq.${CLIENT_UUID}`, false), undefined);
});

test("select lists split on top-level commas only", () => {
  assert.deepEqual(selectItems("id, title, clients(client_name, gstin), status"), ["id", "title", "clients(client_name, gstin)", "status"]);
  assert.deepEqual(project(CLIENT_ROW, "*"), CLIENT_ROW);
  assert.deepEqual(project(CLIENT_ROW, "id,tasks(a,b)"), { id: CLIENT_UUID });
});

test("the row carries every column the gate selects", () => {
  const nav = read("../lib/workspace/ClientNavContext.tsx");
  const m = nav.match(/\.from\("clients"\)\s*\.select\("([^"]+)"\)\s*\.eq\("id", clientId\)/);
  assert.ok(m, "the gate's lookup moved; this guard must follow it");
  for (const column of m![1].split(",").map((c) => c.trim())) {
    assert.ok(column in CLIENT_ROW, `the gate selects ${column} and the stub's client has none`);
  }
});

test("the walk uses the stub's client uuid and its lookup, and does not declare a second one", () => {
  const walk = read("smoke-walk.mjs");
  assert.match(walk, /import \{ CLIENT_UUID, knownRead \} from "\.\/walkStub\.mjs"/);
  assert.doesNotMatch(walk, /const CLIENT_UUID =/);
  assert.match(walk, /knownRead\(url, query, wantsObject\)/);
});

test("the nightly walks the client workspace too, with the digest limit unchanged", () => {
  const wf = fs.readFileSync(path.join(here, "../../../.github/workflows/smoke-walk.yml"), "utf8");
  const code = wf.split("\n").filter((l) => !l.trimStart().startsWith("#")).join("\n");
  assert.match(code, /node scripts\/smoke-walk\.mjs --only \/clients --real-client /);
  assert.match(code, /name: Walk the client workspace\n\s+if: always\(\) && steps\.build\.outcome == 'success'/);
  assert.doesNotMatch(code, /name: Walk the client workspace[\s\S]{0,300}continue-on-error/);
  assert.match(read("smoke-walk.mjs"), /const MAX_ROUTES_PER_DIGEST = 5;/);
});
