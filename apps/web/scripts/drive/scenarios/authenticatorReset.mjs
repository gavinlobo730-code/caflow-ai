/**
 * Group K: a lost authenticator app is asked about from the two places a person is stuck (POST-A-006).
 *
 * A person whose phone is gone is at the sign-in challenge with a password-level session and nowhere else to go; a Partner
 * is on the Team screen. Both send ONE request to the approval engine and say what happens next, and the browser says
 * nothing it cannot know: who may ask, that a different Partner decides and that the only Partner cannot reset their own
 * are the server's rules and arrive as the server's sentences. A source guard can read that the form posts the right body;
 * this drives what a person sees and what the stub is sent.
 */
import assert from "node:assert/strict";
import { expectWrites } from "../kit.mjs";
import { FAKE_USER } from "../fixtures.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "authenticator-reset";

/** An account that holds a verified second factor, so the sign-in challenge is owed. */
const ACCOUNT_WITH_A_FACTOR = {
  ...FAKE_USER,
  factors: [{ id: "f-1", factor_type: "totp", status: "verified", friendly_name: "Authenticator" }],
};

const APPROVALS = /\/api\/approvals$/;

const PENDING_RESET = {
  id: "apr-9", request_type: "mfa_reset", status: "pending", summary: "Reset the authenticator app of Meera Shah",
  requested_by_email: "meera@firm.in", created_at: "2026-01-05T04:00:00Z",
  payload: { user_id: "u-m", target_name: "Meera Shah", reason: "Phone replaced", self_requested: true, asker_aal: "aal1" },
};
// Another type's payload carries a free-text `reason` too; it is not shown as the asker's reason.
const PENDING_OTHER = {
  id: "apr-8", request_type: "role_change", status: "pending", summary: "Change a role",
  requested_by_email: "x@firm.in", created_at: new Date().toISOString(), payload: { reason: "SECRET-FREE-TEXT" },
};

const MEMBERS = [
  { id: "u-m", full_name: "Meera Shah", email: "meera@firm.in", role: "Manager", is_active: true, auth_user_id: "auth-m", firm_id: "f" },
  { id: "u-new", full_name: "Nitin Invited", email: "nitin@firm.in", role: "Executive", is_active: true, auth_user_id: null, firm_id: "f" },
];

async function atTheChallenge({ page, stub, base }) {
  stub.setAuthUser(ACCOUNT_WITH_A_FACTOR);
  await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Two-factor authentication" }).waitFor();
}

async function atTheTeamScreen({ page, stub, base }, permissions) {
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions }) });
  stub.route({ method: "GET", re: /identity\/users$/, reply: () => ok({ users: MEMBERS }) });
  await page.goto(`${base}/team/`, { waitUntil: "networkidle" });
  await page.getByText("Meera Shah").first().waitFor();
}

const menuOf = (page, name) => page.locator("tr", { hasText: name }).locator("td").last().locator("button").first();

