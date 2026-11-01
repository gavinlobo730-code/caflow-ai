/**
 * Group N: a statutory remittance tied to a ledger entry that no longer records the payment, driven in a browser (POST-A-272 and PRE-A-015).
 *
 * The payroll hand-off panel lists, apart from the paid-but-unmatched remittances, each remittance tied to an entry that was later reversed or
 * deleted, in the server's own words, and takes the link back. A source guard
 * (`a-remittance-tied-to-an-entry-that-stopped-recording-the-payment-says-so-and-can-be-untied.test.ts`) reads that the button is the shared
 * single-click one and that the panel decides no state, and this proves it in Chromium.
 *
 *   1. a stale link is drawn with the server's label and note and, when only stale links exist, the panel is drawn at all; two same-tick clicks on
 *      "Take the link back" send ONE DELETE for that remittance; the lists are read again and the remittance reads as unmatched, with its candidate;
 *   2. a refusal raised as an HTTP error is shown above both lists in the server's words and the link stays listed;
 *   3. a link the server could not read (state unknown) is drawn with its label and note and offers no take-back;
 *   4. an answer without `stale_links` (an older server) draws only the unmatched list.
 */
import assert from "node:assert/strict";
import { ok, refuse } from "../stub.mjs";
import { sameTickDouble, expectWrites, until } from "../kit.mjs";
import { CLIENT_ROW } from "../fixtures.mjs";

export const group = "remittance-stale-link";

const RUN = { id: "run-1", month: "2026-09", status: "paid" };
const REMITTANCE = {
  id: "rem-1", client_id: CLIENT_ROW.id, scheme: "esic", state: null, wage_month: "2026-09", challan_number: "C-77", amount_paise: 1_050_000,
  status: "paid", paid_on: "2026-10-15", journal_entry_id: "je-old",
};
const STALE_NOTE = "The ledger entry this remittance is tied to was reversed, so it no longer records the payment. The remittance stays: it was paid. Take the link back and tie it to the entry that now records the payment, if there is one.";
const stale = (state, label, note, canTake = true) => ({ ...REMITTANCE, ledger_link: { state, label, note, can_take_back: canTake } });
const REVERSED = stale("reversed", "Tied to an entry that was reversed", STALE_NOTE);
const CANDIDATE = { journal_entry_id: "je-new", entry_date: "2026-10-15", reference_no: "PAY/NEW", narration: "ESI paid", liability_debit_paise: 1_050_000,
                    entry_total_paise: 1_050_000, days_apart: 0, grade: "exact", reason: "₹10,500.00 left the bank, dated the same day." };

const RECON = /payroll\/clients\/[^/]+\/remittance-reconciliation$/;
const UNLINK = /payroll\/clients\/[^/]+\/remittances\/rem-1\/payment$/;

async function atTheHandoff(env, reconcile) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { payroll: ["read", "write"] } }) });
  stub.route({ method: "GET", re: /payroll\/runs\?/, reply: () => ok([RUN]) });
  stub.route({ method: "GET", re: RECON, reply: reconcile });
  await page.goto(`${env.base}/clients/${CLIENT_ROW.id}/payroll/?tab=file`, { waitUntil: "networkidle" });
}

const text = (page) => page.locator("body").innerText();

export const scenarios = [
  {
    id: "two-clicks-on-take-the-link-back-send-one-delete-and-the-remittance-is-unmatched-again",
    title: "a stale link is drawn in the server's words, a same-tick double click on Take the link back sends one DELETE, and the remittance is then listed as unmatched with its candidate",
    async run(env) {
      const { page, stub } = env;
      let taken = false;
      await atTheHandoff(env, () => ok({
        client_id: CLIENT_ROW.id, window_days: 14,
        unmatched: taken ? [{ ...REMITTANCE, journal_entry_id: null, candidates: [CANDIDATE] }] : [],
        stale_links: taken ? [] : [REVERSED],
      }));
      stub.route({ method: "DELETE", re: UNLINK, reply: () => { taken = true; return ok({ remittance_id: "rem-1", unlinked: true, was: "je-old" }); } });

      await page.getByText("Tied to an entry that was reversed").first().waitFor();
      const body = await text(page);
      assert.ok(body.includes(STALE_NOTE), "the server's note was not shown as written");
      assert.ok(/Tied to an entry that no longer records the payment \(1\)/.test(body), "the panel was not drawn for a stale link alone");

      await sameTickDouble(page.getByRole("button", { name: "Take the link back" }));
      await expectWrites(stub, UNLINK, 1, "two same-tick clicks on Take the link back", "DELETE");
      await until(async () => (await text(page)).includes("Paid, but not yet matched to a bank payment (1)"), "the remittance to be listed as unmatched");
      assert.ok((await text(page)).includes("The link was taken back."), "the result was not said");
      assert.equal(await page.getByRole("button", { name: "Take the link back" }).count(), 0, "the stale link was still offered after it was taken back");
      await page.getByText("PAY/NEW").first().waitFor();
    },
  },
  {
    id: "a-refusal-is-shown-above-both-lists-and-the-link-stays-listed",
    title: "a refusal that arrives as a FastAPI detail is shown in the server's words, the stale link stays listed and the button is released",
    async run(env) {
      const { page, stub } = env;
      const GONE = "Remittance not found, or it is not tied to a ledger entry.";
      await atTheHandoff(env, () => ok({ client_id: CLIENT_ROW.id, window_days: 14, unmatched: [], stale_links: [REVERSED] }));
      stub.route({ method: "DELETE", re: UNLINK, ...refuse(GONE, 404) });
      await page.getByRole("button", { name: "Take the link back" }).click();
      await page.getByText(GONE).first().waitFor();
      assert.ok((await text(page)).includes("Tied to an entry that was reversed"), "a refused take-back removed the stale link from the list");
      assert.equal(await page.getByRole("button", { name: "Take the link back" }).isDisabled(), false, "the button stayed held after a refusal");
    },
  },
  {
    id: "a-link-the-server-could-not-read-offers-no-take-back",
    title: "a link whose entry could not be checked (unknown) is drawn with the server's label and note and offers no Take the link back",
    async run(env) {
      const { page } = env;
      const unknown = stale("unknown", "Tied to an entry (not checked just now)",
        "The ledger could not be read just now, so whether the entry this remittance is tied to still records the payment is not known.", false);
      await atTheHandoff(env, () => ok({ client_id: CLIENT_ROW.id, window_days: 14, unmatched: [], stale_links: [unknown] }));
      await page.getByText("Tied to an entry (not checked just now)").first().waitFor();
      assert.ok((await text(page)).includes("is not known"), "the server's note was not shown");
      assert.equal(await page.getByRole("button", { name: "Take the link back" }).count(), 0, "a link whose entry could not be read was offered for take-back");
    },
  },
  {
    id: "an-older-server-without-stale-links-draws-only-the-unmatched-list",
    title: "an answer with no stale_links key draws the unmatched list alone and no stale block",
    async run(env) {
      const { page } = env;
      await atTheHandoff(env, () => ok({ client_id: CLIENT_ROW.id, window_days: 14, unmatched: [{ ...REMITTANCE, journal_entry_id: null, candidates: [CANDIDATE] }] }));
      await page.getByText("Paid, but not yet matched to a bank payment (1)").first().waitFor();
      assert.doesNotMatch(await text(page), /no longer records the payment \(/, "a stale block was drawn from an answer that had none");
    },
  },
];
