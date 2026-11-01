/**
 * Group L: retracting a TDS challan recorded in error, driven in a browser (POST-A-362 and PRE-A-015).
 *
 * The prompt that takes a challan out of the register is a money action on a statutory record, so what a click really does matters:
 * a source guard (`a-challan-is-retracted-with-a-reason-through-the-servers-door.test.ts`) reads that the confirm button is the shared
 * single-click one and that the page hands it the request's promise, and this proves it in Chromium.
 *
 *   1. two clicks on "Retract challan" in the same tick send ONE request, carrying the reason that was typed, and the server's two
 *      sentences about what the retraction did not change (a month of the calendar still reading filed, a statement already filed)
 *      are shown as written, with the challan gone from the list after the register is read again;
 *   2. a refusal the server raised as an HTTP error (`{"detail": "<sentence>"}`, which has no `success` or `error`) is shown in the
 *      prompt in the server's words, the prompt stays open, and the challan is still listed;
 *   3. a person without the write tier sees no Retract button at all, and the screen still lists the challan;
 *   4. a deposit worksheet whose answer is not a worksheet leaves the Challans tab standing and says the worksheet could not be read (the
 *      screen used to be replaced by its error page: the first run of this group found it).
 *
 * And tying a challan to the ledger entry that paid it (POST-A-272):
 *   5. "Match" opens a dialog listing the entries the server offers with its own sentence for each; two same-tick clicks on "Tie to this
 *      entry" send ONE request naming that entry, and the row then reads "Tied to an entry" after the register is read again;
 *   6. a refusal (the entry does not debit the right account) is shown in the dialog in the server's words, the dialog stays open and
 *      the challan stays untied;
 *   7. a person who can read but not edit sees the entries and no button to tie one;
 *   8. a tied challan's dialog offers "Take the link back", and two same-tick clicks on it send ONE request.
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { pick, sameTickDouble, expectWrites, until } from "../kit.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "tds-challans";

const CHALLAN = {
  id: "ch-1", client_id: CLIENT_ROW.id, bsr_code: "0510001", challan_no: "00045", payment_date: "2026-07-05",
  total_paise: 1_250_000, tds_paise: 1_250_000, surcharge_paise: 0, interest_paise: 0, penalty_paise: 0, minor_head: "200",
  financial_year: "2026-27", quarter: "Q1", section: "194C", status: "deposited",
};

const CALENDAR_NOTE = "The compliance calendar still shows the monthly TDS deposit (non-salary) for April 2026 as filed. Retracting the challan does not reopen it.";
const STATEMENT_NOTE = "The TDS statement for this quarter is recorded as filed. Retracting a challan changes the register and does not change a statement already filed.";
const RETRACT_ROUTE = /tds-workspace\/challans\/ch-1\/retract$/;
const CANDIDATES_ROUTE = /tds-workspace\/challans\/ch-1\/ledger-candidates$/;
const LINK_ROUTE = /tds-workspace\/challans\/ch-1\/link-payment$/;
const UNLINK_ROUTE = /tds-workspace\/challans\/ch-1\/unlink-payment$/;
const ENTRY = {
  journal_entry_id: "0b5a1c2e-0000-4000-8000-000000000001", entry_date: "2026-07-05", reference_no: "JNL-0042", narration: "TDS paid, challan 00045",
  liability_debit_paise: 1_250_000, entry_total_paise: 1_250_000, days_apart: 0, grade: "exact",
  reason: "₹12,500.00 left the bank, dated the same day.",
};
const CANDIDATES = { challan_id: "ch-1", account_name: "TDS Payable", window_days: 7, journal_entry_id: null, candidates: [ENTRY], gap: null };

/** The screen with one challan listed, for a person holding `actions` on tds; opens the Challans tab. */
async function atTheChallans(env, actions, { listAfter = null, challan = CHALLAN, rows = null } = {}) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { tds: actions } }) });
  let retracted = false;
  stub.route({
    method: "GET", re: /tds-workspace\/challans\?/,
    reply: () => ok({ challans: rows ? rows() : retracted && listAfter ? listAfter : [challan], has_more: false, limit: 500, max_limit: 500 }),
  });
  await page.goto(`${env.base}/tds/`, { waitUntil: "networkidle" });
  await pick(page, page.locator('button:has-text("Select client")').first(), CLIENT_ROW.client_name);
  await page.getByRole("button", { name: "Challans", exact: true }).click();
  await page.getByText("00045").waitFor();
  return { markRetracted: () => { retracted = true; } };
}

