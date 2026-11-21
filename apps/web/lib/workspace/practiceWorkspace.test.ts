// POST-A-532: which addresses are My practice, which screens it lists, and which client sections it leaves out and why.
//   node --experimental-strip-types --test lib/workspace/practiceWorkspace.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  NOT_FOR_THE_PRACTICE, PEOPLE_PREFIXES, PRACTICE_PEOPLE_SECTIONS, PRACTICE_PREFIXES, PRACTICE_SECTIONS, booksSectionsFor, isPeoplePath,
  isPracticePath, peopleSectionsOffered, practiceSectionAt, readPracticeLookup, wearsThePracticeFrame, peopleSectionAt,
} from "./practiceWorkspace.ts";
import { rememberPracticeAccess, rememberedPracticeAccess } from "./practiceAccessMemory.ts";
import { canAccessWorkspace, type UserRole } from "../auth/permissions.ts";

const web = path.join(import.meta.dirname, "..", "..");
const read = (rel: string) => fs.readFileSync(path.join(web, rel), "utf8");

test("a practice address is the fixed prefix and everything under it, and nothing that only starts with the same letters", () => {
  for (const p of ["/practice", "/practice/", "/practice/billing/", "/practice/ar", "/practice/billing/?x=1"]) assert.equal(isPracticePath(p), true, p);
  // The earlier fee bills are a practice screen at an address of their own.
  for (const p of ["/billing", "/billing/"]) assert.equal(isPracticePath(p), true, p);
  for (const p of ["/", "", "/practices", "/practice-notes/", "/clients/", "/billings/", "/executive-dashboard/"]) assert.equal(isPracticePath(p), false, p);
});

test("every screen My practice lists is a page that exists under a practice address, once", () => {
  const ids = new Set<string>();
  for (const s of PRACTICE_SECTIONS) {
    assert.ok(!ids.has(s.id), `${s.id} is listed twice`);
    ids.add(s.id);
    assert.ok(isPracticePath(s.href), `${s.href} is not a practice address: it would be drawn in the firm's frame`);
    assert.ok(s.href.endsWith("/"), `${s.href}: the export serves every screen with a trailing slash`);
    const page = `app${s.href}page.tsx`;
    assert.ok(fs.existsSync(path.join(web, page)), `${page} does not exist`);
  }
  // And none is missing: every page under the prefix is on the list, so a screen added there is not left without a tile.
  const walk = (dir: string): string[] => fs.readdirSync(path.join(web, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(`${dir}/${e.name}`) : e.name === "page.tsx" ? [`${dir}/`.replace(/^app/, "")] : []);
  assert.deepEqual(PRACTICE_PREFIXES.flatMap((prefix) => walk(`app${prefix}`)).sort(), PRACTICE_SECTIONS.map((s) => s.href).sort());
});

// ── The People screens: one list, two doors (the owner's decision of 21-11-2026) ────────────────────────────────────────

/** The entries a panel's source lists, as "href|label|resource:action", in the order written. */
function panelEntries(rel: string, shape: RegExp): string[] {
  return [...read(rel).matchAll(shape)].map((m) => `${m.groups!.href}|${m.groups!.label}|${m.groups!.resource}:${m.groups!.action}`);
}
const TEAM_PANEL_ENTRY = /\{\s*href:\s*"(?<href>[^"]+)",\s*label:\s*"(?<label>[^"]+)",[^}]*requires:\s*\["(?<resource>[a-z_]+)",\s*"(?<action>[a-z_]+)"\]\s*\}/g;
const PRACTICE_PANEL_PERSON = /\{\s*label:\s*"(?<label>[^"]+)",\s*href:\s*"(?<href>[^"]+)",[^}]*requires:\s*\["(?<resource>[a-z_]+)",\s*"(?<action>[a-z_]+)"\]\s*\}/g;
const asEntry = (s: { href: string; label: string; requires: readonly [string, string] }) =>
  `${s.href.replace(/\/$/, "")}|${s.label}|${s.requires[0]}:${s.requires[1]}`;

test("the People screens are one list: the Manager's Team menu, My practice's menu and its tiles name the same screens in the same words", () => {
  const shared = PRACTICE_PEOPLE_SECTIONS.map(asEntry);
  assert.ok(shared.length >= 5, "the People list has shrunk");
  // The Manager's door. Its order is its own (it predates this list); the screens, words and pairs are the same.
  assert.deepEqual(panelEntries("components/panels/TeamPanel.tsx", TEAM_PANEL_ENTRY).sort(), [...shared].sort());
  // The Partner's door in the firm menu, in this list's order.
  assert.deepEqual(panelEntries("components/panels/PracticePanel.tsx", PRACTICE_PANEL_PERSON), shared);
  // And the tiles are drawn from the list itself.
  const grid = read("components/client/PracticeModuleGrid.tsx");
  assert.match(grid, /peopleSectionsOffered\(can, resolved\)/);
  assert.doesNotMatch(grid, /These open in the firm/, "the tiles still say they lead out of My practice");
  assert.doesNotMatch(grid, /"\/time\/?"/, "Time Tracking is back in My practice: every member of staff records hours, so it lives in Work");
});

