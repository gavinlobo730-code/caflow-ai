/**
 * THE PERMISSIONS A PARTNER TICKS, GROUPED UNDER THE NAMES ON THE FIRM MENU, and the menu a person will have once a set of
 * ticks is saved (POST-A-543, the owner's decision of 21-11-2026).
 *
 * WHY. The Team screen's access drawer listed every permission the server knows under its technical name ("Compliance
 * Record · Read"), in the server's own order. The owner's rule is that the ticks decide what a person sees on the menu, so
 * a Partner has to be able to see WHICH tick puts WHICH area there. This module answers that from the one table that
 * decides it (`screenAccess.ts`): for each area of the menu, the permissions that put it on the menu or open a screen in
 * it, each with the screens it opens; and what is left over, which are the permissions for what a person may DO inside a
 * screen (add, approve, delete) and put nothing on a menu.
 *
 * THE PREVIEW IS THE MENU'S OWN ARITHMETIC. `menuFor` asks the same `areaOffered` and `outerMenu` the firm menu asks, with
 * the permissions the person would hold. It is a preview of a draft, said as one on the screen; after a save the drawer is
 * given the server's own answer and the preview is worked from that.
 *
 * WORDS. `pairWords` says a permission the way a person would ("See the GST desk"). A permission this file has no words
 * for falls back to its technical name in title case, and a test holds that every permission the TABLE names has words.
 *
 * Pure: no React, no request.
 */
import { AREA_RULES, SCREEN_RULES, areaOffered, type AccessRule, type Pair } from "./screenAccess.ts";
import { getActiveWorkspaceForPathname } from "../workspace/routeOwnership.ts";
import { MAIN_AREAS, MORE_AREAS, outerMenu } from "../workspace/outerMenu.ts";

const key = (p: Pair) => `${p[0]}:${p[1]}`;
const pairsOf = (rule: AccessRule): Pair[] => [...(rule.all ?? []), ...(rule.any ?? [])];

/** What each resource is called when a permission is put into words. */
const RESOURCE_WORDS: Readonly<Record<string, string>> = {
  client: "clients",
  pipeline: "the pipeline of prospective clients",
  portal: "the client portal",
  document: "documents",
  compliance: "the compliance calendar",
  compliance_record: "compliance records",
  gst: "the GST desk",
  einvoice: "e-invoices",
  income_tax: "the income tax desk",
  tds: "the TDS desk",
  mca: "the MCA desk",
  task: "tasks and the work queue",
  time_entry: "timesheets",
  workflow: "workflows",
  team: "the team list",
  assignment: "who is assigned to which client",
  approval: "approvals",
  workload: "workload",
  ai: "the AI assistant and insights",
  copilot: "the copilot and its memory",
  risk: "the risk register",
  report: "reports",
  accounting: "the books",
  billing: "the practice's fee billing",
  payroll: "payroll",
  knowledge: "the knowledge base",
  engagement: "engagement letters",
  // The pairs that open a Settings page (POST-A-545).
  settings: "the firm's settings",
  branding: "branding, the invoice settings and the mail and invoice templates",
  firm: "the firm's profile",
};

/** What each action is called. `read` is "See"; the rest say what the person may do. */
const ACTION_WORDS: Readonly<Record<string, string>> = {
  read: "See",
  write: "Add and change",
  approve: "Approve",
  compute: "Compute",
  delete: "Delete",
  export: "Export",
  admin: "Administer",
};

/** Title Case from a snake_case name: the fallback for a permission this file has no words for. */
function titled(token: string): string {
  return token.split("_").map((w) => (w.length <= 3 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1))).join(" ");
}

/** Whether this file has plain words for a permission (a test asks it of every permission the table names). */
export function hasWords(resource: string, action: string): boolean {
  return resource in RESOURCE_WORDS && action in ACTION_WORDS;
}

/** A permission in a person's words: "See the GST desk", "Compute the income tax desk". */
export function pairWords(resource: string, action: string): string {
  if (!hasWords(resource, action)) return `${titled(resource)}: ${titled(action)}`;
  // "Compute the income tax desk" reads wrongly; the two compute permissions the table names are said in full.
  if (action === "compute" && resource === "income_tax") return "Work out income tax (compute)";
  // "Administer the firm's profile" names the wrong thing: this is the tick behind the AI status page and the deployment card.
  if (action === "admin" && resource === "firm") return "Administer the firm (AI status and how the deployment is set up)";
  return `${ACTION_WORDS[action]} ${RESOURCE_WORDS[resource]}`;
}

export interface MenuPermission {
  resource: string;
  action: string;
  /** True when holding it (alone or with others) puts the AREA on the menu; false when it only opens screens inside it. */
  opensTheArea: boolean;
  /** The addresses in this area whose own rule names it, for the line that says what it opens. */
  screens: string[];
  /** The other areas the same permission also decides, by id: it is one tick, shown wherever it matters. */
  alsoIn: string[];
}

