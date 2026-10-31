/**
 * Group G: a dialog that declares itself modal keeps the keyboard inside it (POST-A-130, frontend_ux-14).
 *
 * The shared Drawer said `aria-modal="true"`, restored focus on close and closed on Escape, and let Tab walk out of the panel into the page
 * behind it. `lib/ui/focusTrap` is the rule both the Drawer and the Modal ask; these drive what a keyboard user does: Tab through the whole
 * drawer and past its last control, Shift+Tab back past its first, open a Modal over it and Tab in that, close it and check the page behind
 * does not scroll while either is open.
 *
 * WHAT IS HELD IS A FACT ABOUT WHERE FOCUS IS, read off the page after each key: inside the dialog, or not.
 */
import assert from "node:assert/strict";
import { openInvoiceDrawer } from "../flows.mjs";
import { ok } from "../stub.mjs";

export const group = "dialogs";

/** Is the focused element inside `selector`'s element? */
const focusIsInside = (page, selector) =>
  page.evaluate((sel) => {
    const el = document.activeElement;
    const root = document.querySelector(sel);
    return !!(el && root && root.contains(el));
  }, selector);

/** Press `key` `times` times and report, after each press, whether focus is still inside the topmost dialog. */
async function pressAndWatch(page, key, times) {
  const stayed = [];
  for (let i = 0; i < times; i += 1) {
    await page.keyboard.press(key);
    stayed.push(await page.evaluate(() => {
      const dialogs = [...document.querySelectorAll('[role="dialog"][aria-modal="true"]')];
      const top = dialogs[dialogs.length - 1];
      const el = document.activeElement;
      return !!(top && el && top.contains(el));
    }));
  }
  return stayed;
}

export const scenarios = [
  {
    id: "drawer-tab-stays-inside",
    title: "Tab through the invoice drawer, far past its last control, never leaves it; Shift+Tab from its first control wraps to its last",
    async run(env) {
      const { page } = env;
      const drawer = await openInvoiceDrawer(env, "issued");
      await drawer.waitFor();
      // Far more presses than the drawer has controls, so the wrap is crossed at least twice.
      const forward = await pressAndWatch(page, "Tab", 60);
      assert.ok(forward.every(Boolean), `Tab left the drawer on press ${forward.indexOf(false) + 1}`);
      const backward = await pressAndWatch(page, "Shift+Tab", 60);
      assert.ok(backward.every(Boolean), `Shift+Tab left the drawer on press ${backward.indexOf(false) + 1}`);
    },
  },
  {
    id: "drawer-shift-tab-from-the-panel-does-not-leave",
    title: "Shift+Tab straight after the drawer opens (focus is on the panel itself) goes to the drawer's last control, not to the page behind",
    async run(env) {
      const { page } = env;
      const drawer = await openInvoiceDrawer(env, "issued");
      await drawer.waitFor();
      // Focus is on the panel (tabindex -1), which is not one of the focusable controls.
      await page.evaluate(() => document.querySelector('[role="dialog"]').focus());
      await page.keyboard.press("Shift+Tab");
      assert.equal(await focusIsInside(page, '[role="dialog"]'), true, "Shift+Tab from the panel left the drawer");
    },
  },
  {
    id: "modal-over-drawer-traps-its-own-tab",
    title: "with Record Payment open over the drawer, Tab and Shift+Tab stay inside the modal, and after it closes Tab is inside the drawer again",
    async run(env) {
      const { page } = env;
      const drawer = await openInvoiceDrawer(env, "issued");
      env.stub.route({ method: "POST", re: /receipts\/$/, reply: () => ok({ id: "r1" }) });
      await drawer.getByRole("button", { name: "Record Payment" }).first().click();
      const modal = page.getByRole("dialog").last();
      await modal.getByRole("button", { name: "Record Payment", exact: true }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 2, "the modal and the drawer should both be open");
      const forward = await pressAndWatch(page, "Tab", 40);
      assert.ok(forward.every(Boolean), `Tab left the modal on press ${forward.indexOf(false) + 1}`);
      const backward = await pressAndWatch(page, "Shift+Tab", 40);
      assert.ok(backward.every(Boolean), `Shift+Tab left the modal on press ${backward.indexOf(false) + 1}`);
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 1, null, { timeout: 4000 });
      const afterwards = await pressAndWatch(page, "Tab", 30);
      assert.ok(afterwards.every(Boolean), `with the modal closed, Tab left the drawer on press ${afterwards.indexOf(false) + 1}`);
    },
  },
  {
    id: "page-behind-does-not-scroll-while-a-dialog-is-open",
    title: "the page behind the drawer is locked while it is open and gets its own overflow back when the last dialog closes",
    async run(env) {
      const { page } = env;
      const before = await (async () => { await page.goto(env.at("/sales/"), { waitUntil: "networkidle" }); return page.evaluate(() => document.body.style.overflow); })();
      const drawer = await openInvoiceDrawer(env, "issued");
      await drawer.waitFor();
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page behind the drawer can still scroll");
      env.stub.route({ method: "POST", re: /receipts\/$/, reply: () => ok({ id: "r1" }) });
      await drawer.getByRole("button", { name: "Record Payment" }).first().click();
      await page.getByRole("dialog").last().getByRole("button", { name: "Record Payment", exact: true }).waitFor();
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 1, null, { timeout: 4000 });
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "closing the modal unlocked the page while the drawer is still open");
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 0, null, { timeout: 4000 });
      assert.equal(await page.evaluate(() => document.body.style.overflow), before, "the page did not get its overflow back");
    },
  },
  {
    id: "escape-returns-focus-to-the-row-that-opened-the-drawer",
    title: "Escape closes the drawer and focus goes back to the row that opened it",
    async run(env) {
      const { page } = env;
      const drawer = await openInvoiceDrawer(env, "issued");
      await drawer.waitFor();
      await page.keyboard.press("Escape");
      await page.waitForFunction(() => document.querySelectorAll('[role="dialog"]').length === 0, null, { timeout: 4000 });
      const onRow = await page.evaluate(() => {
        const el = document.activeElement;
        return !!el && !!el.closest("tr[data-row-clickable]");
      });
      assert.equal(onRow, true, "focus did not return to the invoice row");
    },
  },
];
