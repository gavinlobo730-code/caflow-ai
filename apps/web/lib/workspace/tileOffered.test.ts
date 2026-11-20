// POST-A-447. A workspace tile is offered only when the screens behind it admit the caller, so it never opens a panel
// with every entry filtered out. Team is the case: its screens each ask a different pair, all Manager and above.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { workspaceTileOffered } from "./tileOffered.ts";

const WEB = join(import.meta.dirname, "..", "..");
const API = join(WEB, "..", "api");

type Pair = readonly [string, string];

/** The pairs on the Team entry of WORKSPACE_CONFIGS, read from the source (the file imports icons node cannot load). */
function teamAnyOf(): string[] {
  const src = readFileSync(join(WEB, "lib", "workspace", "workspaceConfig.ts"), "utf8");
  const at = src.indexOf('id: "team"');
  assert.ok(at >= 0, "the Team workspace is gone from workspaceConfig.ts");
  const block = src.slice(at, src.indexOf("\n  },", at));
  const list = block.match(/requiresAnyOf:\s*\[(.*)\],?\s*$/m);
  assert.ok(list, "the Team workspace names no requiresAnyOf: an Executive is offered a tile that opens on nothing");
  return [...list[1].matchAll(/\["([a-z_]+)",\s*"([a-z_]+)"\]/g)].map((m) => `${m[1]}:${m[2]}`).sort();
}

/** Every entry TeamPanel lists, with the pair it filters on, or null where it carries none. */
function teamPanelEntries(): Array<{ href: string; pair: string | null }> {
  const src = readFileSync(join(WEB, "components", "panels", "TeamPanel.tsx"), "utf8");
  const items = [...src.matchAll(/\{\s*href:\s*"([^"]+)"[^}]*\}/g)];
  assert.ok(items.length >= 5, `only ${items.length} Team entries read: the panel's shape has moved`);
  return items.map((m) => {
    const r = m[0].match(/requires:\s*\["([a-z_]+)",\s*"([a-z_]+)"\]/);
    return { href: m[1], pair: r ? `${r[1]}:${r[2]}` : null };
  });
}

test("every Team entry carries a pair, so the tile's any-of is the whole story", () => {
  const bare = teamPanelEntries().filter((e) => e.pair === null).map((e) => e.href);
  assert.deepEqual(bare, [], "a Team entry with no pair is open to everyone, so the tile must not be hidden on the others");
});

test("the Team tile's any-of is exactly the set of pairs its panel filters on", () => {
  const panel = [...new Set(teamPanelEntries().map((e) => e.pair as string))].sort();
  assert.deepEqual(teamAnyOf(), panel);
});

test("each of those pairs is Manager and above in the server's table today, which is why the tile was empty", () => {
  const src = readFileSync(join(API, "core", "permissions.py"), "utf8");
  for (const p of teamAnyOf()) {
    const [resource, action] = p.split(":");
    const block = src.slice(src.indexOf(`"${resource}": {`));
    const line = block.slice(0, block.indexOf("},")).match(new RegExp(`"${action}":\\s*(_[A-Z_]+)`));
    assert.ok(line, `${p} is not in core/permissions.py`);
    assert.ok(["_AT_LEAST_MANAGER", "_PARTNER_ONLY"].includes(line[1]), `${p} is ${line[1]}: an Executive would see an entry`);
  }
});

test("the tile is offered when any one pair admits the caller, and not when none does", () => {
  const ws = { requiresAnyOf: [["team", "read"], ["workload", "read"]] as Pair[] };
  assert.equal(workspaceTileOffered(ws, () => false, true), false);
  assert.equal(workspaceTileOffered(ws, (r) => r === "workload", true), true);
  assert.equal(workspaceTileOffered(ws, (r) => r === "team", true), true);
});

test("a single required pair still decides by itself, and both rules must hold", () => {
  assert.equal(workspaceTileOffered({ requires: ["payroll", "read"] }, () => false, true), false);
  assert.equal(workspaceTileOffered({ requires: ["payroll", "read"] }, () => true, true), true);
  assert.equal(workspaceTileOffered({}, () => false, true), true, "a workspace with neither rule is always offered");
  assert.equal(
    workspaceTileOffered({ requires: ["payroll", "read"], requiresAnyOf: [["team", "read"]] }, (r) => r === "payroll", true),
    false,
  );
});

test("nothing is withheld while the permissions are still being read", () => {
  assert.equal(workspaceTileOffered({ requiresAnyOf: [["team", "read"]] }, () => false, false), true);
});

test("the menu asks this rule, not a hand-written copy of it", () => {
  const menu = readFileSync(join(WEB, "components", "shell", "WorkspaceMegaMenu.tsx"), "utf8");
  assert.match(menu, /workspaceTileOffered\(ws, can, resolved\)/);
  assert.doesNotMatch(menu, /ws\.requires\[0\]/, "the menu checks a pair by hand again and will miss requiresAnyOf");
});
