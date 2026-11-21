// POST-A-543 (the safety step): a screen whose reads ask one permission pair is gated, listed on the menu and offered by
// the guide BY THAT PAIR, and the workflow statistics are shown only to whoever may read them.
//   node --experimental-strip-types --test scripts/a-screen-behind-a-tick-is-offered-by-that-tick.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ALL_SCREENS } from "../lib/navigation/screens.ts";
import { SCREEN_PAIRS, offeredTo, screenId, type Who } from "../lib/guide/whereIs.ts";
import { stripComments } from "./stripComments.ts";

const WEB = path.join(import.meta.dirname, "..");
const code = (rel: string) => stripComments(fs.readFileSync(path.join(WEB, rel), "utf8"));
const who = (role: Who["role"], pairs: string[]): Who => ({
  role, can: (r, a) => pairs.includes(`${r}:${a}`), resolved: true, clientSectionOffered: () => true,
});
const screen = (id: string) => {
  const found = ALL_SCREENS.find((s) => screenId(s) === id);
  assert.ok(found, `${id} is not a screen`);
  return found;
};

test("each gated address has a layout that mounts the gate on the same pair", () => {
  assert.ok(SCREEN_PAIRS.length >= 2);
  for (const [prefix, resource, action] of SCREEN_PAIRS) {
    const layout = code(`app${prefix}/layout.tsx`);
    assert.match(layout, /<TickGate\b/, `${prefix} has no gate`);
    assert.ok(layout.includes(`requires={["${resource}", "${action}"]}`), `${prefix}: the gate asks a different pair from the list`);
  }
  // And no page mounts the gate on a pair this list does not know: a gate added without a line here would leave the guide
  // and the menus offering the screen the gate refuses.
  const walk = (dir: string): string[] => fs.readdirSync(path.join(WEB, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(`${dir}/${e.name}`) : e.name === "layout.tsx" || e.name === "page.tsx" ? [`${dir}/${e.name}`] : []);
  const gated = walk("app").filter((f) => /<TickGate\b/.test(code(f))).map((f) => "/" + f.split("/").slice(1, -1).join("/"));
  assert.deepEqual(gated.sort(), SCREEN_PAIRS.map(([prefix]) => prefix).sort());
});

test("the gate asks the permission and never a role, and waits until the permissions are known", () => {
  const gate = code("components/auth/TickGate.tsx");
  assert.match(gate, /resolved && !can\(requires\[0\], requires\[1\]\)/);
  assert.doesNotMatch(gate, /userRole|"Partner"|"Manager"/);
  assert.match(gate, /is not part of your access/);
  assert.match(gate, /that is not the same as there being nothing/);
});

test("the guide offers a gated screen to whoever holds its pair, whatever their role", () => {
  const pipeline = screen("firm:/pipeline");
  const engagements = screen("firm:/engagements");
  assert.equal(offeredTo(pipeline, who("Executive", [])), false, "an Executive without the tick is pointed at the pipeline");
  assert.equal(offeredTo(pipeline, who("Executive", ["pipeline:read"])), true, "a tick a Partner gave is not honoured");
  assert.equal(offeredTo(pipeline, who("Manager", ["pipeline:read"])), true);
  assert.equal(offeredTo(pipeline, who("Manager", [])), false, "a Manager a Partner blocked is still pointed at it");
  assert.equal(offeredTo(engagements, who("Reviewer", [])), false);
  assert.equal(offeredTo(engagements, who("Reviewer", ["engagement:read"])), true);
  // While the permissions are still being read nothing is withheld on a pair.
  assert.equal(offeredTo(pipeline, { ...who("Manager", []), resolved: false }), true);
});

test("the menu entries follow the same pairs", () => {
  assert.match(code("components/panels/ClientsPanel.tsx"), /item\.href !== "\/pipeline" \|\| can\("pipeline", "read"\)/);
  assert.match(code("app/clients/page.tsx"), /\{can\("pipeline", "read"\) && \(\s*<Link\s+href="\/pipeline"/);
  const config = code("lib/workspace/workspaceConfig.ts");
  const engagements = config.slice(config.indexOf('id: "engagements"'));
  assert.match(engagements.slice(0, engagements.indexOf("},")), /requires: \["engagement", "read"\]/);
});

test("the workflow statistics are asked for and shown only by whoever may read them, and a tile is never a 0 nobody read", () => {
  const page = code("app/workflows/page.tsx");
  assert.match(page, /const mayReadStats = can\("analytics", "read"\);/);
  assert.match(page, /mayReadStats \? api\.workflowEngine\.analytics\(\)/, "the statistics are requested by somebody the server refuses");
  assert.match(page, /\{mayReadStats && \(\s*<div[^>]*data-workflow-stats/);
  assert.match(page, /t !== "analytics" \|\| mayReadStats/);
  assert.doesNotMatch(page, /summary\?\.[a-z_]+ \?\? 0/, "a statistics tile shows 0 where nothing was read");
});
