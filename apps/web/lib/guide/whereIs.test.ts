// POST-A-538: which screens the guide may point a person at, how an answer becomes something to click, and the plain search.
//   node --experimental-strip-types --test lib/guide/whereIs.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ALL_SCREENS } from "../navigation/screens.ts";
import {
  AREA_NAMES, MAX_ANSWERS, answersFor, offeredIds, offeredTo, plainSearch, screenId, sentenceFor, whereOf, wordsOf, type Places, type Who,
} from "./whereIs.ts";
import { MAIN_AREAS, MORE_AREAS } from "../workspace/outerMenu.ts";
import type { UserRole } from "../auth/permissions.ts";

// What each role holds to start with, written from the server's own table (`scripts/drive/role-permissions.json`, which a
// Python test holds to `core/permissions.py`). Since POST-A-543 the guide asks permissions for every firm screen, so a
// person here is a role WITH that role's permissions, less whatever a test blocks.
const MAPS = JSON.parse(readFileSync(join(import.meta.dirname, "..", "..", "scripts", "drive", "role-permissions.json"), "utf8")) as Record<string, Record<string, string[]>>;
const pairsOf = (role: UserRole | null): string[] =>
  Object.entries(MAPS[role ?? "Reviewer"] ?? {}).flatMap(([resource, actions]) => actions.map((a) => `${resource}:${a}`));
/** A person: `pairs` omitted means the role's own permissions; given, exactly those. */
const who = (role: UserRole | null, pairs?: string[], over: Partial<Who> = {}): Who => {
  const held = pairs ?? pairsOf(role);
  return { role, can: (r, a) => held.includes(`${r}:${a}`), resolved: true, clientSectionOffered: () => true, ...over };
};
const without = (role: UserRole, ...blocked: string[]) => who(role, pairsOf(role).filter((p) => !blocked.includes(p)));
const ids = (w: Who) => new Set(offeredIds(w));
const PARTNER = who("Partner");
// The firm menus of a Partner (every area) and of a Manager (every area but My practice), as the menu works them out.
const PARTNER_MENU: Places = { areas: [...MAIN_AREAS, ...MORE_AREAS] };
const MANAGER_MENU: Places = { areas: [...MAIN_AREAS, ...MORE_AREAS].filter((a) => a !== "practice") };
const screen = (id: string) => ALL_SCREENS.find((s) => screenId(s) === id)!;

test("every screen has an id of its own, and the id says whether it is a client's screen", () => {
  const all = ALL_SCREENS.map(screenId);
  assert.equal(new Set(all).size, all.length, "two screens share an id, so an answer could open the wrong one");
  assert.ok(all.length >= 100);
  for (const id of all) assert.match(id, /^(firm|client):/);
});

test("a Partner is offered every screen", () => {
  assert.equal(ids(PARTNER).size, ALL_SCREENS.length);
});

test("a Manager is offered Team and payroll, and nothing of My practice", () => {
  const m = ids(who("Manager"));
  for (const yes of ["firm:/team", "firm:/team/assignments", "firm:/approvals", "firm:/payroll", "firm:/gst", "firm:/settings/statutory-values"]) {
    assert.ok(m.has(yes), `a Manager is not offered ${yes}`);
  }
  for (const s of ALL_SCREENS.filter((x) => x.scope === "firm" && (x.href.startsWith("/practice") || x.href === "/billing" || x.href.startsWith("/accounting/receivables") || x.href === "/executive-dashboard"))) {
    assert.ok(!m.has(screenId(s)), `a Manager is offered ${s.href}, which is My practice`);
  }
});

