// PRE-A-023. Settings is grouped into tabs from one list, lib/settings/groups.ts, and these are its rules: every
// Settings screen is reachable from a tab, a page lights the tab that holds it, a link is listed exactly when the one
// access table opens its page (POST-A-545; it used to repeat the roles each page's own guard admitted, POST-A-447), and a tab with nothing for the person is not shown.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";
import {
  SETTINGS_GROUPS,
  everySettingsPage,
  groupForPage,
  groupFromTab,
  firmProfileShown,
  groupHasContent,
  linkShownTo,
  settingsTabHref,
  visibleLinks,
  type SettingsAsker,
} from "./groups.ts";
import { mayOpen, screenRule } from "../access/screenAccess.ts";

const WEB = join(import.meta.dirname, "..", "..");

/** Every Settings screen on disk, as its address: each folder under app/settings with a page.tsx. */
function settingsPagesOnDisk(): string[] {
  const root = join(WEB, "app", "settings");
  return readdirSync(root)
    .filter((d) => statSync(join(root, d)).isDirectory() && existsSync(join(root, d, "page.tsx")))
    .map((d) => `/settings/${d}`)
    .sort();
}

test("there are six groups in the order the owner asked for", () => {
  assert.deepEqual(
    SETTINGS_GROUPS.map((g) => g.label),
    ["Your profile", "The firm", "Security and access", "Invoices and documents", "Tax and statutory values", "AI and connections"],
  );
});

test("every Settings screen on disk is reachable from a tab, and every link names a screen that exists", () => {
  const onDisk = settingsPagesOnDisk();
  assert.ok(onDisk.length >= 13, `only ${onDisk.length} Settings screens found: the walk stopped seeing the folder`);
  const linked = everySettingsPage().filter((p) => p.startsWith("/settings/")).sort();
  assert.deepEqual(linked, onDisk, "a Settings screen no tab offers, or a link to a screen that is gone");
  for (const p of everySettingsPage().filter((p) => !p.startsWith("/settings"))) {
    assert.ok(existsSync(join(WEB, "app", p.slice(1), "page.tsx")), `${p} is linked and has no page`);
  }
});

test("a link says what it opens: a label and one sentence, and no link is 'Manage'", () => {
  for (const g of SETTINGS_GROUPS) {
    assert.ok(g.says.trim().length > 20, `${g.label} has no line saying what it holds`);
    for (const l of g.links) {
      assert.ok(l.label.trim() && !/^manage\b/i.test(l.label), `${g.label}: "${l.label}" does not say what it opens`);
      assert.ok(l.says.trim().endsWith("."), `${g.label} / ${l.label}: the sentence is missing`);
    }
  }
});

test("the security status is under Security and access, by name", () => {
  const security = SETTINGS_GROUPS.find((g) => g.id === "security")!;
  assert.ok(security.links.some((l) => l.href === "/settings/security#deployment" && /deployment/i.test(l.label)));
  assert.ok(security.links.some((l) => l.href === "/settings/security" && /authenticator/i.test(l.label)));
  assert.ok(security.links.some((l) => l.href === "/settings/audit-log"));
  assert.ok(security.links.some((l) => l.href === "/team"));
});

test("a tab's address is the Settings home, and an unknown tab is the first", () => {
  assert.equal(settingsTabHref("profile"), "/settings");
  assert.equal(settingsTabHref("security"), "/settings?tab=security");
  assert.equal(groupFromTab("documents"), "documents");
  assert.equal(groupFromTab(null), "profile");
  assert.equal(groupFromTab("nonsense"), "profile");
});

test("each Settings page lights the tab that holds it", () => {
  assert.equal(groupForPage("/settings", null), "profile");
  assert.equal(groupForPage("/settings/", "firm"), "firm");
  assert.equal(groupForPage("/settings/security", null), "security", "the security page belongs with security");
  assert.equal(groupForPage("/settings/security/", null), "security");
  assert.equal(groupForPage("/settings/branding", null), "documents");
  assert.equal(groupForPage("/settings/statutory-values", null), "statutory");
  assert.equal(groupForPage("/settings/ai", null), "ai");
  assert.equal(groupForPage("/settings/multi-currency", null), "firm");
  assert.equal(groupForPage("/settings/no-such-page", null), null);
});

// What each role holds to start with, written from the server's own table (a Python test holds the file to it).
const MAPS = JSON.parse(readFileSync(join(WEB, "scripts", "drive", "role-permissions.json"), "utf8")) as Record<string, Record<string, string[]>>;
const person = (role: string, map: Record<string, string[]> = MAPS[role]): SettingsAsker => ({
  who: { can: (r, a) => (map[r] ?? []).includes(a), isPartner: role === "Partner" },
  resolved: true,
});
const offered = (role: string) => SETTINGS_GROUPS.flatMap((g) => visibleLinks(g, person(role)).map((l) => l.href));

