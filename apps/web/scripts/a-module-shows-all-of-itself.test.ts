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
import { SCREENS, ALL_SCREENS } from "../lib/navigation/screens.ts";
import { getActiveWorkspaceForPathname } from "../lib/workspace/routeOwnership.ts";
import { stripComments } from "./stripComments.ts";

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

/**
 * ⚠️ COMMENTS ARE STRIPPED, AND THIS GUARD WAS VACUOUS FOR FOUR SCREENS
 * WITHOUT IT (found 24-09 by a negative control on `/payroll/people`). A panel
 * that gives a screen up writes a comment saying so — `AccountingPanel` names
 * the six payroll routes that left, `TeamPanel` names `/payroll/attendance` —
 * and the quoted match below counts a backticked route in prose exactly like a
 * declared `href`. So removing a screen from a panel whose comment mentions it
 * left this green. It is the hazard `scripts/stripComments.ts` exists for, and
 * the reason that helper is a module rather than a regex in each guard.
 */
function panelSource(component: string): string {
  const p = join(WEB, "components/panels", `${component}.tsx`);
  assert.ok(existsSync(p), `ContextPanel names <${component}/> and there is no such file`);
  return stripComments(readFileSync(p, "utf8"));
}

interface Unlisted { href: string; name: string; panel: string }

function sweep(): Unlisted[] {
  const panels = panelForWorkspace();
  const cache = new Map<string, string>();
  const missing: Unlisted[] = [];

  for (const s of SCREENS) {
    if (s.scope !== "firm") continue;          // held by the client test below
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

/**
 * THE CLIENT WORKSPACE SATISFIES THE SAME RULE IN ITS OWN IDIOM, and this
 * measures it rather than exempting it.
 *
 * `ClientContextPanel` lists the 21 SECTIONS, not their tabs — and expanding
 * all 21 would be a taller wall than the one grouping fixed on the firm side.
 * What makes that sound is that a client sub-screen's SECTION PAGE is an index
 * of its tabs AND the sidebar keeps that section one click away, so from
 * `/clients/:id/reports/ageing` a CA reaches `/reports/trend` in two clicks
 * rather than through the browser's Back button — which is the thing that was
 * actually wrong on the firm side.
 *
 * All 11 were already linked when this was written. It is asserted so the
 * argument stays true: a twelfth sub-screen added with no link on its section
 * page fails here, and the fix is the section page, not this list.
 */
test("every client sub-screen is linked from its own section page", () => {
  const missing: string[] = [];
  let checked = 0;
  for (const s of ALL_SCREENS) {
    if (s.scope !== "client" || !s.href.includes("/")) continue;  // a bare section is in CLIENT_SECTIONS
    checked++;
    const section = s.href.split("/")[0];
    const page = join(WEB, "app/clients/[id]", section, "page.tsx");
    if (!existsSync(page)) { missing.push(`${s.href} — no app/clients/[id]/${section}/page.tsx`); continue; }
    const txt = readFileSync(page, "utf8");
    const tail = s.href.slice(section.length + 1);

    // A page links a sub-screen in one of two shapes, and BOTH had to be
    // recognised for different reasons.
    //
    // 1. THE WHOLE PATH AS A LITERAL — `href: "reports/ageing"`, or the
    //    absolute `/clients/${id}/reports/ageing`.
    // 2. A TEMPLATE PLUS THE SEGMENT — `app/clients/[id]/compliance/page.tsx`
    //    does `router.push(\`/clients/${clientId}/compliance/${path}\`)` over
    //    cards carrying `path: "gst"`, so no literal path exists anywhere in
    //    the file and all three of its sub-screens read as unlinked.
    //
    // ⚠️ THE SEGMENT MUST BE A ROUTE FIELD, not any quoted string. A first
    // draft matched the bare tail and a negative control PASSED against it,
    // because the reports page carries `id: "ageing"` beside its href — so
    // breaking the link left the test green. A guard satisfied by a value that
    // is not a link is not a guard.
    const asLiteral = txt.includes(`"${s.href}"`) || txt.includes(`/${s.href}`);
    const asTemplate =
      txt.includes(`/${section}/\${`) &&
      new RegExp(`\\b(?:path|href|slug|route|segment)\\s*:\\s*"${tail}"`).test(txt);
    if (!asLiteral && !asTemplate)
      missing.push(`${s.href} (${s.name}) — not linked from /clients/:id/${section}`);
  }
  assert.ok(checked >= 10, `only ${checked} client sub-screens seen — CLIENT_SUBSCREENS has probably moved`);
  assert.deepEqual(
    missing,
    [],
    "A client sub-screen its own section page does not link is reachable only by " +
      "typing its name. Add it to that section page's index.\n  " + missing.join("\n  "),
  );
});
