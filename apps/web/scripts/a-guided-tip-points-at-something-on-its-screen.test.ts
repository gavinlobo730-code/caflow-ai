// POST-A-531: a guided tip is a claim about a screen ("this button does that"), so every tip is held to the screen it is on.
// Run with: node --experimental-strip-types --test scripts/a-guided-tip-points-at-something-on-its-screen.test.ts
//
// WHAT IS HELD
//   * a tip's anchor is a `data-tip` attribute in the file the tip names, and that file is the tip's own screen or the shell
//     every screen is drawn in;
//   * every label a tip quotes between “ and ” is on its `holds` list, and every held label is still written in its file,
//     so renaming a button breaks the tip that names it in the same pull request;
//   * a tip's words carry no figure: no digit, no rupee sign and no per cent. A tip says where a thing is and what pressing
//     it does; a rate, a date or a limit belongs to the statutory modules and is never restated in a pop-up;
//   * ids are slugs the server accepts and no two tips share one; every screen with a tip is a real screen and a stop of the
//     tour, and every stop has a label and a tip;
//   * no `data-tip` in the tree is left without a tip (an anchor nothing points at is a tip somebody deleted by half).
//
// WHAT IS NOT. That the pop-up really appears beside the button is a fact about a browser: it was driven by hand in Chromium
// when this was written and is not held here. That the SENTENCE is true beyond the labels it quotes is read by a person.
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { TIPS, TOUR, TOUR_LABELS, type Tip } from "../lib/tips/registry.ts";
import { walkPages } from "./generate-redirects.js";

const web = path.join(import.meta.dirname, "..");
const read = (file: string): string | null => {
  const full = path.join(web, file);
  return fs.existsSync(full) ? fs.readFileSync(full, "utf8") : null;
};
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const quoted = (s: string): string[] => [...s.matchAll(/“([^”]*)”/g)].map((m) => m[1]);
const pageOf = (route: string): string => (route === "/" ? "app/page.tsx" : `app${route}/page.tsx`);
// The dashboard's page file hands over to a component; a tip on "/" may also sit in the shell, which every screen is drawn in.
const SHELL = "components/shell/";

/** Everything wrong with a list of tips, in sentences. Empty when every tip is held. */
function problemsWith(tips: readonly Tip[], readFile: (file: string) => string | null, routes: ReadonlySet<string>, tour: readonly string[]): string[] {
  const out: string[] = [];
  const ids = new Set<string>();
  for (const t of tips) {
    if (!SLUG.test(t.id) || t.id.length > 64) out.push(`${t.id}: the id is not a slug the server accepts`);
    if (ids.has(t.id)) out.push(`${t.id}: two tips share this id`);
    ids.add(t.id);
    if (!routes.has(t.path)) out.push(`${t.id}: ${t.path} is not a screen`);
    if (!tour.includes(t.path)) out.push(`${t.id}: ${t.path} is not a stop of the tour, so no "Next" link leads to it`);
    if (t.source !== pageOf(t.path) && !t.source.startsWith(SHELL)) out.push(`${t.id}: ${t.source} is neither the screen's own page nor the shell`);
    const src = readFile(t.source);
    if (src === null) out.push(`${t.id}: ${t.source} does not exist`);
    else if (!src.includes(`data-tip="${t.anchor}"`)) out.push(`${t.id}: ${t.source} carries no data-tip="${t.anchor}"`);
    const held = new Set(t.holds.map((h) => h.text));
    for (const q of quoted(`${t.title} ${t.body}`)) if (!held.has(q)) out.push(`${t.id}: it quotes “${q}” and does not hold it to a file`);
    for (const h of t.holds) {
      if (!quoted(`${t.title} ${t.body}`).includes(h.text)) out.push(`${t.id}: it holds “${h.text}” and does not quote it`);
      const file = readFile(h.file);
      if (file === null) out.push(`${t.id}: ${h.file} does not exist`);
      else if (!file.includes(h.text)) out.push(`${t.id}: ${h.file} no longer writes “${h.text}”`);
    }
    const words = `${t.title} ${t.body}`.replace(/Ctrl\+K|Command\+K/g, "");
    if (/[0-9₹%]/.test(words)) out.push(`${t.id}: its words carry a figure`);
    if (!t.title.trim() || !t.body.trim()) out.push(`${t.id}: it says nothing`);
  }
  return out;
}

const routes = new Set<string>((walkPages(path.join(web, "app")) as string[][]).map((segments) => "/" + segments.join("/")));

test("every tip is held: its anchor is on its screen, its quoted labels are in the code, and it carries no figure", () => {
  assert.ok(TIPS.length >= 5, "the scan found no tips to judge");
  assert.deepEqual(problemsWith(TIPS, read, routes, TOUR), []);
});

test("the tour's stops are real screens, each with a label and at least one tip", () => {
  assert.equal(new Set(TOUR).size, TOUR.length, "a screen is on the tour twice");
  for (const stop of TOUR) {
    assert.ok(routes.has(stop), `${stop} is not a screen`);
    assert.ok(TOUR_LABELS[stop], `${stop} has no label for the "Next" link`);
    assert.ok(TIPS.some((t) => t.path === stop), `${stop} is on the tour and has no tip`);
  }
  assert.deepEqual(Object.keys(TOUR_LABELS).sort(), [...TOUR].sort(), "a label is written for a screen that is not on the tour");
});

