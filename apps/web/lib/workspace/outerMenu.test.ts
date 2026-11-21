// The firm menu's outer list per role (the owner's decisions of 21-11-2026): what is listed first, what sits under "More",
// that somebody with My practice has no separate Team entry, and that nothing a role was offered has gone.
//   node --experimental-strip-types --test lib/workspace/outerMenu.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { MAIN_AREAS, MORE_AREAS, MORE_ID, areaShown, outerMenu } from "./outerMenu.ts";
import { AREA_RULES, areaOffered } from "../access/screenAccess.ts";
import { PRACTICE_PEOPLE_SECTIONS } from "./practiceWorkspace.ts";
import type { UserRole } from "../auth/permissions.ts";

const WEB = join(import.meta.dirname, "..", "..");
const API = join(WEB, "..", "api");
const read = (rel: string) => readFileSync(join(WEB, rel), "utf8");

/** The ids of the areas of WORKSPACE_CONFIGS, in its order, read from the source (the file imports icons node cannot load). */
function areas(): string[] {
  const src = read("lib/workspace/workspaceConfig.ts");
  const list = src.slice(src.indexOf("export const WORKSPACE_CONFIGS"), src.indexOf("export const DEFAULT_WORKSPACE_ROUTES"));
  const out = [...list.matchAll(/\n    id: "([a-z]+)",/g)].map((m) => m[1]);
  assert.ok(out.length >= 13, `only ${out.length} areas read: workspaceConfig.ts has moved`);
  return out;
}

const ROLE_SETS: Record<string, UserRole[]> = {
  _PARTNER_ONLY: ["Partner"],
  _AT_LEAST_MANAGER: ["Partner", "Manager"],
  _AT_LEAST_EXECUTIVE: ["Partner", "Manager", "Executive"],
  _ALL_STAFF: ["Partner", "Manager", "Executive", "Reviewer"],
};

/** `can` for a role with no per-person overrides, read from the server's own table. */
function canFor(role: UserRole): (resource: string, action: string) => boolean {
  const src = readFileSync(join(API, "core", "permissions.py"), "utf8");
  return (resource, action) => {
    const at = src.indexOf(`"${resource}": {`);
    assert.ok(at >= 0, `${resource} is not in core/permissions.py`);
    const block = src.slice(at, src.indexOf("},", at));
    const set = block.match(new RegExp(`"${action}":\\s*(_[A-Z_]+)`))?.[1];
    assert.ok(set && set in ROLE_SETS, `${resource}:${action} names a role set this test does not know: ${set}`);
    return ROLE_SETS[set].includes(role);
  };
}

/** The ids of the areas a role is offered, as the menu asks: the one table, with the role's own default permissions. */
function offeredTo(role: UserRole): string[] {
  const who = { can: canFor(role), isPartner: role === "Partner" };
  return areas().filter((id) => areaOffered(id, who));
}

test("every area of the menu has a rule in the one table, and the table names no area the menu lacks", () => {
  assert.deepEqual(Object.keys(AREA_RULES).sort(), [...areas()].sort());
});

test("a Partner's list: the daily areas, My practice with no separate Team entry, and the rest under More", () => {
  assert.deepEqual(outerMenu(offeredTo("Partner")), {
    main: ["home", "clients", "deadlines", "work", "practice", "ai"],
    more: ["accounting", "payroll", "relationships", "health", "knowledge", "engagements"],
  });
});

test("a Manager's list: Team where it was, no My practice, and the same More", () => {
  assert.deepEqual(outerMenu(offeredTo("Manager")), {
    main: ["home", "clients", "deadlines", "work", "team", "ai"],
    more: ["accounting", "payroll", "relationships", "health", "knowledge", "engagements"],
  });
});

test("an Executive's list: Deadlines and Work are theirs, with Accounting under More; no Team, My practice, Payroll or Engagements", () => {
  // POST-A-543 (the owner's decision of 21-11-2026): the menu follows the permissions a person holds. An Executive holds the
  // compliance, tax and task permissions (they need them inside a client), so Deadlines and Work are on their menu, each list
  // limited by the server to the clients they are assigned to. Engagements needs engagement:read, a Manager's by default.
  assert.deepEqual(outerMenu(offeredTo("Executive")), {
    main: ["home", "clients", "deadlines", "work", "ai"],
    more: ["accounting", "relationships", "health", "knowledge"],
  });
});

test("a Reviewer's list: the same without Accounting, which needs a permission a Reviewer does not start with", () => {
  assert.deepEqual(outerMenu(offeredTo("Reviewer")), {
    main: ["home", "clients", "deadlines", "work", "ai"],
    more: ["relationships", "health", "knowledge"],
  });
});

test("a tick moves the menu: an area appears for one person a Partner ticked, and goes for one a Partner blocked", () => {
  const base = canFor("Reviewer");
  const ticked = { can: (r: string, a: string) => (r === "accounting" && a === "read") || base(r, a), isPartner: false };
  assert.ok(areas().filter((id) => areaOffered(id, ticked)).includes("accounting"));
  const blocked = { can: (r: string, a: string) => !(r === "knowledge") && base(r, a), isPartner: false };
  assert.ok(!areas().filter((id) => areaOffered(id, blocked)).includes("knowledge"));
  // My practice is not a tick: no permission opens it for somebody who is not a Partner.
  assert.ok(!areas().filter((id) => areaOffered(id, { can: () => true, isPartner: false })).includes("practice"));
});

