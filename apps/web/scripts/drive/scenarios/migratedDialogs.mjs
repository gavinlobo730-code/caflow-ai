/**
 * Group O: dialogs that used to be hand-built are the shared dialog now, and behave like one in a browser (POST-A-130, POST-A-128).
 *
 * A hand-built full-screen overlay has to give itself a role, a name, Escape, focus in and back and a Tab trap, and almost none did. Twelve of them
 * (the Team screen's three invite states and its role editor, the GST page's two notices, the asset delete, the documents screen's two, the
 * task reassign panel, the cost-tranche dialog and the bank "book under" box) were moved onto `components/ui/modal`, which `dialogs.mjs` and
 * `escape.mjs` already drive on the sales and purchase screens. A source guard (`an-overlay-is-the-shared-dialog-or-on-the-frozen-list.test.ts`)
 * holds that none was rebuilt by hand; this drives the Team screen's two, which stand for the rest because they are the same component.
 *
 *   1. Invite Member opens a NAMED dialog, focus lands in its first field, Tab and Shift+Tab never leave it, the page behind it does not scroll,
 *      and Escape closes it, gives the page its scroll back and returns focus to the button that opened it;
 *   2. Edit Role (opened from a row's menu) is a named dialog that Escape closes, and a click on the backdrop closes it too.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { until } from "../kit.mjs";

export const group = "migrated-dialogs";

const MEMBERS = [
  { id: "u-m", full_name: "Meera Shah", email: "meera@firm.in", role: "Manager", is_active: true, auth_user_id: "auth-m", firm_id: "f" },
  { id: "u-n", full_name: "Nitin Rao", email: "nitin@firm.in", role: "Executive", is_active: true, auth_user_id: "auth-n", firm_id: "f" },
];

async function atTheTeamScreen({ page, stub, base }) {
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { team: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /identity\/users$/, reply: () => ok({ users: MEMBERS }) });
  await page.goto(`${base}/team/`, { waitUntil: "networkidle" });
  await page.getByText("Meera Shah").first().waitFor();
}

const insideDialog = (page) => page.evaluate(() => {
  const d = document.querySelector('[role="dialog"]');
  return !!d && d.contains(document.activeElement);
});

export const scenarios = [
  {
    id: "invite-member-is-a-named-dialog-that-traps-tab-locks-the-page-and-gives-focus-back",
    title: "Invite Member opens a named dialog, focus is inside it, Tab and Shift+Tab stay inside, the page is locked, and Escape closes it and returns focus to the button",
    async run(env) {
      const { page } = env;
      await atTheTeamScreen(env);
      const opener = page.getByRole("button", { name: "Invite Member" }).first();
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Invite Team Member" });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the invite opened more than one dialog");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "the dialog does not say it is modal");
      assert.equal(await page.evaluate(() => document.activeElement?.getAttribute("aria-label")), "Full Name", "focus did not land in the first field");
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page behind the dialog can still scroll");
      for (let i = 0; i < 12; i += 1) {
        await page.keyboard.press("Tab");
        assert.equal(await insideDialog(page), true, `Tab number ${i + 1} left the dialog`);
      }
      for (let i = 0; i < 12; i += 1) {
        await page.keyboard.press("Shift+Tab");
        assert.equal(await insideDialog(page), true, `Shift+Tab number ${i + 1} left the dialog`);
      }
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await page.evaluate(() => document.body.style.overflow), "", "the page is still locked after the dialog closed");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, "focus did not return to the Invite Member button");
    },
  },
  {
    id: "edit-role-is-a-named-dialog-that-escape-and-the-backdrop-close",
    title: "Edit Role, opened from a row's menu, is a named dialog; Escape closes it, and so does a click on the backdrop",
    async run(env) {
      const { page } = env;
      await atTheTeamScreen(env);
      const open = async () => {
        await page.locator("tr", { hasText: "Meera Shah" }).locator("td").last().locator("button").first().click();
        await page.getByRole("button", { name: "Edit Role" }).click();
        const dialog = page.getByRole("dialog", { name: "Edit Role" });
        await dialog.waitFor();
        assert.match(await dialog.innerText(), /Meera Shah · meera@firm\.in/, "the dialog does not say whose role it is");
        // The dialog moves focus in once it has mounted its key handler; pressing Escape before that is a keystroke to nobody.
        await until(() => insideDialog(page), "focus to move into the dialog");
        return dialog;
      };
      let dialog = await open();
      // Tab and Shift+Tab never leave it, and the page behind it is locked while it is open
      assert.equal(await page.evaluate(() => document.body.style.overflow), "hidden", "the page behind the role dialog can still scroll");
      for (const key of ["Tab", "Tab", "Tab", "Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab", "Shift+Tab"]) {
        await page.keyboard.press(key);
        assert.equal(await insideDialog(page), true, `${key} left the role dialog`);
      }
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      dialog = await open();
      // The dimmed area beside the panel, below the app's top bar (which is drawn above a Modal: see POST-A-130).
      await page.mouse.click(20, 300);
      await dialog.waitFor({ state: "detached" });
    },
  },
];