test("an Executive and a Reviewer are offered Deadlines, the tax desks and Work, and no Team, My practice, payroll, pipeline or engagements", () => {
  // POST-A-543: the guide follows the permissions. Both roles hold the compliance, tax and task permissions (they need them
  // inside a client), so the firm-wide lists are theirs, each limited by the server to their assigned clients.
  for (const role of ["Executive", "Reviewer"] as UserRole[]) {
    const e = ids(who(role));
    for (const no of ["firm:/team", "firm:/team/workload", "firm:/approvals", "firm:/practice", "firm:/payroll", "firm:/pipeline", "firm:/engagements", "firm:/settings/statutory-values", "firm:/billing", "firm:/risks"]) {
      assert.ok(!e.has(no), `${role} is offered ${no}`);
    }
    for (const yes of ["firm:/", "firm:/clients", "firm:/knowledge", "firm:/ai-assistant", "firm:/deadlines", "firm:/gst", "firm:/tds", "firm:/tasks", "firm:/work"]) assert.ok(e.has(yes), `${role} is not offered ${yes}`);
  }
  // Where the two differ: the books, and the three screens whose read needs the right to compute.
  for (const id of ["firm:/accounting", "firm:/accounting/budget", "firm:/income-tax/book-to-tax", "firm:/income-tax/section-32"]) {
    assert.ok(ids(who("Executive")).has(id), `an Executive is not offered ${id}`);
    assert.ok(!ids(who("Reviewer")).has(id), `a Reviewer is offered ${id}, which the server refuses them`);
  }
});

test("a tick a Partner takes away removes the desk and every screen under it, for any role", () => {
  const deep = ALL_SCREENS.find((s) => s.scope === "firm" && s.href.startsWith("/gst/"));
  assert.ok(deep, "no screen under /gst/: the inventory has moved");
  assert.equal(offeredTo(deep, who("Executive")), true);
  assert.equal(offeredTo(deep, without("Executive", "gst:read")), false);
  assert.equal(offeredTo(deep, without("Manager", "gst:read")), false, "a Manager a Partner blocked is still pointed at it");
  assert.equal(offeredTo(screen("firm:/tds"), without("Manager", "gst:read")), true, "blocking one desk took another");
  // A whole area: nothing under Work is offered to somebody who holds none of its pairs.
  const noWork = without("Executive", "task:read", "time_entry:read", "workflow:read");
  for (const id of ["firm:/work", "firm:/tasks", "firm:/time", "firm:/workflows"]) assert.ok(!ids(noWork).has(id), id);
});

test("nobody signed in, or a role that is not known, is offered what a Reviewer is and no more", () => {
  assert.deepEqual([...ids(who(null))].sort(), [...ids(who("Reviewer"))].sort());
  // And a role that is not known never opens My practice, whatever permissions arrive with it.
  assert.equal(ids(who(null, pairsOf("Partner"))).has("firm:/practice"), false);
});

test("a People screen needs the pair its reads need, once the permissions are known", () => {
  const blocked = without("Manager", "workload:read");
  assert.equal(ids(blocked).has("firm:/team"), true);
  assert.equal(ids(blocked).has("firm:/team/workload"), false, "a Manager blocked from workload is still pointed at it");
  // While the permissions are still being read nothing is withheld on a pair.
  assert.equal(ids(who("Manager", [], { resolved: false })).has("firm:/team/workload"), true);
});

test("a client's screen is offered when its section is, and needs a client to open", () => {
  const noPayroll = who("Executive", [], { clientSectionOffered: (id) => id !== "payroll" });
  assert.equal(ids(noPayroll).has("client:payroll"), false);
  assert.equal(ids(noPayroll).has("client:compliance/tds"), true);
  const offered = ids(PARTNER);
  const [outside] = answersFor(["client:compliance/tds"], offered, null, PARTNER_MENU);
  assert.equal(outside.href, null);
  assert.match(sentenceFor(outside), /Open a client first/);
  const [inside] = answersFor(["client:compliance/tds"], offered, "c-1", PARTNER_MENU);
  assert.equal(inside.href, "/clients/c-1/compliance/tds/");
  assert.doesNotMatch(sentenceFor(inside), /Open a client first/);
});

test("an answer is a screen on the list that the person is offered: in order, once, at most three, and nothing else", () => {
  const offered = ids(who("Manager"));
  const got = answersFor(["firm:/tds", "firm:/made-up", "firm:/practice/billing", "firm:/tds", 7, null, "firm:/gst", "firm:/team", "firm:/"], offered, null, MANAGER_MENU);
  assert.deepEqual(got.map((a) => a.id), ["firm:/tds", "firm:/gst", "firm:/team"]);
  assert.equal(got.length, MAX_ANSWERS);
  assert.equal(got[0].href, "/tds");
  // The words are the screen's own.
  const tds = ALL_SCREENS.find((s) => screenId(s) === "firm:/tds")!;
  assert.equal(got[0].name, tds.name);
  assert.equal(sentenceFor(got[0]), `${tds.name} is in the firm menu, under Deadlines.`);
  assert.deepEqual(answersFor([], offered, null, MANAGER_MENU), []);
});

