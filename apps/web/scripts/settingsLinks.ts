/**
 * Whether Settings links to a page (PRE-A-023), for the guards that used to look for the link written in the
 * Settings landing page's own source.
 *
 * Since the Settings redesign the links are one list, `lib/settings/groups.ts`, which the Settings home renders
 * on its tabs and the Settings panel renders in the workspace menu. So "Settings links to X" is: the list names X,
 * and both surfaces render the list (the home through `visibleLinks`, the panel through `SETTINGS_GROUPS`). A
 * guard that read only the list would pass if either surface stopped rendering it.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { stripComments } from "./stripComments.ts";

const WEB = join(import.meta.dirname, "..");

function code(rel: string): string {
  return stripComments(readFileSync(join(WEB, rel), "utf8"));
}

/** The reasons Settings does not link to `href`; empty when it does. */
export function whySettingsDoesNotLinkTo(href: string): string[] {
  const why: string[] = [];
  const quoted = new RegExp(`href: "${href.replace(/[/.]/g, (c) => `\\${c}`)}(#[^"]*)?"`);
  if (!quoted.test(code("lib/settings/groups.ts"))) why.push(`lib/settings/groups.ts does not list ${href}`);
  const home = code("app/settings/page.tsx");
  // The second argument is the person the links are filtered for (their role since POST-A-447; a Partner flag before).
  if (!/from "@\/lib\/settings\/groups"/.test(home) || !/visibleLinks\(group, [A-Za-z]+\)/.test(home))
    why.push("the Settings home no longer renders the groups' links");
  const panel = code("components/panels/SettingsPanel.tsx");
  if (!/from "@\/lib\/settings\/groups"/.test(panel) || !/SETTINGS_GROUPS\.map\(/.test(panel))
    why.push("the Settings panel no longer renders the groups");
  return why;
}

/**
 * The addresses the Settings panel lists, as quoted strings one per line, for the guards that read a panel's
 * source for the addresses it links to: every `href` in the groups under /settings (the panel's own filter),
 * without a fragment, plus each tab's address.
 */
export function settingsPanelAddresses(): string {
  const groups = code("lib/settings/groups.ts");
  const hrefs = [...groups.matchAll(/href: "(\/settings[^"#]*)/g)].map((m) => m[1]);
  return [...new Set(["/settings", ...hrefs])].map((h) => `"${h}"`).join("\n");
}
