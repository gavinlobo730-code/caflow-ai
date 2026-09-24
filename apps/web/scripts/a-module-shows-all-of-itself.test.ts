/**
 * A module's sidebar lists the whole module.
 *
 * WHAT WAS WRONG. This product has two navigation surfaces per workspace — the
 * 220px panel the shell renders on every page of the module, and the module's
 * own landing page — and, measured on main 5786f68f, they listed DISJOINT sets
 * for every module that had both:
 *
 *   /accounting   10 screens on the landing page, 4 in the panel, no overlap
 *   /settings      8 on the landing page, 1 in the panel, no overlap
 *   /gst /income-tax /tds /reports   11 on landing pages, the panel offered
 *                                    the module ROOT and nothing else
 *   /practice /health /relationships /team /clients /tasks /notifications
 *                                    all in the panel, none on a landing page
 *
 * and two screens — `/payroll/attendance`'s owning panel and `/team/workload` —
 * were in neither, reachable only by typing their names into ⌘K.
 *
 * So which half of their own module a CA could see depended on which surface
 * they happened to navigate by. Worse, standing ON one of those screens the
 * landing page is not in front of them and the panel is, so from
 * `/income-tax/capital-gains` there was no way to `/income-tax/tax-audit`
 * except the browser's Back button.
 *
 * THE RULE, AND WHY THE PANEL RATHER THAN THE LANDING PAGE. The panel is the
 * surface present on every page of the workspace, which is what makes it the
 * one that has to be complete. A landing page may feature whatever it likes —
 * it has room to explain, which a 220px rail has not — so this guard says
 * nothing about landing pages, and adding a screen to one does not satisfy it.
 *
 * WHAT "IN THE PANEL" MEANS. The href appears in the panel's source. A panel
 * may disclose progressively (DeadlinesPanel renders a hub's children only
 * inside that hub, because a flat list of sixteen filing screens is a wall),
 * and that is navigation working rather than a gap — but every href is still
 * DECLARED, which is what this reads.
 *
 * ⚠️ THE OWNING PANEL, NOT ANY PANEL. `/payroll/attendance` is linked from
 * TeamPanel as a cross-module convenience and was missing from the panel that
 * actually owns `/payroll` — so a CA in the Accounting workspace could not
 * reach it. The question is asked of `getActiveWorkspaceForPathname`, which is
 * why that chain moved to `lib/workspace/routeOwnership.ts`: a guard that
 * re-implemented it would be a second copy of the mapping, which is the defect
 * this repository records over and over, and one that regex-matched the source
 * would be a spelling of the rule rather than the rule.
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { SCREENS } from "../lib/navigation/screens.ts";
import { getActiveWorkspaceForPathname } from "../lib/workspace/routeOwnership.ts";

const WEB = join(import.meta.dirname, "..");

/** Which panel component serves which workspace — READ OFF `ContextPanel.tsx`
 *  rather than copied, so a workspace given a new panel cannot leave this
 *  guard asserting against a mapping that no longer exists. */
