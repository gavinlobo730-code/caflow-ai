/**
 * FIVE DIALOGS OF THE DOCUMENT AND PORTAL SCREENS ARE THE SHARED DIALOG (POST-A-130, twentieth step), driven in a browser.
 *
 * Upload Document on the three screens that have one (the firm's client documents, a client's own Documents tab and the Documents
 * screen), New Document Request on the Client Portal screen and Invite to Portal on a client's Portal tab were each a layer built by hand
 * over the page. None had a name a screen reader announces, none kept Tab inside, none closed on Escape and none gave focus back. They
 * are the shared Modal now. The source guard holds the five; this drives what each has to get right:
 *
 *   1. each of the three Upload Document dialogs, and New Document Request, is a named modal dialog with its Cancel and its saving button
 *      inside, the page locked, Tab and Shift+Tab kept inside, and Escape closes it;
 *   2. Invite to Portal the same, and it gives focus back to the button that opened it;
 *   3. FOUND WHILE CONVERTING IT: Invite to Portal's Cancel and its × were live while the invitation was being sent, so a person could
 *      close it and never read a refusal (an address already invited, the mail service's limit). While the invitation is out now, Cancel
 *      is held and the ×, Escape and a click beside the dialog do not close it; the server's refusal is then read inside the dialog and
 *      the request went once.
 *
 * That an upload's expiry and a request's needed-by date are judged before the save is the nightly set's (dates), on the same build.
 *
 * No scenario asserts a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { CLIENT_ID } from "../fixtures.mjs";
import { openUploadDocument, openPortalRequest } from "../scenarios/dates.mjs";

export const group = "document-dialogs";

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

async function namedAndKept(page, dialog, buttons, what, opener) {
  await dialog.waitFor();
  assert.equal(await page.getByRole("dialog").count(), 1, "more than one dialog is open");
  assert.equal(await dialog.getAttribute("aria-modal"), "true", `${what} does not say it is modal`);
  assert.equal(await pageLocked(page), "hidden", `the page behind ${what} can still scroll`);
  for (const name of buttons) {
    assert.equal(await dialog.getByRole("button", { name, exact: true }).count(), 1, `${name} is not inside ${what}`);
  }
  await tabStaysInside(page, dialog, 6, what);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "detached" });
  assert.equal(await pageLocked(page), "", `the page is still locked after ${what} closed`);
  if (opener) assert.equal(await opener.evaluate((el) => el === document.activeElement), true, `focus did not return to the button that opened ${what}`);
}

const upload = (page) => page.getByRole("dialog", { name: "Upload Document", exact: true });
const INVITE = new RegExp(`api\\/portal\\/clients\\/${CLIENT_ID}\\/contacts$`);

/** A client's Portal tab with Invite to Portal open. */
async function atTheInvite(env, invite) {
  const { page, stub } = env;
  stub.setTable("client_portal_users", []);
  stub.route({ method: "POST", re: INVITE, ...invite });
  await page.goto(env.at("/portal/"), { waitUntil: "networkidle" });
  const opener = page.getByRole("button", { name: /^(Invite to Portal|Invite Another Contact)$/ }).first();
  await opener.waitFor();
  await opener.focus();
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Invite to Portal", exact: true });
  await dialog.waitFor();
  return { dialog, opener };
}

export const scenarios = [
  {
    id: "the-three-upload-document-dialogs-are-named-and-keep-the-keyboard",
    title: "Client documents, a client's Documents tab and the Documents screen > Upload Document: each a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it",
    async run(env) {
      const { page, stub } = env;
      await openUploadDocument(env);
      await namedAndKept(page, upload(page), ["Cancel", "Upload"], "Upload Document (client documents)");

      await page.goto(env.at("/documents/"), { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Upload Document" }).first().click();
      await namedAndKept(page, upload(page), ["Cancel", "Upload"], "Upload Document (a client's Documents tab)");

      stub.route({ method: "GET", re: /\/api\/documents(\?|$)/, reply: () => ok({ documents: [], returned: 0, has_more: false }) });
      await page.goto(`${env.base}/documents/`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Upload Document" }).first().click();
      await namedAndKept(page, upload(page), ["Cancel", "Upload"], "Upload Document (the Documents screen)");
    },
  },
  {
    id: "new-document-request-is-named-and-keeps-the-keyboard",
    title: "Client Portal > New Request: a named modal dialog with its buttons inside, the page locked, Tab kept inside, Escape closes it",
    async run(env) {
      const { page } = env;
      await openPortalRequest(env);
      await namedAndKept(page, page.getByRole("dialog", { name: "New Document Request", exact: true }), ["Cancel", "Create Request"], "New Document Request");
    },
  },
  {
    id: "invite-to-portal-is-named-keeps-the-keyboard-and-gives-focus-back",
    title: "A client's Portal tab > Invite to Portal: a named modal dialog with its buttons inside, Tab kept inside, Escape closes it and focus returns to the button that opened it",
    async run(env) {
      const { page } = env;
      const { dialog, opener } = await atTheInvite(env, { reply: () => ok({ contact: { id: "pc-1", invite_token: "t" } }) });
      await namedAndKept(page, dialog, ["Cancel", "Send Invite"], "Invite to Portal", opener);
    },
  },
  {
    id: "invite-to-portal-is-held-while-the-invitation-is-sent-and-the-refusal-is-read-in-it",
    title: "A client's Portal tab > Invite to Portal > Send Invite: while the invitation is being sent Cancel is held and the ×, Escape and a click beside the dialog do not close it; the server's refusal is then read inside the dialog",
    async run(env) {
      const { page, stub } = env;
      const { dialog } = await atTheInvite(env, { delay: 2500, ...refuse("A stub refusal of the invitation.", 422) });
      await dialog.getByLabel("Client email", { exact: true }).fill("owner@acme.example");
      await dialog.getByRole("button", { name: "Send Invite", exact: true }).click();
      await dialog.getByRole("button", { name: "Sending…" }).waitFor({ timeout: 3000 });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), true, "Cancel is live while the invitation is being sent");
      await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);
      assert.equal(await dialog.count(), 1, "the ×, Escape or a click beside it closed Invite to Portal while the invitation was being sent");
      await dialog.getByText("A stub refusal of the invitation.").waitFor({ timeout: 8000 }).catch(() => { throw new Error("the server's refusal was not shown inside the dialog"); });
      assert.equal(await dialog.getByRole("button", { name: "Cancel", exact: true }).isDisabled(), false, "Cancel stayed held after the answer");
      assert.equal(stub.writesTo(INVITE).length, 1, "the invitation was not sent exactly once");
    },
  },
];