test("a Settings link is listed exactly when the one table opens its page, for every role (POST-A-545)", () => {
  // The RULE: the link, the page gate and the guide ask one table, so a page cannot be offered and then refused, or open and
  // unlisted. A link to a card on a page also asks the card's own pair.
  for (const role of ["Partner", "Manager", "Executive", "Reviewer"]) {
    const access = person(role);
    for (const g of SETTINGS_GROUPS) {
      for (const l of g.links) {
        const cardHeld = !l.requires || access.who.can(l.requires[0], l.requires[1]);
        assert.equal(linkShownTo(l, access), cardHeld && mayOpen(l.href, access.who).allowed, `${role}: ${l.href} is listed and refused, or open and unlisted`);
      }
    }
  }
  const deployment = SETTINGS_GROUPS.flatMap((g) => g.links).find((l) => l.href === "/settings/security#deployment");
  assert.deepEqual(deployment?.requires, ["firm", "admin"], "the deployment card is shown on firm admin, and its link does not say so");
  assert.ok(SETTINGS_GROUPS.flatMap((g) => g.links).every((l) => !l.requires || l.href.includes("#")), "a link to a PAGE names a pair of its own: the table answers for pages");
});

test("no Settings page keeps a gate of its own, and every page is in the table or is named as every member's", () => {
  /** Open to every member of staff: nothing on these asks more than being signed in. Read on 22-11-2026. */
  const EVERY_MEMBERS = new Set(["/settings/security", "/settings/scheduled-reports", "/settings/dsc-tracker"]);
  for (const href of settingsPagesOnDisk()) {
    const source = readFileSync(join(WEB, "app", href, "page.tsx"), "utf8");
    assert.doesNotMatch(source, /RoleGuard|hasRole\(/, `${href} asks a role where it should follow the permissions a Partner ticked`);
    const rule = screenRule(href);
    assert.equal(rule !== null, !EVERY_MEMBERS.has(href), `${href} is ${rule ? "in the table and also named as every member's" : "in neither the table nor the named list"}`);
  }
  assert.equal(existsSync(join(WEB, "components", "RoleGuard.tsx")), false, "the role guard is back");
});

test("what each role is offered to start with: a Partner everything, a Manager all but the audit log and the AI page, an Executive and a Reviewer the reference tables their work reads", () => {
  for (const g of SETTINGS_GROUPS) assert.deepEqual(visibleLinks(g, person("Partner")), g.links, `${g.label}: a Partner sees every link`);
  const guarded = (role: string) => offered(role).filter((h) => h.startsWith("/settings/") && (screenRule(h) !== null || h.includes("#"))).sort();
  assert.deepEqual(guarded("Manager"), [
    "/settings/branding", "/settings/email-templates", "/settings/firm-hsn-library", "/settings/invoice-settings",
    "/settings/invoice-templates", "/settings/journal-approval", "/settings/multi-currency", "/settings/statutory-values",
    "/settings/treaty-rates"]);
  assert.deepEqual(guarded("Executive"), ["/settings/firm-hsn-library", "/settings/journal-approval", "/settings/treaty-rates"]);
  assert.deepEqual(guarded("Reviewer"), ["/settings/treaty-rates"]);
  for (const role of ["Executive", "Reviewer"]) assert.ok(offered(role).includes("/settings/security"), `${role} is not offered their own password and authenticator`);
});

test("negative control: the tick decides, in both directions", () => {
  const branding = SETTINGS_GROUPS.flatMap((g) => g.links).find((l) => l.href === "/settings/branding")!;
  assert.ok(linkShownTo(branding, person("Manager")), "premise: a Manager holds branding read");
  assert.ok(!linkShownTo(branding, person("Manager", { ...MAPS.Manager, branding: [] })), "a Manager with the tick taken away is still offered the page");
  assert.ok(!linkShownTo(branding, person("Executive")), "premise: an Executive does not hold branding read");
  assert.ok(linkShownTo(branding, person("Executive", { ...MAPS.Executive, branding: ["read"] })), "an Executive given the tick is not offered the page");
});

test("until the permissions are known nothing is withheld on a pair, as on every menu", () => {
  const unknown: SettingsAsker = { who: { can: () => false, isPartner: false }, resolved: false };
  for (const g of SETTINGS_GROUPS) assert.deepEqual(visibleLinks(g, unknown), g.links);
  assert.ok(firmProfileShown(unknown));
});

test("the Firm Profile card is drawn on firm read, and a tab with nothing for the person is not shown", () => {
  assert.ok(firmProfileShown(person("Partner")) && firmProfileShown(person("Manager")));
  assert.ok(!firmProfileShown(person("Executive")) && !firmProfileShown(person("Reviewer")));
  const tabs = (role: string) => SETTINGS_GROUPS.filter((g) => groupHasContent(g, person(role))).map((g) => g.id);
  assert.deepEqual(tabs("Partner"), ["profile", "firm", "security", "documents", "statutory", "ai"]);
  assert.deepEqual(tabs("Manager"), ["profile", "firm", "security", "documents", "statutory"]);
  assert.ok(!tabs("Reviewer").includes("ai") && tabs("Reviewer").includes("profile"));
});
