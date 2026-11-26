/**
 * THE SHELL'S THREE MENUS CLOSE THE SAME WAY, AND THE ACCOUNT MENU HAS NO LAYER OVER THE WINDOW (POST-A-130, twenty-third step), driven
 * in a browser.
 *
 * The account menu, the workspace menu and a client's module menu each drew a layer over the whole window by hand to catch the click
 * that closes them. The account menu's was invisible and swallowed the first click anywhere, and it had no Escape; the other two closed
 * on an Escape listener of their own that left focus on nothing. The account menu has no layer now, the other two share one dimmed
 * scrim (`components/ui/menu-scrim`), and all three close through `lib/ui/useMenuDismiss`. The source guard holds the three; this drives:
 *
 *   1. the account menu says whether it is open, opens from the keyboard with nothing covering the window, and Escape closes it with
 *      focus back on the Account button; with it open, ONE click on the workspace menu's button closes it and opens that menu (the layer
 *      used to eat the click);
 *   2. the workspace menu: opening it moves focus into it (found while driving this: it comes after the whole bar in the document, so
 *      the next Tab went to the bar's other buttons); Escape closes it with focus back on its button (focus used to be left on nothing),
 *      and a click on the dimmed page closes it;
 *   3. a client's module menu the same.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";

export const group = "shell-menus";

const focusIsOn = (locator) => locator.evaluate((el) => el === document.activeElement);
/** A layer that covers the whole window (the hand-built kind): fixed, as wide as the window and starting at its top. */
const windowLayers = (page) => page.evaluate(() => [...document.querySelectorAll("div")].filter((d) => {
  const s = getComputedStyle(d);
  if (s.position !== "fixed") return false;
  const r = d.getBoundingClientRect();
  return r.top <= 0 && r.left <= 0 && r.width >= window.innerWidth && r.height >= window.innerHeight;
}).length);

/** Open a dimmed menu from the keyboard, move into it, and check Escape and the scrim. */
async function dimmedMenu(page, opener, region, what) {
  await opener.waitFor();
  assert.equal(await opener.getAttribute("aria-expanded"), "false", `${what}'s button says it is open before it is pressed`);
  await opener.focus();
  await page.keyboard.press("Enter");
  await region.waitFor();
  assert.equal(await opener.getAttribute("aria-expanded"), "true", `${what}'s button does not say it is open`);
  const scrim = page.locator("[data-menu-scrim]");
  assert.equal(await scrim.count(), 1, `${what} does not dim the page behind it`);
  assert.equal(await scrim.getAttribute("aria-hidden"), "true", "the scrim is announced to a screen reader");
  // FOUND WHILE DRIVING THIS: the menu comes after the whole top bar in the document, so focus stayed on the button and the next Tab went
  // to the bar's other buttons. Opening it moves focus into it now; Tab then stays among its links.
  await until(() => region.evaluate((r) => r.contains(document.activeElement)), `focus to move into ${what} when it opens`);
  await page.keyboard.press("Tab");
  assert.equal(await region.evaluate((r) => r.contains(document.activeElement)), true, `the first Tab inside ${what} left it`);
  await page.keyboard.press("Escape");
  await region.waitFor({ state: "detached" });
  assert.equal(await focusIsOn(opener), true, `Escape left focus on nothing: it did not return to ${what}'s button`);
  assert.equal(await opener.getAttribute("aria-expanded"), "false", `${what}'s button still says it is open`);
  assert.equal(await scrim.count(), 0, "the scrim outlived the menu");
  // A click on the dimmed page closes it.
  await opener.click();
  await region.waitFor();
  const below = await region.evaluate((r) => window.innerHeight - r.getBoundingClientRect().bottom);
  if (below > 24) await page.mouse.click(20, (await page.viewportSize()).height - 10);
  else await scrim.dispatchEvent("click");
  await region.waitFor({ state: "detached" });
}

export const scenarios = [
  {
    id: "the-account-menu-has-no-layer-closes-on-escape-and-does-not-eat-the-next-click",
    title: "Account menu: says whether it is open, opens from the keyboard with nothing covering the window, Escape closes it with focus back on Account, and one click on the workspace menu's button closes it and opens that menu",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/tasks/`, { waitUntil: "networkidle" });
      const account = page.getByRole("button", { name: "Account" }).first();
      await account.waitFor();
      assert.equal(await account.getAttribute("aria-expanded"), "false", "the Account button says its menu is open before it is pressed");
      await account.focus();
      await page.keyboard.press("Enter");
      const menu = page.getByRole("group", { name: "Account menu" });
      await menu.waitFor();
      assert.equal(await account.getAttribute("aria-expanded"), "true", "the Account button does not say its menu is open");
      assert.equal(await menu.getByRole("button", { name: "Sign out" }).count(), 1, "Sign out is not in the account menu");
      assert.equal(await windowLayers(page), 0, "a layer covers the window while the account menu is open");
      await page.keyboard.press("Escape");
      await menu.waitFor({ state: "detached" });
      assert.equal(await focusIsOn(account), true, "focus did not return to the Account button");
      assert.equal(await account.getAttribute("aria-expanded"), "false", "the Account button still says its menu is open");

      // One click elsewhere closes it AND acts: the workspace menu opens at once.
      await account.click();
      await menu.waitFor();
      await page.locator('button[aria-controls="workspace-menu"]').click();
      await page.getByRole("region", { name: "Workspace menu" }).waitFor({ timeout: 3000 }).catch(() => { throw new Error("the click that closed the account menu was swallowed: the workspace menu did not open"); });
      assert.equal(await menu.count(), 0, "the account menu stayed open after a click elsewhere");
      // And a click on its own button only closes it.
      await page.keyboard.press("Escape");
      await account.click();
      await menu.waitFor();
      await account.click();
      await menu.waitFor({ state: "detached" });
    },
  },
  {
    id: "the-workspace-menu-gives-focus-back-on-escape-and-closes-on-the-dimmed-page",
    title: "Workspace menu: opened from the keyboard it dims the page; Escape from inside it closes it with focus back on its button; a click on the dimmed page closes it",
    async run(env) {
      const { page } = env;
      await page.goto(`${env.base}/tasks/`, { waitUntil: "networkidle" });
      await dimmedMenu(page, page.locator('button[aria-controls="workspace-menu"]'), page.getByRole("region", { name: "Workspace menu" }), "the workspace menu");
    },
  },
  {
    id: "a-clients-module-menu-gives-focus-back-on-escape-and-closes-on-the-dimmed-page",
    title: "A client's module menu: opened from the keyboard it dims the page; Escape from inside it closes it with focus back on its button; a click on the dimmed page closes it",
    async run(env) {
      const { page } = env;
      await page.goto(env.at("/health/"), { waitUntil: "networkidle" });
      await dimmedMenu(page, page.locator('button[aria-controls="client-module-menu"]'), page.getByRole("region", { name: "Modules" }), "the module menu");
    },
  },
];