const text = (page) => page.locator("body").innerText();

export const scenarios = [
  {
    id: "two-clicks-on-retract-challan-send-one-request-and-show-the-servers-notes",
    title: "a same-tick double click on Retract challan sends one request with the typed reason, shows both of the server's notes, and the challan leaves the list",
    async run(env) {
      const { page, stub } = env;
      const screen = await atTheChallans(env, ["read", "compute", "write"], { listAfter: [] });
      stub.route({
        method: "POST", re: RETRACT_ROUTE,
        reply: () => {
          screen.markRetracted();
          return ok({ retracted: "ch-1", challan_no: "00045", payment_date: "2026-07-05", total_paise: 1_250_000,
                      calendar_note: CALENDAR_NOTE, statement_note: STATEMENT_NOTE });
        },
      });

      await page.getByRole("button", { name: /^Retract challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      const confirm = dialog.getByRole("button", { name: "Retract challan", exact: true });
      assert.equal(await confirm.isDisabled(), true, "the confirm button was live with no reason typed");
      await dialog.getByLabel("Why is it being retracted?").fill("Keyed under the wrong quarter");
      assert.equal(await confirm.isDisabled(), false, "the confirm button stayed disabled with a reason typed");

      await sameTickDouble(confirm);

      await expectWrites(stub, RETRACT_ROUTE, 1, "two same-tick clicks on Retract challan");
      const [write] = stub.writesTo(RETRACT_ROUTE);
      assert.deepEqual(JSON.parse(write.body), { reason: "Keyed under the wrong quarter" }, "the typed reason was not what was sent");
      await page.getByText(CALENDAR_NOTE).waitFor();
      const body = await text(page);
      assert.ok(body.includes(STATEMENT_NOTE), "the statement note was not shown as the server wrote it");
      assert.match(body, /Challan retracted\. What happened to the calendar and to a filed statement:/);
      await until(async () => !(await text(page)).includes("00045"), "the retracted challan to leave the list");
      assert.equal(await page.getByRole("dialog").count(), 0, "the prompt stayed open after a retraction");
    },
  },
  {
    id: "a-refusal-raised-as-an-http-error-is-shown-in-the-prompt-in-the-servers-words",
    title: "a refusal that arrives as a FastAPI detail (a locked year) is shown in the prompt as written, the prompt stays open and the challan stays listed",
    async run(env) {
      const { page, stub } = env;
      const LOCKED = "The financial year 2026-27 is locked, so a challan dated in it cannot be retracted. Ask a Partner to unlock it first.";
      await atTheChallans(env, ["read", "compute", "write"]);
      stub.route({ method: "POST", re: RETRACT_ROUTE, ...refuse(LOCKED, 422) });

      await page.getByRole("button", { name: /^Retract challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByLabel("Why is it being retracted?").fill("Wrong quarter");
      await dialog.getByRole("button", { name: "Retract challan", exact: true }).click();

      await dialog.getByRole("alert").filter({ hasText: LOCKED }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the prompt closed on a refusal");
      assert.ok((await text(page)).includes("00045"), "a refused retraction took the challan out of the list");
      // The person can try again: the guard is released when the request settles, on a refusal as on a success.
      assert.equal(await dialog.getByRole("button", { name: "Retract challan", exact: true }).isDisabled(), false,
        "the confirm button stayed held after a refusal");
    },
  },
  {
    id: "a-worksheet-answer-that-is-not-a-worksheet-does-not-take-the-screen-down",
    title: "when the deposit worksheet's answer is not a worksheet, the Challans tab still lists the challan and says the worksheet could not be read",
    async run(env) {
      const { page, stub } = env;
      // Found by driving this tab: the stub's default answer to a read is a list, and the panel read `.length` of a field a list does not
      // have, so the whole screen was replaced by "TDS could not be displayed". The same happens to a deploy that is behind the screen.
      stub.route({ method: "GET", re: /tds-workspace\/deposit-due\?/, reply: () => ok([]) });
      await atTheChallans(env, ["read", "compute", "write"]);
      await page.getByText("The deposit worksheet came back in a shape this screen cannot read.").waitFor();
      assert.ok((await text(page)).includes("00045"), "the challan was not listed beside a worksheet that could not be read");
      assert.doesNotMatch(await text(page), /TDS could not be displayed/, "the screen was replaced by its error page");
    },
  },
  {
    id: "without-the-write-tier-there-is-no-retract-button",
    title: "a person who can record a challan but not remove one sees the challan and no Retract button",
    async run(env) {
      const { page } = env;
      await atTheChallans(env, ["read", "compute"]);
      assert.equal(await page.getByRole("button", { name: /^Retract challan/ }).count(), 0, "a Retract button was offered without tds.write");
      assert.ok((await text(page)).includes("00045"), "the challan was not listed");
    },
  },
  // ── tying a challan to the ledger entry that paid it (POST-A-272) ─────────────────────────────────────────────────────────
  {
    id: "two-clicks-on-tie-to-this-entry-send-one-request-and-the-row-reads-tied",
    title: "Match lists the entries the server offers with its sentence for each; a same-tick double click on Tie to this entry sends one request naming it, and the row then reads Tied to an entry",
    async run(env) {
      const { page, stub } = env;
      let tied = false;
      stub.route({ method: "GET", re: CANDIDATES_ROUTE, reply: () => ok(CANDIDATES) });
      stub.route({ method: "POST", re: LINK_ROUTE, reply: () => { tied = true; return ok({ challan_id: "ch-1", journal_entry_id: ENTRY.journal_entry_id }); } });
      await atTheChallans(env, ["read", "compute", "write"], { rows: () => [tied ? { ...CHALLAN, journal_entry_id: ENTRY.journal_entry_id } : CHALLAN] });
      assert.match(await text(page), /Not tied/, "an untied challan did not say so");

      await page.getByRole("button", { name: /^Match challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText(ENTRY.reason).waitFor();
      assert.match(await dialog.innerText(), /posts nothing/, "the dialog did not say it posts nothing");
      const tie = dialog.getByRole("button", { name: /^Tie the challan to the entry of/ });

      await sameTickDouble(tie);

      await expectWrites(stub, LINK_ROUTE, 1, "two same-tick clicks on Tie to this entry");
      const [write] = stub.writesTo(LINK_ROUTE);
      assert.deepEqual(JSON.parse(write.body), { journal_entry_id: ENTRY.journal_entry_id }, "the entry chosen was not what was sent");
      await until(async () => (await text(page)).includes("Tied to an entry"), "the row to read Tied to an entry");
      assert.equal(await page.getByRole("dialog").count(), 0, "the dialog stayed open after the link was made");
    },
  },
  {
    id: "a-refusal-to-tie-is-shown-in-the-dialog-in-the-servers-words",
    title: "a refusal (the entry does not debit TDS Payable) is shown in the dialog as written, the dialog stays open and the challan stays untied",
    async run(env) {
      const { page, stub } = env;
      const WRONG = 'That entry does not debit "TDS Payable", so it cannot be the payment of this challan.';
      stub.route({ method: "GET", re: CANDIDATES_ROUTE, reply: () => ok(CANDIDATES) });
      stub.route({ method: "POST", re: LINK_ROUTE, ...refuse(WRONG, 422) });
      await atTheChallans(env, ["read", "compute", "write"]);

      await page.getByRole("button", { name: /^Match challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByRole("button", { name: /^Tie the challan to the entry of/ }).click();
      await dialog.getByRole("alert").filter({ hasText: WRONG }).waitFor();
      assert.equal(await page.getByRole("dialog").count(), 1, "the dialog closed on a refusal");
      assert.match(await text(page), /Not tied/, "a refused link changed the row");
      assert.equal(await dialog.getByRole("button", { name: /^Tie the challan to the entry of/ }).isDisabled(), false,
        "the button stayed held after a refusal");
    },
  },
  {
    id: "without-the-edit-tier-the-entries-are-shown-and-nothing-can-be-tied",
    title: "a person without tds.compute sees the entries the server offers and no button to tie one",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: CANDIDATES_ROUTE, reply: () => ok(CANDIDATES) });
      await atTheChallans(env, ["read"]);
      await page.getByRole("button", { name: /^Match challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText(ENTRY.reason).waitFor();
      assert.equal(await dialog.getByRole("button", { name: /^Tie the challan/ }).count(), 0, "a tie button was offered without tds.compute");
    },
  },
  {
    id: "two-clicks-on-take-the-link-back-send-one-request",
    title: "a tied challan's dialog offers Take the link back, and a same-tick double click on it sends one request",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "GET", re: CANDIDATES_ROUTE, reply: () => ok({ ...CANDIDATES, journal_entry_id: ENTRY.journal_entry_id, candidates: [] }) });
      stub.route({ method: "POST", re: UNLINK_ROUTE, reply: () => ok({ challan_id: "ch-1", journal_entry_id: null, was: ENTRY.journal_entry_id }) });
      await atTheChallans(env, ["read", "compute", "write"], { challan: { ...CHALLAN, journal_entry_id: ENTRY.journal_entry_id } });
      assert.match(await text(page), /Tied to an entry/, "a tied challan did not say so");

      await page.getByRole("button", { name: /^Open the ledger link of challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText("This challan is tied to a ledger entry.").waitFor();
      await sameTickDouble(dialog.getByRole("button", { name: "Take the link back", exact: true }));
      await expectWrites(stub, UNLINK_ROUTE, 1, "two same-tick clicks on Take the link back");
    },
  },
  {
    id: "a-challan-tied-to-a-reversed-entry-says-so-in-the-column-and-the-dialog",
    title: "a challan tied to an entry that was reversed reads as such in the Ledger column, and its dialog shows the server's note and still offers Take the link back",
    async run(env) {
      const { page, stub } = env;
      const link = {
        state: "reversed", label: "Tied to an entry that was reversed",
        note: "The ledger entry this challan is tied to was reversed, so it no longer records the payment. Take the link back and tie the challan to the entry that now records the payment, if there is one.",
      };
      stub.route({ method: "GET", re: CANDIDATES_ROUTE,
        reply: () => ok({ ...CANDIDATES, journal_entry_id: ENTRY.journal_entry_id, ledger_link: link, candidates: [] }) });
      await atTheChallans(env, ["read", "compute", "write"],
        { challan: { ...CHALLAN, journal_entry_id: ENTRY.journal_entry_id, ledger_link: link } });
      const body = await text(page);
      assert.match(body, /Tied to an entry that was reversed/, "the column did not say the entry was reversed");
      assert.doesNotMatch(body, /Tied to an entry(?! that)/, "the column still said plainly tied");

      await page.getByRole("button", { name: /^Open the ledger link of challan 00045/ }).click();
      const dialog = page.getByRole("dialog");
      await dialog.getByText(link.note).waitFor();
      assert.equal(await dialog.getByRole("button", { name: "Take the link back", exact: true }).count(), 1, "the way out was not offered");
    },
  },
];