export const scenarios = [
  {
    id: "the-sign-in-challenge-asks-a-partner-and-sends-a-request-for-the-persons-own",
    title: "the challenge offers 'Lost your authenticator app?', needs a reason, and sends one request naming nobody but the asker",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: APPROVALS, reply: () => ok({ id: "apr-1", status: "pending" }) });
      await atTheChallenge(env);
      assert.equal(await page.getByRole("button", { name: "Send request" }).count(), 0, "the form is open before it was asked for");
      await page.getByRole("button", { name: "Lost your authenticator app?" }).click();
      const send = page.getByRole("button", { name: "Send request" });
      assert.equal(await send.isDisabled(), true, "a request with no reason can be sent");
      await page.getByLabel("Why does it need resetting?").fill("  New phone, the old one was stolen  ");
      assert.equal(await send.isDisabled(), false);
      await send.click();
      await page.getByRole("status").getByText(/Request sent/).waitFor();
      await expectWrites(stub, APPROVALS, 1, "the lost-authenticator request", "POST");
      const body = JSON.parse(stub.writesTo(APPROVALS, "POST")[0].body);
      assert.deepEqual(body, {
        request_type: "mfa_reset",
        payload: { reason: "New phone, the old one was stolen", self: true },
      });
      const text = await page.locator("body").innerText();
      assert.match(text, /Once they approve it, sign in again with your password/);
      assert.equal(await page.getByRole("heading", { name: "Two-factor authentication" }).count(), 1, "the code form went away");
    },
  },
  {
    id: "a-refusal-from-the-server-is-shown-in-its-own-words-and-the-request-can-be-sent-again",
    title: "the server's sentence (the only Partner cannot reset their own) is shown as it is, not 'Request sent'",
    async run(env) {
      const { page, stub } = env;
      const sentence = "You are the firm's only active Partner, so there is nobody to approve this.";
      stub.route({ method: "POST", re: APPROVALS, ...refuse(sentence, 409) });
      await atTheChallenge(env);
      await page.getByRole("button", { name: "Lost your authenticator app?" }).click();
      await page.getByLabel("Why does it need resetting?").fill("Lost the phone");
      await page.getByRole("button", { name: "Send request" }).click();
      await page.getByRole("alert").getByText(sentence).waitFor();
      assert.equal(await page.getByText(/Request sent/).count(), 0, "a refused request was reported as sent");
      assert.equal(await page.getByRole("button", { name: "Send request" }).isEnabled(), true, "the person cannot try again");
    },
  },
  {
    id: "the-team-menu-offers-a-partner-the-reset-for-a-member-who-has-signed-in",
    title: "a Partner sees 'Reset authenticator' on a member who has signed in (not on one who never has), and sends the member's id",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: APPROVALS, reply: () => ok({ id: "apr-2", status: "pending" }) });
      await atTheTeamScreen(env, { approval: ["read", "request", "approve"], team: ["read", "write"] });

      await menuOf(page, "Nitin Invited").click();
      assert.equal(await page.getByRole("button", { name: "Reset authenticator" }).count(), 0,
        "offered for a member who has never signed in, who has no authenticator to reset");
      await page.keyboard.press("Escape");
      await page.mouse.click(5, 5);

      await menuOf(page, "Meera Shah").click();
      await page.getByRole("button", { name: "Reset authenticator" }).click();
      const dialog = page.getByRole("dialog", { name: "Reset authenticator app" });
      await dialog.waitFor();
      assert.match(await dialog.innerText(), /Meera Shah/);
      assert.match(await dialog.innerText(), /A Partner other than you approves it first; if you are the firm.s only Partner, you approve it yourself/);
      await dialog.getByLabel("Why does it need resetting?").fill("Phone replaced");
      await dialog.getByRole("button", { name: "Send request" }).click();
      await dialog.getByRole("status").getByText(/Request sent/).waitFor();
      assert.equal(await dialog.getByRole("link", { name: "Approvals" }).count(), 1);
      await expectWrites(stub, APPROVALS, 1, "the member's reset request", "POST");
      assert.deepEqual(JSON.parse(stub.writesTo(APPROVALS, "POST")[0].body), {
        request_type: "mfa_reset",
        payload: { reason: "Phone replaced", user_id: "u-m" },
      });
    },
  },
  {
    id: "the-team-menu-does-not-offer-the-reset-to-someone-who-cannot-approve",
    title: "without approval:approve (a Manager) the menu has Edit Role and Deactivate and no reset",
    async run(env) {
      const { page } = env;
      await atTheTeamScreen(env, { approval: ["read", "request"], team: ["read"] });
      await menuOf(page, "Meera Shah").click();
      await page.getByRole("button", { name: "Edit Role" }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Reset authenticator" }).count(), 0);
    },
  },
  {
    id: "the-approvals-screen-says-how-the-asker-signed-in-and-asks-before-a-reset-is-approved",
    title: "a pending reset shows its reason, how long ago and 'password only'; saying no sends nothing, yes sends one approval",
    async run(env) {
      const { page, stub, base } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { approval: ["read", "request", "approve"] } }) });
      stub.route({ method: "GET", re: /\/api\/approvals(\?.*)?$/, reply: () => ok({ requests: [PENDING_RESET, PENDING_OTHER] }) });
      stub.route({ method: "POST", re: /\/api\/approvals\/apr-9\/approve$/, reply: () => ok({ id: "apr-9", status: "approved" }) });
      await page.goto(`${base}/approvals/`, { waitUntil: "networkidle" });
      await page.getByText("Reset the authenticator app of Meera Shah").waitFor();
      const text = await page.locator("body").innerText();
      assert.match(text, /Reason given: Phone replaced/);
      // The page's clock is the driver's, not this process's, so the age is asserted as present rather than as a figure.
      assert.match(text, /Asked [^\n]*\. Asked with a password only\./);
      assert.equal(text.includes("SECRET-FREE-TEXT"), false, "another request type's free text was shown as a reason");

      const approve = page.locator("div.rounded-xl", { hasText: "Reset the authenticator app of Meera Shah" }).getByRole("button", { name: "Approve" });
      await approve.click();
      const question = page.getByRole("alertdialog");
      await question.waitFor();
      assert.match(await question.innerText(), /confirmed with Meera Shah, by a call or in person/);
      await question.getByRole("button", { name: "Cancel", exact: true }).click();
      await question.waitFor({ state: "detached" });
      await expectWrites(stub, /\/api\/approvals\/apr-9\/approve$/, 0, "saying no to the reset", "POST");

      await approve.click();
      await page.getByRole("alertdialog").getByRole("button", { name: "Reset authenticator" }).click();
      await expectWrites(stub, /\/api\/approvals\/apr-9\/approve$/, 1, "saying yes to the reset", "POST");
    },
  },
  {
    id: "another-request-type-is-approved-without-the-reset-question",
    title: "approving a role change asks nothing extra (the question is for the reset alone)",
    async run(env) {
      const { page, stub, base } = env;
      stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { approval: ["read", "request", "approve"] } }) });
      stub.route({ method: "GET", re: /\/api\/approvals(\?.*)?$/, reply: () => ok({ requests: [PENDING_OTHER] }) });
      stub.route({ method: "POST", re: /\/api\/approvals\/apr-8\/approve$/, reply: () => ok({ id: "apr-8", status: "approved" }) });
      await page.goto(`${base}/approvals/`, { waitUntil: "networkidle" });
      await page.getByText("Change a role").waitFor();
      await page.getByRole("button", { name: "Approve" }).click();
      await expectWrites(stub, /\/api\/approvals\/apr-8\/approve$/, 1, "approving a role change", "POST");
      assert.equal(await page.getByRole("alertdialog").count(), 0, "the reset question was asked for another request type");
    },
  },
];
