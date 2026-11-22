/**
 * A JOURNAL ENTRY'S REFERENCE IS CHANGED AND NEVER REMOVED (POST-A-399), driven in a browser.
 *
 * Every manual journal carries a reference (one is given when none is typed, and it is part of what stops a voucher being posted
 * twice). The editor used to send an emptied Reference box as null, which the server reads as "not sent": the old reference
 * stayed and the screen said the entry was corrected.
 *
 * Against a stubbed server, in Chromium, on a saved draft's edit page:
 *
 *   1. the reference emptied and Save Draft pressed: the sentence is shown as an alert, NOTHING is sent, and the page stays;
 *   2. the reference changed and Save Draft pressed: ONE PATCH carries the new reference, trimmed.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { ACCOUNTS, CLIENT_ID } from "../fixtures.mjs";

export const group = "journal-reference";

const SENTENCE = "A journal entry's reference can be changed but not removed: enter the new reference.";
const [DR, CR] = ACCOUNTS;
const DRAFT = {
  id: "je-draft-1", client_id: CLIENT_ID, entry_date: "2026-06-10", reference_no: "JV/2026/014", narration: "Office rent for June",
  entry_type: "journal", is_posted: false, is_reversed: false, source_type: "manual", status: "draft", editable: true, lock_reason: null,
  total_debit_paise: 2500000, total_credit_paise: 2500000, attachments: [],
  lines: [
    { account_id: DR.id, debit_paise: 2500000, credit_paise: 0, narration: "" },
    { account_id: CR.id, debit_paise: 0, credit_paise: 2500000, narration: "" },
  ],
};

async function openDraft(env) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: /identity\/permissions$/, reply: () => ok({ role: "Partner", permissions: { accounting: ["read", "write", "approve"] } }) });
  stub.route({ method: "GET", re: /api\/accounting\/journal\/je-draft-1$/, reply: () => ok(DRAFT) });
  stub.route({ method: "PATCH", re: /api\/accounting\/journal\/je-draft-1$/, reply: () => ok(DRAFT) });
  await page.goto(env.at("/accounting/journal/je-draft-1/edit/"), { waitUntil: "networkidle" });
  const reference = page.locator("#je-ref");
  await reference.waitFor({ timeout: 10000 });
  assert.equal(await reference.inputValue(), "JV/2026/014", "the edit page did not open with the reference on file");
  return reference;
}

const patches = (stub) => stub.writesTo(/api\/accounting\/journal\/je-draft-1$/, "PATCH");

export const scenarios = [
  {
    id: "an-emptied-reference-is-refused-and-nothing-is-sent",
    title: "the reference emptied on a saved draft: Save Draft shows the sentence as an alert, sends nothing, and the page stays",
    async run(env) {
      const { page, stub } = env;
      const reference = await openDraft(env);
      await reference.fill("");
      await page.getByRole("button", { name: "Save Draft" }).click();
      await page.locator("[role=alert]").filter({ hasText: SENTENCE }).first().waitFor({ timeout: 5000 });
      await stub.quiet();
      assert.equal(patches(stub).length, 0, "an emptied reference was sent to the server");
      assert.match(page.url(), /journal\/je-draft-1\/edit/, "the page left although nothing was saved");
      // The button is live again: the refusal is not a stuck save.
      assert.equal(await page.getByRole("button", { name: "Save Draft" }).isDisabled(), false, "Save Draft stayed disabled after the refusal");
    },
  },
  {
    id: "a-changed-reference-is-sent-trimmed",
    title: "the reference changed on a saved draft: one PATCH carries the new reference, trimmed",
    async run(env) {
      const { page, stub } = env;
      const reference = await openDraft(env);
      await reference.fill("  JV/2026/015 ");
      await page.getByRole("button", { name: "Save Draft" }).click();
      await stub.quiet();
      const sent = patches(stub);
      assert.equal(sent.length, 1, `expected one PATCH, saw ${sent.length}`);
      assert.equal(JSON.parse(sent[0].body).reference_no, "JV/2026/015");
    },
  },
];