export interface MenuGroup {
  areaId: string;
  /** How the area's own rule reads: every permission is needed, or any one is enough. */
  areaNeeds: "all" | "any" | "nothing";
  permissions: MenuPermission[];
}

/**
 * SETTINGS IS A GROUP HERE AND NOT AN AREA OF THE MENU (POST-A-545). No area owns the Settings addresses and Settings is
 * always offered (every person has a profile and a password there), so nothing "puts Settings on the menu". But each
 * Settings PAGE is opened by a permission of its own in the one table, and a Partner has to be able to see which tick opens
 * which page, exactly as for the screens of an area. This is the id of the group that lists them, after the areas.
 */
export const SETTINGS_GROUP = "settings";
const isSettingsPage = (prefix: string) => prefix === "/settings" || prefix.startsWith("/settings/");

/** The areas a Partner ticks permissions for, in the menu's order. Home is always there and My practice is not a tick. */
export const TICKABLE_AREAS: readonly string[] = [...MAIN_AREAS, ...MORE_AREAS].filter((id) => id !== "home" && id !== "practice");

/** The permissions that decide each area of the menu and the screens in it, read from the one table. */
export function menuGroups(): MenuGroup[] {
  // Which areas each permission touches, to say "also decides …".
  const areasOf = new Map<string, Set<string>>();
  const touch = (pair: Pair, area: string) => {
    if (!areasOf.has(key(pair))) areasOf.set(key(pair), new Set());
    areasOf.get(key(pair))!.add(area);
  };
  for (const area of TICKABLE_AREAS) for (const pair of pairsOf(AREA_RULES[area] ?? {})) touch(pair, area);
  const screensIn = new Map<string, Array<readonly [string, AccessRule]>>();
  for (const entry of SCREEN_RULES) {
    const area = isSettingsPage(entry[0]) ? SETTINGS_GROUP : getActiveWorkspaceForPathname(entry[0]);
    if (!area || !(area === SETTINGS_GROUP || TICKABLE_AREAS.includes(area))) continue;
    if (!screensIn.has(area)) screensIn.set(area, []);
    screensIn.get(area)!.push(entry);
    for (const pair of pairsOf(entry[1])) touch(pair, area);
  }

  return [...TICKABLE_AREAS, SETTINGS_GROUP].map((areaId) => {
    const rule = AREA_RULES[areaId] ?? {};
    const own = pairsOf(rule);
    const seen = new Map<string, MenuPermission>();
    const add = (pair: Pair, opensTheArea: boolean, screen?: string) => {
      const k = key(pair);
      if (!seen.has(k)) {
        seen.set(k, {
          resource: pair[0], action: pair[1], opensTheArea, screens: [],
          alsoIn: [...(areasOf.get(k) ?? [])].filter((a) => a !== areaId),
        });
      }
      const entry = seen.get(k)!;
      if (opensTheArea) entry.opensTheArea = true;
      if (screen && !entry.screens.includes(screen)) entry.screens.push(screen);
    };
    for (const pair of own) add(pair, true);
    for (const [prefix, screenRule] of screensIn.get(areaId) ?? []) for (const pair of pairsOf(screenRule)) add(pair, false, prefix);
    return {
      areaId,
      areaNeeds: rule.any && rule.any.length > 0 ? "any" : rule.all && rule.all.length > 0 ? "all" : "nothing",
      permissions: [...seen.values()],
    };
  });
}

/** Every permission `menuGroups` shows, as "resource:action": what is left over is listed under its technical name. */
export function menuPermissionKeys(): Set<string> {
  return new Set(menuGroups().flatMap((g) => g.permissions.map((p) => `${p.resource}:${p.action}`)));
}

export type Choice = "role" | "allow" | "block";

/**
 * Whether a person would hold a permission with a draft of choices: a choice of Allow or Block decides, and Role leaves it
 * to what the role gives. This is the server's own rule (`core/permissions.resolve_permission`: a row for the person wins,
 * else the role), used here only to preview a draft.
 */
export function wouldHold(roleDefaults: Readonly<Record<string, readonly string[]>>, draft: Readonly<Record<string, Choice>>): (resource: string, action: string) => boolean {
  return (resource, action) => {
    const choice = draft[`${resource}:${action}`] ?? "role";
    if (choice === "allow") return true;
    if (choice === "block") return false;
    return (roleDefaults[resource] ?? []).includes(action);
  };
}

/** The firm menu a person would have: the areas listed first and the areas under More, by id, as the menu works it out. */
export function menuFor(can: (resource: string, action: string) => boolean, isPartner: boolean): { main: string[]; more: string[] } {
  const offered = [...MAIN_AREAS, ...MORE_AREAS].filter((id) => areaOffered(id, { can, isPartner }));
  return outerMenu(offered);
}