test("no anchor in the tree is left without a tip, and each sits in the file its tip names", () => {
  const found = new Map<string, string[]>();
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(path.join(web, dir), { withFileTypes: true })) {
      const rel = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(rel);
      else if (/\.tsx$/.test(entry.name)) {
        for (const m of fs.readFileSync(path.join(web, rel), "utf8").matchAll(/data-tip="([a-z0-9]+(?:-[a-z0-9]+)*)"/g)) {
          found.set(m[1], [...(found.get(m[1]) ?? []), rel]);
        }
      }
    }
  };
  walk("app");
  walk("components");
  assert.ok(found.size >= 5, "the scan found no anchors to judge");
  const byAnchor = new Map(TIPS.map((t) => [t.anchor, t]));
  for (const [anchor, files] of found) {
    const tip = byAnchor.get(anchor);
    assert.ok(tip, `data-tip="${anchor}" in ${files.join(", ")} has no tip: delete the attribute or write the tip`);
    assert.deepEqual([...new Set(files)], [tip.source], `data-tip="${anchor}" is written outside the file its tip names`);
  }
  assert.equal(new Set(TIPS.map((t) => t.anchor)).size, TIPS.length, "two tips point at one anchor");
});

test("the check itself fails on each thing it exists to catch", () => {
  const good: Tip = { id: "ok", path: "/x", anchor: "a", source: "app/x/page.tsx", title: "Press “Save”", body: "It saves.", holds: [{ text: "Save", file: "app/x/page.tsx" }] };
  const files: Record<string, string> = { "app/x/page.tsx": `<button data-tip="a">Save</button>`, "components/shell/Bar.tsx": `<button data-tip="b">Menu</button>` };
  const rd = (f: string) => files[f] ?? null;
  const screens = new Set(["/x"]);
  const judge = (over: Partial<Tip>) => problemsWith([{ ...good, ...over }], rd, screens, ["/x"]);
  assert.deepEqual(judge({}), []);
  assert.deepEqual(judge({ anchor: "b", source: "components/shell/Bar.tsx", title: "The menu", holds: [] }), [], "a tip may sit in the shell");
  assert.match(judge({ anchor: "gone" })[0], /carries no data-tip="gone"/);
  assert.match(judge({ source: "app/y/page.tsx" }).join("\n"), /neither the screen's own page nor the shell/);
  assert.match(judge({ source: "app/y/page.tsx" }).join("\n"), /does not exist/);
  assert.match(judge({ holds: [] })[0], /quotes “Save” and does not hold it/);
  assert.match(judge({ holds: [{ text: "Save", file: "components/shell/Bar.tsx" }] })[0], /no longer writes “Save”/);
  assert.match(judge({ title: "Press it" })[0], /holds “Save” and does not quote it/);
  assert.match(judge({ body: "It saves within 30 days." })[0], /carry a figure/);
  assert.match(judge({ body: "It costs ₹ nothing." })[0], /carry a figure/);
  assert.match(judge({ id: "Not A Slug" })[0], /not a slug/);
  assert.match(judge({ path: "/nowhere" }).join("\n"), /is not a screen/);
  assert.match(problemsWith([good, good], rd, screens, ["/x"]).join("\n"), /two tips share this id/);
  assert.match(problemsWith([good], rd, screens, []).join("\n"), /not a stop of the tour/);
});

test("the tips are driven in a browser from the weekly set, and every tip a scenario names exists", () => {
  // The nightly drive and the on-demand matrix are both at the end of their allowance, so these scenarios are in
  // `scripts/drive/weekly/` (run with `--weekly`) and a night does not count them.
  const weekly = fs.readdirSync(path.join(web, "scripts/drive/weekly")).filter((f) => f.endsWith(".mjs"));
  assert.ok(weekly.includes("guidedTips.mjs"), "the tips' browser scenarios are gone from scripts/drive/weekly/");
  assert.ok(!fs.existsSync(path.join(web, "scripts/drive/scenarios/guidedTips.mjs")), "the tips' scenarios are in the nightly set, which has no room for them");
  const src = read("scripts/drive/weekly/guidedTips.mjs")!;
  const ids = new Set(TIPS.map((t) => t.id));
  const named = [...src.matchAll(/"((?:start|add|own|billing|deadlines)-[a-z-]+)"/g)].map((m) => m[1]);
  assert.ok(named.length >= 4, "the scan found no tip id in the scenarios");
  for (const id of named) assert.ok(ids.has(id), `the scenarios name the tip "${id}", which is not a tip`);
  const runner = read("scripts/driveMoneyEditors.mjs")!;
  assert.match(runner, /WEEKLY_DIR = path\.join\(__dirname, "drive", "weekly"\)/);
  assert.match(runner, /flags\["--weekly"\]/, "the runner no longer takes --weekly");
  // A weekly set nothing runs is a set nobody reads: the weekly workflow drives it after its own build.
  const workflow = fs.readFileSync(path.join(web, "../../.github/workflows/frame-walk.yml"), "utf8");
  const body = workflow.split("\n").filter((l) => !l.trim().startsWith("#")).join("\n");
  assert.match(body, /run: node scripts\/driveMoneyEditors\.mjs --weekly\b/, "the weekly workflow no longer drives the weekly scenarios");
});
