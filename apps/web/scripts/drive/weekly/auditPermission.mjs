/**
 * THE AUDIT LOG IS READ ON A PERMISSION OF ITS OWN (POST-A-550), driven in a browser.
 *
 * The audit log used to open on the permission that approves in the books, so a Partner who let a Manager approve journals had
 * also given them the log; and the history panel on a journal entry sent its request for everybody and printed the server's
 * refusal in red. Against a stubbed server, in Chromium:
 *
 *   1. a Manager who was GIVEN the approval of journals is still told, at the audit log's address, that it is not part of their
 *      access, and is offered Request access;
 *   2. the same Manager given the audit log's own permission reads the log;
 *   3. on a journal entry, a Manager opens History and is told it is part of the audit log, with Request access, and NO request
 *      for the history is sent;
 *   4. a Partner opens History and the one record's history is asked for and shown.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { ok } from "../stub.mjs";
import { ACCOUNTS, CLIENT_ID } from "../fixtures.mjs";

export const group = "audit-permission";

const LOG = /\/api\/audit(\?|$)/;
const HISTORY = /\/api\/audit\/entity\//;
const MINE = /\/api\/approvals\/access-requests\/mine$/;
const [DR, CR] = ACCOUNTS;
const ENTRY = {
  id: "je-posted-1", client_id: CLIENT_ID, entry_date: "2026-06-10", reference_no: "JV/2026/014", narration: "Office rent for June",
  entry_type: "journal", is_posted: true, is_reversed: false, source_type: "manual", status: "posted", editable: true, lock_reason: null,
  total_debit_paise: 2500000, total_credit_paise: 2500000, attachments: [],
  lines: [
    { account_id: DR.id, debit_paise: 2500000, credit_paise: 0, narration: "" },
    { account_id: CR.id, debit_paise: 0, credit_paise: 2500000, narration: "" },
  ],
};
const CHANGE = {
  id: "al-1", entity_type: "journal_entry", entity_id: "je-posted-1", action: "update", actor_email: "partner@firm.test",
  created_at: "2026-06-11T06:30:00+00:00", old_data: { narration: "Office rent" }, new_data: { narration: "Office rent for June" },
};

function reads(env) {
  const asked = { log: 0, history: 0 };
  env.stub.route({ method: "GET", re: MINE, reply: () => ok({ requests: [] }) });
  env.stub.route({ method: "GET", re: HISTORY, reply: () => { asked.history += 1; return ok({ entries: [CHANGE], next_cursor: null, has_more: false }); } });
  env.stub.route({ method: "GET", re: LOG, reply: () => { asked.log += 1; return ok({ entries: [CHANGE], next_cursor: null, has_more: false }); } });
  env.stub.route({ method: "GET", re: /api\/accounting\/journal\/je-posted-1$/, reply: () => ok(ENTRY) });
  return asked;
}

const gate = (page, pair) => page.locator(`[data-tick-gate="${pair}"]`);

async function openHistory(env) {
  const { page } = env;
  await page.goto(env.at("/accounting/journal/je-posted-1/edit/"), { waitUntil: "networkidle" });
  await page.locator("#je-ref").waitFor({ timeout: 10000 });
  await page.getByRole("button", { name: /History/ }).click();
}

export const scenarios = [
  {
    id: "a-manager-who-may-approve-journals-is-still-refused-the-audit-log",
    title: "a Manager given the approval of journals: the audit log's address still says it is not part of their access, and offers Request access",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager", { grant: ["accounting:approve"] });
      const asked = reads(env);
      await page.goto(`${env.base}/settings/audit-log/`, { waitUntil: "networkidle" });
      await gate(page, "audit:read").waitFor({ timeout: 10000 });
      await gate(page, "audit:read").getByRole("button", { name: /Request access/ }).waitFor();
      assert.equal(asked.log, 0, "the log was asked for by somebody the screen had refused");
    },
  },
  {
    id: "a-manager-given-the-audit-logs-own-permission-reads-it",
    title: "the same Manager given the audit log's own permission opens the log and it is read",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Manager", { grant: ["audit:read"] });
      const asked = reads(env);
      await page.goto(`${env.base}/settings/audit-log/`, { waitUntil: "networkidle" });
      await page.getByText("partner@firm.test").first().waitFor({ timeout: 10000 });
      assert.equal(await gate(page, "audit:read").count(), 0, "the gate is still drawn for somebody who holds the permission");
      assert.ok(asked.log >= 1, "the log was not asked for");
    },
  },
  {
    id: "the-history-of-an-entry-is-not-asked-for-by-somebody-without-the-permission",
    title: "a Manager opens History on a journal entry: one sentence, Request access, and no request for the history",
    async run(env) {
      const { page, stub } = env;
      stub.signInAs("Manager", { grant: ["accounting:approve"] });
      const asked = reads(env);
      await openHistory(env);
      const told = page.locator("[data-history-not-in-access]");
      await told.waitFor({ timeout: 5000 });
      assert.match(await told.innerText(), /part of the audit log, which is not part of your access/);
      await told.getByRole("button", { name: /Request access/ }).waitFor();
      await stub.quiet();
      assert.equal(asked.history, 0, "the history was requested by somebody who may not read the audit log");
      assert.equal(await page.locator("[role=alert]").filter({ hasText: /history|log/i }).count(), 0, "a refusal is printed as an error");
    },
  },
  {
    id: "a-partner-opens-the-history-of-an-entry",
    title: "a Partner opens History on a journal entry: the one record's history is asked for and shown",
    async run(env) {
      const { page } = env;
      env.stub.signInAs("Partner");
      const asked = reads(env);
      await openHistory(env);
      await page.getByText("partner@firm.test").first().waitFor({ timeout: 10000 });
      assert.equal(asked.history, 1, `expected one request for the history, saw ${asked.history}`);
      assert.equal(await page.locator("[data-history-not-in-access]").count(), 0);
    },
  },
];
