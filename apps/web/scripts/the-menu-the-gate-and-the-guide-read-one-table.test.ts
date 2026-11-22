// POST-A-543: the firm menu, the gate on every firm screen and the guide all ask ONE table which permission opens what, and
// a menu entry that names a pair of its own names one the table also asks. The workflow statistics are shown only to
// whoever may read them.
//   node --experimental-strip-types --test scripts/the-menu-the-gate-and-the-guide-read-one-table.test.ts
import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { ALL_SCREENS } from "../lib/navigation/screens.ts";
import { offeredTo, screenId, type Who } from "../lib/guide/whereIs.ts";
import { AREA_RULES, mayOpen, screenRule, type AccessRule } from "../lib/access/screenAccess.ts";
import { getActiveWorkspaceForPathname } from "../lib/workspace/routeOwnership.ts";
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
const names = (rule: AccessRule | null | undefined): string[] =>
  rule ? [...(rule.all ?? []), ...(rule.any ?? [])].map(([r, a]) => `${r}:${a}`) : [];

test("the shell mounts the one gate around every page, and the gate asks the table and never a role", () => {
  const shell = code("components/AppShell.tsx");
  assert.match(shell, /<ScreenAccessGate pathname=\{realPathname\}>\{children\}<\/ScreenAccessGate>/);
  const gate = code("components/auth/ScreenAccessGate.tsx");
  assert.match(gate, /const \{ verdict \} = useScreenAccess\(\);/);
  assert.match(gate, /if \(!answer \|\| answer\.allowed \|\| answer\.partnerOnly \|\| !answer\.ask\) return <>\{children\}<\/>;/);
  assert.doesNotMatch(gate, /userRole|"Partner"|"Manager"|"Executive"|"Reviewer"/);
  assert.match(gate, /is not part of your access/);
  assert.match(gate, /that is not the same as there being nothing/);
  // Until the permissions are known the hook answers nothing, so the page is drawn as it always was.
  assert.match(code("lib/access/useScreenAccess.ts"), /verdict: \(href\) => \(resolved \? mayOpen\(href, who\) : null\)/);
});

