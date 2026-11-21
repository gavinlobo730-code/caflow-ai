// POST-A-532: which addresses are My practice, which screens it lists, and which client sections it leaves out and why.
//   node --experimental-strip-types --test lib/workspace/practiceWorkspace.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { NOT_FOR_THE_PRACTICE, PRACTICE_PREFIXES, PRACTICE_SECTIONS, PRACTICE_TEAM_SECTIONS, booksSectionsFor, isPracticePath, practiceSectionAt, readPracticeLookup } from "./practiceWorkspace.ts";

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

test("the team and its hours are pointed at, in the firm menus' own words, and are not drawn in the practice's frame", () => {
  const menus = read("components/panels/TeamPanel.tsx") + read("components/panels/WorkPanel.tsx");
  assert.ok(PRACTICE_TEAM_SECTIONS.length >= 3);
  for (const s of PRACTICE_TEAM_SECTIONS) {
    assert.equal(isPracticePath(s.href), false, `${s.href} would be drawn in the practice's frame, and a Manager reaches it too`);
    assert.ok(fs.existsSync(path.join(web, `app${s.href}page.tsx`)), `app${s.href}page.tsx does not exist`);
    const href = s.href.replace(/\/$/, "");
    assert.match(menus, new RegExp(`href: "${href}", label: "${s.label}"`), `the firm menus do not list ${href} as "${s.label}"`);
    assert.ok(!PRACTICE_SECTIONS.some((p) => p.id === s.id), `${s.id} is in both lists`);
  }
  const grid = read("components/client/PracticeModuleGrid.tsx");
  assert.match(grid, /PRACTICE_TEAM_SECTIONS\.map/);
  assert.match(grid, /These open in the firm&apos;s Team and Work menus\./);
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
