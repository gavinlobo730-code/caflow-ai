/**
 * POST-A-056 — GSTR-8 Table 4 / 4.1: the screen records an amendment against the month it amends and shows what the server says about it.
 *
 * `domain/gst/gstr8.py` is the rule: the original month must be earlier than the statement's, Table 3's tax checks are read against the
 * ORIGINAL month, the place of supply is asked from FY 2025-26, and an amendment is never netted against the row it amends because that row's
 * filed figures are on the portal. So the panel decides none of it: the net of each listed row is the server's (`net_liable_paise`), nothing
 * is totalled for the amendments, the result carries the server's own sentence saying they are not netted, and the two doors are the API's.
 *
 *   node --experimental-strip-types --test scripts/a-gstr-8-amendment-is-shown-as-the-server-says-it.test.ts
 */
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = path.resolve(import.meta.dirname, "..");
const read = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const PANEL = read("components/gst/Gstr8Panel.tsx");
const API = read("lib/api/index.ts");

test("each listed amendment shows the server's net and the panel sums nothing for amendments", () => {
  assert.match(PANEL, /formatPaise\(r\.net_liable_paise\)/);
  // Table 3's list derives its own net inline (it predates this); an amendment row must not.
  const amendmentLists = PANEL.slice(PANEL.indexOf("amendments.map("));
  assert.doesNotMatch(amendmentLists.slice(0, amendmentLists.indexOf("Add amendment")),
    /gross_registered_paise\s*\+|\.reduce\(|total_amend/);
  assert.doesNotMatch(PANEL, /amendments\.reduce|unregAmendments\.reduce|amendments\s*\.\s*length\s*\*/);
});

test("the statement shows the server's sentence about netting and its findings, and no amendment total", () => {
  assert.match(PANEL, /statement\.amendment_note/);
  assert.match(PANEL, /statement\?\.amendment_findings/);
  assert.doesNotMatch(PANEL, /total_amendment|amendment_total|amendments_total/);
  assert.doesNotMatch(API, /total_amendment|amendment_total|amendments_total/, "the statement type carries counts and findings, never a total");
});

test("a blank revised value is sent as the original, explicitly, and the month is the one the form was given", () => {
  assert.match(PANEL, /supplier_gstin: amendForm\.supplier_gstin\.trim\(\)\.toUpperCase\(\) \|\| originalGstin/);
  assert.match(PANEL, /enrolment_id: unregAmendForm\.enrolment_id\.trim\(\) \|\| originalId/);
  assert.match(PANEL, /original_period: amendForm\.original_period/);
});

test("the two doors and their withdrawals are the API's, each naming the client", () => {
  assert.match(API, /"\/api\/ecommerce-operator\/amendments"/);
  assert.match(API, /"\/api\/ecommerce-operator\/unregistered-amendments"/);
  assert.match(API, /\/api\/ecommerce-operator\/amendments\/\$\{amendmentId\}\?client_id=\$\{encodeURIComponent\(clientId\)\}/);
  assert.match(API, /\/api\/ecommerce-operator\/unregistered-amendments\/\$\{amendmentId\}\?client_id=\$\{encodeURIComponent\(clientId\)\}/);
});

test("the action is the utility's two answers and nothing else is offered", () => {
  const options = [...PANEL.matchAll(/<option value="(add|delete)">/g)].map((m) => m[1]);
  assert.deepEqual(options, ["add", "delete", "add", "delete"], "one pair per table");
  assert.match(API, /action: "add" \| "delete"/);
});

test("the place of supply is offered for the original and the revised row and the panel does not decide when it is needed", () => {
  assert.match(PANEL, /Original place of supply/);
  assert.match(PANEL, /Revised place of supply/);
  // The server says when it is required (a finding); the handler carries no FY 2025-26 test of its own for an amendment.
  const handler = PANEL.slice(PANEL.indexOf("const addAmendment"), PANEL.indexOf("const removeAmendment"));
  assert.ok(handler.length > 200, "the handler was found");
  assert.doesNotMatch(handler, /2025|pos_required|fyStart|financialYear/);
});