test("the role lists that hid areas and addresses are gone, with the two functions that read them", () => {
  const perms = code("lib/auth/permissions.ts");
  for (const gone of ["STAFF_HIDDEN_HREFS", "MANAGER_HIDDEN_HREFS", "STAFF_HIDDEN_WORKSPACES", "PARTNER_ONLY_WORKSPACES", "ALWAYS_VISIBLE", "canAccessHref", "canAccessWorkspace"]) {
    assert.ok(!perms.includes(gone), `${gone} is back in lib/auth/permissions.ts: the menu would follow a role again`);
  }
  const walk = (dir: string): string[] => fs.readdirSync(path.join(WEB, dir), { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? (e.name === "node_modules" ? [] : walk(`${dir}/${e.name}`)) : /\.tsx?$/.test(e.name) && !e.name.endsWith(".test.ts") ? [`${dir}/${e.name}`] : []);
  for (const file of [...walk("app"), ...walk("components"), ...walk("lib")]) {
    assert.doesNotMatch(code(file), /\bcanAccess(Href|Workspace)\(/, `${file} asks a role list that no longer exists`);
  }
});

test("every panel of the firm menu lists its entries through the table", () => {
  for (const panel of ["HomePanel", "ClientsPanel", "DeadlinesPanel", "WorkPanel", "AIPanel", "AccountingPanel", "RelationshipsPanel", "HealthPanel", "KnowledgePanel"]) {
    const src = code(`components/panels/${panel}.tsx`);
    assert.match(src, /const \{ offered \} = useScreenAccess\(\);/, `${panel} does not ask the table`);
    assert.match(src, /offered\(/, `${panel} reads the table and filters nothing with it`);
  }
  // The four that do not: each of their entries is the area's own rule or carries its pair on the entry.
  //   TeamPanel, PracticePanel: every entry names its pair (`tileOffered.test.ts`, `practiceWorkspace.test.ts`).
  //   PayrollPanel: every entry asks payroll:read, the area's rule. EngagementsPanel: tabs of one screen.
});

test("a menu entry that names a pair of its own names one the table asks for that address", () => {
  const panels = fs.readdirSync(path.join(WEB, "components", "panels")).filter((f) => f.endsWith("Panel.tsx") && f !== "SettingsPanel.tsx");
  let checked = 0;
  for (const file of panels) {
    const src = fs.readFileSync(path.join(WEB, "components", "panels", file), "utf8");
    for (const m of src.matchAll(/\{[^{}]*?href:\s*"([^"]+)"[^{}]*?requires:\s*\["([a-z_]+)",\s*"([a-z_]+)"\][^{}]*?\}/gs)) {
      const [href, pair] = [m[1], `${m[2]}:${m[3]}`];
      const area = getActiveWorkspaceForPathname(href.split("?")[0]);
      const asked = [...names(screenRule(href)), ...names(area ? AREA_RULES[area] : null)];
      assert.ok(asked.includes(pair), `${file}: ${href} is listed by ${pair}, and the table asks ${asked.join(", ") || "nothing"} for it`);
      checked += 1;
    }
  }
  assert.ok(checked >= 25, `only ${checked} entries with a pair were read: the panels' shape has moved`);
});

test("the guide offers exactly what the gate opens, for every firm screen and each role's own permissions", () => {
  const API = path.join(WEB, "..", "api");
  const maps = JSON.parse(fs.readFileSync(path.join(WEB, "scripts", "drive", "role-permissions.json"), "utf8")) as Record<string, Record<string, string[]>>;
  assert.ok(fs.existsSync(path.join(API, "core", "permissions.py")));
  let compared = 0;
  for (const role of ["Partner", "Manager", "Executive", "Reviewer"] as const) {
    const map = maps[role];
    assert.ok(map, `no permission map for ${role}`);
    const can = (r: string, a: string) => (map[r] ?? []).includes(a);
    const asker = { can, isPartner: role === "Partner" };
    for (const s of ALL_SCREENS) {
      // The Settings pages are compared too since they joined the table (POST-A-545): they were skipped while each kept a
      // role guard of its own.
      if (s.scope !== "firm") continue;
      const guide = offeredTo(s, { role, can, resolved: true, clientSectionOffered: () => true });
      assert.equal(guide, mayOpen(s.href, asker).allowed, `${role} on ${s.href}: the guide and the gate disagree`);
      compared += 1;
    }
  }
  assert.ok(compared >= 400);
});

test("the guide offers a screen to whoever holds its pair, whatever their role", () => {
  const pipeline = screen("firm:/pipeline");
  const engagements = screen("firm:/engagements");
  assert.equal(offeredTo(pipeline, who("Executive", ["client:read"])), false, "an Executive without the tick is pointed at the pipeline");
  assert.equal(offeredTo(pipeline, who("Executive", ["client:read", "pipeline:read"])), true, "a tick a Partner gave is not honoured");
  assert.equal(offeredTo(pipeline, who("Manager", ["client:read"])), false, "a Manager a Partner blocked is still pointed at it");
  assert.equal(offeredTo(engagements, who("Reviewer", [])), false);
  assert.equal(offeredTo(engagements, who("Reviewer", ["engagement:read"])), true);
  // Deadlines and Work are a role's no longer: whoever holds the pairs is offered them.
  assert.equal(offeredTo(screen("firm:/deadlines"), who("Reviewer", ["compliance:read"])), true);
  assert.equal(offeredTo(screen("firm:/deadlines"), who("Manager", [])), false);
  assert.equal(offeredTo(screen("firm:/tasks"), who("Executive", ["task:read"])), true);
  // My practice is not a tick.
  assert.equal(offeredTo(screen("firm:/practice"), who("Manager", ["practice:read", "billing:read"])), false);
  assert.equal(offeredTo(screen("firm:/practice"), who("Partner", [])), true);
  // While the permissions are still being read nothing is withheld on a pair.
  assert.equal(offeredTo(pipeline, { ...who("Manager", []), resolved: false }), true);
  assert.equal(offeredTo(screen("firm:/practice"), { ...who("Manager", []), resolved: false }), false);
});

test("the menu entries for the pipeline follow its pair as well as the table", () => {
  assert.match(code("components/panels/ClientsPanel.tsx"), /item\.href !== "\/pipeline" \|\| can\("pipeline", "read"\)/);
  assert.match(code("app/clients/page.tsx"), /\{can\("pipeline", "read"\) && \(\s*<Link\s+href="\/pipeline"/);
});

test("the workflow statistics are asked for and shown only by whoever may read them, and a tile is never a 0 nobody read", () => {
  const page = code("app/workflows/page.tsx");
  assert.match(page, /const mayReadStats = can\("analytics", "read"\);/);
  assert.match(page, /mayReadStats \? api\.workflowEngine\.analytics\(\)/, "the statistics are requested by somebody the server refuses");
  assert.match(page, /\{mayReadStats && \(\s*<div[^>]*data-workflow-stats/);
  assert.match(page, /t !== "analytics" \|\| mayReadStats/);
  assert.doesNotMatch(page, /summary\?\.[a-z_]+ \?\? 0/, "a statistics tile shows 0 where nothing was read");
});
