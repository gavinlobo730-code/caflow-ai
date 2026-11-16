// PRE-A-023. Settings is grouped into tabs from one list, lib/settings/groups.ts, and these are its rules: every
// Settings screen is reachable from a tab, a page lights the tab that holds it, a link is offered only to the roles its
// page's own guard admits (POST-A-447), and a tab with nothing for the person is not shown.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";
import {
  SETTINGS_GROUPS,
  everySettingsPage,
  groupForPage,
  groupFromTab,
  groupHasContent,
  linkShownTo,
  settingsTabHref,
  visibleLinks,
} from "./groups.ts";
import type { UserRole } from "../auth/permissions.ts";

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

test("each link names the roles its page's own guard admits, so the panel, the tabs and the home never offer a page that sends the person back (POST-A-447)", () => {
  // The rule, read off the pages: a Settings page whose outermost guard is `<RoleGuard allowed={[...]}>` (not the
  // in-page `redirect={false}` kind, which guards one section) admits exactly those roles, and its link says so.
  const guardOf = (href: string): string[] | null => {
    const file = join(WEB, "app", href.split("#")[0], "page.tsx");
    if (!existsSync(file)) return null;
    const m = readFileSync(file, "utf8").match(/<RoleGuard allowed=\{\[([^\]]*)\]\}>/);
    return m ? m[1].split(",").map((r) => r.trim().replace(/"/g, "")).filter(Boolean).sort() : null;
  };
  const problems: string[] = [];
  for (const g of SETTINGS_GROUPS) {
    for (const l of g.links) {
      if (l.href.includes("#")) continue;                       // a fragment opens a card, guarded inside the page
      const guard = guardOf(l.href);
      const named = l.roles ? [...l.roles].sort() : null;
      if (JSON.stringify(guard) !== JSON.stringify(named)) {
        problems.push(`${l.href}: the page admits ${guard ? guard.join(", ") : "every role"}; the link names ${named ? named.join(", ") : "none"}`);
      }
    }
  }
  assert.deepEqual(problems, []);
  // The deployment card is shown to whoever may administer the firm, a Partner.
  const deployment = SETTINGS_GROUPS.flatMap((g) => g.links).find((l) => l.href === "/settings/security#deployment");
  assert.deepEqual(deployment?.roles, ["Partner"]);
});

test("each role sees exactly the links its role is admitted to: a Partner every link, a Manager the three statutory screens too, an Executive and a Reviewer none of the guarded ones", () => {
  const shown = (role: UserRole) => SETTINGS_GROUPS.flatMap((g) => visibleLinks(g, role).map((l) => l.href));
  for (const g of SETTINGS_GROUPS) assert.deepEqual(visibleLinks(g, "Partner"), g.links, `${g.label}: a Partner sees every link`);
  const manager = shown("Manager");
  for (const href of ["/settings/statutory-values", "/settings/treaty-rates", "/settings/firm-hsn-library"]) {
    assert.ok(manager.includes(href), `a Manager may open ${href} and was not offered it`);
  }
  for (const href of ["/settings/branding", "/settings/audit-log", "/settings/ai", "/settings/multi-currency"]) {
    assert.ok(!manager.includes(href), `a Manager was offered ${href}, which sends them back to the home page`);
  }
  for (const role of ["Executive", "Reviewer"] as const) {
    const links = SETTINGS_GROUPS.flatMap((g) => visibleLinks(g, role));
    assert.ok(links.every((l) => !l.roles), `${role} was offered a guarded page: ${links.filter((l) => l.roles).map((l) => l.href).join(", ")}`);
    assert.ok(links.length > 0, `${role} sees nothing at all`);
  }
  // An unknown role sees only what every role sees.
  assert.ok(SETTINGS_GROUPS.flatMap((g) => visibleLinks(g, null)).every((l) => !l.roles));
});

test("negative control: a link that drops its page's guard is named", () => {
  const branding = SETTINGS_GROUPS.flatMap((g) => g.links).find((l) => l.href === "/settings/branding")!;
  assert.ok(linkShownTo(branding, "Partner") && !linkShownTo(branding, "Manager"));
  assert.ok(linkShownTo({ ...branding, roles: undefined }, "Manager"), "premise: a link with no roles is shown to anyone");
});

test("a tab with nothing for the person is not shown: a Manager has no AI tab, a Partner has all six", () => {
  assert.deepEqual(SETTINGS_GROUPS.filter((g) => groupHasContent(g, "Partner")).map((g) => g.id),
    ["profile", "firm", "security", "documents", "statutory", "ai"]);
  assert.deepEqual(SETTINGS_GROUPS.filter((g) => groupHasContent(g, "Manager")).map((g) => g.id),
    ["profile", "firm", "security", "documents", "statutory"]);
});
