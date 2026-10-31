/**
 * Group M: reopening a recorded deposit on the Deadlines screen, driven in a browser (POST-A-267 item 3 and PRE-A-015).
 *
 * The prompt that takes a filing back off the compliance calendar is a write on a statutory record. A source guard
 * (`a-recorded-deposit-is-reopened-with-the-servers-rule.test.ts`) reads that the confirm button is the shared single-click one, that
 * Reopen is offered only for the types the SERVER served and only to a person holding compliance.approve, and that the rows are read
 * again afterwards; this proves what a click really does in Chromium:
 *
 *   1. two clicks on the prompt's Reopen in the same tick send ONE request carrying the typed reason; the server's sentence is shown as
 *      written, the prompt closes and the row is read again (it no longer reads Filed);
 *   2. a refusal the server raised as an HTTP error is shown in the prompt in the server's words and the prompt stays open;
 *   3. a filed obligation of a type the server did not serve, or for a person without compliance.approve, has no Reopen button.
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "reopen";

const OBLIGATION = {
  id: "ob-1", client_id: CLIENT_ROW.id, compliance_type: "TDS", obligation_type: "TDS_NON_SALARY_DEPOSIT", status: "Filed",
  period_start: "2026-07-01", period_end: "2026-07-31", due_date: "2026-08-07", filed_date: "2026-08-05", acknowledgement_no: null,
  notes: null, period_label: "TDS deposit July 2026",
};
const REOPEN_ROUTE = /compliance\/obligations\/ob-1\/reopen$/;
const ANSWER = "Reopened. The challan that closed it is still in the TDS register: retract it on the Challans tab first if it was recorded in error. It is back at Ready To File.";

/** Deadlines with one filed obligation, for a person holding `approve` or not, and a server that serves `types` as reopenable. */
async function atDeadlines(env, { canApprove = true, types = ["TDS_NON_SALARY_DEPOSIT"], afterReopen = null } = {}) {
  const { page, stub } = env;
  stub.route({
    method: "GET", re: /identity\/permissions$/,
    reply: () => ok({ role: "Partner", permissions: { compliance: canApprove ? ["read", "write", "approve"] : ["read", "write"] } }),
  });
  stub.route({ method: "GET", re: /compliance\/reopenable-types$/, reply: () => ok({ obligation_types: types, max_reason_chars: 500 }) });
  let reopened = false;
  stub.route({
    method: "GET", re: /compliance\/obligations(\?|$)/,
    reply: () => ok({ obligations: [reopened && afterReopen ? afterReopen : OBLIGATION], total: 1 }),
  });
  await page.goto(`${env.base}/deadlines/`, { waitUntil: "networkidle" });
  await page.getByText("Open Client").first().waitFor();
  return { markReopened: () => { reopened = true; } };
}

const text = (page) => page.locator("body").innerText();

export const scenarios = [
  {
    id: "two-clicks-on-reopen-send-one-request-and-show-the-servers-sentence",
    title: "a same-tick double click on the prompt's Reopen sends one request with the typed reason, shows the server's sentence and reads the rows again",
    async run(env) {
      const { page, stub } = env;
      const screen = await atDeadlines(env, { afterReopen: { ...OBLIGATION, status: "Ready To File", filed_date: null } });
      stub.route({
        method: "POST", re: REOPEN_ROUTE,
        reply: () => { screen.markReopened(); return ok({ id: "ob-1", status: "Ready To File", message: ANSWER }); },
      });

      await page.getByRole("button", { name: "Reopen", exact: true }).click();
      const dialog = page.getByRole("dialog");
      const confirm = dialog.getByRole("button", { name: "Reopen", exact: true });
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with no reason typed");
      await dialog.getByLabel("Why is it being reopened?").fill("Entered against the wrong month");

      await sameTickDouble(confirm);

      await expectWrites(stub, REOPEN_ROUTE, 1, "two same-tick clicks on Reopen");
      const [write] = stub.writesTo(REOPEN_ROUTE);
      assert.deepEqual(JSON.parse(write.body), { reason: "Entered against the wrong month" }, "the typed reason was not what was sent");
      // The toast is drawn once and announced once (a live region repeats it), so the sentence is on the page twice by design.
      await page.getByLabel("Notifications (F8)").getByText(ANSWER).waitFor();
      await until(async () => (await page.getByRole("dialog").count()) === 0, "the prompt to close after a reopen");
      await until(async () => (await page.getByRole("button", { name: "Reopen", exact: true }).count()) === 0,
        "the row to be read again and no longer read Filed");
    },
  },
  {
    id: "a-refusal-to-reopen-is-shown-in-the-prompt-in-the-servers-words",
    title: "a refusal that arrives as a FastAPI detail is shown in the prompt as written, and the prompt stays open for another try",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "Only a deposit that was recorded as filed can be reopened, and this one is not filed any more.";
      await atDeadlines(env);
      stub.route({ method: "POST", re: REOPEN_ROUTE, ...refuse(REFUSED, 422) });

      await page.getByRole("button", { name: "Reopen", exact: true }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Why is it being reopened?").fill("Wrong month");
      await dialog.getByRole("button", { name: "Reopen", exact: true }).click();

      await dialog.getByRole("alert").filter({ hasText: REFUSED }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the prompt closed on a refusal");
      assert.equal(await dialog.getByRole("button", { name: "Reopen", exact: true }).isDisabled(), false, "the confirm button stayed held after a refusal");
    },
  },
  {
    id: "reopen-is-offered-only-for-a-served-type-and-to-compliance-approve",
    title: "a filed obligation of a type the server did not serve, or seen by a person without compliance.approve, has no Reopen button",
    async run(env) {
      const { page } = env;
      await atDeadlines(env, { types: ["ESI_DEPOSIT"] });
      assert.equal(await page.getByRole("button", { name: "Reopen", exact: true }).count(), 0, "Reopen was offered for a type the server did not serve");
    },
  },
  {
    id: "reopen-is-not-offered-without-compliance-approve",
    title: "a person who can work the calendar but not approve sees the filed obligation and no Reopen button",
    async run(env) {
      const { page } = env;
      await atDeadlines(env, { canApprove: false });
      assert.equal(await page.getByRole("button", { name: "Reopen", exact: true }).count(), 0, "Reopen was offered without compliance.approve");
      assert.ok((await text(page)).includes("Open Client"), "the obligation was not listed");
    },
  },
];
