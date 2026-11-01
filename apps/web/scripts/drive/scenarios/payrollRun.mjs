/**
 * Group S: a payroll run, created and released in a browser (POST-A-123, the payroll-run row of what was still missing).
 *
 * Releasing a run ("Finalise") posts a real, immutable general-ledger journal and creating one computes every slip of the month, so
 * the two buttons are the two places a double click costs most. The source guards hold that both are the shared single-click button
 * and that the page decides none of the server's sentences; this proves it in Chromium, against a stubbed server:
 *
 *   1. "Compute & Draft" pressed twice in one tick sends ONE create, with the month typed; the gaps the server names (a deduction it
 *      could not establish) are shown in the server's own sentences;
 *   2. "Finalise" pressed twice in one tick sends ONE release;
 *   3. a release the server blocks over unresolved gaps shows them and offers the override, which stays held until the reason is long
 *      enough, and "Finalise anyway" pressed twice in one tick sends ONE more release, carrying the reason typed (the first, blocked
 *      one carried none);
 *   4. a plain refusal is shown as the server wrote it and the button is released.
 */
import assert from "node:assert/strict";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "payroll-run";

const RUN = {
  id: "run-1", month: "2026-09", status: "draft", headcount: 3, total_gross_paise: 15_000_000, total_net_paise: 12_000_000,
  total_pf_paise: 0, total_esi_paise: 0, total_tds_paise: 0,
};
const CREATE = /api\/payroll\/runs$/;
const FINALIZE = /api\/payroll\/runs\/run-1\/finalize$/;

async function atTheRuns(env, { runs = [RUN] } = {}) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /payroll\/runs\?/, reply: () => ok(runs) });
  await page.goto(env.at("/payroll/?tab=register"), { waitUntil: "networkidle" });
  await page.getByText("Create New Run").waitFor();
}

const finalised = (stub) => stub.writesTo(FINALIZE, "POST").map((w) => JSON.parse(w.body || "{}"));

export const scenarios = [
  {
    id: "two-clicks-on-compute-and-draft-send-one-create-and-show-the-gaps-as-the-server-said",
    title: "Compute & Draft pressed twice in one tick sends ONE create with the month typed, and the server's gap sentences are shown",
    async run(env) {
      const { page, stub } = env;
      const GAPS = ["Attendance for Asha Rao is missing for 3 days of September.", "Professional tax for Karnataka is not modelled, so none was deducted."];
      stub.route({ method: "POST", re: CREATE, reply: () => ok({ id: "run-2", attendance_gaps: [GAPS[0]], statutory_gaps: [GAPS[1]] }) });
      await atTheRuns(env, { runs: [] });
      await page.locator('input[type="month"]').fill("2026-09");
      await sameTickDouble(page.getByRole("button", { name: /Compute & Draft/ }));
      await expectWrites(stub, CREATE, 1, "two same-tick clicks on Compute & Draft", "POST");
      const [body] = stub.writesTo(CREATE, "POST").map((w) => JSON.parse(w.body));
      assert.strictEqual(body.month, "2026-09", `the month sent was ${body.month}`);
      await page.getByText(GAPS[0]).waitFor();
      await page.getByText(GAPS[1]).waitFor();
      assert.ok(await page.getByText(/2 things could not be established/).isVisible(), "the count of gaps was not said");
    },
  },
  {
    id: "two-clicks-on-finalise-send-one-release",
    title: "Finalise pressed twice in one tick sends ONE release (it posts an immutable journal)",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: FINALIZE, reply: () => ok({ id: "run-1", status: "finalized" }) });
      await atTheRuns(env);
      await sameTickDouble(page.getByRole("button", { name: "Finalise", exact: true }));
      await expectWrites(stub, FINALIZE, 1, "two same-tick clicks on Finalise", "POST");
      assert.deepStrictEqual(finalised(stub)[0], {}, "a release with nothing to override sent a reason");
    },
  },
  {
    id: "a-blocked-release-offers-the-override-which-is-held-until-the-reason-is-long-enough-and-goes-once",
    title: "gaps block the release and are listed; the override waits for a 20-character reason; Finalise anyway pressed twice sends ONE release carrying it",
    async run(env) {
      const { page, stub } = env;
      const GAP = "Attendance for Asha Rao is missing for 3 days of September.";
      stub.route({ method: "POST", re: FINALIZE, ...refuse({ message: "This run has gaps that were not resolved.", gaps: [GAP] }, 409) });
      await atTheRuns(env);
      await page.getByRole("button", { name: "Finalise", exact: true }).click();
      await page.getByText(GAP).waitFor();
      const anyway = page.getByRole("button", { name: "Finalise anyway" });
      assert.ok(await anyway.isDisabled(), "the override was offered with no reason");

      const box = page.getByPlaceholder(/Client confirmed by email/);
      await box.fill("too short");
      assert.ok(await anyway.isDisabled(), "the override was offered on a reason shorter than the minimum");
      await box.fill("Client confirmed by email on the 3rd that nobody was on leave.");
      assert.strictEqual(await anyway.isDisabled(), false, "the override stayed held on a long enough reason");

      stub.route({ method: "POST", re: FINALIZE, reply: () => ok({ id: "run-1", status: "finalized", data: { overridden_gaps: [GAP] } }) });
      await sameTickDouble(anyway);
      await until(() => finalised(stub).length >= 2, "the override release to arrive");
      await expectWrites(stub, FINALIZE, 2, "the blocked release and the override (one each)", "POST");
      const [first, second] = finalised(stub);
      assert.deepStrictEqual(first, {}, "the first, blocked release carried a reason");
      assert.strictEqual(second.override_reason, "Client confirmed by email on the 3rd that nobody was on leave.");
    },
  },
  {
    id: "a-plain-refusal-of-a-release-is-shown-and-the-button-is-released",
    title: "a refusal that is a sentence is shown as the server wrote it and Finalise can be pressed again",
    async run(env) {
      const { page, stub } = env;
      const REFUSED = "This run has no payslips to release.";
      stub.route({ method: "POST", re: FINALIZE, ...refuse(REFUSED, 422) });
      await atTheRuns(env);
      await page.getByRole("button", { name: "Finalise", exact: true }).click();
      await page.getByText(REFUSED).waitFor();
      assert.strictEqual(await page.getByRole("button", { name: "Finalise", exact: true }).isDisabled(), false, "Finalise stayed held after a refusal");
      await expectWrites(stub, FINALIZE, 1, "the refused release", "POST");
    },
  },
];
