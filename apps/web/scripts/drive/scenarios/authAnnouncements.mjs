/**
 * Group: the sign-in service announcing a change does not unmount the screen a person is working on (POST-A-493).
 *
 * The sign-in library announces SIGNED_IN again each time a tab regains focus (and TOKEN_REFRESHED hourly, USER_UPDATED after a
 * password change). AuthContext set the sign-in assurance to "not yet read" on EVERY announcement and AuthGuard drew nothing
 * until it was read again, so the page under it was unmounted and mounted again: what was typed was lost and a message set by
 * a request that was already in flight was set on a page that had gone. A source guard can read that the context reacts to
 * the announcement; this drives what a person sees: they type, the tab loses and regains focus, and the box is still there
 * with what they typed in it.
 */
import assert from "node:assert/strict";

export const group = "auth-announcements";

/** What a browser does when a tab goes to the background and comes back: the library listens for exactly this. */
async function leaveAndComeBack(page) {
  await page.evaluate(() => {
    for (const state of ["hidden", "visible"]) {
      Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
      Object.defineProperty(document, "hidden", { value: state === "hidden", configurable: true });
      document.dispatchEvent(new Event("visibilitychange", { bubbles: true }));
    }
  });
}

export const scenarios = [
  {
    id: "the-security-page-keeps-what-is-typed-when-the-tab-regains-focus-and-shows-that-a-password-was-saved",
    title:
      "Settings > Security: type a new password, send the tab to the background and bring it back (the same box stays, with what was typed); then prove the current password, which the sign-in service answers with a NEW session, and save a new one: the page says it was saved although it was unmounted and mounted again while it saved",
    async run(env) {
      const { page, stub } = env;
      await page.goto(`${env.base}/settings/security/`, { waitUntil: "networkidle" });
      const box = page.getByLabel("New password", { exact: true });
      await box.waitFor();
      await box.fill("Brand-new-pass-9");
      await box.evaluate((el) => { el.setAttribute("data-probe", "same-element"); });
      // In production the assurance check is a round trip to the sign-in service (about a quarter of a second to a second);
      // the stub answers at once, which hides the page being unmounted while it waits.
      stub.setAuthUserDelay(900);
      await leaveAndComeBack(page);
      await page.waitForTimeout(2500);
      const kept = await page.evaluate(() => {
        const el = document.querySelector('[data-probe="same-element"]');
        return el ? { present: true, value: el.value } : { present: false, value: null };
      });
      assert.equal(kept.present, true, "the page was unmounted and mounted again when the tab regained focus");
      assert.equal(kept.value, "Brand-new-pass-9", "what was typed was lost when the tab regained focus");

      // The same page, the second thing the announcement used to break: a password change.
      await page.getByLabel("Current password", { exact: true }).fill("Old-password-1");
      await box.fill("Brand-new-pass-9");
      await page.getByLabel("Confirm new password", { exact: true }).fill("Brand-new-pass-9");
      // What a real sign-in service does: the password grant opens a new session with a new token, and the account lookup the
      // assurance check waits for takes a moment.
      stub.setGrantedToken("smoke.walk.token.reverified");
      stub.setAuthUserDelay(700);
      await page.getByRole("button", { name: "Update password" }).click();
      await page.getByText("Your password has been updated.").waitFor({ timeout: 10000 });
    },
  },
];
