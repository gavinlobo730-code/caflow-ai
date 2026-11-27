/**
 * THE HSN LIBRARY'S EDIT DIALOG IS DRIVEN IN A BROWSER (POST-A-555).
 *
 * The sixteenth step of POST-A-130 moved Edit onto the shared dialog and drove six of the seven dialogs of that step; this one needs a library
 * row and was left. Against a stubbed server, in Chromium, as a Partner on Settings, HSN library:
 *
 *   1. Edit opens a dialog NAMED for the code (Edit 4802), the page behind it is locked, focus is in the Description box, Tab and Shift+Tab never
 *      leave it, and Escape closes it, gives the page its scroll back and returns focus to the row's Edit button;
 *   2. while the change is being saved its Cancel is held, the ×, Escape and a click beside it close nothing, the request goes ONCE and carries
 *      what was typed, and the server's refusal is read on the screen it was asked from (the dialog is still open to correct it).
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "hsn-library-edit";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

const EVERYTHING = { role: "Partner", permissions: { settings: ["read", "write"], accounting: ["read", "write"], client: ["read", "write"] } };
const ROW = { id: "hsn-1", hsn_code: "4802", description: "Uncoated paper and paperboard", hsn_type: "goods", gst_rate_pct: 18, uqc: "KGS", is_active: true };
const UPDATE = /api\/firm-hsn-library\/hsn-1$/;

async function atTheLibrary(env, update) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok(EVERYTHING) });
  stub.route({ method: "GET", re: /api\/firm-hsn-library\/?(\?|$)/, reply: () => ok({ codes: [ROW], has_more: false, limit: 500, max_limit: 2000 }) });
  stub.route({ method: "PATCH", re: UPDATE, ...(update ?? { reply: () => ok({ ...ROW }) }) });
  await page.goto(`${env.base}/settings/firm-hsn-library/`, { waitUntil: "networkidle" });
  const opener = page.getByRole("button", { name: "Edit", exact: true }).first();
  await opener.waitFor();
  return opener;
}

export const scenarios = [
  {
    id: "the-hsn-library-edit-is-a-named-dialog-that-keeps-the-keyboard-and-gives-focus-back",
    title: "Settings > HSN library > Edit: a dialog named for the code, the page locked, focus in the Description box, Tab and Shift+Tab kept inside, Escape closes it and focus returns to the row's Edit button",
    async run(env) {
      const { page } = env;
      const opener = await atTheLibrary(env);
      await opener.focus();
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Edit 4802", exact: true });
      await dialog.waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
      assert.equal(await dialog.getAttribute("aria-modal"), "true", "Edit does not say it is modal");
      assert.equal(await pageLocked(page), "hidden", "the page behind Edit can still scroll");
      for (const name of ["Cancel", "Save changes"]) {
        assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside the dialog`);
      }
      await until(() => focusInside(dialog), "focus to move into the Edit dialog");
      assert.equal(await page.evaluate(() => document.activeElement?.tagName), "INPUT", "focus did not land in the Description box");
      for (let i = 0; i < 8; i += 1) {
        await page.keyboard.press("Tab");
        assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left the Edit dialog`);
      }
      for (let i = 0; i < 8; i += 1) {
        await page.keyboard.press("Shift+Tab");
        assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left the Edit dialog`);
      }
      await page.keyboard.press("Escape");
      await dialog.waitFor({ state: "detached" });
      assert.equal(await pageLocked(page), "", "the page is still locked after Edit closed");
      assert.equal(await opener.evaluate((el) => el === document.activeElement), true, `focus did not return to the row's Edit button (it is on ${await page.evaluate(() => (document.activeElement?.outerHTML ?? "nothing").slice(0, 160))})`);
    },
  },
  {
    id: "the-hsn-library-edit-is-held-while-it-saves-and-sends-what-was-typed-once",
    title: "HSN library > Edit > Save changes: while the change is out Cancel is held and the ×, Escape and a click beside the dialog close nothing, the request goes once with what was typed, and the refusal leaves the dialog open",
    async run(env) {
      const { page, stub } = env;
      const opener = await atTheLibrary(env, { delay: 2500, ...refuse("A stub refusal of the change.", 422) });
      await opener.click();
      const dialog = page.getByRole("dialog", { name: "Edit 4802", exact: true });
      await dialog.waitFor();
      const description = dialog.getByLabel("Description");
      await description.fill("Paper, uncoated, for writing and printing");
      stub.forgetWrites();
      await dialog.getByRole("button", { name: "Save changes", exact: true }).click();
      await until(() => dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), "Cancel to be held while the change is out");
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click({ force: true }).catch(() => {});
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed Edit while the change was being saved");
      await until(async () => !(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled()), "the dialog to be let go after the answer");
      assert.equal(await dialog.count(), 1, "the dialog closed on a refusal, so the person could not correct what they typed");
      const sent = stub.writesTo(UPDATE, "PATCH");
      assert.equal(sent.length, 1, "the change was not sent exactly once");
      assert.equal(JSON.parse(sent[0].body).description, "Paper, uncoated, for writing and printing", "the request did not carry what was typed");
      await page.getByText("A stub refusal of the change.").first().waitFor({ timeout: 8000 })
        .catch(() => { throw new Error("the server's refusal was not shown"); });
    },
  },
];