function panelForWorkspace(): Record<string, string> {
  const src = readFileSync(join(WEB, "components/ContextPanel.tsx"), "utf8");
  const out: Record<string, string> = {};
  // `[\s(]*` between the test and the element is load-bearing: prettier wraps
  // the longer branches as `&& (\n  <ClientsPanel onOpenSearch=…`, so a regex
  // wanting `&& <` read six of the twelve pairs and silently reported every
  // Clients screen as owned by no panel. It failed on its first run for exactly
  // that, which is the cheapest place for a spelling to be caught.
  for (const m of src.matchAll(/panelWorkspace === "(\w+)" &&[\s(]*<(\w+)/g)) out[m[1]] = m[2];
  return out;
}

/** `/settings` is the one route ContextPanel picks by PATH rather than by
 *  workspace (`isSettings ? <SettingsPanel/> : …`), because the rail lights its
 *  own gear icon for it. Asserted here so the branch cannot quietly go away. */
function settingsIsPanelledByPath(): boolean {
  const src = readFileSync(join(WEB, "components/ContextPanel.tsx"), "utf8");
  return /isSettings\s*\?[\s(]*<SettingsPanel/.test(src);
}

/**
 * Screens with no owning panel, each with why. A route here is one no
 * workspace owns — NOT one somebody forgot. It may only shrink by argument.
 */
const NO_BROWSE_SURFACE: Record<string, string> = {
  "/search":
    "the command palette's own results page. It is REACHED by ⌘K, so listing " +
    "it in a sidebar would be a link to the thing the reader just used",
  "/platform":
    "the super-admin console. workspaceConfig's own comment says it 'sits above " +
    "the firm workspace model entirely and is never linked from any panel' — " +
    "it is self-gated server-side and is not firm navigation",
  "/onboarding":
    "the firm SIGNUP wizard, which runs before a firm exists and so renders " +
    "with no shell at all (AppShell's NO_SHELL_EXACT). Its ONE sub-route, " +
    "/onboarding/checklist, is a staff screen and is in ClientsPanel",
};

function panelSource(component: string): string {
  const p = join(WEB, "components/panels", `${component}.tsx`);
  assert.ok(existsSync(p), `ContextPanel names <${component}/> and there is no such file`);
  return readFileSync(p, "utf8");
}

interface Unlisted { href: string; name: string; panel: string }

function sweep(): Unlisted[] {
  const panels = panelForWorkspace();
  const cache = new Map<string, string>();
  const missing: Unlisted[] = [];

  for (const s of SCREENS) {
    if (s.scope !== "firm") continue;          // client screens have their own nav
    if (s.href in NO_BROWSE_SURFACE) continue;

    const component = s.href.startsWith("/settings")
      ? "SettingsPanel"
      : panels[getActiveWorkspaceForPathname(s.href) ?? ""];

    if (!component) { missing.push({ ...s, panel: "(no panel owns this route)" }); continue; }
    if (!cache.has(component)) cache.set(component, panelSource(component));
    // Quoted, so `/gst` cannot be satisfied by `/gst/gstr1` appearing.
    if (!new RegExp(`["'\`]${s.href.replace(/\//g, "\\/")}["'\`]`).test(cache.get(component)!))
      missing.push({ ...s, panel: component });
  }
  return missing;
}

test("ContextPanel's workspace→panel mapping is readable, and Settings is by path", () => {
  const panels = panelForWorkspace();
  // Vacuity floor on the POPULATION the mapping covers, not on the offenders —
  // a floor counting what is still wrong breaks when the work succeeds.
  assert.ok(
    Object.keys(panels).length >= 10,
    `only ${Object.keys(panels).length} workspace→panel pairs read out of ` +
      "ContextPanel.tsx — the regex has probably stopped matching its JSX.",
  );
  assert.ok(settingsIsPanelledByPath(), "ContextPanel no longer renders SettingsPanel off the path");
});

test("the sweep still sees a real population of firm screens", () => {
  const firm = SCREENS.filter((s) => s.scope === "firm");
  assert.ok(firm.length >= 90, `only ${firm.length} firm screens — screens.ts has probably moved`);
});

test("every named firm screen is listed in the panel of the workspace that owns it", () => {
  const missing = sweep();
  assert.deepEqual(
    missing.map((m) => `${m.href}  (${m.panel})`).sort(),
    [],
    "These screens have a name in the palette and no place in their own " +
      "module's sidebar, so a CA standing on a sibling cannot reach them.\n" +
      "Add each to the panel named beside it — with its icon and, where a " +
      "FastAPI permission governs the page, a `requires` pair READ OFF the " +
      "endpoint. If a screen genuinely has no browse surface, add it to " +
      "NO_BROWSE_SURFACE here with the argument, not to a landing page.\n  " +
      missing.map((m) => `${m.href}  (${m.panel})`).sort().join("\n  "),
  );
});

test("NO_BROWSE_SURFACE has no entry that is listed after all", () => {
  // The other direction: an exemption that stops being needed has to come out,
  // or the list stops describing anything — "an allowlist nobody re-reads is
  // how an exemption outlives its reason".
  const panels = panelForWorkspace();
  const stale: string[] = [];
  for (const href of Object.keys(NO_BROWSE_SURFACE)) {
    const component = href.startsWith("/settings")
      ? "SettingsPanel"
      : panels[getActiveWorkspaceForPathname(href) ?? ""];
    if (!component) continue;                      // still owned by nothing
    const re = new RegExp(`["'\`]${href.replace(/\//g, "\\/")}["'\`]`);
    if (re.test(panelSource(component))) stale.push(href);
  }
  assert.deepEqual(stale, [], "Listed as having no browse surface, and in a panel:\n  " + stale.join("\n  "));
});

test("every NO_BROWSE_SURFACE entry names a screen that exists", () => {
  const named = new Set(SCREENS.map((s) => s.href));
  const ghosts = Object.keys(NO_BROWSE_SURFACE).filter((h) => !named.has(h));
  assert.deepEqual(ghosts, [], "exempted routes that are not named screens:\n  " + ghosts.join("\n  "));
});

test("the two screens that had no browse surface at all now have one", () => {
  // Negative control with teeth: these are the exact pair the sweep that wrote
  // this guard found in NEITHER a panel nor any landing page, so a rewrite that
  // made `sweep()` vacuous would still have to keep them listed.
  assert.match(panelSource("TeamPanel"), /"\/team\/workload"/);
  assert.match(panelSource("ClientsPanel"), /"\/onboarding\/checklist"/);
});
