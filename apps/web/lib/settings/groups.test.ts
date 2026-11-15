// PRE-A-023. Settings is grouped into tabs from one list, lib/settings/groups.ts, and these are its rules: every
// Settings screen is reachable from a tab, a page lights the tab that holds it, a Partner-only screen is offered to
// a Partner only (as it was), and a tab with nothing for the person is not shown.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, statSync, existsSync } from "node:fs";
import { join } from "node:path";
import {
  SETTINGS_GROUPS,
  everySettingsPage,
  groupForPage,
  groupFromTab,
  groupHasContent,
  settingsTabHref,
  visibleLinks,
} from "./groups.ts";

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

test("a Partner-only screen is offered to a Partner only, as the old Settings page offered it, and the deployment status with it", () => {
  const partnerOnly = SETTINGS_GROUPS.flatMap((g) => g.links.filter((l) => l.partnerOnly).map((l) => l.href)).sort();
  assert.deepEqual(partnerOnly, [
    "/settings/ai",
    "/settings/audit-log",
    "/settings/branding",
    "/settings/email-templates",
    "/settings/firm-hsn-library",
    "/settings/invoice-settings",
    "/settings/invoice-templates",
    "/settings/multi-currency",
    "/settings/security#deployment",
    "/settings/statutory-values",
    "/settings/treaty-rates",
  ]);
  for (const g of SETTINGS_GROUPS) {
    assert.deepEqual(visibleLinks(g, true), g.links, `${g.label}: a Partner sees every link`);
    assert.ok(visibleLinks(g, false).every((l) => !l.partnerOnly), `${g.label}: someone else sees a Partner-only link`);
  }
});

test("a tab with nothing for the person is not shown: a Manager has no AI tab, a Partner has all six", () => {
  assert.deepEqual(SETTINGS_GROUPS.filter((g) => groupHasContent(g, true)).map((g) => g.id),
    ["profile", "firm", "security", "documents", "statutory", "ai"]);
  assert.deepEqual(SETTINGS_GROUPS.filter((g) => groupHasContent(g, false)).map((g) => g.id),
    ["profile", "firm", "security", "documents", "statutory"]);
});
