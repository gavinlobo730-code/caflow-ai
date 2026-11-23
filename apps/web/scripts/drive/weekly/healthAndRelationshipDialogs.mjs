/**
 * SIX DIALOGS OF THE HEALTH, LIFECYCLE AND RELATIONSHIP SCREENS ARE THE SHARED DIALOG (POST-A-130, nineteenth step), driven in a browser.
 *
 * Add Score Override on the health detail screen, Add Override on a client's Health tab, Add Renewal on a client's Lifecycle tab, Link
 * an entity on a client's Relationships tab, Add Entity on the Entity Registry and Edit Entity on an entity's own page were each a layer
 * built by hand over the page. None had a name a screen reader announces, none kept Tab inside, none closed on Escape and none gave focus
 * back. They are the shared Modal now. The source guard holds the six; this drives five of them:
 *
 *   1. Add Score Override, Add Override, Add Renewal, Add Entity and Link an entity are each a named modal dialog with their Cancel and
 *      their saving button inside, the page locked, Tab and Shift+Tab kept inside, and Escape closes it and gives focus back to the
 *      button that opened it;
 *   2. while a new entity is being added, Cancel is held and the ×, Escape and a click beside the dialog do not close it; the server's
 *      refusal is then read inside the dialog and the request went once.
 *
 * Edit Entity is the same component as Add Entity on another page and is not driven here. That an override's expiry and a renewal's date
 * are judged before the save is the nightly set's (dates), which runs on the same build.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";
import { openHealthOverride, openAddRenewal } from "../scenarios/dates.mjs";

export const group = "health-and-relationship-dialogs";

const focusInside = (dialog) => dialog.evaluate((d) => d.contains(document.activeElement));
const pageLocked = (page) => page.evaluate(() => document.body.style.overflow);

async function tabStaysInside(page, dialog, n, what) {
  await until(() => focusInside(dialog), `focus to be inside ${what}`);
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Tab");
    assert.equal(await focusInside(dialog), true, `Tab number ${i + 1} left ${what}`);
  }
  for (let i = 0; i < n; i += 1) {
    await page.keyboard.press("Shift+Tab");
    assert.equal(await focusInside(dialog), true, `Shift+Tab number ${i + 1} left ${what}`);
  }
}

const ENTITIES = /\/api\/relationships\/entities/;
const ENTITY = { id: "en-1", full_name: "Asha Rao", entity_type: "Individual", pan: "ABCPR1234K", gstin: null, email: null, phone: null, is_active: true };

/** The Entity Registry with one entity on it. */
async function atTheRegistry(env, create) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: ENTITIES, reply: () => ok({ entities: [ENTITY], returned: 1, has_more: false, limit: 2000, max_limit: 2000 }) });
  stub.route({ method: "POST", re: /\/api\/relationships\/entities$/, ...(create ?? { reply: () => ok({ ...ENTITY, id: "en-2" }) }) });
  await page.goto(`${env.base}/relationships/`, { waitUntil: "networkidle" });
  await page.getByText("Asha Rao").first().waitFor();
}

/** What every one of these dialogs has to get right, whichever screen it is on. `opener` is the button that opened it, when it is known. */
async function namedAndKept(page, dialog, buttons, what, opener) {
  await dialog.waitFor();
  assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
  assert.equal(await dialog.getAttribute("aria-modal"), "true", `${what} does not say it is modal`);
  assert.equal(await pageLocked(page), "hidden", `the page behind ${what} can still scroll`);
  for (const name of buttons) {
    assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside ${what}`);
  }
  await tabStaysInside(page, dialog, 8, what);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  assert.equal(await pageLocked(page), "", `the page is still locked after ${what} closed`);
  if (opener) assert.equal(await opener.evaluate((el) => el === document.activeElement), true, `focus did not return to the button that opened ${what}`);
}

export const scenarios = [
  {
    id: "the-two-health-override-dialogs-are-named-and-keep-the-keyboard",
    title: "Health detail > Add Override and a client's Health tab > Add Override: each a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it",
    async run(env) {
      const { page } = env;
      await openHealthOverride(env, `${env.base}/health/${CLIENT_ID}/`);
      await namedAndKept(page, page.getByRole("dialog", { name: "Add Score Override", exact: true }), ["Cancel", "Add Override"], "Add Score Override");
      await openHealthOverride(env, env.at("/health/"));
      await namedAndKept(page, page.getByRole("dialog", { name: "Add Override", exact: true }), ["Cancel", "Add Override"], "Add Override");
    },
  },
  {
    id: "add-renewal-is-named-and-keeps-the-keyboard",
    title: "A client's Lifecycle tab > Add Renewal: a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it",
    async run(env) {
      const { page } = env;
      await openAddRenewal(env);
      await namedAndKept(page, page.getByRole("dialog", { name: "Add Renewal", exact: true }), ["Cancel", "Save"], "Add Renewal");
    },
  },
  {
    id: "add-entity-and-link-an-entity-are-named-keep-the-keyboard-and-give-focus-back",
    title: "Entity Registry > Add Entity and a client's Relationships tab > Link Entity: each a named modal dialog with its buttons inside, Tab kept inside, Escape closes it and focus returns to the button that opened it",
    async run(env) {
      const { page, stub } = env;
      await atTheRegistry(env);
      const add = page.getByRole("button", { name: "Add Entity" }).first();
      await add.focus();
      await add.click();
      const dialog = page.getByRole("dialog", { name: "Add Entity", exact: true });
      await dialog.waitFor();
      assert.equal(await dialog.getByLabel("Full Name", { exact: true }).evaluate((el) => el === document.activeElement), true, "focus is not in the first field of Add Entity");
      await namedAndKept(page, dialog, ["Cancel", "Add Entity"], "Add Entity", add);

      stub.route({ method: "GET", re: /\/api\/relationships\/roles/, reply: () => ok({ roles: [], returned: 0, has_more: false, limit: 500, max_limit: 500 }) });
      await page.goto(env.at("/relationships/"), { waitUntil: "networkidle" });
      const link = page.getByRole("button", { name: "Link Entity" }).first();
      await link.waitFor();
      await link.focus();
      await link.click();
      await namedAndKept(page, page.getByRole("dialog", { name: "Link an entity to this client", exact: true }), ["Cancel", "Link entity"], "Link an entity", link);
    },
  },
  {
    id: "add-entity-is-held-while-the-entity-is-added-and-the-refusal-is-read-in-it",
    title: "Entity Registry > Add Entity > Add Entity: while the entity is being added Cancel is held and the ×, Escape and a click beside the dialog do not close it; the server's refusal is then read inside the dialog",
    async run(env) {
      const { page, stub } = env;
      await atTheRegistry(env, { delay: 2500, ...refuse("A stub refusal of the entity.", 422) });
      await page.getByRole("button", { name: "Add Entity" }).first().click();
      const dialog = page.getByRole("dialog", { name: "Add Entity", exact: true });
      await dialog.waitFor();
      await dialog.getByLabel("Full Name", { exact: true }).fill("Vikram Shah");
      await dialog.getByRole("button", { name: "Add Entity", exact: true }).click();
      await until(async () => await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), "Cancel to be held while the entity is being added", 3000);
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed Add Entity while the entity was being added");
      await dialog.getByText("A stub refusal of the entity.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside the dialog"); });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), false, "Cancel stayed held after the answer");
      assert.equal(stub.writesTo(/\/api\/relationships\/entities$/).length, 1, "the entity was not sent exactly once");
    },
  },
];