test("every People screen is a page that exists, under a People address, and is on neither list twice", () => {
  const ids = new Set(PRACTICE_SECTIONS.map((s) => s.id));
  for (const s of PRACTICE_PEOPLE_SECTIONS) {
    assert.ok(!ids.has(s.id), `${s.id} is listed twice`);
    ids.add(s.id);
    assert.ok(s.href.endsWith("/"), `${s.href}: the export serves every screen with a trailing slash`);
    assert.ok(fs.existsSync(path.join(web, `app${s.href}page.tsx`)), `app${s.href}page.tsx does not exist`);
    assert.equal(isPeoplePath(s.href), true, s.href);
    assert.equal(isPracticePath(s.href), false, `${s.href} would be drawn in the practice's frame for a Manager too`);
  }
  // Every page under a People address is a People address, so a screen added there follows the person as well.
  const walk = (dir: string): string[] => fs.readdirSync(path.join(web, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(`${dir}/${e.name}`) : e.name === "page.tsx" ? [`${dir}/`.replace(/^app/, "")] : []);
  for (const page of PEOPLE_PREFIXES.flatMap((prefix) => walk(`app${prefix}`))) assert.equal(isPeoplePath(page), true, page);
  for (const p of ["/teams/", "/team-notes", "/approvals-old/", "/workflows/approvals/", "/time/", "/", ""]) assert.equal(isPeoplePath(p), false, p);
});

test("a People screen wears the My practice frame for somebody who may open My practice, and the firm's frame for everybody else", () => {
  const roles: UserRole[] = ["Partner", "Manager", "Executive", "Reviewer", "Client"];
  for (const role of roles) {
    const may = canAccessWorkspace("practice", role);
    for (const s of PRACTICE_PEOPLE_SECTIONS) {
      assert.equal(wearsThePracticeFrame(s.href, may), role === "Partner", `${role} on ${s.href}`);
    }
    // The practice's own screens are in its frame whoever asks: the server refuses their reads and the page sends them away.
    assert.equal(wearsThePracticeFrame("/practice/billing/", may), true);
    // And no other firm screen is pulled into it, for anybody.
    for (const p of ["/", "/clients/", "/work/", "/time/", "/payroll/", "/settings/", "/tasks/"]) assert.equal(wearsThePracticeFrame(p, may), false, `${role} on ${p}`);
  }
  // Nobody signed in, or a role that has not been read: the firm's frame.
  assert.equal(wearsThePracticeFrame("/team/", canAccessWorkspace("practice", null)), false);
});

test("the open People screen is named on the bar, and the longer address wins", () => {
  assert.equal(practiceSectionAt("/team/")?.id, "team");
  assert.equal(practiceSectionAt("/team")?.id, "team");
  assert.equal(practiceSectionAt("/team/assignments/")?.id, "assignments");
  assert.equal(practiceSectionAt("/team/workload/")?.id, "workload");
  assert.equal(practiceSectionAt("/team/login-history/")?.id, "login-history");
  assert.equal(practiceSectionAt("/approvals/")?.id, "approvals");
  // A page under Team that has no entry of its own is Team's.
  assert.equal(practiceSectionAt("/team/work-allocation/")?.id, "team");
});

test("a People entry is offered to whoever may read it, and nothing is withheld while the permissions are still being read", () => {
  assert.equal(peopleSectionsOffered(() => false, false).length, PRACTICE_PEOPLE_SECTIONS.length);
  assert.deepEqual(peopleSectionsOffered(() => false, true), []);
  assert.deepEqual(peopleSectionsOffered((r) => r === "workload", true).map((s) => s.id), ["workload"]);
});

test("the shell asks who is looking, and stands on the last answer only until the role has been read", () => {
  const shell = read("components/AppShell.tsx");
  assert.match(shell, /wearsThePracticeFrame\(realPathname, mayOpenPractice\)/);
  assert.match(shell, /const mayOpenPractice = roleLoading \? remembered : canAccessWorkspace\("practice", userRole\);/);
  assert.match(shell, /if \(!roleLoading\) rememberPracticeAccess\(canAccessWorkspace\("practice", userRole\)\);/);
});

test("the remembered answer is a convenience: empty or blocked storage answers no, and writing to it never throws", () => {
  const g = globalThis as unknown as { window?: unknown };
  const before = g.window;
  try {
    const held = new Map<string, string>();
    g.window = { localStorage: { getItem: (k: string) => held.get(k) ?? null, setItem: (k: string, v: string) => { held.set(k, v); } } };
    assert.equal(rememberedPracticeAccess(), false, "nothing remembered must be the firm's frame");
    rememberPracticeAccess(true);
    assert.equal(rememberedPracticeAccess(), true);
    rememberPracticeAccess(false);
    assert.equal(rememberedPracticeAccess(), false);
    g.window = { localStorage: { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } } };
    assert.equal(rememberedPracticeAccess(), false);
    assert.doesNotThrow(() => rememberPracticeAccess(true));
    g.window = undefined;
    assert.equal(rememberedPracticeAccess(), false);
    assert.doesNotThrow(() => rememberPracticeAccess(true));
  } finally {
    g.window = before;
  }
});