test("nothing a role was offered has gone: every area is on the list or under More, and a Partner's Team screens are in My practice", () => {
  for (const role of ["Partner", "Manager", "Executive", "Reviewer"] as UserRole[]) {
    const offered = offeredTo(role);
    const menu = outerMenu(offered);
    const listed = [...menu.main, ...menu.more];
    assert.equal(new Set(listed).size, listed.length, `${role}: an area is listed twice`);
    const dropped = offered.filter((id) => !listed.includes(id));
    if (role === "Partner") {
      // The one area a Partner's list leaves out, and every screen of it is offered inside My practice by the same pairs.
      assert.deepEqual(dropped, ["team"]);
      const can = canFor(role);
      const peoplePairs = PRACTICE_PEOPLE_SECTIONS.map((s) => s.requires.join(":"));
      for (const pair of AREA_RULES.team.any ?? []) assert.ok(peoplePairs.includes(pair.join(":")), `no People screen asks ${pair.join(":")}`);
      for (const s of PRACTICE_PEOPLE_SECTIONS) assert.ok(can(s.requires[0], s.requires[1]), `a Partner is not offered ${s.href}`);
    } else {
      assert.deepEqual(dropped, [], `${role} lost ${dropped.join(", ")}`);
    }
    assert.deepEqual(listed.filter((id) => !offered.includes(id)), [], `${role} is offered an area the rules do not admit`);
  }
});

test("every area of the firm menu is placed on exactly one of the two lists", () => {
  const ids = [...areas()].sort();
  assert.deepEqual([...MAIN_AREAS, ...MORE_AREAS].sort(), ids);
  assert.equal(new Set([...MAIN_AREAS, ...MORE_AREAS]).size, MAIN_AREAS.length + MORE_AREAS.length);
});

test("More needs two areas to exist, and an area on neither list is kept", () => {
  assert.deepEqual(outerMenu(["home", "knowledge"]), { main: ["home", "knowledge"], more: [] });
  assert.deepEqual(outerMenu(["home"]), { main: ["home"], more: [] });
  assert.deepEqual(outerMenu(["home", "knowledge", "health"]), { main: ["home"], more: ["health", "knowledge"] });
  assert.deepEqual(outerMenu(["home", "something-new", "knowledge", "health"]), { main: ["home", "something-new"], more: ["health", "knowledge"] });
  // Team is left out only for somebody who has My practice.
  assert.deepEqual(outerMenu(["team", "home"]).main, ["home", "team"]);
  assert.deepEqual(outerMenu(["team", "home", "practice"]).main, ["home", "practice"]);
});

test("the list the open menu shows: under the pointer, else where the address is, else Home, and never an area not offered", () => {
  const partner = outerMenu(offeredTo("Partner"));
  const executive = outerMenu(offeredTo("Executive"));
  assert.equal(areaShown(null, "clients", partner), "clients");
  assert.equal(areaShown("payroll", "clients", partner), "payroll");
  assert.equal(areaShown(MORE_ID, "clients", partner), MORE_ID);
  assert.equal(areaShown(null, null, partner), "home");
  // A Partner standing on a People screen that somehow wears the firm's frame is shown My practice's list, which holds it.
  assert.equal(areaShown(null, "team", partner), "practice");
  // An area the person is not offered is not shown, whatever the address says.
  assert.equal(areaShown(null, "payroll", executive), "home");
  assert.equal(areaShown("practice", "clients", executive), "clients");
  assert.equal(areaShown(MORE_ID, null, { main: ["home"], more: [] }), "home");
});

test("the menu draws this rule, an entry is a link to the area's first screen, and the preview follows the pointer only", () => {
  const menu = read("components/shell/WorkspaceMegaMenu.tsx");
  assert.match(menu, /const menu = outerMenu\(offered\.map\(\(ws\) => ws\.id\)\);/);
  assert.match(menu, /const shown = areaShown\(hovered, activeWorkspace, menu\);/);
  assert.match(menu, /<Link\s+key=\{ws\.id\}\s+href=\{ws\.defaultRoute\}/, "an area's entry is not a link to its first screen: a click on it goes nowhere");
  assert.match(menu, /onMouseEnter=\{\(\) => setHovered\(ws\.id\)\}/);
  assert.doesNotMatch(menu.replace(/\/\*[\s\S]*?\*\//g, ""), /onFocus=/, "the preview follows keyboard focus again, so a focused button holds the list on another area");
  assert.match(menu, /aria-expanded=\{moreIsOpen\}/);
  const bar = read("components/shell/WorkspaceTopBar.tsx");
  assert.match(bar, /onNavigate=\{\(\) => setMenuOpen\(false\)\}/, "a click on the area the person is already in leaves the menu open over it");
});
