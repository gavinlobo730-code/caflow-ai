/**
 * "WHERE IS…?": A PERSON ASKS WHERE SOMETHING IS AND IS SHOWN THE SCREEN (POST-A-538), driven in a browser.
 *
 * Against a stubbed server, in Chromium:
 *
 *   1. the button on the bar opens the box; the box says who reads the question and that it leaves India before anything is
 *      sent; the request carries the question and the ids of the screens the person is offered, and nothing else; the answer
 *      is drawn in the product's own words, an id the product does not have is not drawn, a client's screen with no client
 *      open offers the client list, and "Open" goes to the screen and closes the box;
 *   2. when the AI cannot be asked the same box does a plain search, says that it did and why, and still opens a screen;
 *   3. a Manager's request offers no screen of My practice, and an answer naming one is not drawn;
 *   4. when the AI finds nothing the box says no screen matches and points at PracticeSync AI for a question about tax.
 *
 * No scenario has a date of its own, so none has a zone.
 */
import assert from "node:assert/strict";
import { until } from "../kit.mjs";
import { ok, refuse } from "../stub.mjs";
import { FAKE_USERS_ROW } from "../fixtures.mjs";

export const group = "where-is";

const WHERE = /\/api\/guide\/where$/;
const box = (page) => page.locator("[data-where-is]");
const answer = (page) => page.locator("[data-where-is-answer]");

/** The server's side of the guide: it answers with `ids` and keeps what it was asked. */
function guideAnswers(env, ids) {
  const asked = [];
  env.stub.route({ method: "POST", re: WHERE, reply: (_req, body) => { asked.push(JSON.parse(body)); return ok({ screens: ids }); } });
  return asked;
}

async function ask(page, question) {
  await page.locator("[data-guide-open]").click();
  await box(page).waitFor();
  await box(page).getByLabel("What are you looking for?").fill(question);
  await box(page).getByRole("button", { name: /Find it/ }).click();
}

export const scenarios = [
  {
    id: "the-guide-shows-the-screen-and-a-button-that-opens-it",
    title: "the box says who reads the question; the request is the question and the offered screens; the answer is the product's words and Open goes there",
    async run(env) {
      const { page } = env;
      const asked = guideAnswers(env, ["client:compliance/tds", "firm:/made-up", "firm:/tds"]);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await page.locator("[data-guide-open]").click();
      await box(page).waitFor();
      // Before anything is sent: who reads it, and that it leaves India. The input is described by that sentence.
      const notice = page.locator('[data-ai-surface="guide"]');
      assert.match(await notice.innerText(), /Groq, an AI provider outside India/);
      const input = box(page).getByLabel("What are you looking for?");
      assert.equal(await input.getAttribute("aria-describedby"), await notice.getAttribute("id"));
      assert.equal(asked.length, 0, "the question was sent before the person asked");

      await input.fill("where do I record a TDS challan?");
      await input.press("Enter");
      await until(async () => (await answer(page).getAttribute("data-where-is-answer")) === "ai", "the answer");
      assert.equal(asked.length, 1);
      assert.deepEqual(Object.keys(asked[0]).sort(), ["offered", "question"]);
      assert.equal(asked[0].question, "where do I record a TDS challan?");
      assert.ok(asked[0].offered.length > 100 && asked[0].offered.includes("firm:/practice/billing"), "a Partner's request does not offer the practice's screens");
      assert.ok(asked[0].offered.every((id) => /^(firm|client):/.test(id)));

      const rows = answer(page).locator("li");
      assert.equal(await rows.count(), 2, "an id that is not a screen of the product was drawn");
      assert.match(await rows.nth(0).innerText(), /TDS compliance[\s\S]*inside a client’s workspace[\s\S]*Open a client first/);
      assert.equal(await rows.nth(0).getByRole("link", { name: /Choose a client/ }).getAttribute("href"), "/clients/");
      assert.match(await rows.nth(1).innerText(), /TDS\s+TDS is in the firm menu, under Deadlines\./);
      await rows.nth(1).getByRole("link", { name: /Open/ }).click();
      await page.waitForURL(/\/tds\/$/);
      await until(async () => (await box(page).count()) === 0, "the box to close");
    },
  },
  {
    id: "the-guide-falls-back-to-a-plain-search-and-says-so",
    title: "when the AI cannot be asked, the box searches the screens' names, says that it did and why, and still opens a screen",
    async run(env) {
      const { page } = env;
      env.stub.route({ method: "POST", re: WHERE, ...refuse("PracticeSync AI is not configured on this server.", 503) });
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await ask(page, "26Q");
      await until(async () => (await answer(page).getAttribute("data-where-is-answer")) === "plain", "the plain search");
      const said = await answer(page).getByRole("status").innerText();
      assert.match(said, /could not be asked, so this is a plain search of the screens’? ?names|plain search of the screens' names/);
      // The server's own sentence is the reason shown (the real one also names the setting; no key's name is written in
      // the web app, this file included, which a Python test holds).
      assert.match(said, /PracticeSync AI is not configured on this server\./);
      const open = answer(page).getByRole("link", { name: /Open TDS returns/ });
      assert.equal(await open.getAttribute("href"), "/tds/returns/");
    },
  },
  {
    id: "a-manager-is-not-pointed-at-my-practice",
    title: "a Manager's request offers no screen of My practice, and an answer that names one is not drawn",
    async run(env) {
      const { page } = env;
      env.stub.setTable("users", [{ ...FAKE_USERS_ROW, role: "Manager" }]);
      const asked = guideAnswers(env, ["firm:/practice/billing", "firm:/team"]);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await page.waitForTimeout(400);
      await ask(page, "where do I bill my fees?");
      await until(async () => (await answer(page).getAttribute("data-where-is-answer")) === "ai", "the answer");
      assert.ok(asked[0].offered.includes("firm:/team"));
      assert.deepEqual(asked[0].offered.filter((id) => id.startsWith("firm:/practice") || id === "firm:/billing"), []);
      assert.deepEqual((await answer(page).locator("li p:first-child").allInnerTexts()).map((t) => t.trim()), ["Team"]);
      // The sentence names the entry a Manager has: Team, and not the My practice a Partner finds it in.
      assert.match(await answer(page).locator("li").first().innerText(), /Team is in the firm menu, under Team\./);
    },
  },
  {
    id: "the-guide-says-when-no-screen-matches",
    title: "when the AI finds nothing the box says no screen matches and points at PracticeSync AI for a question about tax",
    async run(env) {
      const { page } = env;
      guideAnswers(env, []);
      await page.goto(`${env.base}/clients/`, { waitUntil: "networkidle" });
      await ask(page, "what is the TDS rate on rent?");
      await until(async () => (await answer(page).getAttribute("data-where-is-answer")) === "ai", "the answer");
      assert.match(await answer(page).innerText(), /No screen in PracticeSync matches that\./);
      assert.equal(await answer(page).getByRole("link", { name: "PracticeSync AI" }).getAttribute("href"), "/ai-assistant/");
      assert.equal(await answer(page).locator("li").count(), 0);
    },
  },
];