test("the books row in the firm menu keeps its place whatever the server said", () => {
  const panel = read("components/panels/PracticePanel.tsx");
  for (const state of ["ready", "not-set-up", "unavailable", "reading"]) {
    assert.match(panel, new RegExp(`data-practice-books="${state}"`), `no row is drawn while the books are ${state}, so the list under it moves`);
  }
});

test("a screen the firm menu also lists carries the same words there", () => {
  const panel = read("components/panels/PracticePanel.tsx");
  for (const s of PRACTICE_SECTIONS) {
    if (s.id === "home") continue;      // the panel calls it Overview, inside a panel that is already headed My practice
    const href = s.href.replace(/\/$/, "");
    assert.match(panel, new RegExp(`label: "${s.label}",\\s*href: "${href}"`), `the firm menu does not list ${href} as "${s.label}"`);
  }
});

test("the practice's books are every client section but the ones left out, and each of those is a real section with a reason", () => {
  const nav = read("lib/workspace/ClientNavContext.tsx");
  const sections = [...nav.matchAll(/\{ id: "([a-z-]+)",\s*label:/g)].map((m) => ({ id: m[1] }));
  assert.ok(sections.length >= 20, "the scan found no client sections");
  for (const [id, why] of Object.entries(NOT_FOR_THE_PRACTICE)) {
    assert.ok(sections.some((s) => s.id === id), `${id} is left out of My practice and is not a client section any more: delete its line`);
    assert.ok(why.length > 30, `${id} is left out with no reason`);
  }
  const offered = booksSectionsFor(sections).map((s) => s.id);
  // Payroll is one of them since the firm's own staff payroll was allowed (POST-A-532, second part).
  for (const must of ["overview", "accounting", "sales", "purchases", "bank", "compliance", "payroll", "fixed-assets", "year-end", "tax", "reports", "documents", "tasks"]) {
    assert.ok(offered.includes(must), `the practice's books lost ${must}`);
  }
  assert.equal(offered.length, sections.length - Object.keys(NOT_FOR_THE_PRACTICE).length);
});

test("the screen an address is: the home exactly, and a screen for itself and what is under it", () => {
  assert.equal(practiceSectionAt("/practice/")?.id, "home");
  assert.equal(practiceSectionAt("/practice/billing/")?.id, "billing");
  assert.equal(practiceSectionAt("/practice/billing/anything/")?.id, "billing");
  assert.equal(practiceSectionAt("/practice/unknown/"), null);
  assert.equal(practiceSectionAt("/clients/"), null);
});

test("the server's answer about the practice is ready, not set up, or unavailable, and a failed read is never 'not set up'", () => {
  assert.deepEqual(readPracticeLookup({ success: true, data: { internal_client_id: "c-1", provisioned: true } }), { state: "ready", practiceId: "c-1" });
  assert.deepEqual(readPracticeLookup({ success: true, data: { internal_client_id: null, provisioned: false } }), { state: "not-set-up", practiceId: null });
  for (const bad of [null, undefined, "x", [], { success: false, data: null, error: "no" }, { success: true, data: null }, { success: true, data: [] },
    { success: true, data: {} }, { success: true, data: { internal_client_id: "" } }, { success: true, data: { internal_client_id: 7, provisioned: true } },
    // The walk's stub answers every unknown read with an empty list.
    { success: true, data: { provisioned: "false" } }]) {
    assert.deepEqual(readPracticeLookup(bad), { state: "unavailable", practiceId: null }, JSON.stringify(bad));
  }
});

test("the People screen an address is on, for the pair its gate asks (POST-A-542)", () => {
  // Each People screen's own address, with and without the trailing slash, a query and a deeper address.
  for (const s of PRACTICE_PEOPLE_SECTIONS) {
    assert.equal(peopleSectionAt(s.href)?.id, s.id);
    assert.equal(peopleSectionAt(s.href.replace(/\/$/, ""))?.id, s.id);
    assert.equal(peopleSectionAt(`${s.href}?tab=x`)?.id, s.id);
  }
  // The longest address wins: Workload is not Team, although its address is under Team's.
  assert.deepEqual(peopleSectionAt("/team/workload/")?.requires, ["workload", "read"]);
  assert.deepEqual(peopleSectionAt("/team/assignments/x/")?.requires, ["assignment", "read"]);
  // An address under Team that is no screen of its own takes Team's pair, so nothing under /team is ungated.
  assert.deepEqual(peopleSectionAt("/team/work-allocation/")?.requires, ["team", "read"]);
  // Nothing else is a People screen.
  for (const other of ["/", "/teams/", "/practice/", "/approvals-x/", "/clients/c-1/", ""]) assert.equal(peopleSectionAt(other), null, other);
});
