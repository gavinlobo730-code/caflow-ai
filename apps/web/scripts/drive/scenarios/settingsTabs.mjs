/**
 * Group: settings-tabs. Settings is a row of tabs across the top, grouped the way a practice thinks (PRE-A-023).
 *
 * The owner, looking for the security status on 16-11-2026, could not find it: Settings was one column of
 * fourteen cards and the status sat behind a card titled Security whose only link read "Manage 2FA". This drives
 * the redesign in Chromium: the six tabs are there in order across the top, the security status is one tab and
 * one click away by its own name, a Settings screen shows the tab it belongs to, and on a phone the row scrolls
 * inside itself rather than widening the page.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";

export const group = "settings-tabs";

const TABS = ["Your profile", "The firm", "Security and access", "Invoices and documents", "Tax and statutory values", "AI and connections"];

function tabRow(page) {
  return page.getByRole("navigation", { name: "Settings sections" });
}

async function litTab(page) {
  return tabRow(page).locator('[aria-current="page"]').innerText();
}

export const scenarios = [
  {
    id: "settings-opens-on-six-tabs-across-the-top",
    title: "Settings opens under six tabs across the top, on Your profile",
    async run(env) {
      const { page } = env;
      await page.goto(env.base + "/settings/", { waitUntil: "networkidle" });
      await tabRow(page).waitFor();
      const labels = (await tabRow(page).getByRole("link").allInnerTexts()).map((t) => t.trim());
      assert.deepEqual(labels, TABS, "the tabs, in order");
      assert.strictEqual(await litTab(page), "Your profile");
      const box = await tabRow(page).boundingBox();
      const main = await page.locator("main").boundingBox();
      assert.ok(box && main && Math.abs(box.y - main.y) <= 1, "the tab row sits at the top of the page, not down a column");
    },
  },
  {
    id: "the-security-status-is-one-tab-and-one-click-away",
    title: "Security and access lists the deployment status by name, and it opens on that section",
    async run(env) {
      const { page, stub } = env;
      // The deployment card is a Partner's (the page asks `firm:admin`), and it reads the posture the server resolved.
      stub.route({ method: "GET", re: /identity\/permissions$/,
                   reply: () => ok({ role: "Partner", permissions: { firm: ["read", "write", "admin"] } }) });
      stub.route({ method: "GET", re: /\/api\/security\/posture/, reply: () => ok({
        ok: true, app_env_is_production: true, use_user_jwt: true, use_user_jwt_explicit: true, require_mfa: true,
        require_mfa_explicit: true, mfa_required_roles: ["Partner", "Manager"], supabase_anon_key_present: true,
        scheduler_enabled: true, cors_origin_count: 1, problems: [],
      }) });
      await page.goto(env.base + "/settings/", { waitUntil: "networkidle" });
      await tabRow(page).getByRole("link", { name: "Security and access" }).click();
      await page.waitForURL(/\/settings\/?\?tab=security$/);
      assert.strictEqual(await litTab(page), "Security and access");
      const row = page.locator("li", { hasText: "How this deployment is set up" });
      await row.waitFor();
      await row.getByRole("link").click();
      await page.waitForURL(/\/settings\/security\/?#deployment$/);
      await page.locator("#deployment").waitFor();
      assert.strictEqual(await litTab(page), "Security and access", "the security page lights the tab it belongs to");
    },
  },
  {
    id: "a-settings-screen-shows-the-tab-it-belongs-to",
    title: "Branding shows the tab row with Invoices and documents lit",
    async run(env) {
      const { page } = env;
      await page.goto(env.base + "/settings/branding/", { waitUntil: "networkidle" });
      await tabRow(page).waitFor();
      assert.strictEqual(await litTab(page), "Invoices and documents");
    },
  },
  {
    id: "the-tab-row-scrolls-inside-itself-on-a-phone",
    title: "at phone width the tab row scrolls sideways and the page does not",
    async run(env) {
      const { page } = env;
      await page.setViewportSize({ width: 375, height: 800 });
      await page.goto(env.base + "/settings/", { waitUntil: "networkidle" });
      await tabRow(page).waitFor();
      const m = await page.evaluate(() => {
        const nav = document.querySelector('nav[aria-label="Settings sections"] > div');
        return {
          pageWide: document.documentElement.scrollWidth,
          window: innerWidth,
          rowScrolls: nav ? getComputedStyle(nav).overflowX : null,
        };
      });
      assert.ok(m.pageWide <= m.window, `the page is ${m.pageWide}px wide in a ${m.window}px window`);
      assert.strictEqual(m.rowScrolls, "auto", "the tab row does not scroll inside itself");
    },
  },
];
