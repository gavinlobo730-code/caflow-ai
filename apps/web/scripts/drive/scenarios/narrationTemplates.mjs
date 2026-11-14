/**
 * A CLIENT'S SAVED NARRATIONS FILL A MANUAL JOURNAL'S NARRATION BOX (POST-A-093), driven in a browser.
 *
 * Against a stubbed server, in Chromium, on a new manual journal of the client:
 *
 *   1. picking a saved narration fills the box with its words, which stay editable (the entry's own save is the editor's and is
 *      unchanged: it sends the words in the box);
 *   2. "Save this narration" sends the box's words for this client, says whether they were new, and a second click in the same tick
 *      sends one request;
 *   3. a narration picked from the list can be removed from it while the box still holds its words, and the server is told which;
 *   4. the server's refusal is shown in its own words;
 *   5. a search that matches none of the client's saved narrations says so, and does not say there are none;
 *   6. a list the server could not read is said as such with Try again, never as "no saved narrations", and Try again reads it.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";

export const group = "narration-templates";

const LIST = /api\/narration-templates\?client_id=/;
const SAVE = /api\/narration-templates$/;
const ARCHIVE = /api\/narration-templates\/nt-2\?client_id=/;
const TEMPLATES = [
  { id: "nt-1", narration: "Being audit fee provided for the year", created_at: "2026-10-01T10:00:00+05:30" },
  { id: "nt-2", narration: "Being salary payable for the month", created_at: "2026-10-02T10:00:00+05:30" },
];

async function atANewJournal(env, list = () => ok(TEMPLATES)) {
  const { page, stub } = env;
  stub.route({ method: "GET", re: LIST, reply: list });
  await page.goto(env.at("/accounting/journal/new/edit/"), { waitUntil: "networkidle" });
  await page.waitForSelector("#je-narration");
  await page.getByTestId("narration-templates").waitFor();
}

const picker = (page) => page.locator('[aria-label="Saved narration"]').first();

async function pickSaved(page, words) {
  await until(async () => !(await picker(page).isDisabled()), "the saved narrations to be read");
  await picker(page).click();
  await page.getByRole("option", { name: words }).click();
}

export const scenarios = [
  {
    id: "picking-a-saved-narration-fills-the-box-and-the-words-stay-editable",
    title: "a picked narration fills the box with its words, which stay editable",
    async run(env) {
      const { page } = env;
      await atANewJournal(env);
      await pickSaved(page, "Being salary payable for the month");
      assert.equal(await page.locator("#je-narration").inputValue(), "Being salary payable for the month");
      await page.locator("#je-narration").fill("Being salary payable for October");
      assert.equal(await page.locator("#je-narration").inputValue(), "Being salary payable for October");
      assert.equal(await page.getByRole("button", { name: "Remove it from the saved narrations" }).count(), 0,
        "the box no longer holds the template's words, so there is nothing of it to remove");
    },
  },
  {
    id: "save-this-narration-sends-the-boxs-words-once-and-says-whether-they-were-new",
    title: "Save this narration: one request for a double click, the client and the words sent, 'Saved' or 'Already saved' said",
    async run(env) {
      const { page, stub } = env;
      const sent = [];
      let created = true;
      stub.route({ method: "POST", re: SAVE, reply: (req, body) => {
        sent.push(JSON.parse(body));
        return ok({ template: { id: "nt-9", narration: "Being rent for the month", created_at: null }, created });
      } });
      await atANewJournal(env);
      await page.locator("#je-narration").fill("Being rent for the month");
      await page.getByRole("button", { name: "Save this narration" }).dblclick();
      await page.getByText("Saved for this client.").waitFor();
      assert.equal(sent.length, 1, `the save was sent ${sent.length} times`);
      assert.deepEqual(sent[0], { client_id: env.clientId, narration: "Being rent for the month" });
      created = false;
      await page.getByRole("button", { name: "Save this narration" }).click();
      await page.getByText("Already saved for this client.").waitFor();
    },
  },
  {
    id: "a-picked-narration-can-be-removed-from-the-list",
    title: "the picked template can be removed while the box holds its words; the server is told which, and the words stay",
    async run(env) {
      const { page, stub } = env;
      const asked = [];
      stub.route({ method: "DELETE", re: ARCHIVE, reply: (req, body, url) => { asked.push(url.pathname); return ok({ id: "nt-2", archived: true }); } });
      await atANewJournal(env);
      await pickSaved(page, "Being salary payable for the month");
      await page.getByRole("button", { name: "Remove it from the saved narrations" }).click();
      await page.getByText("Removed from this client's saved narrations.", { exact: false }).waitFor();
      assert.equal(asked.length, 1, `the removal was sent ${asked.length} times`);
      assert.match(asked[0], /\/api\/narration-templates\/nt-2$/);
      assert.equal(await page.locator("#je-narration").inputValue(), "Being salary payable for the month", "the box lost its words");
    },
  },
  {
    id: "the-servers-refusal-is-said-in-its-own-words",
    title: "a refused save says the server's sentence",
    async run(env) {
      const { page, stub } = env;
      stub.route({ method: "POST", re: SAVE, ...refuse("A narration template is at most 300 characters; this one is 301.") });
      await atANewJournal(env);
      await page.locator("#je-narration").fill("x".repeat(301));
      await page.getByRole("button", { name: "Save this narration" }).click();
      await page.getByRole("alert").filter({ hasText: "at most 300 characters; this one is 301" }).waitFor();
    },
  },
  {
    id: "a-search-that-matches-nothing-says-so-and-does-not-say-there-are-none",
    title: "searching a client's saved narrations for words none of them has says no match, never 'no saved narrations'",
    async run(env) {
      const { page } = env;
      await atANewJournal(env);
      await until(async () => !(await picker(page).isDisabled()), "the saved narrations to be read");
      await picker(page).click();
      await page.getByPlaceholder("Search saved narrations").fill("bonus");
      await page.getByText("No saved narration matches what you typed.").waitFor();
      assert.equal(await page.getByText("No saved narrations for this client yet.").count(), 0);
    },
  },
  {
    id: "a-list-that-could-not-be-read-is-not-an-empty-one",
    title: "the list read fails: it is said with Try again, the picker stays shut, never 'No saved narrations'; Try again reads it",
    async run(env) {
      const { page } = env;
      let fail = true;
      await atANewJournal(env, () => (fail ? { success: false, data: null, error: "The saved narrations could not be read." } : ok(TEMPLATES)));
      await page.getByRole("alert").filter({ hasText: "could not be read" }).waitFor();
      assert.equal(await page.getByText("No saved narrations for this client yet.").count(), 0);
      assert.ok(await picker(page).isDisabled(), "a list that was not read can be opened as if it were empty");
      fail = false;
      await page.getByRole("button", { name: "Try again" }).click();
      await pickSaved(page, "Being audit fee provided for the year");
      assert.equal(await page.locator("#je-narration").inputValue(), "Being audit fee provided for the year");
    },
  },
];
