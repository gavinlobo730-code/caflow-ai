// POST-A-543: the permissions a Partner ticks, grouped under the menu's own names, and the preview of a person's menu.
//   node --experimental-strip-types --test lib/access/permissionGroups.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { TICKABLE_AREAS, hasWords, menuFor, menuGroups, menuPermissionKeys, pairWords, wouldHold, type Choice } from "./permissionGroups.ts";
import { AREA_RULES, everyPair } from "./screenAccess.ts";

const MAPS = JSON.parse(readFileSync(join(import.meta.dirname, "..", "..", "scripts", "drive", "role-permissions.json"), "utf8")) as Record<string, Record<string, string[]>>;

test("every area a Partner can tick is there, in the menu's order, and Home and My practice are not", () => {
  assert.deepEqual(menuGroups().map((g) => g.areaId), [...TICKABLE_AREAS]);
  assert.ok(!TICKABLE_AREAS.includes("home") && !TICKABLE_AREAS.includes("practice"));
  assert.deepEqual([...TICKABLE_AREAS].sort(), Object.keys(AREA_RULES).filter((a) => a !== "home" && a !== "practice").sort());
});

test("every permission the table names is shown under an area, and has plain words", () => {
  const shown = menuPermissionKeys();
  for (const [resource, action] of everyPair()) {
    assert.ok(shown.has(`${resource}:${action}`), `${resource}:${action} decides the menu or a screen and is in no group`);
    assert.ok(hasWords(resource, action), `${resource}:${action} has no plain words: a Partner would be shown its technical name`);
    assert.doesNotMatch(pairWords(resource, action), /_|: /, `${resource}:${action} reads as a technical name`);
  }
});

test("a group says which permissions put the area on the menu and which only open screens in it", () => {
  const groups = Object.fromEntries(menuGroups().map((g) => [g.areaId, g]));
  const of = (area: string, k: string) => groups[area].permissions.find((p) => `${p.resource}:${p.action}` === k);
  assert.equal(groups.deadlines.areaNeeds, "any");
  assert.equal(of("deadlines", "gst:read")?.opensTheArea, true);
  assert.deepEqual(of("deadlines", "gst:read")?.screens, ["/gst", "/einvoice"]);
  assert.equal(of("deadlines", "income_tax:compute")?.opensTheArea, false);
  assert.deepEqual(of("deadlines", "income_tax:compute")?.screens, ["/income-tax/book-to-tax", "/income-tax/section-32", "/income-tax/deductions"]);
  assert.equal(groups.accounting.areaNeeds, "all");
  assert.equal(of("accounting", "accounting:read")?.opensTheArea, true);
  assert.equal(of("accounting", "billing:read")?.opensTheArea, false);
  // One tick, shown wherever it matters: seeing clients is Clients, Relationships and Health, and opens five accounting lists.
  assert.deepEqual(of("clients", "client:read")?.alsoIn.sort(), ["accounting", "health", "relationships"]);
  assert.equal(of("clients", "pipeline:read")?.opensTheArea, false);
});

test("a permission is said in a person's words", () => {
  assert.equal(pairWords("gst", "read"), "See the GST desk");
  assert.equal(pairWords("accounting", "write"), "Add and change the books");
  assert.equal(pairWords("accounting", "approve"), "Approve the books");
  assert.equal(pairWords("income_tax", "compute"), "Work out income tax (compute)");
  // One this file has no words for falls back to its technical name, in title case.
  assert.equal(pairWords("tally_migration", "approve"), "Tally Migration: Approve");
});

test("the preview is the menu each role really starts with, and a draft moves it", () => {
  const start = (role: string) => menuFor(wouldHold(MAPS[role], {}), role === "Partner");
  assert.deepEqual(start("Partner"), { main: ["home", "clients", "deadlines", "work", "practice", "ai"], more: ["accounting", "payroll", "relationships", "health", "knowledge", "engagements"] });
  assert.deepEqual(start("Manager"), { main: ["home", "clients", "deadlines", "work", "team", "ai"], more: ["accounting", "payroll", "relationships", "health", "knowledge", "engagements"] });
  assert.deepEqual(start("Executive"), { main: ["home", "clients", "deadlines", "work", "ai"], more: ["accounting", "relationships", "health", "knowledge"] });
  assert.deepEqual(start("Reviewer"), { main: ["home", "clients", "deadlines", "work", "ai"], more: ["relationships", "health", "knowledge"] });

  const draft = (role: string, choices: Record<string, Choice>) => menuFor(wouldHold(MAPS[role], choices), role === "Partner");
  // Allow puts an area on; Block takes one off; Role hands it back to the role.
  assert.ok(draft("Reviewer", { "accounting:read": "allow" }).more.includes("accounting"));
  assert.ok(draft("Executive", { "payroll:read": "allow" }).more.includes("payroll"));
  assert.ok(!draft("Executive", { "knowledge:read": "block" }).more.includes("knowledge"));
  assert.ok(draft("Executive", { "knowledge:read": "role" }).more.includes("knowledge"));
  // An area that needs any one of several stays until the last of them is blocked.
  assert.ok(draft("Executive", { "task:read": "block" }).main.includes("work"));
  assert.ok(!draft("Executive", { "task:read": "block", "time_entry:read": "block", "workflow:read": "block" }).main.includes("work"));
  // My practice is not a tick: no draft puts it on the menu of somebody who is not a Partner.
  const everything = Object.fromEntries([...menuPermissionKeys()].map((k) => [k, "allow" as Choice]));
  assert.ok(!draft("Manager", { ...everything, "practice:read": "allow", "billing:read": "allow" }).main.includes("practice"));
});