test("where a screen is, is said in the names on the person's own menu", () => {
  // The same screen, two people: Team is a group inside My practice for a Partner and an entry of its own for a Manager.
  assert.equal(whereOf(screen("firm:/team/workload"), PARTNER_MENU), "in the firm menu, under My practice, in the People group");
  assert.equal(whereOf(screen("firm:/team/workload"), MANAGER_MENU), "in the firm menu, under Team");
  assert.equal(whereOf(screen("firm:/approvals"), MANAGER_MENU), "in the firm menu, under Team");
  // An area that sits under More is said to, and one listed directly is not.
  assert.equal(whereOf(screen("firm:/accounting"), PARTNER_MENU), "in the firm menu, under More, then Accounting");
  assert.equal(whereOf(screen("firm:/gst"), PARTNER_MENU), "in the firm menu, under Deadlines");
  assert.equal(whereOf(screen("firm:/practice/billing"), PARTNER_MENU), "in the firm menu, under My practice");
  // Somebody offered only one of the More areas has no More entry, so the sentence does not send them to one.
  assert.equal(whereOf(screen("firm:/knowledge"), { areas: ["home", "clients", "knowledge"] }), "in the firm menu, under Knowledge");
  assert.equal(whereOf(screen("firm:/settings/statutory-values"), MANAGER_MENU), "in Settings, the gear at the top right");
  assert.equal(whereOf(screen("client:compliance/tds"), MANAGER_MENU), "inside a client’s workspace");
});

test("no sentence names a place that is on no menu", () => {
  // The inventory's own headings ("Practice", "Insights", "General", "Setup") are the command palette's and are on no menu.
  const names = new Set(Object.values(AREA_NAMES));
  for (const s of ALL_SCREENS) {
    for (const places of [PARTNER_MENU, MANAGER_MENU]) {
      const where = whereOf(s, places);
      if (s.scope === "client" || where === "" || where.startsWith("in Settings")) continue;
      const named = where.replace(/^in the firm menu, under (More, then )?/, "").replace(/, in the People group$/, "");
      assert.ok(names.has(named), `${s.href}: "${where}" names "${named}", which is not an area of the firm menu`);
    }
  }
  // A screen no area owns is named without a place.
  const search = screen("firm:/search");
  assert.equal(whereOf(search, PARTNER_MENU), "");
  assert.match(sentenceFor({ id: "firm:/search", name: search.name, where: "", href: "/search" }), /opens from the button here\.$/);
});

test("the words of a question: lower case, no small words, no punctuation, none twice", () => {
  assert.deepEqual(wordsOf("Where do I record a TDS challan?"), ["tds", "challan"]);
  assert.deepEqual(wordsOf("26Q"), ["26q"]);
  assert.deepEqual(wordsOf("43B(h) report, 43b(h)"), ["43b(h)", "report"]);
  assert.deepEqual(wordsOf("where is it"), []);
  assert.deepEqual(wordsOf(""), []);
});

test("the plain search finds a screen by its name or by a word a CA calls it, among the offered screens only", () => {
  const offered = ids(PARTNER);
  assert.ok(plainSearch("where do I record a TDS challan?", offered).some((id) => id.includes("tds")));
  assert.ok(plainSearch("26Q", offered).some((id) => id.includes("tds")));
  assert.equal(plainSearch("pt slabs", offered)[0], "firm:/settings/statutory-values");
  assert.equal(plainSearch("who handles which client", offered)[0], "firm:/team/assignments");
  // It understands no meaning, and says nothing when no word matches.
  assert.deepEqual(plainSearch("where is it", offered), []);
  assert.deepEqual(plainSearch("zzzz qqqq", offered), []);
  // A short word is not matched inside a longer one: "pay" is not payroll.
  assert.ok(!plainSearch("pay", offered).includes("firm:/payroll"));
  // Never a screen the person is not offered.
  const executive = ids(who("Executive"));
  for (const id of plainSearch("tds challan payroll team", executive, 20)) assert.ok(executive.has(id), `${id} is not offered to an Executive`);
  assert.ok(plainSearch("tds", offered).length <= MAX_ANSWERS);
});
