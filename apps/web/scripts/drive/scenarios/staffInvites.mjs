/**
 * Group: staff-invites. A staff invitation is sent by the server, can be sent again, and its link signs the invitee in
 * by itself (POST-A-445).
 *
 * The owner, inviting himself on the live site on 15-11-2026, found an invitation nothing could send again and a mail
 * that named neither the practice nor who had invited. The Team screen used to ask Supabase to mail an ordinary
 * sign-in link from the Partner's browser; the server sends the invitation now and the screen shows what the mail
 * service did with it. These drive what a person sees and what the stub is sent: the screen asks Supabase to mail
 * nothing, Resend invite is offered only to somebody waiting to join and says what came of it, a withdrawn invitation
 * shows as withdrawn without a reload, and the join page signs a signed-out invitee in from the bare link, and asks
 * before signing somebody else out of the browser.
 */
import assert from "node:assert/strict";
import { expectWrites } from "../kit.mjs";
import { FAKE_USER } from "../fixtures.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "staff-invites";

const USERS = /\/api\/identity\/users$/;
const RESEND = /\/api\/identity\/users\/u-new\/resend-invite$/;
const SUSPEND = /\/api\/identity\/users\/u-new\/suspend$/;
const SESSION = /\/api\/identity\/accept-invite\/session$/;
const ACCEPT = /\/api\/identity\/accept-invite$/;

const EXPIRES = "2026-10-15T08:00:00+00:00";
const RESENT_EXPIRES = "2026-10-15T09:00:00+00:00";

const ACTIVE = { id: "u-m", full_name: "Meera Shah", email: "meera@firm.in", role: "Manager", is_active: true,
                 auth_user_id: "auth-m", firm_id: "f", member_state: "active" };
const INVITED = { id: "u-new", full_name: "Nitin Invited", email: "nitin@firm.in", role: "Executive", is_active: true,
                  auth_user_id: null, firm_id: "f", member_state: "invited", invite_expires_at: EXPIRES };

/** Every request the page makes, so a scenario can say what it did NOT ask for (Supabase's own sign-in mail). */
function recordRequests(page) {
  const seen = [];
  page.on("request", (r) => seen.push(`${r.method()} ${new URL(r.url()).pathname}`));
  return seen;
}

async function atTheTeamScreen({ page, stub, base }, members) {
  let current = members;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { team: ["read", "write"] } }) });
  stub.route({ method: "GET", re: USERS, reply: () => ok({ users: current }) });
  await page.goto(`${base}/team/`, { waitUntil: "networkidle" });
  await page.getByText("Meera Shah").first().waitFor();
  return { setMembers: (next) => { current = next; } };
}

const menuOf = (page, name) => page.locator("tr", { hasText: name }).locator("td").last().locator("button").first();

/** The join page opened signed out: the walk seeds a session for every page, and this one has to arrive without one. */
async function signedOut(page) {
  await page.addInitScript(() => {
    try { for (const k of Object.keys(localStorage)) if (k.startsWith("sb-")) localStorage.removeItem(k); } catch { /* none to clear */ }
  });
}

export const scenarios = [
  {
    id: "inviting-asks-the-server-and-supabase-mails-nothing-and-a-mail-that-did-not-go-is-said",
    title: "Invite Member posts to the server only; when the server says the mail did not go, the dialog says so in its words",
    async run(env) {
      const { page, stub } = env;
      const seen = recordRequests(page);
      const problem = "The mail service did not accept it. Use Resend invite on their row to try again.";
      stub.route({ method: "POST", re: USERS, reply: () => ok({ id: "u-x", member_state: "invited", invite_expires_at: EXPIRES,
                                                               invite_mail: { sent: false, problem } }) });
      await atTheTeamScreen(env, [ACTIVE]);
      await page.getByRole("button", { name: "Invite Member" }).first().click();
      const dialog = page.getByRole("dialog", { name: "Invite Team Member" });
      await dialog.getByLabel("Full Name").fill("Asha New");
      await dialog.getByLabel("Email Address").fill("asha@firm.in");
      await dialog.getByRole("button", { name: "Send Invitation" }).click();
      const notSent = page.getByRole("dialog", { name: "Invite created — email not sent" });
      await notSent.waitFor();
      assert.match(await notSent.innerText(), /The invite for Asha New was created, but the email to asha@firm\.in could not be sent\./);
      assert.match(await notSent.innerText(), /Use Resend invite on their row/);
      await expectWrites(stub, USERS, 1, "the invitation", "POST");
      assert.deepEqual(seen.filter((r) => /\/auth\/v1\/otp/.test(r)), [], "the browser asked Supabase to mail a sign-in link");
    },
  },
  {
    id: "a-mail-that-went-says-whose-practice-and-until-when",
    title: "a sent invitation's dialog says it went, that it names the practice and the Partner, and until when it works",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: USERS, reply: () => ok({ id: "u-x", member_state: "invited", invite_expires_at: EXPIRES,
                                                               invite_mail: { sent: true, problem: null } }) });
      await atTheTeamScreen(env, [ACTIVE]);
      await page.getByRole("button", { name: "Invite Member" }).first().click();
      const dialog = page.getByRole("dialog", { name: "Invite Team Member" });
      await dialog.getByLabel("Full Name").fill("Asha New");
      await dialog.getByLabel("Email Address").fill("asha@firm.in");
      await dialog.getByRole("button", { name: "Send Invitation" }).click();
      const sent = page.getByRole("dialog", { name: "Invitation Sent" });
      await sent.waitFor();
      const text = await sent.innerText();
      assert.match(text, /The invitation went to asha@firm\.in\. Its link signs Asha New in until 15 Oct 2026, /,
        "the instant the server stored is not stated");
      assert.doesNotMatch(text, /names your practice/, "the dialog promises what the mail may not have named");
      assert.doesNotMatch(text, /magic link/);
    },
  },
  {
    id: "resend-is-offered-to-somebody-waiting-to-join-and-says-the-earlier-link-stopped-working",
    title: "Resend invite appears on an invited row and not on a joined one; it posts once and says what the server did",
    async run(env) {
      const { page, stub } = env;
      const team = await atTheTeamScreen(env, [ACTIVE, INVITED]);
      stub.route({ method: "POST", re: RESEND, reply: () => {
        team.setMembers([ACTIVE, { ...INVITED, invite_expires_at: RESENT_EXPIRES }]);
        return ok({ ...INVITED, invite_expires_at: RESENT_EXPIRES, invite_mail: { sent: true, problem: null } });
      } });

      await menuOf(page, "Meera Shah").click();
      await page.getByRole("button", { name: "Edit Role" }).waitFor();
      assert.equal(await page.getByRole("button", { name: "Resend invite" }).count(), 0, "offered to a member who has joined");
      await page.mouse.click(5, 5);

      await menuOf(page, "Nitin Invited").click();
      await page.getByRole("button", { name: "Resend invite" }).click();
      const notice = page.locator("[data-team-notice]");
      await notice.getByText(/A new invitation went to nitin@firm\.in\. The link in any earlier email no longer works\./).waitFor();
      await expectWrites(stub, RESEND, 1, "the resend", "POST");
    },
  },
  {
    id: "a-resend-the-server-refused-or-could-not-mail-is-said-and-never-reads-as-sent",
    title: "a refused resend shows the server's sentence; one whose mail did not go says so and that the old link stopped",
    async run(env) {
      const { page, stub } = env;
      await atTheTeamScreen(env, [ACTIVE, INVITED]);
      const sentence = "The invitation to Nitin Invited was withdrawn. Activate them first, then send the invitation again.";
      stub.route({ method: "POST", re: RESEND, ...refuse(sentence, 409) });
      await menuOf(page, "Nitin Invited").click();
      await page.getByRole("button", { name: "Resend invite" }).click();
      await page.locator("[data-team-notice]").getByText(sentence).waitFor();
      assert.equal(await page.getByText(/A new invitation went to/).count(), 0);

      stub.route({ method: "POST", re: RESEND, reply: () => ok({ ...INVITED, invite_mail: { sent: false, problem: "The mail service did not accept it." } }) });
      await menuOf(page, "Nitin Invited").click();
      await page.getByRole("button", { name: "Resend invite" }).click();
      await page.locator("[data-team-notice]").getByText(
        /its email to nitin@firm\.in did not go, and the link in any earlier email no longer works\. The mail service did not accept it\./).waitFor();
    },
  },
  {
    id: "withdrawing-an-invitation-shows-it-withdrawn-without-a-reload",
    title: "Withdraw invite reads the list again, so the badge is the server's Inactive and not a stale Invited",
    async run(env) {
      const { page, stub } = env;
      const team = await atTheTeamScreen(env, [ACTIVE, INVITED]);
      stub.route({ method: "POST", re: SUSPEND, reply: () => {
        team.setMembers([ACTIVE, { ...INVITED, is_active: false, member_state: "inactive", invite_expires_at: null }]);
        return ok({ ...INVITED, is_active: false });
      } });
      const row = page.locator("tr", { hasText: "Nitin Invited" });
      await row.getByText(/^Invited/).waitFor();
      await menuOf(page, "Nitin Invited").click();
      await page.getByRole("button", { name: "Withdraw invite" }).click();
      await page.locator("tr", { hasText: "Nitin Invited" }).getByText("Inactive", { exact: true }).waitFor();
      assert.equal(await page.locator("tr", { hasText: "Nitin Invited" }).getByText(/^Invited/).count(), 0);
    },
  },
  {
    id: "the-join-link-signs-a-signed-out-invitee-in-from-the-bare-token-and-accepts",
    title: "a signed-out browser opening /join?token= asks the server for the sign-in, redeems it, then accepts once; then the same shape for a SIGN-UP link (POST-A-485, 497): /signup/continue asks what the link is for and signs nobody in until a press, the press carries what the link was asked for into a browser that never held the form, a link that cannot be used offers a new one, a browser signed in as somebody else is asked, and the form asks the server and Supabase mails nothing",
    async run(env) {
      const { page, stub, base } = env;
      await signedOut(page);
      const seen = recordRequests(page);
      stub.route({ method: "POST", re: SESSION, reply: () => ok({ token_hash: "th-1", verification_type: "magiclink", email: FAKE_USER.email }) });
      // As the server does: the token is single use, so a second accept is refused. Signing in remounts the page (the
      // sign-in guard withholds it while it asks about a second factor); a page that started its journey again would
      // accept twice and tell the person who had just joined that the invitation could not be used.
      // The stub answers `reply` before it asks `status`, so the count is taken in `reply`.
      let accepts = 0;
      stub.route({ method: "POST", re: ACCEPT,
        reply: () => (accepts += 1) === 1 ? ok({ firm_id: "f", role: "Executive", full_name: "Nitin Invited" })
                                          : { detail: "Invalid or expired invite." },
        status: () => accepts === 1 ? 200 : 404 });
      await page.goto(`${base}/join/?token=tok-live`, { waitUntil: "networkidle" });
      // A mail scanner that runs a link's scripts must not sign in and use the invitation up: nothing until a press.
      const ready = page.locator("[data-join-ready]");
      await ready.waitFor();
      assert.equal(stub.writesTo(SESSION, "POST").length, 0, "a sign-in was opened before anybody pressed anything");
      assert.equal(stub.writesTo(ACCEPT, "POST").length, 0);
      await ready.getByRole("button", { name: "Accept the invitation" }).click();
      await page.getByRole("heading", { name: /Welcome to the team, Nitin Invited/ }).waitFor();
      assert.ok(seen.some((r) => /^POST .*\/auth\/v1\/verify/.test(r)), "the sign-in the server opened was never redeemed");
      await expectWrites(stub, SESSION, 1, "the sign-in request", "POST");
      await expectWrites(stub, ACCEPT, 1, "the accept", "POST");
      assert.deepEqual(JSON.parse(stub.writesTo(SESSION, "POST")[0].body), { token: "tok-live" });

      // ── the sign-up link's page (POST-A-485, 497), a block of this same run (a scenario of its own would push the nightly drive past its allowance) ──
      // The same shape as the invitation above: the server keeps the link, the page asks what it is for and signs nobody in until a press.
      const LOOK = /\/api\/signup\/link\/look$/;
      const LINK_SESSION = /\/api\/signup\/link\/session$/;
      const ASK = /\/api\/signup\/link$/;
      const link = { email: "ravi@sharma-co.in", firm_name: "Sharma & Associates", full_name: "CA Ravi Sharma", valid_until: "21 November 2026, 2:30 pm IST" };
      stub.route({ method: "POST", re: LOOK, reply: () => ok(link) });
      stub.route({ method: "POST", re: LINK_SESSION, reply: () => ok({ token_hash: "th-link", verification_type: "magiclink", email: link.email, firm_name: link.firm_name, full_name: link.full_name }) });
      stub.route({ method: "POST", re: ASK, reply: () => ok({ sent: true, valid_until: link.valid_until, wait_seconds: 30 }) });
      stub.forgetWrites();

      // A browser that never sent the form (a phone, another laptop): the link says what it is for, and a scanner that opened the page spent nothing.
      const fresh = await env.newPage();
      await signedOut(fresh);
      const freshSeen = recordRequests(fresh);
      await fresh.goto(`${base}/signup/continue/#token=tok-link`, { waitUntil: "networkidle" });
      const linkReady = fresh.locator("[data-signup-continue-ready]");
      await linkReady.waitFor();
      const readyText = await linkReady.innerText();
      assert.match(readyText, /Continue setting up Sharma & Associates/);
      assert.match(readyText, /ravi@sharma-co\.in/);
      assert.match(readyText, /until 21 November 2026, 2:30 pm IST/);
      assert.equal(stub.writesTo(LINK_SESSION, "POST").length, 0, "a sign-in was opened before anybody pressed anything");
      assert.equal(freshSeen.filter((r) => /\/auth\/v1\/verify/.test(r)).length, 0, "the page signed somebody in by itself");
      assert.equal(await fresh.evaluate(() => localStorage.getItem("practicesync_signup")), null, "this browser never sent the form, so it holds no note of it");
      await linkReady.getByRole("button", { name: "Continue" }).click();
      // POST-A-497: the drive's signed-in user belongs to a practice, and the wizard says so although THIS browser never held the form's note:
      // the names came with the link, from the server's answer.
      await fresh.locator("[data-existing-practice]").waitFor({ timeout: 10000 });
      assert.ok(freshSeen.some((r) => /^POST .*\/auth\/v1\/verify/.test(r)), "the sign-in the server opened was never redeemed");
      await expectWrites(stub, LINK_SESSION, 1, "the sign-in request", "POST");
      assert.deepEqual(JSON.parse(stub.writesTo(LINK_SESSION, "POST")[0].body), { token: "tok-link" });
      assert.deepEqual(JSON.parse(await fresh.evaluate(() => localStorage.getItem("practicesync_signup"))),
        { firmName: "Sharma & Associates", fullName: "CA Ravi Sharma", email: "ravi@sharma-co.in" }, "the intent did not travel with the link");

      // A browser signed in as somebody else is asked before anything is done. (A signed-in member of a practice is not bounced from this page.)
      const other = await env.newPage();
      const otherSeen = recordRequests(other);
      await other.goto(`${base}/signup/continue/#token=tok-link`, { waitUntil: "networkidle" });
      const otherAsk = other.locator("[data-signup-continue-other-account]");
      await otherAsk.waitFor();
      const otherText = await otherAsk.innerText();
      assert.match(otherText, new RegExp(`signed in as ${FAKE_USER.email.replace(/[.]/g, "\\.")}`));
      assert.match(otherText, /The link is for ravi@sharma-co\.in/);
      assert.equal(otherSeen.filter((r) => /\/auth\/v1\/(verify|logout)/.test(r)).length, 0, "the browser was signed out before anybody asked");

      // A link that cannot be used: one sentence, and a new one offered only where this browser kept the address and names.
      stub.route({ method: "POST", re: LOOK, ...refuse("This sign-up link is no longer active. It may have expired, been replaced by a newer one, or already been used to create the practice.", 404) });
      stub.forgetWrites();
      const gone = await env.newPage();
      await signedOut(gone);
      await gone.addInitScript((note) => { try { localStorage.setItem("practicesync_signup", note); } catch { /* none to set */ } },
        JSON.stringify({ firmName: "Sharma & Associates", fullName: "CA Ravi Sharma", email: "ravi@sharma-co.in" }));
      await gone.goto(`${base}/signup/continue/#token=tok-old`, { waitUntil: "networkidle" });
      const goneView = gone.locator("[data-signup-continue-gone]");
      await goneView.waitFor();
      assert.match(await goneView.innerText(), /This sign-up link is no longer active/);
      await goneView.getByRole("button", { name: "Email me a new link" }).click();
      await gone.getByText(/A new link is on its way to ravi@sharma-co\.in\. It works until 21 November 2026, 2:30 pm IST/).waitFor();
      await expectWrites(stub, ASK, 1, "the request for a new link", "POST");
      assert.deepEqual(JSON.parse(stub.writesTo(ASK, "POST")[0].body), { email: "ravi@sharma-co.in", firm_name: "Sharma & Associates", full_name: "CA Ravi Sharma" });
      assert.equal(await goneView.getByRole("button", { name: /Email me a new link \(wait/ }).count(), 1, "the wait the server named was not applied");
      const bare = await env.newPage();
      await signedOut(bare);
      // Every page of a scenario shares one browser's storage, and the pages above kept the form's note there: this one has none.
      await bare.addInitScript(() => { try { localStorage.removeItem("practicesync_signup"); } catch { /* none to remove */ } });
      await bare.goto(`${base}/signup/continue/#token=tok-old`, { waitUntil: "networkidle" });
      await bare.locator("[data-signup-continue-gone]").waitFor();
      assert.equal(await bare.getByRole("button", { name: "Email me a new link" }).count(), 0, "a new link was offered with no address to send it to");
      assert.equal(await bare.getByRole("link", { name: "Start the sign-up again" }).count(), 1);

      // The form asks the SERVER; Supabase mails nothing from the browser.
      stub.forgetWrites();
      const form = await env.newPage();
      await signedOut(form);
      const formSeen = recordRequests(form);
      await form.goto(`${base}/signup/`, { waitUntil: "networkidle" });
      await form.getByLabel("Firm Name").fill("Sharma & Associates");
      await form.getByLabel("Your Full Name").fill("CA Ravi Sharma");
      await form.getByLabel("Email Address").fill("ravi@sharma-co.in");
      await form.getByRole("button", { name: "Get started" }).click();
      await form.getByRole("heading", { name: "Check your inbox" }).waitFor();
      assert.match(await form.getByText(/We sent a link to/).innerText(), /ravi@sharma-co\.in/);
      assert.match(await form.locator("body").innerText(), /works until 21 November 2026, 2:30 pm IST/);
      await expectWrites(stub, ASK, 1, "the request for a link", "POST");
      assert.deepEqual(JSON.parse(stub.writesTo(ASK, "POST")[0].body), { email: "ravi@sharma-co.in", firm_name: "Sharma & Associates", full_name: "CA Ravi Sharma" });
      assert.deepEqual(formSeen.filter((r) => /\/auth\/v1\/otp/.test(r)), [], "the browser asked Supabase to mail a sign-in link");
    },
  },
  {
    id: "an-invitation-that-cannot-be-used-says-so-in-words",
    title: "a link the server refuses shows why, in a person's words, and offers Sign in for somebody who already joined",
    async run(env) {
      const { page, stub, base } = env;
      await signedOut(page);
      stub.route({ method: "POST", re: SESSION, ...refuse("Invalid or expired invite.", 404) });
      await page.goto(`${base}/join/?token=tok-dead`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Accept the invitation" }).click();
      await page.getByRole("heading", { name: "This invitation could not be used" }).waitFor();
      assert.match(await page.locator("p[role=alert]").innerText(), /It may have expired, been replaced by a newer one, been withdrawn, or already been accepted/);
      assert.equal(await page.getByRole("link", { name: "Sign in" }).count(), 1);
    },
  },
  {
    id: "a-browser-signed-in-as-somebody-else-is-asked-before-it-is-signed-out",
    title: "signed in as another address, the join page names both and signs out only when asked, then accepts",
    async run(env) {
      const { page, stub, base } = env;
      const seen = recordRequests(page);
      let accepts = 0;
      stub.route({ method: "POST", re: SESSION, reply: () => ok({ token_hash: "th-2", verification_type: "invite", email: "nitin@firm.in" }) });
      // Refused under the other account's session, accepted after switching, refused again as a spent token after that.
      stub.route({ method: "POST", re: ACCEPT,
        reply: () => (accepts += 1) === 2 ? ok({ firm_id: "f", role: "Executive", full_name: "Nitin Invited" })
                                          : { detail: "Invalid or expired invite." },
        status: () => accepts === 2 ? 200 : 404 });
      await page.goto(`${base}/join/?token=tok-live`, { waitUntil: "networkidle" });
      const ask = page.locator("[data-join-other-account]");
      await ask.waitFor();
      const text = await ask.innerText();
      assert.match(text, new RegExp(`signed in as ${FAKE_USER.email.replace(/[.]/g, "\\.")}`));
      assert.match(text, /The invitation is for nitin@firm\.in/);
      assert.equal(seen.filter((r) => /\/auth\/v1\/(verify|logout)/.test(r)).length, 0, "the browser was signed out before anybody asked");

      await ask.getByRole("button", { name: "Sign out and join as nitin@firm.in" }).click();
      await page.getByRole("heading", { name: /Welcome to the team, Nitin Invited/ }).waitFor();
      assert.ok(seen.some((r) => /\/auth\/v1\/logout/.test(r)), "the other account was never signed out");
      assert.ok(seen.some((r) => /^POST .*\/auth\/v1\/verify/.test(r)));
      // Whose invitation this is was asked WITHOUT opening a sign-in (merely looking creates nothing at Supabase); the
      // sign-in was opened only after the sign-out.
      await expectWrites(stub, SESSION, 2, "the address and then the sign-in", "POST");
      const [asked, opened] = stub.writesTo(SESSION, "POST").map((w) => JSON.parse(w.body));
      assert.deepEqual(asked, { token: "tok-live", open_sign_in: false });
      assert.deepEqual(opened, { token: "tok-live" });
      // One accept refused under the other account's session, and one after switching: never a third from a remount.
      await expectWrites(stub, ACCEPT, 2, "the two accepts", "POST");
    },
  },
  {
    id: "an-address-that-already-has-a-sign-in-is-told-to-sign-in-first",
    title: "the server's refusal for an address that already signs in is shown in its words, and nobody is signed in",
    async run(env) {
      const { page, stub, base } = env;
      await signedOut(page);
      const seen = recordRequests(page);
      const sentence = "This email address already has a PracticeSync sign-in. Sign in with it the way you usually do, then open this invitation's link again to join.";
      stub.route({ method: "POST", re: SESSION, ...refuse(sentence, 409) });
      await page.goto(`${base}/join/?token=tok-live`, { waitUntil: "networkidle" });
      await page.getByRole("button", { name: "Accept the invitation" }).click();
      await page.locator("p[role=alert]").getByText(sentence).waitFor();
      assert.equal(seen.filter((r) => /\/auth\/v1\/verify/.test(r)).length, 0, "somebody was signed in");
      assert.equal(stub.writesTo(ACCEPT, "POST").length, 0);
    },
  },
  {
    id: "a-sign-in-that-already-belongs-to-a-practice-is-told-so-and-is-not-offered-another",
    title: "signed in as the invited address, an accept the server refuses in words shows those words and opens no sign-in",
    async run(env) {
      const { page, stub, base } = env;
      const sentence = "This sign-in already belongs to a member of a practice on PracticeSync, and one sign-in can belong to one practice. Ask the practice that invited you to send the invitation to another email address.";
      stub.route({ method: "POST", re: ACCEPT, ...refuse(sentence, 409) });
      await page.goto(`${base}/join/?token=tok-live`, { waitUntil: "networkidle" });
      await page.locator("p[role=alert]").getByText(sentence).waitFor();
      assert.equal(stub.writesTo(SESSION, "POST").length, 0, "a sign-in was opened for somebody already signed in");
    },
  },
];
